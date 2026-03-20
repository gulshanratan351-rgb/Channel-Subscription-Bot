import os
import telebot
from flask import Flask, request
from datetime import datetime, timedelta
from threading import Thread
import time
from pymongo import MongoClient

# 🔐 ENV
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
MONGO_URL = os.getenv("MONGO_URL")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# 🗄️ DB
client = MongoClient(MONGO_URL)
db = client["botdb"]
users_col = db["users"]

# 💰 Plans (minutes : price)
PLANS = {
    1440: 30,
    43200: 199
}

# ▶️ START
@bot.message_handler(commands=['start'])
def start(message):
    text = "💳 Available Plans:\n\n"
    for mins, price in PLANS.items():
        text += f"{mins//1440} Days = ₹{price}\n"

    text += "\nPayment karne ke liye link par click kare."

    bot.send_message(message.chat.id, text)

# 🔥 Webhook (Razorpay)
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
                {
                    "$set": {
                        "expire": expire_time,
                        "warned": False
                    }
                },
                upsert=True
            )

            invite = bot.create_chat_invite_link(CHANNEL_ID, member_limit=1)

            bot.send_message(
                user_id,
                f"✅ Payment Success!\n\nJoin Link:\n{invite.invite_link}\n\n⏰ Expire: {expire_time}"
            )

    except Exception as e:
        print(e)

    return "OK", 200

# ⏱️ Background Checker
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

# ▶️ Thread start
Thread(target=checker).start()

# ▶️ Run Flask
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
