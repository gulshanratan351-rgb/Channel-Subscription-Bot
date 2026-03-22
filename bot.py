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
        sms_text = request.args.get('message', '')
        if not sms_text and request.is_json:
            sms_text = request.json.get('message', '')

        if sms_text:
            # Admin ko message bhej raha hai taaki aap log dekh sakein
            bot.send_message(ADMIN_ID, f"📩 **Notification Aayi:**\n`{sms_text}`")

            # 12-digit UTR dhoondna
            utr_match = re.search(r'(\d{12})', sms_text)
            if utr_match:
                found_utr = utr_match.group(1)
                # Payment save karna (pichle 10 min tak valid rahegi)
                utr_col.update_one(
                    {"utr": found_utr}, 
                    {"$set": {"status": "unclaimed", "time": datetime.now()}}, 
                    upsert=True
                )
                bot.send_message(ADMIN_ID, f"✅ UTR Found & Saved: `{found_utr}`")
                return "SUCCESS", 200 
            else:
                bot.send_message(ADMIN_ID, "⚠️ Is message mein 12-digit UTR nahi mila!")
        
        return "NO DATA", 200
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
    
    # Deep Link Check (Video links ke liye)
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
                bot.send_message(uid, "🔒 **Prime Required!**\nNiche diye gaye plan choose karein aur pay karein:", reply_markup=markup)
        return
    
    if uid == ADMIN_ID:
        bot.send_message(uid, "👑 **ADMIN PANEL**\n/short - Create Link\n/stats - Check Users\n/broadcast - Send Msg")
    else:
        bot.send_message(uid, "👋 Welcome! Kisi file link par click karke access paayein.")

# --- PAYMENT PROCESS (Direct Approval) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, price = call.data.split('_')
    upi_url = f"upi://pay?pa={UPI_ID}&am={price}&cu=INR"
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_url)}"
    
    # Button: No UTR entry needed
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⚡ Verify Payment (Auto)", callback_data=f"verify_{mins}")]])
    bot.send_photo(call.message.chat.id, qr_api, caption=f"💰 **Plan:** {int(mins)//1440} Day(s)\n💵 **Price:** ₹{price}\n\n1. QR Scan karke Payment karein.\n2. 30 second wait karein.\n3. Niche 'Verify' button dabayein.", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('verify_'))
def direct_verify(call):
    uid = call.from_user.id
    mins = call.data.split('_')[1]
    
    # Pichle 10 minute ki koi bhi unclaimed payment dhundna
    ten_mins_ago = datetime.now() - timedelta(minutes=10)
    payment = utr_col.find_one({"status": "unclaimed", "time": {"$gt": ten_mins_ago}})
    
    if payment:
        exp = int((datetime.now() + timedelta(minutes=int(mins))).timestamp())
        users_col.update_one({"user_id": uid}, {"$set": {"expiry": exp}}, upsert=True)
        # Payment ko verify mark karna taaki koi aur use na kar sake
        utr_col.update_one({"utr": payment['utr']}, {"$set": {"status": "verified", "user_id": uid}})
        
        bot.send_message(uid, "✅ **Payment Verified!** Aapka Prime active ho gaya hai.")
        bot.send_message(ADMIN_ID, f"💰 **Auto-Success!**\nUser: `{uid}`\nUTR: `{payment['utr']}`")
    else:
        bot.answer_callback_query(call.id, "❌ Payment nahi mili! Pay karne ke 30-60 second baad try karein.", show_alert=True)

# --- ADMIN FUNCTIONS ---
@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🔗 File Link bhejein jise protect karna hai:")
    bot.register_next_step_handler(msg, process_short)

def process_short(message):
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    bot.send_message(ADMIN_ID, f"✅ Protected Link:\n`https://t.me/{bot.get_me().username}?start=vid_{fid}`", parse_mode="Markdown")

# --- SCHEDULER (Expiry Check) ---
def check_subs():
    now = datetime.now().timestamp()
    users_col.delete_many({"expiry": {"$lte": now}})

# --- START ---
if __name__ == '__main__':
    threading.Thread(target=run_web).start()
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_subs, 'interval', minutes=1)
    scheduler.start()
    print("Bot is starting...")
    bot.infinity_polling()
    
