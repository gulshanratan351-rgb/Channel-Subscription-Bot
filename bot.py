import os, telebot, urllib.parse, uuid, datetime
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
def home(): return "Bot is Online and Verified!"

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

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['sub_management']
users_col = db['users']
links_col = db['short_links']

# --- PLANS CONFIG ---
PLANS = {
    "1440": "29",    # 1 Day - ₹29
    "10080": "99",   # 7 Days - ₹99
    "43200": "199"   # 30 Days - ₹199
}

# --- ADMIN COMMANDS ---

@bot.message_handler(commands=['start'])
def start_handler(message):
    uid = message.from_user.id
    args = message.text.split()

    # FILE ACCESS LOGIC
    if len(args) > 1 and args[1].startswith('vid_'):
        fid = args[1].replace('vid_', '')
        link_obj = links_col.find_one({"file_id": fid})
        
        if link_obj:
            u_data = users_col.find_one({"user_id": uid})
            if u_data and u_data.get('expiry', 0) > datetime.now().timestamp():
                bot.send_message(uid, f"✅ **Access Granted!**\n\n📂 **Your File:** {link_obj['url']}")
            else:
                markup = InlineKeyboardMarkup()
                for mins, price in PLANS.items():
                    label = f"{int(mins)//1440} Day" if int(mins) >= 1440 else f"{mins} Min"
                    markup.add(InlineKeyboardButton(f"💳 {label} - ₹{price}", callback_data=f"p_{fid}_{mins}_{price}"))
                bot.send_message(uid, "🔒 **Prime Membership Required!**\n\nEk baar pay karein aur 24h tak saare links access karein:", reply_markup=markup)
        return

    if uid == ADMIN_ID:
        bot.send_message(uid, "👑 **DV PRIME ADMIN PANEL**\n\n/short - Create Prime File Link\n/stats - Check Active Users\n/broadcast - Message All Users\n/deactivate - Remove User Access")
    else:
        bot.send_message(uid, "👋 Welcome! Click on a file link from our channel to get started.")

@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🔗 Please send the **File Link** you want to shorten:")
    bot.register_next_step_handler(msg, process_short)

def process_short(message):
    if not message.text or "t.me" not in message.text:
        bot.send_message(ADMIN_ID, "❌ Invalid link. Try /short again.")
        return
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    p_link = f"https://t.me/{bot.get_me().username}?start=vid_{fid}"
    bot.send_message(ADMIN_ID, f"✅ **Prime Link Created!**\n\n`{p_link}`", parse_mode="Markdown")

@bot.message_handler(commands=['stats'], func=lambda m: m.from_user.id == ADMIN_ID)
def stats_cmd(message):
    active = users_col.count_documents({"expiry": {"$gt": datetime.now().timestamp()}})
    bot.send_message(ADMIN_ID, f"📊 **Active Prime Users:** `{active}`")

@bot.message_handler(commands=['broadcast'], func=lambda m: m.from_user.id == ADMIN_ID)
def broadcast_cmd(message):
    msg = bot.send_message(ADMIN_ID, "📢 Send the message to broadcast:")
    bot.register_next_step_handler(msg, do_broadcast)

def do_broadcast(message):
    users = users_col.find({})
    for u in users:
        try: bot.copy_message(u['user_id'], ADMIN_ID, message.message_id)
        except: pass
    bot.send_message(ADMIN_ID, "✅ Broadcast Done!")

# --- PAYMENT FLOW ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, price = call.data.split('_')
    upi_url = f"upi://pay?pa={UPI_ID}&pn=DvPrime&am={price}&cu=INR"
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_url)}"
    
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ I Have Paid", callback_data=f"paid_{fid}_{mins}")]])
    bot.send_photo(call.message.chat.id, qr_api, caption=f"💰 **Total: ₹{price}**\n\nScan and send screenshot.\nUPI: `{UPI_ID}`", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('paid_'))
def wait_ss(call):
    _, fid, mins = call.data.split('_')
    msg = bot.send_message(call.message.chat.id, "📸 Send Screenshot now:")
    bot.register_next_step_handler(msg, verify_admin, fid, mins)

def verify_admin(message, fid, mins):
    if message.content_type != 'photo':
        bot.send_message(message.chat.id, "❌ Please send a photo.")
        return
    
    # User Details Extraction
    u_name = message.from_user.first_name
    u_id = message.from_user.id
    u_username = f"@{message.from_user.username}" if message.from_user.username else "No Username"
    
    caption = (f"📩 **New Payment SS!**\n\n"
               f"👤 **Name:** {u_name}\n"
               f"🆔 **User ID:** `{u_id}`\n"
               f"🔗 **Username:** {u_username}\n"
               f"⏳ **Plan:** {mins} Mins")
    
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"app_{u_id}_{mins}_{fid}")]])
    bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('app_'))
def admin_approve(call):
    _, uid, mins, fid = call.data.split('_')
    exp = int((datetime.now() + timedelta(minutes=int(mins))).timestamp())
    users_col.update_one({"user_id": int(uid)}, {"$set": {"expiry": exp, "warned": False}}, upsert=True)
    
    link_obj = links_col.find_one({"file_id": fid})
    f_url = link_obj['url'] if link_obj else "File Link"
    
    bot.send_message(int(uid), f"🥳 **Approved!** All links open now.\n\n📂 **Your File:** {f_url}")
    bot.edit_message_caption("✅ User Approved Successfully", call.message.chat.id, call.message.message_id)

# --- DEACTIVATE COMMAND ---

@bot.message_handler(commands=['deactivate'], func=lambda m: m.from_user.id == ADMIN_ID)
def deactivate_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🚫 Send **User ID** to deactivate:")
    bot.register_next_step_handler(msg, process_deactivation)

def process_deactivation(message):
    try:
        target_id = int(message.text)
        result = users_col.delete_one({"user_id": target_id})
        if result.deleted_count > 0:
            bot.send_message(ADMIN_ID, f"✅ User {target_id} deactivated.")
            try: bot.send_message(target_id, "⚠️ **Your Prime access has been revoked.**")
            except: pass
        else:
            bot.send_message(ADMIN_ID, "❌ User not found.")
    except:
        bot.send_message(ADMIN_ID, "❌ Invalid ID.")

# --- AUTO EXPIRE & WARNING SYSTEM ---

def check_subscriptions():
    now = datetime.now().timestamp()
    
    # 1. Send Warning (10 mins before)
    warning_limit = (datetime.now() + timedelta(minutes=10)).timestamp()
    users_to_warn = users_col.find({"expiry": {"$lte": warning_limit, "$gt": now}, "warned": {"$ne": True}})
    for user in users_to_warn:
        try:
            bot.send_message(user['user_id'], "⚠️ **Reminder:** Aapka access 10 minute mein khatam ho jayega. Dubara access ke liye abhi renew karein!")
            users_col.update_one({"_id": user["_id"]}, {"$set": {"warned": True}})
        except: pass

    # 2. Final Deactivation
    expired_users = users_col.find({"expiry": {"$lte": now}})
    for user in expired_users:
        try: bot.send_message(user['user_id'], "🚫 **Expired:** Aapka Prime access khatam ho gaya hai. Please renew karein.")
        except: pass
        users_col.delete_one({"_id": user["_id"]})

if __name__ == '__main__':
    keep_alive()
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_subscriptions, 'interval', minutes=1)
    scheduler.start()
    bot.infinity_polling()
    
