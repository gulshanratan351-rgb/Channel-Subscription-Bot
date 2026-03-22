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
utr_col = db['transactions'] # Status track karne ke liye change kiya

PLANS = {"1440": "29", "10080": "99", "43200": "199"}

# --- SERVER & WEBHOOK (BharatPe Connection) ---
app = Flask(__name__)

@app.route('/')
def home(): return "Bot is Online!"

@app.route('/sms_webhook', methods=['POST'])
def handle_sms():
    try:
        data = request.json
        sms_text = data.get('message', '').lower()
        # SMS se 12-digit UTR nikalna
        utr_match = re.search(r'(\d{12})', sms_text)
        
        if utr_match:
            found_utr = utr_match.group(1)
            # Check karein kya koi user is UTR ka wait kar raha hai
            pending = utr_col.find_one({"utr": found_utr, "status": "pending"})
            
            if pending:
                uid, mins = pending['user_id'], pending['mins']
                exp = int((datetime.now() + timedelta(minutes=int(mins))).timestamp())
                
                # Payment Verify aur Subscription Active karein
                users_col.update_one({"user_id": uid}, {"$set": {"expiry": exp, "warned": False}}, upsert=True)
                utr_col.update_one({"utr": found_utr}, {"$set": {"status": "verified"}})
                
                bot.send_message(uid, "✅ **Payment Verified!**\nAccess granted automatically.")
                bot.send_message(ADMIN_ID, f"💰 **Auto-Success!**\nUser: `{uid}`\nUTR: `{found_utr}`", parse_mode="Markdown")
        
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        bot.send_message(uid, "👑 **ADMIN PANEL**\n/short, /stats, /broadcast, /deactivate")
    else:
        bot.send_message(uid, "👋 Welcome! Use a file link to start.")

# (Baqi Admin Commands Same Rahenge...)
@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🔗 Send File Link:")
    bot.register_next_step_handler(msg, process_short)

def process_short(message):
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    bot.send_message(ADMIN_ID, f"✅ Link: `https://t.me/{bot.get_me().username}?start=vid_{fid}`", parse_mode="Markdown")

# --- PAYMENT PROCESS (Automatic logic ke saath) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, price = call.data.split('_')
    qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(f'upi://pay?pa={UPI_ID}&am={price}&cu=INR')}"
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ I Have Paid (Enter UTR)", callback_data=f"utr_{fid}_{mins}")]])
    bot.send_photo(call.message.chat.id, qr, caption=f"💰 Pay ₹{price} & click below to enter UTR for instant access.", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('utr_'))
def ask_utr(call):
    msg = bot.send_message(call.message.chat.id, "⌨️ Enter 12-digit UTR Number:")
    bot.register_next_step_handler(msg, verify_utr, call.data.split('_')[1], call.data.split('_')[2])

def verify_utr(message, fid, mins):
    utr = message.text.strip()
    if not utr.isdigit() or len(utr) != 12:
        bot.send_message(message.chat.id, "❌ Invalid UTR! Must be 12 digits.")
        return
    
    # UTR ko database mein 'pending' status ke saath save karein
    utr_col.insert_one({"utr": utr, "user_id": message.from_user.id, "mins": mins, "status": "pending"})
    bot.send_message(message.chat.id, "⏳ Verifying your payment... please wait 10-30 seconds.")

# --- SUBSCRIPTION CHECKER ---
def check_subs():
    now = datetime.now().timestamp()
    users_col.delete_many({"expiry": {"$lte": now}})

if __name__ == '__main__':
    threading.Thread(target=run_web).start()
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_subs, 'interval', minutes=1)
    scheduler.start()
    bot.infinity_polling()
    
