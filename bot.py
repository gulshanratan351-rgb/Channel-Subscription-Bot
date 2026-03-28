import os
import telebot
import urllib.parse
import uuid
import datetime
import re
import threading
import random
import time
import logging
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from flask import Flask, request

# --- LOGGING SETUP ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
UPI_ID = os.getenv('UPI_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

# Multiple Channels Support (Comma separated in Render)
CHANNELS = [c.strip() for c in os.environ.get("CHANNEL", "").split(",") if c.strip()]

# Initializing Bot and DB
bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['sub_management']
users_col = db['users']
links_col = db['short_links']
temp_pay_col = db['temp_payments']

PLANS = {
    "1440": {"price": "29", "label": "1 Day"},
    "10080": {"price": "99", "label": "7 Days"},
    "43200": {"price": "199", "label": "30 Days"}
}

app = Flask(__name__)

# --- UTILITY FUNCTIONS ---

def get_expiry_date(minutes):
    return int((datetime.now() + timedelta(minutes=minutes)).timestamp())

def format_timestamp(ts):
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

def check_fsub(user_id):
    """Checks if user joined all required channels."""
    not_joined = []
    for channel in CHANNELS:
        try:
            chat_id = channel if channel.startswith("-100") else f"@{channel.replace('@', '')}"
            member = bot.get_chat_member(chat_id, user_id)
            if member.status not in ["member", "administrator", "creator", "owner"]:
                not_joined.append(channel)
        except Exception as e:
            logger.error(f"FSub Check Error for {channel}: {e}")
            not_joined.append(channel)
    return not_joined

# --- TIMER THREAD ---

def monitor_payment(chat_id, user_id, unique_amt):
    """Sends screenshot option only if payment isn't approved in 20 seconds."""
    time.sleep(20)
    # Check if the temporary payment record still exists
    record = temp_pay_col.find_one({"user_id": user_id, "amount": str(unique_amt)})
    
    if record:
        markup = InlineKeyboardMarkup()
        btn = InlineKeyboardButton("📸 Send Screenshot to Admin", url=f"tg://user?id={ADMIN_ID}")
        markup.add(btn)
        
        msg = (
            "❓ **Auto-Approval Pending...**\n\n"
            f"Bhai, ₹{unique_amt} ka payment system mein abhi tak nahi dikha.\n"
            "Agar aapne paise bhej diye hain, toh niche diye button se Admin ko Screenshot bhejein."
        )
        try:
            bot.send_message(chat_id, msg, reply_markup=markup)
        except Exception as e:
            logger.error(f"Timer Message Error: {e}")

# --- WEBHOOKS ---

@app.route('/')
def index():
    return {"status": "running", "bot": "DV Prime"}, 200

@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Unauthorized", 403

@app.route('/sms_webhook', methods=['GET', 'POST'])
def handle_sms():
    """Handles incoming SMS for auto-payment verification."""
    data = request.args if request.method == 'GET' else request.json
    sms_text = data.get('message', '').lower() if data else ""
    
    if not sms_text:
        return "No Message", 200

    logger.info(f"Incoming SMS: {sms_text}")
    bot.send_message(ADMIN_ID, f"📩 **New SMS Received:**\n`{sms_text}`")

    # Accurate regex for amount matching
    match = re.search(r'(\d+\.\d{2})', sms_text)
    if not match:
        return "No Amount Found", 200

    paid_amt = str(match.group(1))
    payment = temp_pay_col.find_one({"amount": paid_amt})

    if payment:
        user_id = payment['user_id']
        mins = int(payment['mins'])
        fid = payment.get('fid')

        # Activate Prime
        expiry = get_expiry_date(mins)
        users_col.update_one({"user_id": user_id}, {"$set": {"expiry": expiry}}, upsert=True)
        
        # Cleanup temp record to stop timer
        temp_pay_col.delete_one({"_id": payment['_id']})

        # Notify User
        success_msg = (
            "🎉 **Payment Successful!**\n\n"
            "Aapka Prime account activate ho gaya hai.\n"
            f"📅 **Expiry:** `{format_timestamp(expiry)}`"
        )
        bot.send_message(user_id, success_msg)

        # Immediate File Delivery
        if fid:
            link_data = links_col.find_one({"file_id": fid})
            if link_data:
                bot.send_message(user_id, f"🎁 **Aapka Requested Link:**\n{link_data['url']}")

        bot.send_message(ADMIN_ID, f"✅ **Auto-Approved:** User `{user_id}` paid ₹{paid_amt}")
        return "SUCCESS", 200

    return "Payment Record Not Found", 200

# --- BOT HANDLERS ---

@bot.message_handler(commands=['start'])
def handle_start(message):
    uid = message.from_user.id
    args = message.text.split()
    
    # 1. Force Join Check
    not_joined = check_fsub(uid)
    if not_joined:
        markup = InlineKeyboardMarkup()
        for ch in not_joined:
            markup.add(InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{ch}"))
        
        return bot.send_message(
            message.chat.id, 
            "🚫 **Access Denied!**\n\nSaare channels join karke phir se /start dabayein.",
            reply_markup=markup
        )

    # 2. Process File ID if exists
    if len(args) > 1 and args[1].startswith('vid_'):
        fid = args[1].replace('vid_', '')
        link_data = links_col.find_one({"file_id": fid})
        
        if link_data:
            user = users_col.find_one({"user_id": uid})
            if user and user.get('expiry', 0) > datetime.now().timestamp():
                bot.send_message(uid, f"✅ **Link Access Granted:**\n{link_data['url']}")
            else:
                markup = InlineKeyboardMarkup()
                for mins, data in PLANS.items():
                    markup.add(InlineKeyboardButton(f"💳 {data['label']} - ₹{data['price']}", callback_data=f"pay_{fid}_{mins}_{data['price']}"))
                bot.send_message(uid, "🔒 **Prime Required!**\n\nIs link ko dekhne ke liye subscription lein:", reply_markup=markup)
            return

    # 3. Standard Welcome
    welcome_txt = "👋 **Welcome to DV Prime Bot!**\n\nStatus: "
    user = users_col.find_one({"user_id": uid})
    if user and user.get('expiry', 0) > datetime.now().timestamp():
        welcome_txt += f"✅ **Active** until {format_timestamp(user['expiry'])}"
    else:
        welcome_txt += "❌ **No Active Plan**"
    
    if uid == ADMIN_ID:
        welcome_txt += "\n\n👑 **Admin Commands:**\n/short - Create Link\n/stats - User Stats\n/broadcast - Send Global MSG\n/approve ID Days\n/deactivate ID"
        
    bot.send_message(uid, welcome_txt)

@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_'))
def process_payment_step(call):
    _, fid, mins, base_price = call.data.split('_')
    
    # Generate unique decimal to track payment (e.g., 29.45)
    unique_amt = f"{base_price}.{random.randint(10, 99)}"
    
    temp_pay_col.update_one(
        {"user_id": call.from_user.id},
        {"$set": {"amount": unique_amt, "mins": mins, "fid": fid, "timestamp": datetime.now()}},
        upsert=True
    )

    upi_link = f"upi://pay?pa={UPI_ID}&am={unique_amt}&cu=INR&tn=Prime_Sub"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={urllib.parse.quote(upi_link)}&margin=10"

    caption = (
        f"💳 **Payment Invoice**\n\n"
        f"💵 Amount: `₹{unique_amt}`\n"
        f"⏳ Time Limit: 15 Minutes\n\n"
        "⚠️ **IMPORTANT:** Pura amount bhejyein (Paise ke saath) varna auto-approval nahi hoga.\n\n"
        "Payment ke baad 15-20 seconds wait karein."
    )
    
    bot.send_photo(call.message.chat.id, qr_url, caption=caption, parse_mode="Markdown")
    
    # Start the monitoring thread
    threading.Thread(target=monitor_payment, args=(call.message.chat.id, call.from_user.id, unique_amt)).start()

# --- ADMIN FUNCTIONS ---

@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def admin_short(message):
    msg = bot.send_message(ADMIN_ID, "🔗 Please send the URL you want to shorten:")
    bot.register_next_step_handler(msg, save_short_link)

def save_short_link(message):
    if not message.text or not message.text.startswith('http'):
        return bot.send_message(ADMIN_ID, "❌ Invalid URL. Try again.")
    
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text, "created_at": datetime.now()})
    
    bot_link = f"https://t.me/{bot.get_me().username}?start=vid_{fid}"
    bot.send_message(ADMIN_ID, f"✅ **Link Created!**\n\n`{bot_link}`")

@bot.message_handler(commands=['stats'], func=lambda m: m.from_user.id == ADMIN_ID)
def admin_stats(message):
    total = users_col.count_documents({})
    active = users_col.count_documents({"expiry": {"$gt": datetime.now().timestamp()}})
    bot.send_message(ADMIN_ID, f"📊 **Bot Statistics**\n\nTotal Database Users: `{total}`\nActive Prime Users: `{active}`")

@bot.message_handler(commands=['approve'], func=lambda m: m.from_user.id == ADMIN_ID)
def admin_approve(message):
    try:
        _, target_id, days = message.text.split()
        expiry = get_expiry_date(int(days) * 1440)
        users_col.update_one({"user_id": int(target_id)}, {"$set": {"expiry": expiry}}, upsert=True)
        bot.send_message(target_id, "✅ **Prime Activated by Admin!**")
        bot.send_message(ADMIN_ID, f"✅ User `{target_id}` approved for {days} days.")
    except:
        bot.send_message(ADMIN_ID, "❌ Format: `/approve ID Days`")

@bot.message_handler(commands=['deactivate'], func=lambda m: m.from_user.id == ADMIN_ID)
def admin_deactivate(message):
    try:
        target_id = int(message.text.split()[1])
        users_col.delete_one({"user_id": target_id})
        bot.send_message(ADMIN_ID, f"🚫 User `{target_id}` prime deactivated.")
    except:
        bot.send_message(ADMIN_ID, "❌ Format: `/deactivate ID`")

@bot.message_handler(commands=['broadcast'], func=lambda m: m.from_user.id == ADMIN_ID)
def admin_broadcast(message):
    msg = bot.send_message(ADMIN_ID, "📢 Send the message for broadcast:")
    bot.register_next_step_handler(msg, run_broadcast)

def run_broadcast(message):
    users = users_col.find({})
    count = 0
    for user in users:
        try:
            bot.send_message(user['user_id'], message.text)
            count += 1
            time.sleep(0.05) # Prevent flood
        except: continue
    bot.send_message(ADMIN_ID, f"📢 Broadcast finished. Sent to `{count}` users.")

# --- EXECUTION ---

if __name__ == '__main__':
    # Webhook setup
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    logger.info(f"Bot Webhook set to {WEBHOOK_URL}")
    
    # Run Flask
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
    
