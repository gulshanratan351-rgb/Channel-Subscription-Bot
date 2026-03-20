import os
import telebot
from flask import Flask, request
from datetime import datetime, timedelta
from threading import Thread
import time
from pymongo import MongoClient

# 🔐 CHANGE ONLY THESE 3
BOT_TOKEN = "PASTE_BOT_TOKEN"
CHANNEL_ID = -1001234567890
MONGO_URL = "mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# 🗄️ MongoDB
client = MongoClient(MONGO_URL)
db = client["botdb"]
users_col = db["users"]

# 💰 Plans (minutes)
PLANS = {
    "1 Day - ₹30": 1440,
    "30 Days - ₹199": 43200
}

# ▶️ START
@bot.message_handler(commands=['start'])
def start(message):
    text = "💳 Available Plans:\n\n"
    for name in PLANS:
        text += f"{name}\n"
    
    text += "\nPayment link ke liye admin se contact kare."
    bot.send_message(message.chat.id, text)

# 🔥 TELEGRAM WEBHOOK
@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    json_str = request.get_data().decode("UTF-8")
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

# 🔥 RAZORPAY WEBHOOK
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json

    try:
        if data.get("event") == "payment.captured":
            payment = data["payload"]["payment"]["entity"]

            user_id = int(payment["notes"]["user_id"])
            minutes = int(payment["notes"]["plan"])

            expire_time = datetime.utcnow() + timedelta(minutes=minutes)

            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"expire": expire_time, "warned": False}},
                upsert=True
            )

            invite = bot.create_chat_invite_link(CHANNEL_ID, member_limit=1)

            bot.send_message(
                user_id,
                f"✅ Payment Success!\n\nJoin:\n{invite.invite_link}\n\n⏰ Expire: {expire_time}"
            )

    except Exception as e:
        print(e)

    return "OK", 200

# ⏱️ CHECKER
def checker():
    while True:
        now = datetime.utcnow()
        users = list(users_col.find())

        for user in users:
            user_id = user["user_id"]
            expire = user["expire"]
            warned = user.get("warned", False)

            # ⚠️ 1 hour warning
            if not warned and (expire - now).total_seconds() <= 3600:
                try:
                    bot.send_message(user_id, "⚠️ 1 hour baad subscription expire ho jayega!")
                    users_col.update_one(
                        {"user_id": user_id},
                        {"$set": {"warned": True}}
                    )
                except:
                    pass

            # ❌ Expire remove
            if now >= expire:
                try:
                    bot.ban_chat_member(CHANNEL_ID, user_id)
                    bot.unban_chat_member(CHANNEL_ID, user_id)
                except:
                    pass

                try:
                    bot.send_message(user_id, "❌ Subscription expired!")
                except:
                    pass

                users_col.delete_one({"user_id": user_id})

        time.sleep(30)

# ▶️ THREAD START
Thread(target=checker).start()

# ▶️ MAIN RUN
if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"https://your-app-name.onrender.com/{BOT_TOKEN}")
    app.run(host="0.0.0.0", port=10000)
