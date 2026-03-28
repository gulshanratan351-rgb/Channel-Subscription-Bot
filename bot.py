"""
🚀 PROJECT: DV PRIME MANAGEMENT BOT (ULTRALITE EDITION)
🛠️ FEATURES: Auto-Payment, Multi-FSub, File Storage, Admin Dashboard
📅 UPDATED: March 2026
"""

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

# ==========================================
# ⚙️ CONFIGURATION & LOGGING
# ==========================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment Variables se data uthana
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
UPI_ID = os.getenv('UPI_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

# Channels for Force Join (Comma separated: "channel1,channel2")
FSUB_CHANNELS = [c.strip() for c in os.environ.get("CHANNELS", "").split(",") if c.strip()]

# Database Connection
bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['dv_prime_db']
users_col = db['users']
links_col = db['file_links']
temp_pay_col = db['pending_payments']

# Subscription Plans
PLANS = {
    "1440": {"price": "29", "name": "1 Day Prime"},
    "10080": {"price": "99", "name": "7 Days Weekly"},
    "43200": {"price": "199", "name": "30 Days Monthly"}
}

app = Flask(__name__)

# ==========================================
# 🛠️ HELPER FUNCTIONS
# ==========================================

def is_prime(user_id):
    """Checks if a user has an active subscription."""
    user = users_col.find_one({"user_id": user_id})
    if user and user.get('expiry', 0) > datetime.now().timestamp():
        return True, user['expiry']
    return False, 0

def get_fsub_status(user_id):
    """Checks which channels the user hasn't joined yet."""
    left_channels = []
    for channel in FSUB_CHANNELS:
        try:
            status = bot.get_chat_member(f"@{channel.replace('@','')}", user_id).status
            if status not in ['member', 'administrator', 'creator']:
                left_channels.append(channel)
        except Exception as e:
            logger.error(f"FSub Error for {channel}: {e}")
            # Agar bot admin nahi hai toh skip karega
    return left_channels

# ==========================================
# 🛰️ WEBHOOKS & AUTO-APPROVAL LOGIC
# ==========================================

@app.route('/sms_webhook', methods=['POST', 'GET'])
def sms_verification():
    """The Heart of Auto-Approval: Processes SMS for matching payments."""
    data = request.args if request.method == 'GET' else request.json
    msg = data.get('message', '').lower() if data else ""

    if not msg: return "No Content", 200

    # Log SMS for Admin (Useful for debugging rejection issues)
    bot.send_message(ADMIN_ID, f"📩 **Incoming SMS Log:**\n`{msg}`")

    # Regex to find amount like 29.89 or 29.41
    match = re.search(r'(\d+\.\d{2})', msg)
    if match:
        amount_received = str(match.group(1))
        # Find who was supposed to pay this exact unique amount
        record = temp_pay_col.find_one({"amount": amount_received})

        if record:
            uid = record['user_id']
            fid = record.get('fid')
            duration = int(record['mins'])

            # 1. Update Subscription in DB
            new_expiry = int((datetime.now() + timedelta(minutes=duration)).timestamp())
            users_col.update_one({"user_id": uid}, {"$set": {"expiry": new_expiry}}, upsert=True)
            
            # 2. DELETE temp record to prevent duplicate use & stop timer
            temp_pay_col.delete_one({"_id": record['_id']})

            # 3. Notify User & Admin
            bot.send_message(uid, "✅ **Payment Verified Successfully!**\nYour Prime access is now active.")
            
            # Instant File Delivery if FID exists
            if fid:
                file_data = links_col.find_one({"file_id": fid})
                if file_data:
                    bot.send_message(uid, f"🎁 **Your Requested File:**\n{file_data['url']}")

            bot.send_message(ADMIN_ID, f"💰 **Auto-Approved:** ₹{amount_received} from User `{uid}`")
            return "MATCHED", 200

    return "NO_MATCH", 200

# ==========================================
# ⏱️ TIMER THREAD (Screenshot Trigger)
# ==========================================

def payment_monitor(chat_id, user_id, amount):
    """Wait and check if auto-approval happened. If not, ask for screenshot."""
    time.sleep(25) # Giving extra 5 seconds for SMS lag
    
    # Re-check database for the record
    still_pending = temp_pay_col.find_one({"user_id": user_id, "amount": str(amount)})
    
    if still_pending:
        # If record still exists, it means SMS wasn't received/matched
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📸 Send Screenshot", url=f"tg://user?id={ADMIN_ID}"))
        
        bot.send_message(
            chat_id, 
            f"❓ **Payment Not Detected (₹{amount})**\n\nAgar aapne paise bhej diye hain toh Admin ko screenshot bhej kar manual approval lein.",
            reply_markup=markup
        )

# ==========================================
# 🤖 BOT HANDLERS
# ==========================================

@bot.message_handler(commands=['start'])
def welcome(message):
    uid = message.from_user.id
    text = message.text
    
    # Force Sub Check
    left = get_fsub_status(uid)
    if left:
        markup = InlineKeyboardMarkup()
        for c in left: markup.add(InlineKeyboardButton(f"📢 Join {c}", url=f"https://t.me/{c}"))
        markup.add(InlineKeyboardButton("✅ Check Again", callback_data="check_fsub"))
        return bot.send_message(uid, "🚫 **Pehle channels join karo!**", reply_markup=markup)

    # Process File Link
    match = re.search(r'vid_([a-zA-Z0-9]+)', text)
    if match:
        fid = match.group(1)
        active, exp = is_prime(uid)
        
        if active:
            link = links_col.find_one({"file_id": fid})
            if link: return bot.send_message(uid, f"✅ **Link:** {link['url']}")
        else:
            # Show Payment Plans
            markup = InlineKeyboardMarkup()
            for m, p in PLANS.items():
                markup.add(InlineKeyboardButton(f"💳 {p['name']} - ₹{p['price']}", callback_data=f"buy_{fid}_{m}_{p['price']}"))
            return bot.send_message(uid, "🔒 **Prime Required!**\n\nIs link ko dekhne ke liye subscription lein:", reply_markup=markup)

    bot.send_message(uid, "👋 Welcome to DV Prime Bot!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def pay_request(call):
    _, fid, mins, base = call.data.split('_')
    
    # Generate unique amount (e.g., 29.45) to identify the user
    unique_val = f"{base}.{random.randint(10, 99)}"
    
    temp_pay_col.update_one(
        {"user_id": call.from_user.id},
        {"$set": {"amount": str(unique_val), "mins": mins, "fid": fid, "at": datetime.now()}},
        upsert=True
    )

    pay_url = f"upi://pay?pa={UPI_ID}&am={unique_val}&cu=INR&tn=DV_Prime"
    qr = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={urllib.parse.quote(pay_url)}"

    bot.send_photo(
        call.message.chat.id, 
        qr, 
        caption=f"⚠️ Pay exactly **₹{unique_val}**\n\n15-20 second wait karein activation ke liye."
    )
    
    # Start Monitoring Thread
    threading.Thread(target=payment_monitor, args=(call.message.chat.id, call.from_user.id, unique_val)).start()

# ==========================================
# 👑 ADMIN COMMANDS (With Safety Checks)
# ==========================================

@bot.message_handler(commands=['approve'], func=lambda m: m.from_user.id == ADMIN_ID)
def manual_ok(message):
    try:
        # Format: /approve 123456 30 (ID then Days)
        cmd = message.text.split()
        target, days = int(cmd[1]), int(cmd[2])
        exp = int((datetime.now() + timedelta(days=days)).timestamp())
        
        users_col.update_one({"user_id": target}, {"$set": {"expiry": exp}}, upsert=True)
        bot.send_message(target, "🎉 **Prime Activated by Admin!**")
        bot.send_message(ADMIN_ID, f"✅ User `{target}` approved for {days} days.")
    except:
        bot.send_message(ADMIN_ID, "❌ Format: `/approve ID Days`")

@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def make_link(message):
    msg = bot.send_message(ADMIN_ID, "🔗 Link bhejein:")
    bot.register_next_step_handler(msg, finalize_short)

def finalize_short(message):
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    bot.send_message(ADMIN_ID, f"✅ Bot Link: `https://t.me/{bot.get_me().username}?start=vid_{fid}`")

# ==========================================
# 🚀 FLASK & WEBHOOK STARTUP
# ==========================================

@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def tg_in():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "OK", 200

if __name__ == '__main__':
    bot.remove_webhook()
    time.sleep(2)
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
    
