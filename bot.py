import os, telebot, urllib.parse, uuid, datetime, re, threading, random
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
temp_pay_col = db['temp_payments']

PLANS = {"1440": "29", "10080": "99", "43200": "199"}
app = Flask(__name__)

@app.route('/')
def home(): return "Bot is Online!"

@app.route('/sms_webhook', methods=['GET', 'POST'])
def handle_sms():
    try:
        sms_text = request.args.get('message', '').lower()
        if not sms_text and request.is_json:
            sms_text = request.json.get('message', '').lower()
        if sms_text:
            bot.send_message(ADMIN_ID, f"📩 **Notification Check:**\n`{sms_text}`")
            amount_match = re.search(r'(\d+\.\d{2})', sms_text)
            if amount_match:
                amt = amount_match.group(1)
                pay_record = temp_pay_col.find_one({"amount": amt})
                if pay_record:
                    uid = pay_record['user_id']
                    mins = pay_record['mins']
                    exp = int((datetime.now() + timedelta(minutes=int(mins))).timestamp())
                    users_col.update_one({"user_id": uid}, {"$set": {"expiry": exp}}, upsert=True)
                    temp_pay_col.delete_one({"_id": pay_record['_id']})
                    bot.send_message(uid, f"✅ **Payment Verified (₹{amt})!**\nAapka Prime active ho gaya hai.")
                    bot.send_message(ADMIN_ID, f"💰 **Auto-Approve Success:** User `{uid}` paid ₹{amt}")
                    return "SUCCESS", 200
        return "NO MATCH", 200
    except Exception as e:
        return str(e), 500

# --- FIXED START HANDLER (Priority to Link) ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    uid = message.from_user.id
    text = message.text

    # Priority 1: Check if it's a File Link (Start with /start vid_...)
    if len(text.split()) > 1:
        parameter = text.split()[1]
        if parameter.startswith('vid_'):
            fid = parameter.replace('vid_', '').strip()
            link_obj = links_col.find_one({"file_id": fid})
            
            if link_obj:
                u_data = users_col.find_one({"user_id": uid})
                # Prime Expiry Check
                if u_data and u_data.get('expiry', 0) > datetime.now().timestamp():
                    bot.send_message(uid, f"✅ **Access Granted!**\n\n📂 **Link:** {link_obj['url']}")
                else:
                    # Show Price List for Everyone (Admin or User)
                    markup = InlineKeyboardMarkup()
                    for mins, price in PLANS.items():
                        label = f"{int(mins)//1440} Day" if int(mins) >= 1440 else f"{mins} Min"
                        markup.add(InlineKeyboardButton(f"💳 {label} - ₹{price}", callback_data=f"p_{fid}_{mins}_{price}"))
                    bot.send_message(uid, "🔒 **Prime Required!**\nAuto-approval ke liye naya system active hai. Plan choose karein:", reply_markup=markup)
                return
            else:
                bot.send_message(uid, "❌ Sorry, ye link expire ho gaya hai.")
                return

    # Priority 2: Normal Start for Admin
    if uid == ADMIN_ID:
        bot.send_message(uid, "👑 **ADMIN PANEL**\n/short - Create Link\n/stats - Check Users\n/approve [ID] [Days] - Manual Approve")
    
    # Priority 3: Normal Start for User
    else:
        bot.send_message(uid, "👋 Welcome! Kisi link par click karein access ke liye.")

@bot.message_handler(commands=['approve'], func=lambda m: m.from_user.id == ADMIN_ID)
def manual_approve(message):
    try:
        args = message.text.split()
        target_id = int(args[1])
        days = int(args[2])
        exp = int((datetime.now() + timedelta(days=days)).timestamp())
        users_col.update_one({"user_id": target_id}, {"$set": {"expiry": exp}}, upsert=True)
        bot.send_message(ADMIN_ID, f"✅ User `{target_id}` active for {days} days.")
        bot.send_message(target_id, "🎉 Admin ne aapka access manually active kar diya hai!")
    except:
        bot.send_message(ADMIN_ID, "❌ Use: `/approve 1234567 30`")

@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, base_price = call.data.split('_')
    random_extra = random.randint(10, 99)
    unique_price = f"{base_price}.{random_extra}"
    temp_pay_col.update_one({"user_id": call.from_user.id}, {"$set": {"amount": unique_price, "mins": mins, "time": datetime.now()}}, upsert=True)
    upi_url = f"upi://pay?pa={UPI_ID}&am={unique_price}&cu=INR"
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_url)}"
    bot.send_photo(call.message.chat.id, qr_api, caption=f"⚠️ **DHYAN SE:**\nExactly **₹{unique_price}** hi pay karein.\n\nBot 1 min mein auto-approve kar dega.")

@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🔗 File Link bhejein:")
    bot.register_next_step_handler(msg, process_short)

def process_short(message):
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    bot.send_message(ADMIN_ID, f"✅ Link: `https://t.me/{bot.get_me().username}?start=vid_{fid}`")

@bot.message_handler(commands=['stats'], func=lambda m: m.from_user.id == ADMIN_ID)
def stats_cmd(message):
    active = users_col.count_documents({"expiry": {"$gt": datetime.now().timestamp()}})
    bot.send_message(ADMIN_ID, f"📊 Active Users: `{active}`")

def clean_up():
    temp_pay_col.delete_many({"time": {"$lt": datetime.now() - timedelta(minutes=30)}})

if __name__ == '__main__':
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))).start()
    scheduler = BackgroundScheduler(); scheduler.add_job(clean_up, 'interval', minutes=5); scheduler.start()
    bot.infinity_polling()
    
