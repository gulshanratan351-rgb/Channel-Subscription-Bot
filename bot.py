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
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://channel-subscription-bot-4nav.onrender.com').rstrip('/')

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['sub_management']
users_col = db['users']
links_col = db['short_links']
temp_pay_col = db['temp_payments']

PLANS = {"1440": "29", "10080": "99", "43200": "199"}
app = Flask(__name__)

@app.route('/')
def home(): return "Bot is Online!", 200

@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Forbidden", 403

@app.route('/sms_webhook', methods=['GET', 'POST'])
def handle_sms():
    try:
        sms_text = request.args.get('message') or request.form.get('message') or ""
        if sms_text:
            bot.send_message(ADMIN_ID, f"📩 **SMS Log:**\n`{sms_text}`")
            amount_match = re.search(r'(\d+\.\d{2})', sms_text)
            if amount_match:
                amt = str(amount_match.group(1))
                pay_record = temp_pay_col.find_one({"amount": amt})
                if pay_record:
                    uid, mins, fid = pay_record['user_id'], int(pay_record['mins']), pay_record.get('fid')
                    exp = int((datetime.now() + timedelta(minutes=mins)).timestamp())
                    users_col.update_one({"user_id": uid}, {"$set": {"expiry": exp}}, upsert=True)
                    bot.send_message(uid, "✅ **Prime Active!**")
                    if fid:
                        link_obj = links_col.find_one({"file_id": fid})
                        if link_obj: bot.send_message(uid, f"🎁 **Link:** {link_obj['url']}")
                    temp_pay_col.delete_one({"_id": pay_record['_id']})
                    bot.send_message(ADMIN_ID, f"💰 **Approved:** ₹{amt}")
        return "OK", 200
    except Exception as e: return str(e), 500

# --- COMMANDS ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    uid = message.from_user.id
    
    # Check Admin First
    if uid == ADMIN_ID:
        bot.send_message(uid, "👑 **ADMIN PANEL ACTIVE**\n\n/short - Create Link\n/stats - Bot Stats\n/broadcast - Message All\n/approve ID Days")
        # Agar admin start link click kare toh niche ka logic bhi chale
    
    # Video Link Check
    if 'vid_' in message.text:
        fid = message.text.split('vid_')[1]
        link_obj = links_col.find_one({"file_id": fid})
        if link_obj:
            u_data = users_col.find_one({"user_id": uid})
            if u_data and u_data.get('expiry', 0) > datetime.now().timestamp():
                bot.send_message(uid, f"✅ **Link:** {link_obj['url']}")
            else:
                markup = InlineKeyboardMarkup()
                for mins, price in PLANS.items():
                    label = f"{int(mins)//1440} Day"
                    markup.add(InlineKeyboardButton(f"💳 {label} - ₹{price}", callback_data=f"p_{fid}_{mins}_{price}"))
                bot.send_message(uid, "🔒 **Prime Required!**", reply_markup=markup)
        return

    if uid != ADMIN_ID:
        bot.send_message(uid, "👋 **Welcome!** Subscribe to get premium links.")

@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    if message.from_user.id == ADMIN_ID:
        total = users_col.count_documents({})
        active = users_col.count_documents({"expiry": {"$gt": datetime.now().timestamp()}})
        bot.send_message(ADMIN_ID, f"📊 **Stats:**\nTotal: {total}\nActive: {active}")

@bot.message_handler(commands=['short'])
def short_cmd(message):
    if message.from_user.id == ADMIN_ID:
        msg = bot.send_message(ADMIN_ID, "🔗 Link bhejein:")
        bot.register_next_step_handler(msg, process_short)

def process_short(message):
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    bot.send_message(ADMIN_ID, f"✅ Done! Link:\n`https://t.me/{bot.get_me().username}?start=vid_{fid}`")

@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, base_price = call.data.split('_')
    unique_price = f"{base_price}.{random.randint(10, 99)}"
    temp_pay_col.update_one({"user_id": call.from_user.id}, {"$set": {"amount": str(unique_price), "mins": mins, "fid": fid}}, upsert=True)
    upi_url = f"upi://pay?pa={UPI_ID}&am={unique_price}&cu=INR"
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_url)}"
    bot.send_photo(call.message.chat.id, qr_api, caption=f"⚠️ Pay exactly **₹{unique_price}**")

if __name__ == '__main__':
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
    
