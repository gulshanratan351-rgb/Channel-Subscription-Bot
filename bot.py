import os
import telebot
from pymongo import MongoClient
from flask import Flask
from threading import Thread
import re

# Flask setup for Render
app = Flask('')
@app.route('/')
def home(): return "I am alive"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# Bot Setup
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
bot = telebot.TeleBot(TOKEN)
client = MongoClient(MONGO_URI)
db = client['subscription_bot']

def parse_plans(text):
    pattern = r'(\d+)\s*[:]\s*(\d+)'
    matches = re.findall(pattern, text)
    return {m[0]: m[1] for m in matches} if matches else None

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "✅ Admin Panel Active!\n/add - Setup Channel\n/channels - Manage")

@bot.message_handler(commands=['add'])
def add_init(message):
    msg = bot.reply_to(message, "1. Channel se message FORWARD karein.")
    bot.register_next_step_handler(msg, process_step_1)

def process_step_1(message):
    if message.forward_from_chat:
        c_id, c_name = message.forward_from_chat.id, message.forward_from_chat.title
        msg = bot.reply_to(message, f"Detected: {c_name}\nAb Plans bhejein (Min:Price).")
        bot.register_next_step_handler(msg, process_step_2, c_id, c_name)
    else:
        bot.reply_to(message, "❌ Message forward nahi kiya gaya.")

def process_step_2(message, c_id, c_name):
    plans = parse_plans(message.text)
    if plans:
        # Yahan hum data save kar rahe hain aur confirmation BHEJ RAHE HAIN
        db.channels.update_one({'channel_id': c_id}, {'$set': {'name': c_name, 'plans': plans}}, upsert=True)
        bot.send_message(message.chat.id, f"✅ SETUP DONE!\n\nChannel: {c_name}\nPlans: {plans}\n\nAb users bot use kar sakte hain.")
    else:
        bot.reply_to(message, "❌ Invalid format. Sirf '1440:30' jaise likhein.")

if __name__ == "__main__":
    keep_alive()
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
    
