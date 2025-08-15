import requests

# 🔐 API credentials and endpoint
API_KEY = "6acd4de42emsh65e16067f4c61fap14903ajsnd665e63a4218"  # Replace with env var in production
API_URL = "https://your-sms-api-provider.com/send"  # Replace with actual SMS API endpoint

def send_sms(phone_number, message):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "to": phone_number,
        "message": message
    }

    try:
        response = requests.post(API_URL, json=payload, headers=headers)
        response.raise_for_status()
        print(f"✅ SMS sent to {phone_number}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to send SMS: {e}")

if __name__ == "__main__":
    print("📲 SMS Notification System")
    phone = input("Enter recipient phone number: ")
    message = input("Enter your message: ")
    send_sms(phone, message)
