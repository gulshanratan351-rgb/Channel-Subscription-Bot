import os
import telebot
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread

# --- RENDER KEEP-ALIVE SERVER (DO NOT REMOVE) ---
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
    bot_username = bot.get_me().username
    args = message.text.split()

    # User coming from a specific channel link
    if len(args) > 1:
        try:
            ch_id = int(args[1])
            ch_data = channels_col.find_one({"channel_id": ch_id})
            if ch_data:
                markup = InlineKeyboardMarkup()
                for p_time, p_price in ch_data['plans'].items():
                    # Format label: Minutes to Days conversion
                    t_val = int(p_time)
                    label = f"{t_val} Min" if t_val < 60 else f"{t_val//1440} Days"
                    markup.add(InlineKeyboardButton(f"💳 {label} - ₹{p_price}", callback_data=f"sel_{ch_id}_{p_time}"))
                
                markup.add(InlineKeyboardButton("📞 Contact Admin", url=f"https://t.me/{CONTACT_USERNAME}"))
                bot.send_message(message.chat.id, 
                    f"✨ **Welcome to {ch_data['name']}**\n\nPlease select your preferred subscription plan to get instant access:", 
                    reply_markup=markup, parse_mode="Markdown")
                return
        except Exception as e:
            print(f"Start Error: {e}")

    # Default Start
    if user_id == ADMIN_ID:
        admin_text = (
            "👑 **Admin Control Panel**\n\n"
            "/add - Add a new channel & set prices\n"
            "/channels - View all managed channels & links\n"
            "/setlink - Set the File Store Bot link\n"
            "/stats - Check total prime users"
        )
        bot.send_message(message.chat.id, admin_text, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "👋 Welcome! Please use an official link to subscribe to our channels.")

@bot.message_handler(commands=['channels'], func=lambda m: m.from_user.id == ADMIN_ID)
def list_all_channels(message):
    bot_username = bot.get_me().username
    cursor = channels_col.find({"admin_id": ADMIN_ID})
    msg_text = "📢 **Your Active Channels:**\n\n"
    count = 0
    for ch in cursor:
        link = f"https://t.me/{bot_username}?start={ch['channel_id']}"
        msg_text += f"📍 **Name:** {ch['name']}\n🔗 **Link:** `{link}`\n\n"
        count += 1
    
    if count == 0:
        bot.send_message(ADMIN_ID, "No channels added yet. Use /add")
    else:
        bot.send_message(ADMIN_ID, msg_text, parse_mode="Markdown")

@bot.message_handler(commands=['add'], func=lambda m: m.from_user.id == ADMIN_ID)
def start_add_process(message):
    sent = bot.send_message(ADMIN_ID, "➡️ Please **Forward** any message from the target channel here.\n(Make sure the bot is an Admin in that channel first)")
    bot.register_next_step_handler(sent, process_forwarded_msg)

def process_forwarded_msg(message):
    if message.forward_from_chat:
        ch_id = message.forward_from_chat.id
        ch_name = message.forward_from_chat.title
        instr = (
            f"✅ **Channel Detected:** {ch_name}\n\n"
            "Enter plans in this format (Minutes:Price):\n"
            "`1440:29, 43200:199`"
        )
        sent = bot.send_message(ADMIN_ID, instr, parse_mode="Markdown")
        bot.register_next_step_handler(sent, save_channel_data, ch_id, ch_name)
    else:
        bot.send_message(ADMIN_ID, "❌ Error: You didn't forward a message. Try /add again.")

def save_channel_data(message, ch_id, ch_name):
    try:
        raw_input = message.text.split(',')
        plans_dict = {}
        for item in raw_input:
            t, p = item.strip().split(':')
            plans_dict[t] = p
        
        channels_col.update_one(
            {"channel_id": ch_id}, 
            {"$set": {"name": ch_name, "plans": plans_dict, "admin_id": ADMIN_ID}}, 
            upsert=True
        )
        bot_username = bot.get_me().username
        final_link = f"https://t.me/{bot_username}?start={ch_id}"
        bot.send_message(ADMIN_ID, f"🎉 **Success!**\n\nChannel: {ch_name}\nLink: `{final_link}`", parse_mode="Markdown")
    except:
        bot.send_message(ADMIN_ID, "❌ Invalid format. Please use /add and try again.")

@bot.message_handler(commands=['setlink'], func=lambda m: m.from_user.id == ADMIN_ID)
def set_file_bot_link(message):
    sent = bot.send_message(ADMIN_ID, "📧 Send the **URL** of your File Store Bot (or any link users get after payment):")
    bot.register_next_step_handler(sent, save_final_link)

def save_final_link(message):
    settings_col.update_one({"id": "config"}, {"$set": {"file_link": message.text}}, upsert=True)
    bot.send_message(ADMIN_ID, f"✅ **Link Saved!**\nUsers will see: {message.text}")

# --- PAYMENT & SCREENSHOT HANDLING ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('sel_'))
def handle_plan_selection(call):
    _, ch_id, mins = call.data.split('_')
    ch_data = channels_col.find_one({"channel_id": int(ch_id)})
    price = ch_data['plans'][mins]
    
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=upi://pay?pa={UPI_ID}%26am={price}%26cu=INR"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ I Have Paid", callback_data=f"paid_{ch_id}_{mins}"))
    
    cap = f"💰 **Payment Details**\n\nPlan: {mins} Minutes\nAmount: ₹{price}\nUPI ID: `{UPI_ID}`\n\nPay via QR and click the button below to send screenshot."
    bot.send_photo(call.message.chat.id, qr_api, caption=cap, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('paid_'))
def request_screenshot(call):
    _, ch_id, mins = call.data.split('_')
    sent = bot.send_message(call.message.chat.id, "📸 **Please send the Payment Screenshot now.**\nAdmin will verify it shortly.")
    bot.register_next_step_handler(sent, handle_admin_verification, ch_id, mins)

def handle_admin_verification(message, ch_id, mins):
    if message.content_type != 'photo':
        sent = bot.send_message(message.chat.id, "❌ Error: Please send a **Photo**. Try clicking 'I Have Paid' again.")
        return

    user = message.from_user
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Approve", callback_data=f"app_{user.id}_{ch_id}_{mins}"))
    markup.add(InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user.id}"))
    
    bot.send_photo(ADMIN_ID, message.photo[-1].file_id, 
                   caption=f"🔔 **New Verification Request!**\n\nUser: {user.first_name}\nID: `{user.id}`\nPlan: {mins} Mins", 
                   reply_markup=markup, parse_mode="Markdown")
    bot.send_message(message.chat.id, "✅ Screenshot sent! Please wait for Admin approval.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('app_'))
def finalize_approval(call):
    _, u_id, ch_id, mins = call.data.split('_')
    u_id, ch_id, mins = int(u_id), int(ch_id), int(mins)
    
    # Get saved link
    cfg = settings_col.find_one({"id": "config"})
    f_link = cfg.get('file_link', 'Not Set') if cfg else 'Not Set'
    
    expiry_ts = int((datetime.now() + timedelta(minutes=mins)).timestamp())
    users_col.update_one({"user_id": u_id, "channel_id": ch_id}, {"$set": {"expiry": expiry_ts}}, upsert=True)
    
    bot.send_message(u_id, f"🥳 **Congratulations!**\nYour payment is approved.\n\n🔗 **Access Link:** {f_link}")
    bot.edit_message_caption("✅ Approved and Database Updated!", call.message.chat.id, call.message.message_id)

# --- AUTO JOIN & EXPIRY SYSTEM ---

@bot.chat_join_request_handler()
def auto_approve_logic(request):
    u_id = request.from_user.id
    u_data = users_col.find_one({"user_id": u_id})
    
    if u_data and u_data.get('expiry', 0) > datetime.now().timestamp():
        bot.approve_chat_join_request(request.chat.id, u_id)
        bot.send_message(u_id, "✅ **Welcome!** Your join request was automatically approved because you are a Prime Member.")
    else:
        bot.send_message(u_id, "❌ **Access Denied!** You don't have an active subscription. Please pay first.")

def kick_expired_members():
    now = datetime.now().timestamp()
    expired = users_col.find({"expiry": {"$lte": now}})
    for u in expired:
        try:
            bot.ban_chat_member(u['channel_id'], u['user_id'])
            bot.unban_chat_member(u['channel_id'], u['user_id'])
            users_col.delete_one({"_id": u['_id']})
        except: pass

# --- RUN BOT ---
if __name__ == '__main__':
    keep_alive()
    scheduler = BackgroundScheduler()
    scheduler.add_job(kick_expired_members, 'interval', minutes=1)
    scheduler.start()
    print("Bot is starting...")
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
    
