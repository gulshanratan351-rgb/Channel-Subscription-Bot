import os, telebot, urllib.parse, uuid, datetime, re, threading, random, time
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from flask import Flask, request

# --- CONFIG ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
UPI_ID = os.getenv('UPI_ID')

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)

# YAHAN DHAYAN DEN: sample_mflix use kar rahe hain purane users ke liye
db = client['sample_mflix'] 
users_col = db['users']
links_col = db['short_links']
temp_pay_col = db['temp_payments']

PLANS = {"1440": "29", "10080": "99", "43200": "199"}
app = Flask(__name__)

@app.route('/')
def home(): return "Bot is Running in Polling Mode!", 200

# SMS Webhook for MacroDroid
@app.route('/sms_webhook', methods=['GET', 'POST'])
def handle_sms():
    try:
        sms_text = request.args.get('message') or request.form.get('message') or ""
        if sms_text:
            sms_text = sms_text.lower()
            bot.send_message(ADMIN_ID, f"📩 **SMS Log:**\n`{sms_text}`")
            amount_match = re.search(r'(\d+\.\d{2})', sms_text)
            if amount_match:
                amt = str(amount_match.group(1))
                pay_record = temp_pay_col.find_one({"amount": amt})
                if pay_record:
                    uid, mins, fid = pay_record['user_id'], int(pay_record['mins']), pay_record.get('fid')
                    exp = int((datetime.now() + timedelta(minutes=mins)).timestamp())
                    users_col.update_one({"user_id": uid}, {"$set": {"expiry": exp}}, upsert=True)
                    bot.send_message(uid, "✅ **Payment Success!** Prime membership active.")
                    if fid:
                        link_obj = links_col.find_one({"file_id": fid})
                        if link_obj: bot.send_message(uid, f"🎁 **Link:** {link_obj['url']}")
                    temp_pay_col.delete_one({"_id": pay_record['_id']})
                    bot.send_message(ADMIN_ID, f"💰 **Auto-Approved:** ₹{amt}")
        return "OK", 200
    except: return "Error", 500

# --- BOT COMMANDS (FIXED START HANDLER) ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    uid = message.from_user.id
    text = message.text
    
    # Check if coming from a Link (Deep Linking)
    if len(text.split()) > 1 and text.split()[1].startswith('vid_'):
        fid = text.split()[1].replace('vid_', '')
        link_obj = links_col.find_one({"file_id": fid})
        
        if link_obj:
            u_data = users_col.find_one({"user_id": uid})
            if u_data and u_data.get('expiry', 0) > datetime.now().timestamp():
                bot.send_message(uid, f"✅ **Aapka Link:** {link_obj['url']}")
            else:
                markup = InlineKeyboardMarkup()
                for mins, price in PLANS.items():
                    label = f"{int(mins)//1440} Day"
                    markup.add(InlineKeyboardButton(f"💳 {label} - ₹{price}", callback_data=f"p_{fid}_{mins}_{price}"))
                bot.send_message(uid, "🔒 **Prime Membership Required!**\n\nNiche se plan chunein:", reply_markup=markup)
        else:
            bot.send_message(uid, "❌ Link invalid ya expire ho gaya hai.")
        return

    # Normal Start
    if uid == ADMIN_ID:
        bot.reply_to(message, "👑 **ADMIN PANEL**\n\n/short - Create Link\n/stats - Check Users\n/broadcast - Send Msg")
    else:
        bot.send_message(uid, "👋 **Welcome!** Premium links ke liye prime membership lein.")

@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    if message.from_user.id == ADMIN_ID:
        total = users_col.count_documents({})
        active = users_col.count_documents({"expiry": {"$gt": datetime.now().timestamp()}})
        bot.reply_to(message, f"📊 **Stats:**\nTotal: {total}\nActive: {active}")

@bot.message_handler(commands=['short'])
def short_cmd(message):
    if message.from_user.id == ADMIN_ID:
        msg = bot.send_message(ADMIN_ID, "🔗 Link bhejein:")
        bot.register_next_step_handler(msg, process_short)

def process_short(message):
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    bot.send_message(ADMIN_ID, f"✅ **Link Ready:**\n`https://t.me/{bot.get_me().username}?start=vid_{fid}`")

@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, base_price = call.data.split('_')
    unique_price = f"{base_price}.{random.randint(10, 99)}"
    temp_pay_col.update_one({"user_id": call.from_user.id}, {"$set": {"amount": str(unique_price), "mins": mins, "fid": fid}}, upsert=True)
    upi_url = f"upi://pay?pa={UPI_ID}&am={unique_price}&cu=INR"
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_url)}"
    bot.send_photo(call.message.chat.id, qr_api, caption=f"⚠️ Exactly **₹{unique_price}** pay karein.")

# --- RUN BOT ---
if __name__ == '__main__':
    bot.remove_webhook()
    time.sleep(1)
    def run_flask():
        app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
    threading.Thread(target=run_flask).start()
    bot.infinity_polling()
    
