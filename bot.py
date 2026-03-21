import os
import telebot
import urllib.parse
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread

# --- RENDER KEEP-ALIVE ---
app = Flask('')
@app.route('/')
def home(): return "Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# --- CONFIG ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
UPI_ID = os.getenv('UPI_ID')
CONTACT_USERNAME = os.getenv('CONTACT_USERNAME')

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['sub_management']
channels_col = db['channels']
users_col = db['users']
settings_col = db['settings']

# --- COMMANDS ---

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    args = message.text.split()

    if len(args) > 1:
        try:
            ch_id = int(args[1])
            ch_data = channels_col.find_one({"channel_id": ch_id})
            if ch_data:
                markup = InlineKeyboardMarkup()
                for p_time, p_price in ch_data['plans'].items():
                    t_val = int(p_time)
                    label = f"{t_val} Min" if t_val < 60 else f"{t_val//1440} Days"
                    markup.add(InlineKeyboardButton(f"💳 {label} - ₹{p_price}", callback_data=f"sel_{ch_id}_{p_time}"))
                markup.add(InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{CONTACT_USERNAME}"))
                bot.send_message(message.chat.id, f"✨ **Welcome to {ch_data['name']}**\nSelect a plan:", reply_markup=markup, parse_mode="Markdown")
                return
        except: pass

    if user_id == ADMIN_ID:
        msg = "👑 **Admin Panel**\n\n/add - Add Channel\n/channels - Get Links\n/setlink - Set Final Link"
        bot.send_message(message.chat.id, msg, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "👋 Welcome! Use a valid link to subscribe.")

@bot.message_handler(commands=['channels'], func=lambda m: m.from_user.id == ADMIN_ID)
def list_channels(message):
    bot_username = bot.get_me().username
    # FIXED: Sabhi channels dikhayega bina kisi filter ke
    cursor = channels_col.find()
    msg_text = "📢 **Your Active Channels:**\n\n"
    count = 0
    for ch in cursor:
        link = f"https://t.me/{bot_username}?start={ch['channel_id']}"
        msg_text += f"📍 **Name:** {ch['name']}\n🔗 **Link:** `{link}`\n\n"
        count += 1
    
    if count == 0:
        bot.send_message(ADMIN_ID, "No channels found. Please use /add first.")
    else:
        bot.send_message(ADMIN_ID, msg_text, parse_mode="Markdown")

@bot.message_handler(commands=['add'], func=lambda m: m.from_user.id == ADMIN_ID)
def add_channel_start(message):
    sent = bot.send_message(ADMIN_ID, "➡️ **Forward** a message from the channel now.")
    bot.register_next_step_handler(sent, process_step_1)

def process_step_1(message):
    if message.forward_from_chat:
        ch_id = message.forward_from_chat.id
        ch_name = message.forward_from_chat.title
        sent = bot.send_message(ADMIN_ID, f"✅ Channel: {ch_name}\nEnter Plans (Min:Price):\nExample: `1440:29, 43200:199`", parse_mode="Markdown")
        bot.register_next_step_handler(sent, process_step_2, ch_id, ch_name)
    else:
        bot.send_message(ADMIN_ID, "❌ Error: Please FORWARD a message.")

def process_step_2(message, ch_id, ch_name):
    try:
        plans = {i.split(':')[0].strip(): i.split(':')[1].strip() for i in message.text.split(',')}
        channels_col.update_one({"channel_id": ch_id}, {"$set": {"name": ch_name, "plans": plans, "admin_id": ADMIN_ID}}, upsert=True)
        bot.send_message(ADMIN_ID, "🎉 Success! Use /channels to get the link.")
    except: bot.send_message(ADMIN_ID, "❌ Format error. Try /add again.")

@bot.message_handler(commands=['setlink'], func=lambda m: m.from_user.id == ADMIN_ID)
def set_link(message):
    sent = bot.send_message(ADMIN_ID, "📧 Send the link for users:")
    bot.register_next_step_handler(sent, save_link)

def save_link(message):
    settings_col.update_one({"id": "config"}, {"$set": {"file_link": message.text}}, upsert=True)
    bot.send_message(ADMIN_ID, "✅ Saved!")

# --- PAYMENTS (FIXED QR) ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('sel_'))
def pay_qr(call):
    _, ch_id, mins = call.data.split('_')
    ch_data = channels_col.find_one({"channel_id": int(ch_id)})
    price = ch_data['plans'][mins]
    
    upi_payload = f"upi://pay?pa={UPI_ID}&pn=Admin&am={price}&cu=INR"
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_payload)}"
    
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ I Have Paid", callback_data=f"paid_{ch_id}_{mins}")]])
    bot.send_photo(call.message.chat.id, qr_api, caption=f"💰 Pay ₹{price}\nUPI: `{UPI_ID}`", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('paid_'))
def ask_ss(call):
    sent = bot.send_message(call.message.chat.id, "📸 Send Screenshot now.")
    bot.register_next_step_handler(sent, verify_ss, call.data.split('_')[1], call.data.split('_')[2])

def verify_ss(message, ch_id, mins):
    if message.content_type != 'photo': return
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"app_{message.from_user.id}_{ch_id}_{mins}")]])
    bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"🔔 Request from {message.from_user.id}", reply_markup=markup)
    bot.send_message(message.chat.id, "⌛ Waiting for Admin...")

@bot.callback_query_handler(func=lambda call: call.data.startswith('app_'))
def approve(call):
    _, u_id, ch_id, mins = call.data.split('_')
    cfg = settings_col.find_one({"id": "config"})
    f_link = cfg.get('file_link', 'None')
    expiry = int((datetime.now() + timedelta(minutes=int(mins))).timestamp())
    users_col.update_one({"user_id": int(u_id)}, {"$set": {"expiry": expiry, "ch_id": int(ch_id)}}, upsert=True)
    bot.send_message(int(u_id), f"🥳 Approved!\nLink: {f_link}")
    bot.edit_message_caption("✅ Done", call.message.chat.id, call.message.message_id)

# --- AUTO APPROVE & KICK ---

@bot.chat_join_request_handler()
def handle_join(req):
    u = users_col.find_one({"user_id": req.from_user.id})
    if u and u.get('expiry', 0) > datetime.now().timestamp():
        bot.approve_chat_join_request(req.chat.id, req.from_user.id)
    else: bot.send_message(req.from_user.id, "❌ Pay first!")

def kick_expired():
    now = datetime.now().timestamp()
    for u in users_col.find({"expiry": {"$lte": now}}):
        try:
            bot.ban_chat_member(u['ch_id'], u['user_id'])
            bot.unban_chat_member(u['ch_id'], u['user_id'])
            users_col.delete_one({"_id": u['_id']})
        except: pass

if __name__ == '__main__':
    keep_alive()
    scheduler = BackgroundScheduler()
    scheduler.add_job(kick_expired, 'interval', minutes=1)
    scheduler.start()
    bot.infinity_polling()
    
