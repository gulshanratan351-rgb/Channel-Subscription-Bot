# =========================================================================
# 🚀 PROJECT: DV PRIME SUBSCRIPTION & FILE MANAGEMENT SYSTEM
# 🛠️ DEVELOPER: GEMINI AI (CUSTOM FOR USER)
# 📅 DATE: MARCH 2026
# 📜 DESCRIPTION: Advanced Auto-Approval Payment Bot with SMS Webhook,
#                Deep-Linking, Multi-Channel Force Sub, and Admin Panel.
# =========================================================================

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

# -------------------------------------------------------------------------
# 1. LOGGING & SYSTEM SETUP
# -------------------------------------------------------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# 2. ENVIRONMENT VARIABLES (REQUIRED)
# -------------------------------------------------------------------------
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
UPI_ID = os.getenv('UPI_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

# -------------------------------------------------------------------------
# 3. DATABASE & BOT INITIALIZATION
# -------------------------------------------------------------------------
try:
    bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")
    client = MongoClient(MONGO_URI)
    db = client['dv_prime_management']
    
    # Collections
    users_col = db['registered_users']
    links_col = db['stored_links']
    temp_pay_col = db['pending_txns']
    logs_col = db['system_logs']
    
    logger.info("Successfully connected to MongoDB and Telegram.")
except Exception as e:
    logger.error(f"Initialization Failed: {e}")

# Subscription Plans Configuration
PLANS = {
    "1440": {"price": "29", "label": "1 Day Prime Pass"},
    "10080": {"price": "99", "label": "7 Days Weekly Pack"},
    "43200": {"price": "199", "label": "30 Days Monthly Pro"}
}

app = Flask(__name__)

# -------------------------------------------------------------------------
# 4. CORE UTILITY FUNCTIONS
# -------------------------------------------------------------------------

def save_log(action, details):
    """Saves system actions to database logs."""
    logs_col.insert_one({
        "timestamp": datetime.now(),
        "action": action,
        "details": details
    })

def check_prime_status(user_id):
    """Returns (IsPrime, ExpiryString)"""
    user = users_col.find_one({"user_id": user_id})
    if user:
        expiry = user.get('expiry', 0)
        if expiry > datetime.now().timestamp():
            dt_object = datetime.fromtimestamp(expiry)
            return True, dt_object.strftime('%d %b %Y, %I:%M %p')
    return False, None

# -------------------------------------------------------------------------
# 5. SMART TIMER & SCREENSHOT LOGIC
# -------------------------------------------------------------------------

def monitor_payment_timeout(chat_id, user_id, amount_str):
    """
    This function runs in a background thread.
    It waits for 25 seconds and checks if the payment was approved.
    If not, it sends the 'Send Screenshot' button.
    """
    logger.info(f"Started monitoring for User {user_id}, Amount {amount_str}")
    time.sleep(25)
    
    # Check if the payment record still exists in 'pending_txns'
    still_pending = temp_pay_col.find_one({"user_id": user_id, "amount": amount_str})
    
    if still_pending:
        # Auto-approval failed or SMS didn't arrive
        markup = InlineKeyboardMarkup()
        btn = InlineKeyboardButton("📸 Send Screenshot to Admin", url=f"tg://user?id={ADMIN_ID}")
        markup.add(btn)
        
        fail_text = (
            "❌ **Auto-Approval Update**\n\n"
            f"Bhai, ₹{amount_str} ka payment system mein detect nahi hua.\n\n"
            "**Possible Reasons:**\n"
            "1. SMS delay hona.\n"
            "2. Galat amount pay karna.\n"
            "3. Network issue.\n\n"
            "Agar aapne pay kar diya hai, toh niche button se Admin ko screenshot bhej do."
        )
        try:
            bot.send_message(chat_id, fail_text, reply_markup=markup)
            save_log("TIMER_NOTIFICATION", f"Sent screenshot prompt to {user_id}")
        except Exception as e:
            logger.error(f"Error sending timeout message: {e}")
    else:
        logger.info(f"Payment for {user_id} was approved. No timeout message needed.")

# -------------------------------------------------------------------------
# 6. WEBHOOK ROUTES (FLASK)
# -------------------------------------------------------------------------

@app.route('/')
def status_check():
    return "<h1>DV Prime Bot is Running</h1>", 200

@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def receive_updates():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Forbidden", 403

@app.route('/sms_webhook', methods=['GET', 'POST'])
def sms_webhook_handler():
    """Processes incoming SMS for payment verification."""
    try:
        # Handle both GET and POST requests from SMS Apps
        data = request.args if request.method == 'GET' else request.json
        full_msg = data.get('message', '').lower() if data else ""
        
        if not full_msg:
            return "No message content", 200

        # Log all SMS for Admin Review
        bot.send_message(ADMIN_ID, f"📩 **Incoming SMS Log:**\n`{full_msg}`")
        
        # Regex to find exact decimal amount (e.g. 29.45)
        match = re.search(r'(\d+\.\d{2})', full_msg)
        if match:
            paid_amount = str(match.group(1))
            txn_record = temp_pay_col.find_one({"amount": paid_amount})
            
            if txn_record:
                uid = txn_record['user_id']
                fid = txn_record.get('fid')
                duration_mins = int(txn_record['mins'])
                
                # 1. Calculate New Expiry
                current_user = users_col.find_one({"user_id": uid})
                base_time = max(datetime.now().timestamp(), current_user.get('expiry', 0)) if current_user else datetime.now().timestamp()
                new_expiry = int(base_time + (duration_mins * 60))
                
                # 2. Update Database
                users_col.update_one({"user_id": uid}, {"$set": {"expiry": new_expiry}}, upsert=True)
                
                # 3. CRITICAL: Remove from Pending (Stops the Timer)
                temp_pay_col.delete_one({"_id": txn_record['_id']})
                
                # 4. Notify User
                bot.send_message(uid, "🎉 **Payment Verified!**\nAapka Prime subscription activate kar diya gaya hai.")
                
                # 5. Delivery of File Link
                if fid:
                    time.sleep(1) # Small buffer for DB
                    link_doc = links_col.find_one({"file_id": fid})
                    if link_doc:
                        bot.send_message(uid, f"🎁 **Aapka Requested Link Ye Raha:**\n\n{link_doc['url']}")
                
                # 6. Notify Admin
                bot.send_message(ADMIN_ID, f"✅ **Approved:** User `{uid}` paid ₹{paid_amount}")
                save_log("AUTO_APPROVE", f"User {uid} paid {paid_amount}")
                return "SUCCESS", 200
        
        return "NO_PAYMENT_MATCH", 200
    except Exception as e:
        logger.error(f"SMS Webhook Error: {e}")
        return str(e), 500

# -------------------------------------------------------------------------
# 7. TELEGRAM BOT HANDLERS
# -------------------------------------------------------------------------

@bot.message_handler(commands=['start'])
def handle_start_command(message):
    user_id = message.from_user.id
    username = message.from_user.first_name
    text = message.text
    
    save_log("START", f"User {user_id} started bot")
    
    # Check for Deep Link (vid_xxxx)
    deep_link = re.search(r'vid_([a-zA-Z0-9]+)', text)
    if deep_link:
        file_id = deep_link.group(1)
        is_p, exp_str = check_prime_status(user_id)
        
        if is_p:
            # User is Prime - Give File
            file_obj = links_col.find_one({"file_id": file_id})
            if file_obj:
                return bot.send_message(user_id, f"✅ **Access Granted!**\n\n🔗 **Link:** {file_obj['url']}")
        else:
            # User is NOT Prime - Show Payment Options
            markup = InlineKeyboardMarkup()
            for mins, data in PLANS.items():
                markup.add(InlineKeyboardButton(f"💳 {data['label']} - ₹{data['price']}", callback_data=f"buy_{file_id}_{mins}_{data['price']}"))
            
            buy_text = (
                f"👋 **Namaste {username}!**\n\n"
                "🔒 Ye file sirf **Prime Members** ke liye hai.\n\n"
                "Niche diye gaye buttons se subscription lein aur turant access payein."
            )
            return bot.send_message(user_id, buy_text, reply_markup=markup)

    # Standard Start Message
    if user_id == ADMIN_ID:
        admin_txt = "👑 **ADMIN DASHBOARD**\n\n/short - New File Link\n/stats - User Statistics\n/approve ID Days - Manual Approve\n/deactivate ID - Remove Prime"
        bot.send_message(user_id, admin_txt)
    else:
        bot.send_message(user_id, f"👋 **Hello {username}!**\n\nApne manpasand links lene ke liye channel se click karein.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def handle_payment_selection(call):
    user_id = call.from_user.id
    _, fid, mins, base_price = call.data.split('_')
    
    # Generate Unique Amount (29.xx)
    unique_decimal = f"{base_price}.{random.randint(10, 99)}"
    
    # Save to Pending Collection
    temp_pay_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "amount": unique_decimal,
            "mins": mins,
            "fid": fid,
            "created_at": datetime.now()
        }},
        upsert=True
    )
    
    # Generate UPI QR
    upi_string = f"upi://pay?pa={UPI_ID}&am={unique_decimal}&cu=INR&tn=Prime_Sub"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={urllib.parse.quote(upi_string)}&margin=10"
    
    caption = (
        "💳 **Payment Invoice Generated**\n\n"
        f"💵 **Pay Exactly:** `₹{unique_decimal}`\n"
        "⏳ **Time Limit:** 15 Minutes\n\n"
        "⚠️ **Note:** Agar aapne 1 bhi paisa kam ya zyada diya, toh system auto-approve nahi karega.\n\n"
        "Payment ke baad 20 second wait karein."
    )
    
    bot.send_photo(user_id, qr_url, caption=caption)
    
    # START THE MONITORING TIMER THREAD
    threading.Thread(target=monitor_payment_timeout, args=(call.message.chat.id, user_id, unique_decimal)).start()

# -------------------------------------------------------------------------
# 8. ADMIN DASHBOARD FUNCTIONS
# -------------------------------------------------------------------------

@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def admin_create_link(message):
    msg = bot.send_message(ADMIN_ID, "🔗 Please send the **URL** you want to hide:")
    bot.register_next_step_handler(msg, process_short_link_save)

def process_short_link_save(message):
    try:
        url_text = message.text
        if not url_text.startswith("http"):
            return bot.send_message(ADMIN_ID, "❌ Invalid URL! Please start with http:// or https://")
        
        new_fid = str(uuid.uuid4())[:8]
        links_col.insert_one({
            "file_id": new_fid,
            "url": url_text,
            "created_by": ADMIN_ID,
            "date": datetime.now()
        })
        
        bot_username = bot.get_me().username
        final_link = f"https://t.me/{bot_username}?start=vid_{new_fid}"
        
        bot.send_message(ADMIN_ID, f"✅ **Link Shortened!**\n\n`{final_link}`")
        save_log("LINK_CREATED", f"FID: {new_fid}")
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Error: {e}")

@bot.message_handler(commands=['approve'], func=lambda m: m.from_user.id == ADMIN_ID)
def admin_manual_approve(message):
    try:
        # Format: /approve 1234567 30
        cmd_parts = message.text.split()
        target_id = int(cmd_parts[1])
        days = int(cmd_parts[2])
        
        new_exp = int((datetime.now() + timedelta(days=days)).timestamp())
        users_col.update_one({"user_id": target_id}, {"$set": {"expiry": new_exp}}, upsert=True)
        
        bot.send_message(target_id, f"🎁 **Prime Activated!**\nAdmin ne aapka Prime {days} dinon ke liye activate kar diya hai.")
        bot.send_message(ADMIN_ID, f"✅ User {target_id} is now Prime for {days} days.")
        save_log("MANUAL_APPROVE", f"To {target_id} for {days} days")
    except:
        bot.send_message(ADMIN_ID, "❌ Usage: `/approve UserID Days`")

@bot.message_handler(commands=['stats'], func=lambda m: m.from_user.id == ADMIN_ID)
def admin_stats(message):
    total_users = users_col.count_documents({})
    active_prime = users_col.count_documents({"expiry": {"$gt": datetime.now().timestamp()}})
    total_links = links_col.count_documents({})
    
    stats_msg = (
        "📊 **Bot Real-Time Stats**\n\n"
        f"👥 Total Registered: `{total_users}`\n"
        f"⚡ Active Prime Users: `{active_prime}`\n"
        f"🔗 Total Files Hidden: `{total_links}`\n"
        "--------------------------\n"
        f"⏰ Server Time: `{datetime.now().strftime('%H:%M:%S')}`"
    )
    bot.send_message(ADMIN_ID, stats_msg)

# -------------------------------------------------------------------------
# 9. STARTUP & WEBHOOK EXECUTION
# -------------------------------------------------------------------------

if __name__ == '__main__':
    # Initializing Webhook
    bot.remove_webhook()
    time.sleep(2)
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    
    # Run the Flask App
    # This keeps the bot alive on Render/Heroku
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Web-Server on Port {port}")
    app.run(host='0.0.0.0', port=port)

# =========================================================================
# 👋 END OF CODE - DV PRIME ULTIMATE
# =========================================================================
