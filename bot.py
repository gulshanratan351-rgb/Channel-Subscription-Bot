import os, telebot, urllib.parse, uuid, datetime, re, threading, random, time, razorpay
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from flask import Flask, request

# ================= CONFIGURATION =================
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
UPI_ID = os.getenv('UPI_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

# Razorpay Keys
RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID')
RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET')

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['sub_management']
users_col = db['users']
links_col = db['short_links']
temp_pay_col = db['temp_payments']

# Razorpay Client
razor_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

app = Flask(__name__)

# ================= FLASK SERVER =================
@app.route('/')
def home():
    return "🚀 Master Bot is Online and Healthy!"

# --- Naya Webhook Route (Automation ke liye) ---
@app.route('/razorpay_webhook', methods=['POST'])
def razorpay_webhook():
    data = request.json
    if data and data.get('event') == 'payment_link.paid':
        entity = data['payload']['payment_link']['entity']
        uid = int(entity['reference_id'])
        mins = int(entity['notes']['mins'])
        fid = entity['notes']['fid']
        
        expiry = int((datetime.now() + timedelta(minutes=mins)).timestamp())
        users_col.update_one({"user_id": uid}, {"$set": {"expiry": expiry}}, upsert=True)
        
        l_data = links_col.find_one({"file_id": fid})
        msg = f"✅ **Payment Successful!**\n\n🎁 Your Link: {l_data['url']}" if l_data else "✅ Payment Successful! Prime Activated."
        bot.send_message(uid, msg)
        return "OK", 200
    return "Ignored", 200

@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Forbidden", 403

# ================= HELPER FUNCTIONS =================
def is_prime(uid):
    user = users_col.find_one({"user_id": uid})
    if user and user.get('expiry', 0) > datetime.now().timestamp():
        return True
    return False

def get_expiry_date(timestamp):
    return datetime.fromtimestamp(timestamp).strftime('%d %b %Y, %I:%M %p')

# ================= ADMIN COMMANDS (UNTOUCHED) =================
@bot.message_handler(commands=['stats'], func=lambda m: m.from_user.id == ADMIN_ID)
def stats_handler(message):
    total_users = users_col.count_documents({})
    active_prime = users_col.count_documents({"expiry": {"$gt": datetime.now().timestamp()}})
    total_links = links_col.count_documents({})
    text = (f"📊 **Bot Statistics**\n\n"
            f"👤 Total Users: {total_users}\n"
            f"👑 Active Prime: {active_prime}\n"
            f"🔗 Total Links: {total_links}")
    bot.reply_to(message, text)

@bot.message_handler(commands=['approve'], func=lambda m: m.from_user.id == ADMIN_ID)
def manual_approve(message):
    try:
        args = message.text.split()
        target_id = int(args[1]); days = int(args[2])
        expiry = int((datetime.now() + timedelta(days=days)).timestamp())
        users_col.update_one({"user_id": target_id}, {"$set": {"expiry": expiry}}, upsert=True)
        bot.send_message(target_id, f"✅ **Congratulations!**\nAdmin has activated your Prime for {days} days.")
        bot.reply_to(message, f"✅ User {target_id} approved.")
    except: bot.reply_to(message, "❌ Use: `/approve [ID] [Days]`")

@bot.message_handler(commands=['broadcast'], func=lambda m: m.from_user.id == ADMIN_ID)
def broadcast_msg(message):
    msg = bot.send_message(ADMIN_ID, "📢 Send the message for broadcast:")
    bot.register_next_step_handler(msg, start_broadcasting)

def start_broadcasting(message):
    for user in users_col.find({}):
        try:
            bot.copy_message(user['user_id'], ADMIN_ID, message.message_id)
            time.sleep(0.1)
        except: pass
    bot.send_message(ADMIN_ID, "✅ Done!")

@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_link(message):
    msg = bot.reply_to(message, "🔗 Paste original link:")
    bot.register_next_step_handler(msg, save_link)

def save_link(message):
    file_id = str(uuid.uuid4())[:8].lower()
    links_col.insert_one({"file_id": file_id, "url": message.text})
    bot.send_message(ADMIN_ID, f"✅ Link: `https://t.me/{bot.get_me().username}?start=vid_{file_id}`")

# ================= USER LOGIC =================
@bot.message_handler(commands=['start'])
def handle_start(message):
    uid = message.from_user.id
    users_col.update_one({"user_id": uid}, {"$setOnInsert": {"joined": datetime.now()}}, upsert=True)
    match = re.search(r'vid_([a-zA-Z0-9]+)', message.text)
    if match:
        fid = match.group(1)
        if is_prime(uid):
            link_data = links_col.find_one({"file_id": fid})
            bot.send_message(uid, f"🍿 Content: {link_data['url']}") if link_data else bot.send_message(uid, "❌ Expired")
        else:
            markup = InlineKeyboardMarkup()
            markup.row(InlineKeyboardButton("💳 2 Days - ₹50", callback_data=f"pay_{fid}_2880_50"))
            markup.row(InlineKeyboardButton("💳 7 Days - ₹100", callback_data=f"pay_{fid}_10080_100"))
            markup.row(InlineKeyboardButton("💳 1 Month - ₹200", callback_data=f"pay_{fid}_43200_200"))
            markup.row(InlineKeyboardButton("💳 3 Months - ₹400", callback_data=f"pay_{fid}_129600_400"))
            bot.send_message(uid, "🔒 **Membership Required!**", reply_markup=markup)
    else:
        bot.send_message(uid, "👋 Welcome! " + ("👑 Prime User" if is_prime(uid) else "Free User"))

# --- Razorpay Link Generator ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('pay_'))
def create_pay_link(call):
    _, fid, mins, price = call.data.split('_')
    uid = call.from_user.id
    try:
        link = razor_client.payment_link.create({
            "amount": int(price) * 100, "currency": "INR",
            "description": f"Subscription {mins}m",
            "reference_id": str(uid),
            "notes": {"mins": mins, "fid": fid},
            "callback_url": f"https://t.me/{bot.get_me().username}",
            "callback_method": "get"
        })
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("💳 Pay Online", url=link['short_url']))
        bot.edit_message_text("💰 Payment karein niche link se:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    except: bot.answer_callback_query(call.id, "⚠️ Error in Payment Gateway")

# ================= RUNNER =================
if __name__ == '__main__':
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
    
