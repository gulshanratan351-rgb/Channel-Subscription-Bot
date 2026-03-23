import os, telebot, urllib.parse, uuid, datetime, re, threading, random
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from flask import Flask, request

# --- CONFIG ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
UPI_ID = os.getenv('UPI_ID')
# Aapka Render URL (Pura link)
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://channel-subscription-bot-4nav.onrender.com')

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['sub_management']
users_col = db['users']
links_col = db['short_links']
temp_pay_col = db['temp_payments']

PLANS = {"1440": "29", "10080": "99", "43200": "199"}
app = Flask(__name__)

@app.route('/')
def home(): return "Bot is Online!"

# --- WEBHOOK HANDLER (Very Important) ---
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Forbidden", 403

# --- START HANDLER (Sabse Pehle Link Check Karega) ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    uid = message.from_user.id
    text = message.text # Ye "/start vid_77521f90" jaisa hota hai

    # 1. Check agar link parameter (vid_...) ke sath aaya hai
    if len(text.split()) > 1:
        param = text.split()[1] # Ye "vid_77521f90" nikal lega
        
        if param.startswith('vid_'):
            fid = param.replace('vid_', '').strip()
            link_obj = links_col.find_one({"file_id": fid})
            
            if link_obj:
                u_data = users_col.find_one({"user_id": uid})
                # Prime Expiry Check
                if u_data and u_data.get('expiry', 0) > datetime.now().timestamp():
                    bot.send_message(uid, f"✅ **Access Granted!**\n\n📂 **Link:** {link_obj['url']}")
                else:
                    # Agar prime nahi hai toh PRICE LIST dikhao
                    markup = InlineKeyboardMarkup()
                    for mins, price in PLANS.items():
                        label = f"{int(mins)//1440} Day" if int(mins) >= 1440 else f"{mins} Min"
                        markup.add(InlineKeyboardButton(f"💳 {label} - ₹{price}", callback_data=f"p_{fid}_{mins}_{price}"))
                    bot.send_message(uid, "🔒 **Prime Required!**\nAuto-approval system active hai. Plan choose karein:", reply_markup=markup)
                return
            else:
                bot.send_message(uid, "❌ Sorry, ye link expire ho gaya hai.")
                return

    # 2. Normal Start (Jab bina link ke /start likhein)
    if uid == ADMIN_ID:
        bot.send_message(uid, "👑 **ADMIN PANEL**\n/short - Create Link\n/stats - Check Users\n/broadcast - Message All")
    else:
        bot.send_message(uid, "👋 Welcome! Link par click karke bot use karein.")

# --- BROADCAST FEATURE ---
@bot.message_handler(commands=['broadcast'], func=lambda m: m.from_user.id == ADMIN_ID)
def broadcast_cmd(message):
    msg = bot.send_message(ADMIN_ID, "📢 Kya message bhejna hai sabko?")
    bot.register_next_step_handler(msg, send_to_all)

def send_to_all(message):
    users = users_col.find({})
    count = 0
    for u in users:
        try:
            bot.send_message(u['user_id'], message.text)
            count += 1
        except: continue
    bot.send_message(ADMIN_ID, f"✅ Broadcast Done! {count} users ko mila.")

# --- PAYMENT PROCESS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, base_price = call.data.split('_')
    unique_price = f"{base_price}.{random.randint(10, 99)}"
    temp_pay_col.update_one({"user_id": call.from_user.id}, {"$set": {"amount": unique_price, "mins": mins, "time": datetime.now()}}, upsert=True)
    
    # UPI QR Generator
    upi_url = f"upi://pay?pa={UPI_ID}&am={unique_price}&cu=INR"
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_url)}"
    bot.send_photo(call.message.chat.id, qr_api, caption=f"⚠️ **DHYAN SE:**\nExactly **₹{unique_price}** hi pay karein.\n\nBot 1 min mein auto-approve kar dega.")

# --- CREATE LINK ---
@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🔗 File Link bhejein:")
    bot.register_next_step_handler(msg, process_short)

def process_short(message):
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    bot.send_message(ADMIN_ID, f"✅ Link: `https://t.me/{bot.get_me().username}?start=vid_{fid}`")

# --- STATS ---
@bot.message_handler(commands=['stats'], func=lambda m: m.from_user.id == ADMIN_ID)
def stats_cmd(message):
    active = users_col.count_documents({"expiry": {"$gt": datetime.now().timestamp()}})
    bot.send_message(ADMIN_ID, f"📊 Total Active Prime Users: `{active}`")

# --- MAIN ---
if __name__ == '__main__':
    bot.remove_webhook()
    import time
    time.sleep(2)
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
    
