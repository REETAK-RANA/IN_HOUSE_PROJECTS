import os
import time
import requests
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
from flask_sqlalchemy import SQLAlchemy
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---- Hardware sensor imports ----
# Requires: sudo apt install -y libgpiod2
# pip install adafruit-circuitpython-dht
import adafruit_dht
import board

# ==============================
# Configuration (can override with environment variables)
# ==============================
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', "rajputpraful791@gmail.com")
RECEIVER_EMAIL = os.environ.get('RECEIVER_EMAIL', "reetakrana65@gmail.com")
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', "tehj edww iiqu cwgy")  # Gmail App Password recommended
OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY', 'REPLACE_WITH_YOUR_OPENWEATHER_KEY')

# Hardware config
DHT_GPIO = os.environ.get('DHT_GPIO', 'GPIO17')  # DHT22 pin, e.g., GPIO17
PREFER_DS18B20 = os.environ.get('PREFER_DS18B20', 'false').lower() == 'true'

# ==============================
# Single-file sensor helpers
# ==============================
def _read_ds18b20_temp():
    """Read first DS18B20 temperature from 1-Wire filesystem. Returns float °C or None."""
    try:
        base_dir = '/sys/bus/w1/devices/'
        devices = [d for d in os.listdir(base_dir) if d.startswith('28-')]
        if not devices:
            return None
        device_file = os.path.join(base_dir, devices[0], 'w1_slave')
        with open(device_file, 'r') as f:
            lines = f.read().strip().split('\n')
        if not lines.endswith('YES'):
            return None
        pos = lines.find('t=')
        if pos == -1:
            return None
        return int(lines[pos+2:]) / 1000.0
    except Exception:
        return None

class SensorReader:
    """
    Reads from DHT22 on a chosen GPIO; optionally overrides temperature using DS18B20.
    - dht_gpio: 'GPIO17' is recommended
    - prefer_ds18b20: if True and DS18B20 present, use it for temperature
    """
    def __init__(self, dht_gpio='GPIO17', prefer_ds18b20=False):
        self.prefer_ds18b20 = prefer_ds18b20
        time.sleep(1.0)
        self.dht = adafruit_dht.DHT22(getattr(board, dht_gpio), use_pulseio=False)

    def read(self, retries=3, delay_s=2.0):
        """
        Returns (temperature_c, humidity_percent), rounded to 1 decimal.
        Retries on transient DHT errors (common).
        """
        last_temp = None
        last_hum = None
        for _ in range(max(1, retries)):
            try:
                hum = self.dht.humidity
                temp = self.dht.temperature
                if self.prefer_ds18b20:
                    t_ds = _read_ds18b20_temp()
                    if t_ds is not None:
                        temp = t_ds
                if hum is not None and temp is not None:
                    last_hum = hum
                    last_temp = temp
                    break
            except Exception:
                pass
            time.sleep(delay_s)
        if last_temp is None or last_hum is None:
            raise RuntimeError("Failed to read from DHT22/DS18B20 sensors.")
        return round(float(last_temp), 1), round(float(last_hum), 1)

# ==============================
# HTML Template (your original, unchanged)
# ==============================
INDEX_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cold Room AI Monitor</title>
<style>
:root {
  --bg-color: #0d1117;
  --primary-widget-color: #161b22;
  --text-color: #c9d1d9;
  --text-secondary-color: #8b949e;
  --border-color: #30363d;
  --accent-color: #58a6ff;
  --accent-hover-color: #1f6feb;
  --risk-high-color: #f85149;
  --risk-medium-color: #f0a32e;
  --risk-low-color: #3fb950;
  --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
html { scroll-behavior: smooth; }
body {
  font-family: var(--font-family);
  margin: 0;
  padding: 2em;
  background-color: var(--bg-color);
  color: var(--text-color);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
.container { display: flex; flex-wrap: wrap; gap: 2em; }
.main, .sidebar {
  padding: 2em;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background-color: var(--primary-widget-color);
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.main:hover, .sidebar:hover {
  transform: translateY(-5px);
  box-shadow: 0 12px 32px rgba(88, 166, 255, 0.2);
}
.main { flex-grow: 1; min-width: 400px; }
.sidebar { width: 320px; }
h1 { color: #fff; text-align: center; margin-bottom: 1em; font-size: 2.5em; font-weight: 600; }
h2, h3 { border-bottom: 1px solid var(--border-color); padding-bottom: 0.6em; color: var(--text-color); font-weight: 500; }
hr { border: none; border-top: 1px solid var(--border-color); margin: 2em 0; }
form { display: grid; gap: 1em; }
label { font-weight: 600; color: var(--text-secondary-color); font-size: 0.9em; }
input[type="number"], select {
  padding: 12px; border-radius: 8px; border: 1px solid var(--border-color);
  background-color: var(--bg-color); color: var(--text-color);
  width: 100%; box-sizing: border-box; font-size: 1em;
  transition: border-color 0.2s, box-shadow 0.2s;
}
input[type="number"]:focus, select:focus {
  outline: none; border-color: var(--accent-color);
  box-shadow: 0 0 0 3px rgba(88, 166, 255, 0.3);
}
button {
  padding: 14px; background: linear-gradient(145deg, var(--accent-color), var(--accent-hover-color));
  color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 1.1em; font-weight: bold;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
button:hover { transform: translateY(-2px); box-shadow: 0 4px 15px rgba(88, 166, 255, 0.2); }
button:active { transform: translateY(1px); box-shadow: none; }
.live-data { font-size: 2em; margin: 1em 0; text-align: center; }
.live-data span { font-weight: bold; color: #fff; }
.ai-analysis p { font-size: 1.1em; }
.ai-analysis b { font-size: 1.2em; padding: 4px 8px; border-radius: 6px; font-weight: 600; }
#spoilage-risk.High { color: var(--risk-high-color); background-color: rgba(248, 81, 73, 0.1); }
#spoilage-risk.Medium { color: var(--risk-medium-color); background-color: rgba(240, 163, 46, 0.1); }
#spoilage-risk.Low { color: var(--risk-low-color); background-color: rgba(63, 185, 80, 0.1); }
#alert-list { list-style-type: none; padding-left: 0; max-height: 200px; overflow-y: auto; }
#alert-list li {
  background-color: var(--bg-color); margin-bottom: 8px; padding: 12px; border-radius: 6px;
  border-left: 4px solid var(--accent-color); font-size: 0.95em; transition: background-color 0.2s;
}
#alert-list li:hover { background-color: #222831; }
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
      <h3 class="ai-analysis">AI Analysis (Factoring in External Weather)</h3>
      <p class="ai-analysis">Spoilage Risk: <b id="spoilage-risk" class="{{ spoilage_risk }}">{{ spoilage_risk }}</b></p>
      <p class="ai-analysis">Anomaly Status: <b id="anomaly-status">{{ anomaly_status }}</b></p>
      <h2>Historical Data (Last 100 Readings)</h2>
      <canvas id="dataChart" width="400" height="200"></canvas>
    </div>
    <div class="sidebar">
      <h3>Weather Station</h3>
      <form id="location-form">
        <label for="location">Select Location:</label>
        <select id="location" name="location">
          {% for loc in locations %}
          <option value="{{ loc }}" {% if loc == selected_location %}selected{% endif %}>{{ loc.split(',')[0] }}</option>
          {% endfor %}
        </select>
        <button type="submit">Get Weather</button>
      </form>
      <hr>
      {% if weather and not weather.error %}
        <h4>{{ weather.location }}</h4>
        <p>Temp: {{ weather.temperature }}°C | Humidity: {{ weather.humidity }}%</p>
        <p>Conditions: {{ weather.description|title }}</p>
      {% elif weather %}
        <p style="color:#f85149;">{{ weather.error }}</p>
      {% endif %}
      <hr>
      <h3>Manual Data Entry</h3>
      <form id="data-form">
        <label for="temperature">Internal Temp (°C):</label>
        <input type="number" id="temperature" name="temperature" step="0.1" required>
        <label for="humidity">Internal Humidity (%):</label>
        <input type="number" id="humidity" name="humidity" step="0.1" required>
        <button type="submit">Submit Data</button>
      </form>
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
      <button id="read-sensor-btn">Read Hardware Sensor Now</button>
    </div>
  </div>

  <script>
  document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('location-form').addEventListener('submit', function(e) {
      e.preventDefault();
      const selectedLocation = document.getElementById('location').value;
      window.location.href = '/?location=' + encodeURIComponent(selectedLocation);
    });

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
              tension: 0.2, yAxisID: 'y', borderWidth: 2, pointBackgroundColor: 'rgb(248, 81, 73)' },
            { label: 'Humidity (%)', data: chartData.humidities,
              borderColor: 'rgb(88, 166, 255)', backgroundColor: 'rgba(88, 166, 255, 0.2)',
              tension: 0.2, yAxisID: 'y1', borderWidth: 2, pointBackgroundColor: 'rgb(88, 166, 255)' }
          ]
        },
        options: {
          scales: {
            y: { type: 'linear', display: true, position: 'left', title: { display: true, text: 'Temperature (°C)' }, grid: { color: 'rgba(48, 54, 61, 0.8)' } },
            y1: { type: 'linear', display: true, position: 'right', title: { display: true, text: 'Humidity (%)' }, grid: { drawOnChartArea: false } },
            x: { type: 'time', time: { unit: 'minute' }, grid: { color: 'rgba(48, 54, 61, 0.8)' } }
          }
        }
      });
    }

    async function updateChart() {
      const response = await fetch('/api/historical-data');
      const chartData = await response.json();
      createChart(chartData);
    }

    document.getElementById('data-form').addEventListener('submit', async function (e) {
      e.preventDefault();
      const formData = new FormData(e.target);
      const response = await fetch('/data', { method: 'POST', body: formData });
      const result = await response.json();
      if (result.status === 'success') {
        alert('Data submitted successfully! The page will now refresh.');
        window.location.href = window.location.href;
      } else {
        alert('Error submitting data: ' + result.message);
      }
    });

    document.getElementById('read-sensor-btn').addEventListener('click', async function () {
      try {
        const res = await fetch('/read_sensor', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') {
          alert('Hardware read: ' + data.temperature + '°C, ' + data.humidity + '%');
          window.location.href = window.location.href;
        } else {
          alert('Read error: ' + data.message);
        }
      } catch (e) {
        alert('Request failed: ' + e);
      }
    });

    updateChart();
  });
  </script>
</body>
</html>
"""

# ==============================
# Flask App + DB
# ==============================
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'cold_storage.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Instantiate sensor early
sensor = None
try:
    sensor = SensorReader(dht_gpio=DHT_GPIO, prefer_ds18b20=PREFER_DS18B20)
except Exception as e:
    print(f"WARNING: Sensor init failed: {e}")
    sensor = None

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
    text = f"""
Hi,

Automated alert from the Cold Room AI Monitoring system.

An anomaly has been detected:
---
{alert_message}
---

Please check the system.
"""
    part = MIMEText(text, "plain")
    message.attach(part)
    server = None
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SENDER_EMAIL, EMAIL_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, message.as_string())
        print(f"Email alert sent successfully to {RECEIVER_EMAIL}!")
    except Exception as e:
        print(f"ERROR sending email: {e}")
    finally:
        if server:
            server.quit()

# ==============================
# Weather
# ==============================
def get_weather_forecast(location="Bhoranj,IN"):
    """ Fetches weather data for a given location."""
    API_KEY = OPENWEATHER_API_KEY
    if not API_KEY or API_KEY.startswith('REPLACE_'):
        return {"error": "OpenWeather API key not set"}
    BASE_URL = "http://api.openweathermap.org/data/2.5/weather"
    url = f"{BASE_URL}?q={location}&appid={API_KEY}&units=metric"
    try:
        response = requests.get(url, timeout=8)
        if response.status_code == 200:
            data = response.json()
            return {
                "location": data.get('name', 'Unknown'), "temperature": data['main']['temp'],
                "humidity": data['main']['humidity'], "description": data['weather'][0]['description'],
                "error": None
            }
        else:
            return {"error": f"Weather API error: {response.json().get('message', 'Unknown error')}"}
    except requests.exceptions.RequestException as e:
        return {"error": f"Network error fetching weather: {e}"}

# ==============================
# AI Logic (unchanged)
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
# Routes
# ==============================
@app.route('/')
def index():
    locations = [
        "Bilaspur,IN", "Chamba,IN", "Hamirpur,IN", "Kangra,IN",
        "Kinnaur,IN", "Kullu,IN", "Lahaul and Spiti,IN", "Mandi,IN",
        "Shimla,IN", "Sirmaur,IN", "Solan,IN", "Una,IN"
    ]
    selected_location = request.args.get('location', 'Kinnaur,IN')
    if selected_location not in locations:
        selected_location = "Bhoranj,IN"

    weather_data = get_weather_forecast(selected_location)
    latest_reading = SensorReading.query.order_by(SensorReading.timestamp.desc()).first()
    alerts = AlertLog.query.order_by(AlertLog.timestamp.desc()).limit(10).all()

    spoilage_risk = "N/A"
    anomaly_status = "N/A"
    if latest_reading:
        external_temp = weather_data.get('temperature') if weather_data and not weather_data.get('error') else None
        spoilage_risk = predict_spoilage(latest_reading.temperature, latest_reading.humidity, external_temp)
        _, anomaly_status = detect_anomaly(latest_reading.temperature, latest_reading.humidity, external_temp)

    return render_template_string(
        INDEX_HTML_TEMPLATE, reading=latest_reading, alerts=alerts, weather=weather_data,
        spoilage_risk=spoilage_risk, anomaly_status=anomaly_status,
        locations=locations, selected_location=selected_location
    )

@app.route('/data', methods=['POST'])
def add_data():
    """Manual input endpoint."""
    try:
        temp = float(request.form['temperature'])
        humidity = float(request.form['humidity'])
        weather_data = get_weather_forecast()
        external_temp = weather_data.get('temperature') if weather_data and not weather_data.get('error') else None

        reading = SensorReading(temperature=temp, humidity=humidity)
        db.session.add(reading)

        is_anomaly, anomaly_reason = detect_anomaly(temp, humidity, external_temp)
        if is_anomaly:
            send_email_alert(anomaly_reason)
            db.session.add(AlertLog(message=anomaly_reason))

        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/read_sensor', methods=['POST'])
def read_sensor():
    """Takes a hardware reading and stores it, triggering alerts if needed."""
    if sensor is None:
        return jsonify({'status': 'error', 'message': 'Sensor not initialized'}), 500
    try:
        temp, hum = sensor.read()
        weather_data = get_weather_forecast()
        external_temp = weather_data.get('temperature') if weather_data and not weather_data.get('error') else None

        reading = SensorReading(temperature=temp, humidity=hum)
        db.session.add(reading)

        is_anomaly, anomaly_reason = detect_anomaly(temp, hum, external_temp)
        if is_anomaly:
            send_email_alert(anomaly_reason)
            db.session.add(AlertLog(message=anomaly_reason))

        db.session.commit()
        return jsonify({'status': 'success', 'temperature': temp, 'humidity': hum})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/historical-data')
def historical_data():
    readings = SensorReading.query.order_by(SensorReading.timestamp.desc()).limit(100).all()
    readings.reverse()
    return jsonify({
        'labels': [r.timestamp.strftime('%Y-%m-%dT%H:%M:%S') for r in readings],
        'temperatures': [r.temperature for r in readings],
        'humidities': [r.humidity for r in readings]
    })

# ==============================
# Main
# ==============================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # Bind to all interfaces for LAN access
    app.run(host='0.0.0.0', port=5000, debug=True)