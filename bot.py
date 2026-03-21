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

# --- RENDER KEEP-ALIVE SERVER ---
app = Flask('')
@app.route('/')
def home(): 
    return "Bot is running and healthy!"

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# --- CONFIGURATION ---
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

# --- ADMIN COMMANDS ---

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
                bot.send_message(message.chat.id, 
                    f"✨ **Welcome to {ch_data['name']}**\n\nPlease select your plan for instant access:", 
                    reply_markup=markup, parse_mode="Markdown")
                return
        except: pass

    if user_id == ADMIN_ID:
        admin_text = "👑 **Admin Panel**\n/add - Add Channel\n/channels - Links\n/setlink - Set File Bot Link"
        bot.send_message(message.chat.id, admin_text, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "👋 Please use an official link to subscribe.")

@bot.message_handler(commands=['add'], func=lambda m: m.from_user.id == ADMIN_ID)
def start_add_process(message):
    sent = bot.send_message(ADMIN_ID, "➡️ **Forward** a message from the channel (Bot must be Admin).")
    bot.register_next_step_handler(sent, process_forwarded_msg)

def process_forwarded_msg(message):
    if message.forward_from_chat:
        ch_id = message.forward_from_chat.id
        ch_name = message.forward_from_chat.title
        sent = bot.send_message(ADMIN_ID, f"✅ Channel: {ch_name}\nEnter Plans (Min:Price):\n`1440:29, 43200:199`", parse_mode="Markdown")
        bot.register_next_step_handler(sent, save_channel_data, ch_id, ch_name)
    else:
        bot.send_message(ADMIN_ID, "❌ Error: Forward a message!")

def save_channel_data(message, ch_id, ch_name):
    try:
        plans_dict = {item.split(':')[0].strip(): item.split(':')[1].strip() for item in message.text.split(',')}
        channels_col.update_one({"channel_id": ch_id}, {"$set": {"name": ch_name, "plans": plans_dict, "admin_id": ADMIN_ID}}, upsert=True)
        link = f"https://t.me/{bot.get_me().username}?start={ch_id}"
        bot.send_message(ADMIN_ID, f"🎉 Success!\nLink: `{link}`", parse_mode="Markdown")
    except: bot.send_message(ADMIN_ID, "❌ Invalid format.")

@bot.message_handler(commands=['setlink'], func=lambda m: m.from_user.id == ADMIN_ID)
def set_file_bot_link(message):
    sent = bot.send_message(ADMIN_ID, "📧 Send the File Store Bot Link:")
    bot.register_next_step_handler(sent, lambda m: [settings_col.update_one({"id":"config"},{"$set":{"file_link":m.text}},upsert=True), bot.send_message(ADMIN_ID, "✅ Saved!")])

# --- PAYMENT HANDLING (FIXED QR) ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('sel_'))
def handle_plan_selection(call):
    _, ch_id, mins = call.data.split('_')
    ch_data = channels_col.find_one({"channel_id": int(ch_id)})
    price = ch_data['plans'][mins]
    
    # --- QR ENCODING FIX ---
    upi_payload = f"upi://pay?pa={UPI_ID}&pn=PrimeService&am={price}&cu=INR"
    encoded_upi = urllib.parse.quote(upi_payload)
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={encoded_upi}"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ I Have Paid", callback_data=f"paid_{ch_id}_{mins}"))
    cap = f"💰 **Payment**\nPlan: {mins} Min\nAmount: ₹{price}\nUPI: `{UPI_ID}`\n\nScan QR & send screenshot."
    bot.send_photo(call.message.chat.id, qr_api, caption=cap, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('paid_'))
def request_screenshot(call):
    _, ch_id, mins = call.data.split('_')
    sent = bot.send_message(call.message.chat.id, "📸 Send Payment Screenshot now.")
    bot.register_next_step_handler(sent, handle_admin_verification, ch_id, mins)

def handle_admin_verification(message, ch_id, mins):
    if message.content_type != 'photo': return
    user = message.from_user
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"app_{user.id}_{ch_id}_{mins}"), 
                                    InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user.id}")]])
    bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"🔔 Request!\nUser: {user.first_name}\nID: `{user.id}`\nPlan: {mins}", reply_markup=markup)
    bot.send_message(message.chat.id, "✅ Screenshot sent! Wait for approval.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('app_'))
def finalize_approval(call):
    _, u_id, ch_id, mins = call.data.split('_')
    cfg = settings_col.find_one({"id": "config"})
    f_link = cfg.get('file_link', 'Not Set') if cfg else 'Not Set'
    expiry = int((datetime.now() + timedelta(minutes=int(mins))).timestamp())
    users_col.update_one({"user_id": int(u_id)}, {"$set": {"expiry": expiry, "ch_id": int(ch_id)}}, upsert=True)
    bot.send_message(int(u_id), f"🥳 Approved!\n🔗 Access Link: {f_link}")
    bot.edit_message_caption("✅ Done!", call.message.chat.id, call.message.message_id)

# --- AUTO JOIN REQUEST HANDLER ---

@bot.chat_join_request_handler()
def handle_join_request(request):
    u_id = request.from_user.id
    u_data = users_col.find_one({"user_id": u_id})
    now = datetime.now().timestamp()

    if u_data and u_data.get('expiry', 0) > now:
        bot.approve_chat_join_request(request.chat.id, u_id)
        bot.send_message(u_id, "✅ Prime Member! Your request is auto-approved. Enjoy!")
    else:
        bot.send_message(u_id, "❌ Not a Prime Member! Pay first to join.")

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
    
