import os
import telebot
from pymongo import MongoClient
from flask import Flask
from threading import Thread
import re

# --- FLASK SERVER FOR RENDER ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is Running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- BOT LOGIC ---
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
bot = telebot.TeleBot(TOKEN)
client = MongoClient(MONGO_URI)
db = client['subscription_bot']

# --- SMART PARSER (Galti Sudharne Wala Function) ---
def parse_plans(text):
    # Ye line text mein se sirf "number:number" dhoondti hai
    pattern = r'(\d+)\s*[:]\s*(\d+)'
    matches = re.findall(pattern, text)
    if not matches:
        return None
    return {m[0]: m[1] for m in matches}

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "✅ Bot Active! Use /add to setup.")

@bot.message_handler(commands=['add'])
def add_channel(message):
    msg = bot.reply_to(message, "1. Apne Channel se koi message FORWARD karein.")
    bot.register_next_step_handler(msg, process_channel)

def process_channel(message):
    if message.forward_from_chat:
        channel_id = message.forward_from_chat.id
        channel_name = message.forward_from_chat.title
        msg = bot.reply_to(message, f"Detected: {channel_name}\nAb Plans likhein. Example: 1440:30, 43200:199 (Aap kuch bhi likh sakte hain, bot sirf numbers utha lega).")
        bot.register_next_step_handler(msg, save_plans, channel_id, channel_name)
    else:
        bot.reply_to(message, "❌ Error: Message forward nahi kiya gaya.")

def save_plans(message, channel_id, channel_name):
    plans = parse_plans(message.text)
    if plans:
        db.channels.update_one(
            {'channel_id': channel_id},
            {'$set': {'name': channel_name, 'plans': plans}},
            upsert=True
        )
        bot.reply_to(message, f"✅ Setup Successful for {channel_name}!\nPlans: {plans}")
    else:
        bot.reply_to(message, "❌ Invalid Format! Sirf 'Minutes:Price' likhein.")

if __name__ == "__main__":
    keep_alive() # Flask start karega
    print("Bot is starting...")
    bot.infinity_polling()
    
