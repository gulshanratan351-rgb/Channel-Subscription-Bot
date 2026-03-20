import os
import telebot
from flask import Flask, request
from datetime import datetime, timedelta
from threading import Thread
import time

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# 🗄️ simple storage (demo)
users = {}

# 💰 Plans (minutes : price)
PLANS = {
    60: 10,        # 1 hour = ₹10
    1440: 30,      # 1 day = ₹30
    43200: 199     # 30 days = ₹199
}

# ▶️ START
@bot.message_handler(commands=['start'])
def start(message):
    text = "💳 Plans:\n\n"
    for mins, price in PLANS.items():
        text += f"{mins//60} hrs / days = ₹{price}\n"

    bot.send_message(message.chat.id, text)

# 🔥 Webhook (Payment Success)
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json

    try:
        if data.get("event") == "payment.captured":
            payment = data["payload"]["payment"]["entity"]

            user_id = int(payment["notes"]["user_id"])
            minutes = int(payment["notes"]["plan"])

            expire_time = datetime.now() + timedelta(minutes=minutes)

            users[user_id] = {
                "expire": expire_time,
                "warned": False
            }

            invite = bot.create_chat_invite_link(CHANNEL_ID, member_limit=1)

            bot.send_message(
                user_id,
                f"✅ Payment Success!\n\nJoin:\n{invite.invite_link}\n\n⏰ Expire: {expire_time}"
            )

    except Exception as e:
        print(e)

    return "OK", 200

# ⏱️ Background checker
def checker():
    while True:
        now = datetime.now()

        for user_id, data in list(users.items()):
            expire = data["expire"]

            # ⚠️ 1 hour warning
            if not data["warned"] and (expire - now).total_seconds() <= 3600:
                bot.send_message(user_id, "⚠️ Your subscription will expire in 1 hour!")
                users[user_id]["warned"] = True

            # ❌ Remove after expiry
            if now >= expire:
                try:
                    bot.ban_chat_member(CHANNEL_ID, user_id)
                    bot.unban_chat_member(CHANNEL_ID, user_id)
                except:
                    pass

                bot.send_message(user_id, "❌ Subscription expired!")
                del users[user_id]

        time.sleep(30)

# ▶️ Start background thread
Thread(target=checker).start()

# ▶️ Run Flask
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
