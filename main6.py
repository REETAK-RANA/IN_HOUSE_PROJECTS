#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import threading
from datetime import datetime
import requests
from flask import Flask, jsonify, render_template_string
from flask_sqlalchemy import SQLAlchemy
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==============================
# Hardware imports (fail-safe)
# ==============================
SENSOR_AVAILABLE = True
try:
    import board
    import adafruit_dht
except Exception as e:
    print(f"NOTE: Hardware libs not available or sensor not connected: {e}")
    SENSOR_AVAILABLE = False
    board = None
    adafruit_dht = None

# ==============================
# Configuration (ENV-first)
# ==============================
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', "rajputpraful791")  # set to full email in env
RECEIVER_EMAIL = os.environ.get('RECEIVER_EMAIL', "reetakrana65") # set to full email in env
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', "tehj edww iiqu cwgy")  # Gmail App Password recommended
OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY', "32322b3a704cf8713c242c2f1c2bfae7")

# Preferred GPIO from env (like "D4" or "D17"); code will auto-scan common pins if this fails
DHT_GPIO_PIN = os.environ.get("DHT_GPIO_PIN", "D17")

# Background read interval (seconds)
READ_INTERVAL_SEC = int(os.environ.get("READ_INTERVAL_SEC", "300"))  # 5 minutes

# Weather default (ALWAYS show Hamirpur on start)
DEFAULT_LOCATION = "Hamirpur,IN"

def _resolve_board_pin(pin_name: str):
    if not board:
        return None
    if not (isinstance(pin_name, str) and pin_name.upper().startswith("D")):
        pin_name = "D17"
    return getattr(board, pin_name.upper(), getattr(board, "D17", None))

# ==============================
# Flask App + DB
# ==============================
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'cold_storage.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ==============================
# Database Models
# ==============================
class SensorReading(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    temperature = db.Column(db.Float, nullable=False)
    humidity = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)

class AlertLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)

# ==============================
# Email Alerts
# ==============================
def send_email_alert(alert_message):
    print("="*20 + f"\nEMAIL ALERT TRIGGERED: {alert_message}\n" + "="*20)
    if not all([SENDER_EMAIL, RECEIVER_EMAIL, EMAIL_PASSWORD]):
        print("DEBUG: Email credentials not set. Skipping email.")
        return
    message = MIMEMultipart("alternative")
    message["Subject"] = "Cold Room AI Monitor - ALERT"
    message["From"] = SENDER_EMAIL
    message["To"] = RECEIVER_EMAIL
    text = f"""Hi,

Automated alert from the Cold Room AI Monitoring system.

An anomaly has been detected:
---
{alert_message}
---

Please check the system.
"""
    message.attach(MIMEText(text, "plain"))
    server = None
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
        server.starttls()
        server.login(SENDER_EMAIL, EMAIL_PASSWORD)
        server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], message.as_string())
        print(f"Email alert sent successfully to {RECEIVER_EMAIL}!")
    except Exception as e:
        print(f"ERROR sending email: {e}")
    finally:
        try:
            if server: server.quit()
        except Exception:
            pass

# ==============================
# Weather
# ==============================
def get_weather_forecast(location=DEFAULT_LOCATION):
    API_KEY = OPENWEATHER_API_KEY
    if not API_KEY:
        return {"error": "OpenWeather API key not set"}
    BASE_URL = "http://api.openweathermap.org/data/2.5/weather"
    url = f"{BASE_URL}?q={location}&appid={API_KEY}&units=metric"
    try:
        response = requests.get(url, timeout=8)
        if response.status_code == 200:
            data = response.json()
            return {
                "location": data.get('name', 'Unknown'),
                "temperature": data['main']['temp'],
                "humidity": data['main']['humidity'],
                "description": data['weather'][0]['description'],
                "error": None
            }
        else:
            try:
                return {"error": f"Weather API error: {response.json().get('message', 'Unknown error')}"}
            except Exception:
                return {"error": f"Weather API error: HTTP {response.status_code}"}
    except requests.exceptions.RequestException as e:
        return {"error": f"Network error fetching weather: {e}"}

# ==============================
# AI Logic
# ==============================
def predict_spoilage(temperature, humidity, external_temp=None):
    risk_score = 0
    if temperature > 4: risk_score += (temperature - 4) * 10
    if temperature < 0: risk_score += abs(temperature) * 15
    if humidity > 95: risk_score += (humidity - 95) * 5
    if humidity < 85: risk_score += (85 - humidity) * 5
    if external_temp and external_temp > 25:
        strain_factor = (external_temp - 25) * 1.5
        risk_score += strain_factor
        print(f"DEBUG: External temp {external_temp}°C added {strain_factor:.1f} to risk score.")
    if risk_score > 70: return "High"
    if risk_score > 30: return "Medium"
    return "Low"

def detect_anomaly(temperature, humidity, external_temp=None):
    NORMAL_TEMP_MIN, NORMAL_TEMP_MAX_BASE = 0, 4
    NORMAL_HUMIDITY_MIN, NORMAL_HUMIDITY_MAX = 90, 95
    temp_strain_allowance = 0
    if external_temp and external_temp > 20:
        temp_strain_allowance = ((external_temp - 20) / 5) * 0.1
    NORMAL_TEMP_MAX = NORMAL_TEMP_MAX_BASE + temp_strain_allowance
    if not (NORMAL_TEMP_MIN <= temperature <= NORMAL_TEMP_MAX):
        return True, f"Temperature {temperature}°C is out of the acceptable range ({NORMAL_TEMP_MIN:.1f}°C - {NORMAL_TEMP_MAX:.1f}°C)."
    if not (NORMAL_HUMIDITY_MIN <= humidity <= NORMAL_HUMIDITY_MAX):
        return True, f"Humidity {humidity}% is out of the acceptable range ({NORMAL_HUMIDITY_MIN}% - {NORMAL_HUMIDITY_MAX}%)."
    return False, f"Conditions are Normal (Max Temp adjusted to {NORMAL_TEMP_MAX:.1f}°C due to weather)"

# ==============================
# HTML Template (NO manual controls)
# ==============================
INDEX_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Cold Room AI Monitor</title>
<style>
:root{--bg-color:#0d1117;--primary-widget-color:#161b22;--text-color:#c9d1d9;--text-secondary-color:#8b949e;--border-color:#30363d;--accent-color:#58a6ff;--accent-hover-color:#1f6feb;--risk-high-color:#f85149;--risk-medium-color:#f0a32e;--risk-low-color:#3fb950;--font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;}
html{scroll-behavior:smooth}
body{font-family:var(--font-family);margin:0;padding:2em;background-color:var(--bg-color);color:var(--text-color)}
.container{display:flex;flex-wrap:wrap;gap:2em}
.main,.sidebar{padding:2em;border:1px solid var(--border-color);border-radius:12px;background-color:var(--primary-widget-color);box-shadow:0 8px 24px rgba(0,0,0,.4)}
.main{flex-grow:1;min-width:400px}.sidebar{width:320px}
h1{color:#fff;text-align:center;margin-bottom:1em;font-size:2.2em;font-weight:600}
h2,h3{border-bottom:1px solid var(--border-color);padding-bottom:.6em;color:var(--text-color);font-weight:500}
.live-data{font-size:2em;margin:1em 0;text-align:center}
.live-data span{font-weight:700;color:#fff}
.ai-analysis p{font-size:1.05em}
.ai-analysis b{font-size:1.1em;padding:4px 8px;border-radius:6px;font-weight:600}
#spoilage-risk.High{color:var(--risk-high-color);background-color:rgba(248,81,73,.1)}
#spoilage-risk.Medium{color:var(--risk-medium-color);background-color:rgba(240,163,46,.1)}
#spoilage-risk.Low{color:var(--risk-low-color);background-color:rgba(63,185,80,.1)}
#alert-list{list-style:none;padding-left:0;max-height:220px;overflow-y:auto}
#alert-list li{background-color:#0d1117;margin-bottom:8px;padding:12px;border-radius:6px;border-left:4px solid var(--accent-color);font-size:.95em}
.small{color:var(--text-secondary-color);font-size:.9em}
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns"></script>
</head>
<body>
  <h1>🍎 Cold Room AI Monitor</h1>
  <div class="container">
    <div class="main">
      <h2>Live Status</h2>
      <div class="live-data">
        🌡 Temp: <span id="current-temp">{{ reading.temperature if reading else 'N/A' }}</span> °C&nbsp;&nbsp;&nbsp;
        💧 Humidity: <span id="current-hum">{{ reading.humidity if reading else 'N/A' }}</span> %
      </div>
      <p class="small">Background logger samples every {{ read_interval }} seconds (auto-detects DHT22 pin).</p>
      <h3 class="ai-analysis">AI Analysis (factoring external weather for Hamirpur)</h3>
      <p class="ai-analysis">Spoilage Risk: <b id="spoilage-risk" class="{{ spoilage_risk }}">{{ spoilage_risk }}</b></p>
      <p class="ai-analysis">Anomaly Status: <b id="anomaly-status">{{ anomaly_status }}</b></p>
      <h2>Historical Data (Last 100 Readings)</h2>
      <canvas id="dataChart" width="400" height="200"></canvas>
    </div>
    <div class="sidebar">
      <h3>Hamirpur Weather</h3>
      {% if weather and not weather.error %}
        <h4>{{ weather.location }}</h4>
        <p>Temp: {{ weather.temperature }}°C | Humidity: {{ weather.humidity }}%</p>
        <p>Conditions: {{ weather.description|title }}</p>
      {% else %}
        <p style="color:#f85149;">{{ weather.error if weather else 'Weather unavailable' }}</p>
      {% endif %}
      <hr>
      <h3>Recent Alerts</h3>
      <ul id="alert-list">
        {% for alert in alerts %}
          <li><small>{{ alert.timestamp.strftime('%Y-%m-%d %H:%M') }}</small>: {{ alert.message }}</li>
        {% else %}
          <li>No recent alerts.</li>
        {% endfor %}
      </ul>
      <hr>
      <p class="small">Service health: <span id="svc">{{ 'OK' if service_ok else 'Degraded' }}</span></p>
    </div>
  </div>

<script>
document.addEventListener('DOMContentLoaded', function () {
  const ctx = document.getElementById('dataChart').getContext('2d');
  let dataChart;
  function createChart(chartData) {
    if (dataChart) dataChart.destroy();
    Chart.defaults.color = 'rgba(201, 209, 217, 0.8)';
    dataChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: chartData.labels,
        datasets: [
          { label: 'Temperature (°C)', data: chartData.temperatures,
            borderColor: 'rgb(248, 81, 73)', backgroundColor: 'rgba(248, 81, 73, 0.2)',
            tension: 0.2, yAxisID: 'y', borderWidth: 2, pointRadius: 1 },
          { label: 'Humidity (%)', data: chartData.humidities,
            borderColor: 'rgb(88, 166, 255)', backgroundColor: 'rgba(88, 166, 255, 0.2)',
            tension: 0.2, yAxisID: 'y1', borderWidth: 2, pointRadius: 1 }
        ]
      },
      options: {
        scales: {
          y: { type: 'linear', position: 'left', title: { display: true, text: 'Temperature (°C)' } },
          y1: { type: 'linear', position: 'right', title: { display: true, text: 'Humidity (%)' }, grid: { drawOnChartArea: false } },
          x: { type: 'time', time: { unit: 'minute' } }
        }
      }
    });
  }
  async function updateChart() {
    const response = await fetch('/api/historical-data');
    const chartData = await response.json();
    createChart(chartData);
  }
  updateChart();
  setInterval(updateChart, 60_000); // refresh chart every minute
});
</script>
</body>
</html>
"""

# ==============================
# Background Sensor Logic
# ==============================
sensor = None
last_background_tick = None
_sensor_lock = threading.Lock()

def _try_init_sensor():
    """Try (re)initializing the DHT22 on preferred or common pins."""
    global sensor
    if not SENSOR_AVAILABLE:
        print("DEBUG: SENSOR_AVAILABLE=False; cannot init sensor.")
        return

    candidates = []
    # Preferred from env first
    pref_pin = _resolve_board_pin(DHT_GPIO_PIN)
    if pref_pin is not None:
        candidates.append(("ENV", pref_pin))
    # Common BCM GPIOs used with DHT: D4, D17, D27, D22
    for name in ("D4", "D17", "D27", "D22"):
        pin = _resolve_board_pin(name)
        if pin is not None and (not candidates or pin != candidates[0][1]):
            candidates.append((name, pin))

    for name, pin in candidates:
        try:
            print(f"DEBUG: Trying DHT22 on {name} ...")
            d = adafruit_dht.DHT22(pin, use_pulseio=False)
            time.sleep(1.0)
            # quick probe read
            _ = d.humidity
            _ = d.temperature
            with _sensor_lock:
                sensor = d
            print(f"INFO: DHT22 initialized on {name}.")
            return
        except Exception as e:
            print(f"DEBUG: Init failed on {name}: {e}")
            try:
                d.exit()  # best-effort cleanup if provided
            except Exception:
                pass
    print("WARN: Could not initialize DHT22 on any tested pin.")

def _background_reader():
    """Loop forever: read sensor every READ_INTERVAL_SEC, store to DB, log/alert."""
    global last_background_tick
    with app.app_context():
        while True:
            last_background_tick = datetime.utcnow()
            try:
                # Ensure sensor object exists
                if sensor is None:
                    _try_init_sensor()

                if sensor is None:
                    print("WARN: Sensor not initialized; will retry next cycle.")
                else:
                    with _sensor_lock:
                        hum = sensor.humidity
                        temp = sensor.temperature

                    if hum is None or temp is None:
                        raise RuntimeError("Null reading from DHT22.")

                    weather = get_weather_forecast(DEFAULT_LOCATION)
                    external_temp = weather.get('temperature') if weather and not weather.get('error') else None

                    reading = SensorReading(temperature=float(temp), humidity=float(hum))
                    db.session.add(reading)

                    is_anom, reason = detect_anomaly(float(temp), float(hum), external_temp)
                    if is_anom:
                        db.session.add(AlertLog(message=reason))
                        send_email_alert(reason)

                    db.session.commit()
                    print(f"INFO: Logged reading: {temp:.1f}°C, {hum:.1f}%")
            except Exception as e:
                print(f"ERROR in background read loop: {e}")
                try:
                    db.session.rollback()
                except Exception:
                    pass
            finally:
                time.sleep(READ_INTERVAL_SEC)

def start_background_thread():
    t = threading.Thread(target=_background_reader, name="sensor_reader", daemon=True)
    t.start()
    print(f"Background reader thread started (interval={READ_INTERVAL_SEC}s).")

# ==============================
# Routes
# ==============================
@app.route('/')
def index():
    weather_data = get_weather_forecast(DEFAULT_LOCATION)
    latest_reading = SensorReading.query.order_by(SensorReading.timestamp.desc()).first()
    alerts = AlertLog.query.order_by(AlertLog.timestamp.desc()).limit(10).all()

    spoilage_risk = "N/A"
    anomaly_status = "N/A"
    if latest_reading:
        external_temp = weather_data.get('temperature') if weather_data and not weather_data.get('error') else None
        spoilage_risk = predict_spoilage(latest_reading.temperature, latest_reading.humidity, external_temp)
        _, anomaly_status = detect_anomaly(latest_reading.temperature, latest_reading.humidity, external_temp)

    return render_template_string(
        INDEX_HTML_TEMPLATE,
        reading=latest_reading,
        alerts=alerts,
        weather=weather_data,
        spoilage_risk=spoilage_risk,
        anomaly_status=anomaly_status,
        read_interval=READ_INTERVAL_SEC,
        service_ok=True
    )

@app.route('/api/historical-data')
def historical_data():
    readings = SensorReading.query.order_by(SensorReading.timestamp.desc()).limit(100).all()
    readings.reverse()
    return jsonify({
        'labels': [r.timestamp.strftime('%Y-%m-%dT%H:%M:%S') for r in readings],
        'temperatures': [r.temperature for r in readings],
        'humidities': [r.humidity for r in readings]
    })

@app.route('/health')
def health():
    return jsonify({
        "ok": True,
        "sensor_initialized": sensor is not None,
        "last_background_tick": last_background_tick.isoformat() if last_background_tick else None
    })

# ==============================
# Main
# ==============================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # Kick off the background logger
    start_background_thread()
    # Disable reloader to avoid two background threads
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
