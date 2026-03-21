import os
import telebot
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread

# --- RENDER KEEP-ALIVE SERVER ---
app = Flask('')
@app.route('/')
def home(): return "Bot is running and healthy!"

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    Thread(target=run_web).start()

# --- CONFIGURATION (Environment Variables) ---
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

# --- ADMIN LOGIC ---

@bot.message_handler(commands=['start'])
def start_handler(message):
    user_id = message.from_user.id
    text = message.text.split()

    if len(text) > 1:
        try:
            ch_id = int(text[1])
            ch_data = channels_col.find_one({"channel_id": ch_id})
            if ch_data:
                markup = InlineKeyboardMarkup()
                for p_time, p_price in ch_data['plans'].items():
                    label = f"{p_time} Min" if int(p_time) < 60 else f"{int(p_time)//1440} Days"
                    markup.add(InlineKeyboardButton(f"💳 {label} - ₹{p_price}", callback_data=f"select_{ch_id}_{p_time}"))
                
                markup.add(InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{CONTACT_USERNAME}"))
                bot.send_message(message.chat.id, 
                    f"Welcome!\n\nYou are joining: *{ch_data['name']}*.\n\nPlease select a subscription plan below:", 
                    reply_markup=markup, parse_mode="Markdown")
                return
        except: pass

    if user_id == ADMIN_ID:
        bot.send_message(message.chat.id, "✅ Admin Panel Active!\n\n/add - Add/Edit Channel\n/setlink - Set File Link\n/channels - Manage Channels")
    else:
        bot.send_message(message.chat.id, "Welcome! To join a channel, please use the link provided by the Admin.")

@bot.message_handler(commands=['channels'], func=lambda m: m.from_user.id == ADMIN_ID)
def list_channels(message):
    markup = InlineKeyboardMarkup()
    cursor = channels_col.find({"admin_id": ADMIN_ID})
    count = 0
    for ch in cursor:
        markup.add(InlineKeyboardButton(f"Channel: {ch['name']}", callback_data=f"manage_{ch['channel_id']}"))
        count += 1
    markup.add(InlineKeyboardButton("➕ Add New Channel", callback_data="add_new"))
    bot.send_message(ADMIN_ID, "Your Managed Channels:", reply_markup=markup)

@bot.message_handler(commands=['add'], func=lambda m: m.from_user.id == ADMIN_ID)
def add_channel_start(message):
    msg = bot.send_message(ADMIN_ID, "Please FORWARD any message from that channel (Bot must be Admin there).")
    bot.register_next_step_handler(msg, get_plans)

@bot.message_handler(commands=['setlink'], func=lambda m: m.from_user.id == ADMIN_ID)
def set_file_link(message):
    msg = bot.send_message(ADMIN_ID, "📧 Send your **File Store Bot link**:")
    bot.register_next_step_handler(msg, save_file_link)

def save_file_link(message):
    new_link = message.text
    db['settings'].update_one({"id": "bot_config"}, {"$set": {"file_link": new_link}}, upsert=True)
    bot.send_message(ADMIN_ID, f"✅ Link Saved:\n`{new_link}`", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "add_new")
def cb_add_new(call):
    msg = bot.send_message(ADMIN_ID, "Please FORWARD any message from your channel here.")
    bot.register_next_step_handler(msg, get_plans)

def get_plans(message):
    if message.forward_from_chat:
        ch_id = message.forward_from_chat.id
        ch_name = message.forward_from_chat.title
        msg = bot.send_message(ADMIN_ID, 
            f"Channel: *{ch_name}*\nEnter plans (Min:Price):\nExample: `1440:99, 43200:199`", parse_mode="Markdown")
        bot.register_next_step_handler(msg, finalize_channel, ch_id, ch_name)
    else:
        bot.send_message(ADMIN_ID, "❌ Error: Message not forwarded.")

def finalize_channel(message, ch_id, ch_name):
    try:
        raw_plans = message.text.split(',')
        plans_dict = {p.strip().split(':')[0]: p.strip().split(':')[1] for p in raw_plans}
        channels_col.update_one({"channel_id": ch_id}, {"$set": {"name": ch_name, "plans": plans_dict, "admin_id": ADMIN_ID}}, upsert=True)
        bot.send_message(ADMIN_ID, f"✅ Setup Successful for {ch_name}!")
    except:
        bot.send_message(ADMIN_ID, "❌ Invalid format.")

# --- PAYMENT FLOW ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_'))
def user_pays(call):
    _, ch_id, mins = call.data.split('_')
    ch_data = channels_col.find_one({"channel_id": int(ch_id)})
    price = ch_data['plans'][mins]
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=upi://pay?pa={UPI_ID}%26am={price}%26cu=INR"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ I Have Paid", callback_data=f"paid_{ch_id}_{mins}"))
    bot.send_photo(call.message.chat.id, qr_url, caption=f"Pay ₹{price} to `{UPI_ID}` and click button.", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('paid_'))
def admin_notify(call):
    _, ch_id, mins = call.data.split('_')
    user = call.from_user
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Approve", callback_data=f"app_{user.id}_{ch_id}_{mins}"))
    markup.add(InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user.id}"))
    bot.send_message(ADMIN_ID, f"🔔 Payment from {user.first_name}\nPlan: {mins} Mins", reply_markup=markup)
    bot.send_message(call.message.chat.id, "✅ Request sent to Admin.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('app_'))
def approve_now(call):
    _, u_id, ch_id, mins = call.data.split('_')
    u_id, ch_id, mins = int(u_id), int(ch_id), int(mins)
    config = db['settings'].find_one({"id": "bot_config"})
    final_link = config.get('file_link', 'Link not set!') if config else 'Link not set!'
    expiry_ts = int((datetime.now() + timedelta(minutes=mins)).timestamp())
    users_col.update_one({"user_id": u_id, "channel_id": ch_id}, {"$set": {"expiry": expiry_ts}}, upsert=True)
    bot.send_message(u_id, f"🥳 Approved!\nLink: {final_link}")
    bot.edit_message_text("✅ Approved!", call.message.chat.id, call.message.message_id)

# --- AUTO APPROVE LOGIC ---
@bot.chat_join_request_handler()
def handle_join_request(request):
    user_id = request.from_user.id
    chat_id = request.chat.id
    user_data = users_col.find_one({"user_id": user_id})
    if user_data and user_data.get('expiry', 0) > datetime.now().timestamp():
        try:
            bot.approve_chat_join_request(chat_id, user_id)
            bot.send_message(user_id, "✅ Welcome! Your Prime is active.")
        except: pass
    else:
        bot.send_message(user_id, "❌ Prime active nahi hai. Pehle pay karein.")

def kick_expired_users():
    now = datetime.now().timestamp()
    expired_users = users_col.find({"expiry": {"$lte": now}})
    for user in expired_users:
        try:
            bot.ban_chat_member(user['channel_id'], user['user_id'])
            bot.unban_chat_member(user['channel_id'], user['user_id'])
            users_col.delete_one({"_id": user['_id']})
        except: pass

if __name__ == '__main__':
    keep_alive()
    scheduler = BackgroundScheduler()
    scheduler.add_job(kick_expired_users, 'interval', minutes=1)
    scheduler.start()
    print("Bot is running...")
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
    
