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
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://channel-subscription-bot-4nav.onrender.com')

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['sub_management']
users_col = db['users']
links_col = db['short_links']
temp_pay_col = db['temp_payments']

PLANS = {"1440": "29", "10080": "99", "43200": "199"}
app = Flask(__name__)

@app.route('/')
def home(): return "Bot is Online and Running!"

@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Forbidden", 403

# --- AUTO-APPROVAL WEBHOOK (Sahi wala) ---
@app.route('/sms_webhook', methods=['GET', 'POST'])
def handle_sms():
    try:
        # SMS app se 'message' parameter mein data aayega
        sms_text = request.args.get('message', '') or request.form.get('message', '')
        
        if sms_text:
            sms_text = sms_text.lower()
            bot.send_message(ADMIN_ID, f"📩 **New SMS Received:**\n`{sms_text}`")
            
            # Amount dhundhne ke liye (e.g. 29.15)
            amount_match = re.search(r'(\d+\.\d{2})', sms_text)
            if amount_match:
                amt = str(amount_match.group(1))
                
                # Database mein check karna
                pay_record = temp_pay_col.find_one({"amount": amt})
                if pay_record:
                    uid = pay_record['user_id']
                    mins = int(pay_record['mins'])
                    fid = pay_record.get('fid')
                    
                    # Expiry set karna
                    exp = int((datetime.now() + timedelta(minutes=mins)).timestamp())
                    users_col.update_one({"user_id": uid}, {"$set": {"expiry": exp}}, upsert=True)
                    
                    # User ko notify karna
                    bot.send_message(uid, "✅ **Payment Verified!** Aapka Prime membership active ho gaya hai.")
                    
                    # Link bhejna agar 'fid' tha
                    if fid:
                        link_obj = links_col.find_one({"file_id": fid})
                        if link_obj:
                            bot.send_message(uid, f"🎁 **Aapka Link:**\n{link_obj['url']}")
                    
                    # Cleanup aur Admin report
                    temp_pay_col.delete_one({"_id": pay_record['_id']})
                    bot.send_message(ADMIN_ID, f"💰 **Auto-Approved:** User `{uid}` ne ₹{amt} pay kiye.")
                    return "SUCCESS", 200
                    
        return "OK", 200
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Webhook Error: {str(e)}")
        return "ERROR", 500

# --- START & CALLBACK HANDLERS ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    uid = message.from_user.id
    text = message.text
    
    # Video link check
    match = re.search(r'vid_([a-zA-Z0-9]+)', text)
    if match:
        fid = match.group(1)
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
                bot.send_message(uid, "🔒 **Subscription Required!** Is link ko dekhne ke liye Prime membership chahiye.", reply_markup=markup)
            return

    if uid == ADMIN_ID:
        bot.send_message(uid, "👑 **ADMIN DASHBOARD**\n/short - Create Link\n/stats - Bot Status\n/approve ID Days")
    else:
        bot.send_message(uid, "👋 Hello! Subscribe karke premium content ka maza lein.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, base_price = call.data.split('_')
    # Random amount generate karna (e.g. 29.15) verification ke liye
    unique_price = f"{base_price}.{random.randint(10, 99)}"
    
    # Payment record save karna
    temp_pay_col.update_one(
        {"user_id": call.from_user.id}, 
        {"$set": {"amount": str(unique_price), "mins": mins, "fid": fid, "time": datetime.now()}}, 
        upsert=True
    )
    
    # QR Code banana
    upi_url = f"upi://pay?pa={UPI_ID}&am={unique_price}&cu=INR&tn=Prime_Sub"
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_url)}"
    
    bot.send_photo(call.message.chat.id, qr_api, caption=f"⚠️ **Payment Alert!**\n\nExactly **₹{unique_price}** pay karein.\n\nAutomatic approval ke liye sahi amount zaruri hai.")

# --- ADMIN UTILS ---
@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🔗 Content ka link bhejein:")
    bot.register_next_step_handler(msg, process_short)

def process_short(message):
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    bot.send_message(ADMIN_ID, f"✅ Done! Bot Link:\n`https://t.me/{bot.get_me().username}?start=vid_{fid}`")

# --- APP START ---
if __name__ == '__main__':
    bot.remove_webhook()
    time.sleep(2)
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
    
