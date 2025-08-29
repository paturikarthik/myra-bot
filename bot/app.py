# app.py
from flask import Flask, request
import os
from dotenv import load_dotenv
from handlers import handle_update, auto_refresh, send_duty_reminders, daily_checkup

load_dotenv()

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print(data)
    handle_update(data)
    return "OK", 200
  
@app.route("/refresh", methods=["GET"])
def refresh():
    auto_refresh()
    return "OK", 200

@app.route("/reminder", methods=["GET"])
def reminder():
    send_duty_reminders()
    return "OK", 200

@app.route("/wellbeing", methods=["GET"])
def wellbeing():
    daily_checkup()
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
