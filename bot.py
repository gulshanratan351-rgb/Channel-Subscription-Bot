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

# --- ADMIN PANEL & COMMANDS ---

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
        bot.send_message(message.chat.id, "✅ Admin Panel Active!\n\n/add - Add Channel\n/setlink - Set File Bot Link\n/channels - List Channels")
    else:
        bot.send_message(message.chat.id, "Welcome! To join, use the link provided by Admin.")

@bot.message_handler(commands=['add'], func=lambda m: m.from_user.id == ADMIN_ID)
def add_ch(message):
    msg = bot.send_message(ADMIN_ID, "Forward any message from the channel here (Bot must be Admin).")
    bot.register_next_step_handler(msg, get_plans)

def get_plans(message):
    if message.forward_from_chat:
        ch_id = message.forward_from_chat.id
        ch_name = message.forward_from_chat.title
        msg = bot.send_message(ADMIN_ID, f"Channel: {ch_name}\nEnter Plans (Min:Price):\nExample: `1440:99, 43200:299`")
        bot.register_next_step_handler(msg, finalize_ch, ch_id, ch_name)

def finalize_ch(message, ch_id, ch_name):
    try:
        raw = message.text.split(',')
        plans = {p.strip().split(':')[0]: p.strip().split(':')[1] for p in raw}
        channels_col.update_one({"channel_id": ch_id}, {"$set": {"name": ch_name, "plans": plans, "admin_id": ADMIN_ID}}, upsert=True)
        bot.send_message(ADMIN_ID, f"✅ Setup Success for {ch_name}!")
    except: bot.send_message(ADMIN_ID, "❌ Format Error.")

@bot.message_handler(commands=['setlink'], func=lambda m: m.from_user.id == ADMIN_ID)
def set_link(message):
    msg = bot.send_message(ADMIN_ID, "Send your **File Store Bot link**:")
    bot.register_next_step_handler(msg, save_link)

def save_link(message):
    db['settings'].update_one({"id": "bot_config"}, {"$set": {"file_link": message.text}}, upsert=True)
    bot.send_message(ADMIN_ID, "✅ Link Saved!")

# --- USER FLOW: PAYMENT & SCREENSHOT ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('select_'))
def show_qr(call):
    _, ch_id, mins = call.data.split('_')
    ch_data = channels_col.find_one({"channel_id": int(ch_id)})
    price = ch_data['plans'][mins]
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=upi://pay?pa={UPI_ID}%26am={price}%26cu=INR"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ I Have Paid", callback_data=f"paid_{ch_id}_{mins}"))
    bot.send_photo(call.message.chat.id, qr_url, caption=f"Pay ₹{price} to `{UPI_ID}` and click below.", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('paid_'))
def ask_screenshot(call):
    _, ch_id, mins = call.data.split('_')
    msg = bot.send_message(call.message.chat.id, "📸 **Kripya Payment ka Screenshot yahan bhejein.**")
    bot.register_next_step_handler(msg, forward_to_admin, ch_id, mins)

def forward_to_admin(message, ch_id, mins):
    if message.content_type != 'photo':
        msg = bot.send_message(message.chat.id, "❌ Sirf Photo bhejein!")
        bot.register_next_step_handler(msg, forward_to_admin, ch_id, mins)
        return
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Approve", callback_data=f"app_{message.from_user.id}_{ch_id}_{mins}"))
    markup.add(InlineKeyboardButton("❌ Reject", callback_data=f"rej_{message.from_user.id}"))
    
    bot.send_photo(ADMIN_ID, message.photo[-1].file_id, 
                   caption=f"🔔 **New Payment!**\nUser: {message.from_user.first_name}\nPlan: {mins} Mins", 
                   reply_markup=markup)
    bot.send_message(message.chat.id, "✅ Screenshot Admin ko bhej diya gaya hai.")

# --- APPROVAL & AUTO-APPROVE ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('app_'))
def approve_user(call):
    _, u_id, ch_id, mins = call.data.split('_')
    u_id, ch_id, mins = int(u_id), int(ch_id), int(mins)
    
    config = db['settings'].find_one({"id": "bot_config"})
    link = config.get('file_link', 'Link not set') if config else 'Link not set'
    expiry = int((datetime.now() + timedelta(minutes=mins)).timestamp())
    
    users_col.update_one({"user_id": u_id, "channel_id": ch_id}, {"$set": {"expiry": expiry}}, upsert=True)
    bot.send_message(u_id, f"🥳 **Approved!**\nAccess Link: {link}")
    bot.edit_message_caption("✅ Approved!", call.message.chat.id, call.message.message_id)

@bot.chat_join_request_handler()
def handle_join(request):
    user_id = request.from_user.id
    user_data = users_col.find_one({"user_id": user_id})
    if user_data and user_data.get('expiry', 0) > datetime.now().timestamp():
        bot.approve_chat_join_request(request.chat.id, user_id)
        bot.send_message(user_id, "✅ Welcome! Your Prime is active.")
    else:
        bot.send_message(user_id, "❌ Access Denied! Pay first.")

def kick_expired():
    now = datetime.now().timestamp()
    expired = users_col.find({"expiry": {"$lte": now}})
    for user in expired:
        try:
            bot.ban_chat_member(user['channel_id'], user['user_id'])
            bot.unban_chat_member(user['channel_id'], user['user_id'])
            users_col.delete_one({"_id": user['_id']})
        except: pass

if __name__ == '__main__':
    keep_alive()
    scheduler = BackgroundScheduler()
    scheduler.add_job(kick_expired, 'interval', minutes=1)
    scheduler.start()
    print("Bot is running...")
    bot.infinity_polling(timeout=20)
    
