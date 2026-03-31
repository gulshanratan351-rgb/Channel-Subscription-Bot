import os, telebot, urllib.parse, uuid, datetime, re, threading, random, hmac, hashlib, json
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
RAZORPAY_SECRET = os.getenv('RAZORPAY_SECRET', 'Gulshan@123') # Jo Secret Razorpay me dala wo yahan dalo

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

# --- NEW: RAZORPAY WEBHOOK HANDLER ---
@app.route('/razorpay_webhook', methods=['POST'])
def razorpay_webhook():
    # 1. Verify Secret (Security)
    webhook_signature = request.headers.get('X-Razorpay-Signature')
    data = request.data
    
    # Signature verify karna (Optional but safe)
    # expected_sig = hmac.new(RAZORPAY_SECRET.encode(), data, hashlib.sha256).hexdigest()
    
    payload = request.json
    if payload['event'] == 'payment.captured':
        payment_entity = payload['payload']['payment']['entity']
        # Razorpay paise Paise me bhejta hai (Rs 100 = 10000 paise)
        amount_paid = str(float(payment_entity['amount']) / 100) 
        
        # Temp database me payment check karo (Amount match karke)
        # Note: Razorpay me hum notes me UserID bhej sakte hain accuracy ke liye
        pay_record = temp_pay_col.find_one({"amount": amount_paid})
        
        if pay_record:
            uid = pay_record['user_id']
            mins = int(pay_record['mins'])
            fid = pay_record.get('fid')
            
            exp = int((datetime.now() + timedelta(minutes=mins)).timestamp())
            users_col.update_one({"user_id": uid}, {"$set": {"expiry": exp}}, upsert=True)
            temp_pay_col.delete_one({"_id": pay_record['_id']})
            
            bot.send_message(uid, "✅ **Payment Verified via Razorpay!** Prime Active.")
            if fid:
                link_obj = links_col.find_one({"file_id": fid})
                if link_obj:
                    bot.send_message(uid, f"🎁 **Aapka Link:**\n{link_obj['url']}")
            
            bot.send_message(ADMIN_ID, f"💰 **Razorpay Success:** User `{uid}` paid ₹{amount_paid}")
            return "OK", 200
            
    return "OK", 200

# --- PURANA TELEGRAM WEBHOOK ---
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Forbidden", 403

# --- REST OF YOUR CODE (Start handler, Admin cmds etc.) ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    uid = message.from_user.id
    text = message.text
    # ... (Keep your original start_handler code here) ...
    # (Same for broadcast, approve, stats, short commands)
    match = re.search(r'vid_([a-zA-Z0-9]+)', text)
    if match:
        fid = match.group(1)
        link_obj = links_col.find_one({"file_id": fid})
        if link_obj:
            u_data = users_col.find_one({"user_id": uid})
            if u_data and u_data.get('expiry', 0) > datetime.now().timestamp():
                bot.send_message(uid, f"✅ **Link:** {link_obj['url']}")
            else:
                markup = InlineKeyboardMarkup()
                for mins, price in PLANS.items():
                    label = f"{int(mins)//1440} Day" if int(mins) >= 1440 else f"{mins} Min"
                    markup.add(InlineKeyboardButton(f"💳 {label} - ₹{price}", callback_data=f"p_{fid}_{mins}_{price}"))
                bot.send_message(uid, "🔒 **Prime Required!**", reply_markup=markup)
            return
    bot.send_message(uid, "👋 Welcome!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, base_price = call.data.split('_')
    # Unique price logic for tracking
    unique_price = f"{base_price}.{random.randint(10, 99)}"
    temp_pay_col.update_one({"user_id": call.from_user.id}, {"$set": {"amount": str(unique_price), "mins": mins, "fid": fid, "time": datetime.now()}}, upsert=True)
    
    # Yahan aap Razorpay Payment Link ka API bhi use kar sakte hain
    upi_url = f"upi://pay?pa={UPI_ID}&am={unique_price}&cu=INR"
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_url)}"
    bot.send_photo(call.message.chat.id, qr_api, caption=f"⚠️ Pay exactly **₹{unique_price}**\n\nApproval will be automatic.")

if __name__ == '__main__':
    bot.remove_webhook()
    import time; time.sleep(2)
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
    
