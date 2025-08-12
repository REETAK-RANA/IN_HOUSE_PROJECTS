import os
import requests
from datetime import datetime
from flask import Flask, request, jsonify, render_template_string
from flask_sqlalchemy import SQLAlchemy

# --- 1. HTML and JavaScript Template ---
# The HTML and JS from the original files are combined into a single string.
# The JavaScript is now embedded directly inside a <script> tag.

INDEX_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cold Room AI Monitor</title>
    <style>
        body { font-family: sans-serif; margin: 2em; background-color: #f4f4f9; color: #333; }
        .container { display: flex; flex-wrap: wrap; gap: 2em; }
        .main, .sidebar { padding: 1.5em; border: 1px solid #ccc; border-radius: 8px; background-color: #fff; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
        .main { flex-grow: 1; min-width: 400px; }
        .sidebar { width: 320px; }
        h1 { color: #2c3e50; }
        h2, h3 { border-bottom: 2px solid #eee; padding-bottom: 0.5em; color: #34495e; }
        form { display: grid; gap: 0.8em; }
        input[type="number"] { padding: 8px; border-radius: 4px; border: 1px solid #ccc; }
        button { padding: 10px; background-color: #3498db; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1em; }
        button:hover { background-color: #2980b9; }
        .live-data { font-size: 1.5em; margin: 1em 0; }
        #alert-list { list-style-type: none; padding-left: 0; }
        #alert-list li { background-color: #ecf0f1; margin-bottom: 5px; padding: 8px; border-radius: 4px; }
    </style>
    <!-- Using Chart.js for graphs from a CDN -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <h1>Cold Room AI Monitor</h1>
    <div class="container">
        <div class="main">
            <h2>Live Status</h2>
            <div class="live-data">
                🌡 Temperature: <span id="current-temp">{{ reading.temperature if reading else 'N/A' }}</span> °C <br>
                💧 Humidity: <span id="current-hum">{{ reading.humidity if reading else 'N/A' }}</span> %
            </div>
            <h3>AI Analysis</h3>
            <p>Spoilage Risk: <b id="spoilage-risk">N/A</b></p>
            <p>Anomaly Status: <b id="anomaly-status">N/A</b></p>
            
            <h2>Historical Data (Last 100 Readings)</h2>
            <canvas id="dataChart" width="400" height="200"></canvas>
        </div>
        <div class="sidebar">
            <h3>Manual Data Entry</h3>
            <form id="data-form">
                <label for="temperature">Temperature (°C):</label>
                <input type="number" id="temperature" name="temperature" step="0.1" required>
                <label for="humidity">Humidity (%):</label>
                <input type="number" id="humidity" name="humidity" step="0.1" required>
                <button type="submit">Submit Data</button>
            </form>
            <hr>
            <h3>External Weather: {{ weather.location if not weather.error else 'Error' }}</h3>
            {% if not weather.error %}
                <p>Temp: {{ weather.temperature }}°C | Humidity: {{ weather.humidity }}%</p>
                <p>Conditions: {{ weather.description|title }}</p>
            {% else %}
                <p style="color:red;">{{ weather.error }}</p>
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
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function () {
            const dataForm = document.getElementById('data-form');
            const ctx = document.getElementById('dataChart').getContext('2d');
            let dataChart;

            function createChart(chartData) {
                if (dataChart) {
                    dataChart.destroy(); // Destroy old chart before creating new one
                }
                dataChart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: chartData.labels,
                        datasets: [
                            {
                                label: 'Temperature (°C)',
                                data: chartData.temperatures,
                                borderColor: 'rgb(255, 99, 132)',
                                backgroundColor: 'rgba(255, 99, 132, 0.2)',
                                tension: 0.1,
                                yAxisID: 'y'
                            },
                            {
                                label: 'Humidity (%)',
                                data: chartData.humidities,
                                borderColor: 'rgb(54, 162, 235)',
                                backgroundColor: 'rgba(54, 162, 235, 0.2)',
                                tension: 0.1,
                                yAxisID: 'y1'
                            }
                        ]
                    },
                    options: {
                        scales: {
                            y: {
                                type: 'linear',
                                display: true,
                                position: 'left',
                                title: { display: true, text: 'Temperature (°C)' }
                            },
                            y1: {
                                type: 'linear',
                                display: true,
                                position: 'right',
                                title: { display: true, text: 'Humidity (%)' },
                                grid: { drawOnChartArea: false }
                            }
                        }
                    }
                });
            }

            async function updateChart() {
                try {
                    const response = await fetch('/api/historical-data');
                    const chartData = await response.json();
                    createChart(chartData);
                } catch (error) {
                    console.error('Error fetching chart data:', error);
                }
            }
            
            dataForm.addEventListener('submit', async function (e) {
                e.preventDefault();
                const formData = new FormData(dataForm);

                try {
                    const response = await fetch('/data', {
                        method: 'POST',
                        body: formData
                    });
                    const result = await response.json();
                    
                    if (result.status === 'success') {
                        // Update live data display
                        document.getElementById('current-temp').textContent = result.reading.temperature;
                        document.getElementById('current-hum').textContent = result.reading.humidity;
                        document.getElementById('spoilage-risk').textContent = result.spoilage_risk;
                        document.getElementById('anomaly-status').textContent = result.is_anomaly ? 'Anomaly Detected!' : 'Normal';
                        
                        alert('Data submitted successfully! The page will now refresh to update charts and logs.');
                        dataForm.reset();
                        location.reload(); // Simple way to refresh alerts and chart
                    } else {
                        alert('Error submitting data.');
                    }
                } catch (error) {
                    console.error('Error submitting form:', error);
                    alert('An error occurred. Please check the console.');
                }
            });

            // Initial chart load when the page is opened
            updateChart();
        });
    </script>
</body>
</html>
"""

# --- 2. Flask App Initialization and Configuration ---
app = Flask(__name__)

# Configure the database to be a file named 'cold_storage.db' in the same directory
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'cold_storage.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- 3. Database Models ---
class SensorReading(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    temperature = db.Column(db.Float, nullable=False)
    humidity = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)

    def _repr_(self):
        return f'<SensorReading T:{self.temperature} H:{self.humidity}>'

class AlertLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)

    def _repr_(self):
        return f'<AlertLog {self.message}>'

# --- 4. Helper Functions (Services and AI Logic) ---
def send_alert(message):
    """Prints an alert to the console. Can be replaced with email/SMS logic."""
    print("="*20)
    print("SENDING ALERT:")
    print(message)
    print("="*20)

def get_weather_forecast(location="Bhoranj,IN"):
    """Fetches weather data from OpenWeatherMap."""
    API_KEY = os.environ.get('OPENWEATHER_API_KEY', None) # Get key from environment variable
    BASE_URL = "http://api.openweathermap.org/data/2.5/weather"

    if not API_KEY:
        return {"error": "Weather API Key not set."}

    params = {'q': location, 'appid': API_KEY, 'units': 'metric'}
    try:
        response = requests.get(BASE_URL, params=params)
        response.raise_for_status()
        data = response.json()
        return {
            "location": data['name'],
            "temperature": data['main']['temp'],
            "humidity": data['main']['humidity'],
            "description": data['weather'][0]['description']
        }
    except requests.exceptions.RequestException as e:
        return {"error": f"Could not fetch weather: {e}"}

def predict_spoilage(temperature, humidity):
    """Simple rule-based spoilage prediction."""
    risk_score = 0
    if temperature > 4: risk_score += (temperature - 4) * 10
    if temperature < 0: risk_score += abs(temperature) * 15
    if humidity > 95: risk_score += (humidity - 95) * 5
    if humidity < 85: risk_score += (85 - humidity) * 5

    if risk_score > 70: return "High"
    elif risk_score > 30: return "Medium"
    else: return "Low"

def detect_anomaly(temperature, humidity):
    """Simple rule-based anomaly detection."""
    NORMAL_TEMP_MIN, NORMAL_TEMP_MAX = 0, 4
    NORMAL_HUMIDITY_MIN, NORMAL_HUMIDITY_MAX = 90, 95
    if not (NORMAL_TEMP_MIN <= temperature <= NORMAL_TEMP_MAX):
        return True, f"Temp {temperature}°C is outside normal range ({NORMAL_TEMP_MIN}-{NORMAL_TEMP_MAX}°C)."
    if not (NORMAL_HUMIDITY_MIN <= humidity <= NORMAL_HUMIDITY_MAX):
        return True, f"Humidity {humidity}% is outside normal range ({NORMAL_HUMIDITY_MIN}-{NORMAL_HUMIDITY_MAX}%)."
    return False, "Conditions are normal."

# --- 5. Flask Routes (API Endpoints) ---
@app.route('/')
def index():
    """Renders the main dashboard page."""
    latest_reading = SensorReading.query.order_by(SensorReading.timestamp.desc()).first()
    alerts = AlertLog.query.order_by(AlertLog.timestamp.desc()).limit(10).all()
    weather_data = get_weather_forecast() # Uses your default location
    return render_template_string(INDEX_HTML_TEMPLATE, reading=latest_reading, alerts=alerts, weather=weather_data)

@app.route('/data', methods=['POST'])
def add_data():
    """Endpoint to receive new sensor data."""
    try:
        temp = float(request.form['temperature'])
        humidity = float(request.form['humidity'])

        # Save reading
        reading = SensorReading(temperature=temp, humidity=humidity)
        db.session.add(reading)

        # Run AI checks
        spoilage_risk = predict_spoilage(temp, humidity)
        is_anomaly, anomaly_reason = detect_anomaly(temp, humidity)

        # Trigger alerts if needed
        if is_anomaly:
            send_alert(anomaly_reason)
            alert_log = AlertLog(message=anomaly_reason)
            db.session.add(alert_log)
        
        db.session.commit()

        return jsonify({
            'status': 'success',
            'reading': {'temperature': temp, 'humidity': humidity},
            'spoilage_risk': spoilage_risk,
            'is_anomaly': is_anomaly
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/historical-data')
def historical_data():
    """Provides historical data for charts."""
    readings = SensorReading.query.order_by(SensorReading.timestamp.asc()).limit(100).all()
    data = {
        'labels': [r.timestamp.strftime('%H:%M:%S') for r in readings],
        'temperatures': [r.temperature for r in readings],
        'humidities': [r.humidity for r in readings]
    }
    return jsonify(data)

# --- 6. Main Execution Block ---
if __name__ == '__main__':
    # Create the database and tables if they don't exist
    with app.app_context():
        db.create_all()
    
    # Run the Flask application
    app.run(debug=True)