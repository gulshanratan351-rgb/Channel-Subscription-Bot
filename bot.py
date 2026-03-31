import os, telebot, urllib.parse, uuid, datetime, re, threading, random, hmac, hashlib, json
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from flask import Flask, request

# --- CONFIG (Render Environment Variables se uthayega) ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
UPI_ID = os.getenv('UPI_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://channel-subscription-bot-4nav.onrender.com')
RAZORPAY_SECRET = os.getenv('RAZORPAY_SECRET', 'Gulshan@123') 

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['sub_management']
users_col = db['users']
links_col = db['short_links']
temp_pay_col = db['temp_payments']

PLANS = {"1440": "29", "10080": "99", "43200": "199"}
app = Flask(__name__)

@app.route('/')
def home(): return "Bot is Online and Ready!"

# --- 1. RAZORPAY WEBHOOK (Automatic Approval) ---
@app.route('/razorpay_webhook', methods=['POST'])
def razorpay_webhook():
    try:
        payload = request.json
        if payload and payload.get('event') == 'payment.captured':
            payment_entity = payload['payload']['payment']['entity']
            # Razorpay amount paise mein hota hai, isliye 100 se divide kiya
            amount_paid = "{:.2f}".format(float(payment_entity['amount']) / 100) 
            
            # Temp DB mein user dhoondo jisne ye exact amount pay kiya
            pay_record = temp_pay_col.find_one({"amount": str(amount_paid)})
            
            if pay_record:
                uid = pay_record['user_id']
                mins = int(pay_record['mins'])
                fid = pay_record.get('fid')
                
                exp = int((datetime.now() + timedelta(minutes=mins)).timestamp())
                users_col.update_one({"user_id": uid}, {"$set": {"expiry": exp}}, upsert=True)
                temp_pay_col.delete_one({"_id": pay_record['_id']})
                
                bot.send_message(uid, "✅ **Payment Verified!** Prime Subscription Activated.")
                
                if fid:
                    link_obj = links_col.find_one({"file_id": fid})
                    if link_obj:
                        bot.send_message(uid, f"🎁 **Aapka Requested Link:**\n{link_obj['url']}")
                
                bot.send_message(ADMIN_ID, f"💰 **Razorpay Success:** User `{uid}` paid ₹{amount_paid}")
        return "OK", 200
    except Exception as e:
        print(f"Webhook Error: {e}")
        return "Error", 500

# --- 2. TELEGRAM WEBHOOK ---
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Forbidden", 403

# --- 3. START & LINK HANDLER ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    uid = message.from_user.id
    text = message.text
    
    # Check if it's a file link request
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
                    label = f"{int(mins)//1440} Day" if int(mins) >= 1440 else f"{mins} Min"
                    markup.add(InlineKeyboardButton(f"💳 {label} - ₹{price}", callback_data=f"p_{fid}_{mins}_{price}"))
                bot.send_message(uid, "🔒 **Subscription Required!**\n\nIs link ko dekhne ke liye Prime membership chahiye.", reply_markup=markup)
            return

    if uid == ADMIN_ID:
        bot.send_message(uid, "👑 **ADMIN PANEL**\n\n/short - Create Link\n/stats - Bot Stats\n/broadcast - Message All")
    else:
        bot.send_message(uid, "👋 Hello! Links dekhne ke liye unhe open karein.")

# --- 4. SHORT LINK GENERATOR (Fixed) ---
@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🔗 Link bhejein jise short karna hai:")
    bot.register_next_step_handler(msg, process_short_link)

def process_short_link(message):
    if not message.text or message.text.startswith('/'):
        bot.send_message(ADMIN_ID, "❌ Galat Link! Fir se /short try karein.")
        return
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    bot_username = bot.get_me().username
    bot.send_message(ADMIN_ID, f"✅ **Short Link Taiyar Hai:**\n\nhttps://t.me/{bot_username}?start=vid_{fid}")

# --- 5. PAYMENT HANDLER (QR Generation) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, base_price = call.data.split('_')
    # Unique price for tracking (e.g., 29.45)
    unique_price = f"{base_price}.{random.randint(10, 99)}"
    
    temp_pay_col.update_one(
        {"user_id": call.from_user.id}, 
        {"$set": {"amount": str(unique_price), "mins": mins, "fid": fid, "time": datetime.now()}}, 
        upsert=True
    )
    
    upi_url = f"upi://pay?pa={UPI_ID}&am={unique_price}&cu=INR"
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_url)}"
    
    bot.send_photo(
        call.message.chat.id, 
        qr_api, 
        caption=f"⚠️ **Payment Required**\n\nPay exactly: **₹{unique_price}**\n\nPayment hote hi link automatic mil jayega."
    )

# --- 6. ADMIN TOOLS ---
@bot.message_handler(commands=['stats'], func=lambda m: m.from_user.id == ADMIN_ID)
def stats_cmd(message):
    total = users_col.count_documents({})
    bot.send_message(ADMIN_ID, f"📊 **Total Users:** {total}")

@bot.message_handler(commands=['broadcast'], func=lambda m: m.from_user.id == ADMIN_ID)
def broadcast_cmd(message):
    msg = bot.send_message(ADMIN_ID, "📢 Kya message bhejna hai?")
    bot.register_next_step_handler(msg, send_broadcast)

def send_broadcast(message):
    users = users_col.find({})
    count = 0
    for u in users:
        try:
            bot.send_message(u['user_id'], message.text)
            count += 1
        except: continue
    bot.send_message(ADMIN_ID, f"✅ {count} users ko message bhej diya.")

# --- LAUNCH ---
if __name__ == '__main__':
    bot.remove_webhook()
    import time; time.sleep(2)
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
    
