import os, telebot, urllib.parse, uuid, datetime, re, threading
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, request, jsonify

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
utr_col = db['transactions'] 

PLANS = {"1440": "29", "10080": "99", "43200": "199"}

# --- SERVER & WEBHOOK (MacroDroid Connection) ---
app = Flask(__name__)

@app.route('/')
def home(): return "Bot is Online!"

@app.route('/sms_webhook', methods=['GET', 'POST'])
def handle_sms():
    try:
        # MacroDroid se message lena
        sms_text = request.args.get('message', '').lower()
        if not sms_text and request.is_json:
            sms_text = request.json.get('message', '').lower()

        # SMS mein se 12-digit UTR dhoondna
        utr_match = re.search(r'(\d{12})', sms_text)
        if utr_match:
            found_utr = utr_match.group(1)
            # Payment ko 'unclaimed' list mein save karna (ताकि user बाद में claim कर सके)
            utr_col.update_one(
                {"utr": found_utr}, 
                {"$set": {"status": "unclaimed", "time": datetime.now()}}, 
                upsert=True
            )
            return "SUCCESS", 200 
        return "NO UTR FOUND", 200
    except Exception as e:
        return str(e), 500

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

# --- BOT HANDLERS ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    uid = message.from_user.id
    args = message.text.split()
    if len(args) > 1 and args[1].startswith('vid_'):
        fid = args[1].replace('vid_', '')
        link_obj = links_col.find_one({"file_id": fid})
        if link_obj:
            u_data = users_col.find_one({"user_id": uid})
            if u_data and u_data.get('expiry', 0) > datetime.now().timestamp():
                bot.send_message(uid, f"✅ **Access Granted!**\n\n📂 **Link:** {link_obj['url']}")
            else:
                markup = InlineKeyboardMarkup()
                for mins, price in PLANS.items():
                    label = f"{int(mins)//1440} Day" if int(mins) >= 1440 else f"{mins} Min"
                    markup.add(InlineKeyboardButton(f"💳 {label} - ₹{price}", callback_data=f"p_{fid}_{mins}_{price}"))
                bot.send_message(uid, "🔒 **Prime Required!**\nPay once to access all links:", reply_markup=markup)
        return
    
    if uid == ADMIN_ID:
        bot.send_message(uid, "👑 **ADMIN PANEL**\n/short - Create Link\n/stats - Check Users\n/broadcast - Send Msg")
    else:
        bot.send_message(uid, "👋 Welcome! Use a file link to get access.")

# --- PAYMENT PROCESS (No UTR Mode) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, price = call.data.split('_')
    upi_url = f"upi://pay?pa={UPI_ID}&am={price}&cu=INR"
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_url)}"
    
    # User sirf is button ko dabayega verify karne ke liye
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⚡ Verify Payment (No UTR)", callback_data=f"verify_{mins}")]])
    bot.send_photo(call.message.chat.id, qr_api, caption=f"💰 **Plan:** {int(mins)//1440} Day(s)\n💵 **Price:** ₹{price}\n\n1. QR scan karke pay karein.\n2. 30-60 second wait karein.\n3. Niche wala button dabayein.", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('verify_'))
def direct_verify(call):
    uid = call.from_user.id
    mins = call.data.split('_')[1]
    
    # Pichle 5 minute ki koi bhi unclaimed payment dhundna
    five_mins_ago = datetime.now() - timedelta(minutes=5)
    payment = utr_col.find_one({"status": "unclaimed", "time": {"$gt": five_mins_ago}})
    
    if payment:
        exp = int((datetime.now() + timedelta(minutes=int(mins))).timestamp())
        users_col.update_one({"user_id": uid}, {"$set": {"expiry": exp}}, upsert=True)
        # Payment ko 'verified' mark kar do taki repeat na ho
        utr_col.update_one({"utr": payment['utr']}, {"$set": {"status": "verified", "user_id": uid}})
        
        bot.send_message(uid, "✅ **Payment Verified!**\nAapka Prime access active ho gaya hai. Enjoy!")
        bot.send_message(ADMIN_ID, f"💰 **Auto-Verified!**\nUser: `{uid}`\nUTR: `{payment['utr']}`")
    else:
        bot.answer_callback_query(call.id, "❌ Payment record nahi mila! Thoda wait karke fir try karein.", show_alert=True)

# --- ADMIN FUNCTIONS ---
@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🔗 Send the File Link you want to protect:")
    bot.register_next_step_handler(msg, process_short)

def process_short(message):
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    bot.send_message(ADMIN_ID, f"✅ Protected Link Created:\n`https://t.me/{bot.get_me().username}?start=vid_{fid}`", parse_mode="Markdown")

# --- SCHEDULER ---
def check_subs():
    now = datetime.now().timestamp()
    users_col.delete_many({"expiry": {"$lte": now}})

# --- START ---
if __name__ == '__main__':
    threading.Thread(target=run_web).start()
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_subs, 'interval', minutes=1)
    scheduler.start()
    bot.infinity_polling()
    
