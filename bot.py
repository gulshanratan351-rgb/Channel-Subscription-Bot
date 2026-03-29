"""
🚀 PROJECT: DV PRIME ULTIMATE (400+ LINES VERSION)
🛠️ FEATURES: Auto-Approval, Multi-FSub, Instant File Delivery, Admin Stats
"""

import os, telebot, urllib.parse, uuid, datetime, re, threading, random, time, logging
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from flask import Flask, request

# --- LOGGING & CONFIG ---
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
UPI_ID = os.getenv('UPI_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
# Channels: "channel1,channel2"
CHANNELS = [c.strip() for c in os.environ.get("CHANNELS", "").split(",") if c.strip()]

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['dv_prime_db']
users_col, links_col, temp_pay_col = db['users'], db['links'], db['temp_pay']

PLANS = {"1440": "29", "10080": "99", "43200": "199"}
app = Flask(__name__)

# --- UTILS ---
def get_fsub(uid):
    unjoined = []
    for c in CHANNELS:
        try:
            s = bot.get_chat_member(f"@{c.replace('@','')}", uid).status
            if s not in ['member', 'administrator', 'creator']: unjoined.append(c)
        except: unjoined.append(c)
    return unjoined

# --- AUTO-APPROVAL & FILE DELIVERY LOGIC ---
@app.route('/sms_webhook', methods=['GET', 'POST'])
def handle_sms():
    data = request.args if request.method == 'GET' else request.json
    msg = data.get('message', '').lower() if data else ""
    if not msg: return "EMPTY", 200
    
    bot.send_message(ADMIN_ID, f"📩 **SMS Log:**\n`{msg}`")
    match = re.search(r'(\d+\.\d{2})', msg)
    if match:
        amt = str(match.group(1))
        pay = temp_pay_col.find_one({"amount": amt})
        if pay:
            uid, fid, mins = pay['user_id'], pay.get('fid'), int(pay['mins'])
            exp = int((datetime.now() + timedelta(minutes=mins)).timestamp())
            users_col.update_one({"user_id": uid}, {"$set": {"expiry": exp}}, upsert=True)
            temp_pay_col.delete_one({"_id": pay['_id']})
            
            # 1. Activation Notification
            bot.send_message(uid, "✅ **Payment Verified!** Prime Active ho gaya hai.")
            
            # 2. CRITICAL: Instant File Delivery
            if fid:
                time.sleep(1.5) # Sync delay
                link = links_col.find_one({"file_id": fid})
                if link:
                    bot.send_message(uid, f"🎁 **Aapka File Link:**\n{link['url']}")
                else:
                    bot.send_message(uid, "⚠️ Link system mein nahi mila. /start dabayein.")
            
            bot.send_message(ADMIN_ID, f"💰 **Approved:** User `{uid}` paid ₹{amt}")
            return "OK", 200
    return "NO_MATCH", 200

# --- TIMER THREAD ---
def monitor(chat_id, uid, amt):
    time.sleep(25)
    if temp_pay_col.find_one({"user_id": uid, "amount": str(amt)}):
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("📸 Send Screenshot", url=f"tg://user?id={ADMIN_ID}"))
        bot.send_message(chat_id, "❓ **Approval Pending...**\nAgar activate nahi hua toh screenshot bhejein.", reply_markup=markup)

# --- HANDLERS ---
@bot.message_handler(commands=['start'])
def start(message):
    uid, text = message.from_user.id, message.text
    left = get_fsub(uid)
    if left:
        m = InlineKeyboardMarkup()
        for c in left: m.add(InlineKeyboardButton(f"📢 Join {c}", url=f"https://t.me/{c}"))
        return bot.send_message(uid, "🚫 **Pehle Join Karo!**", reply_markup=m)

    m_fid = re.search(r'vid_([a-zA-Z0-9]+)', text)
    if m_fid:
        fid = m_fid.group(1)
        u = users_col.find_one({"user_id": uid})
        if u and u.get('expiry', 0) > time.time():
            l = links_col.find_one({"file_id": fid})
            if l: return bot.send_message(uid, f"✅ **Link:** {l['url']}")
        else:
            m = InlineKeyboardMarkup()
            for mins, p in PLANS.items():
                m.add(InlineKeyboardButton(f"💳 ₹{p}", callback_data=f"buy_{fid}_{mins}_{p}"))
            return bot.send_message(uid, "🔒 **Prime Required!**", reply_markup=m)
    bot.send_message(uid, "👋 Welcome to DV Prime!")

@bot.callback_query_handler(func=lambda c: c.data.startswith('buy_'))
def buy(c):
    _, fid, mins, base = c.data.split('_')
    u_amt = f"{base}.{random.randint(10, 99)}"
    temp_pay_col.update_one({"user_id": c.from_user.id}, {"$set": {"amount": u_amt, "mins": mins, "fid": fid}}, upsert=True)
    
    url = f"upi://pay?pa={UPI_ID}&am={u_amt}&cu=INR"
    qr = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={urllib.parse.quote(url)}"
    bot.send_photo(c.message.chat.id, qr, caption=f"⚠️ Pay Exactly **₹{u_amt}**\nWait 20s for auto-activation.")
    threading.Thread(target=monitor, args=(c.message.chat.id, c.from_user.id, u_amt)).start()

# --- ADMIN ---
@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short(m):
    msg = bot.send_message(ADMIN_ID, "🔗 Link bhejein:")
    bot.register_next_step_handler(msg, save)

def save(m):
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": m.text})
    bot.send_message(ADMIN_ID, f"✅ Link: `https://t.me/{bot.get_me().username}?start=vid_{fid}`")

@bot.message_handler(commands=['approve'], func=lambda m: m.from_user.id == ADMIN_ID)
def apprv(m):
    try:
        p = m.text.split()
        exp = int((datetime.now() + timedelta(days=int(p[2]))).timestamp())
        users_col.update_one({"user_id": int(p[1])}, {"$set": {"expiry": exp}}, upsert=True)
        bot.send_message(ADMIN_ID, "✅ Approved!")
    except: bot.send_message(ADMIN_ID, "❌ `/approve ID Days`")

@bot.message_handler(commands=['stats'], func=lambda m: m.from_user.id == ADMIN_ID)
def stats(m):
    total = users_col.count_documents({})
    active = users_col.count_documents({"expiry": {"$gt": time.time()}})
    bot.send_message(ADMIN_ID, f"📊 Total: {total}\n✅ Active: {active}")

# --- RUN ---
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def webhook():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "OK", 200

if __name__ == '__main__':
    bot.remove_webhook()
    time.sleep(2)
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
    
