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
def home(): return "Bot is Online!"

@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Forbidden", 403

# --- AUTO-APPROVAL FIX (With Link Delivery) ---
@app.route('/sms_webhook', methods=['GET', 'POST'])
def handle_sms():
    try:
        sms_text = request.args.get('message', '').lower()
        if not sms_text and request.is_json:
            sms_text = request.json.get('message', '').lower()
        
        if sms_text:
            bot.send_message(ADMIN_ID, f"📩 **SMS Log:**\n`{sms_text}`")
            
            # --- Naya Solid Regex Implementation ---
            amount_match = re.search(r'(?:rs\.?|inr|amt)\s*([\d,]+\.\d{2})|([\d,]+\.\d{2})\s*(?:paid|received|deposited)', sms_text)

            if amount_match:
                # Decimal amount filter karke nikal lega
                amt = amount_match.group(1) or amount_match.group(2)
                amt = str(amt).replace(',', '') # Comma hatane ke liye
                
                # Database mein check karna ki ye amount kis user ka hai
                pay_record = temp_pay_col.find_one({"amount": amt})
                
                if pay_record:
                    uid = pay_record['user_id']
                    mins = int(pay_record['mins'])
                    fid = pay_record.get('fid')
                    
                    # Expiry update karna
                    exp = int((datetime.now() + timedelta(minutes=mins)).timestamp())
                    users_col.update_one({"user_id": uid}, {"$set": {"expiry": exp}}, upsert=True)
                    
                    # Temp record delete karna
                    temp_pay_col.delete_one({"_id": pay_record['_id']})
                    
                    # User ko Confirmation aur Link bhejna
                    bot.send_message(uid, "✅ **Payment Verified!** Aapka Prime account active ho gaya hai.")
                    
                    if fid:
                        link_obj = links_col.find_one({"file_id": fid})
                        if link_obj:
                            bot.send_message(uid, f"🎁 **Aapka Requested Link Ye Raha:**\n{link_obj['url']}")
                    
                    bot.send_message(ADMIN_ID, f"💰 **Auto-Approved:** User `{uid}` paid ₹{amt}")
                    return "SUCCESS", 200
                    
        return "NO MATCH", 200
    except Exception as e: 
        bot.send_message(ADMIN_ID, f"❌ Webhook Error: {str(e)}")
        return "ERROR", 500
                
# --- START HANDLER ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    uid = message.from_user.id
    text = message.text
    if uid != ADMIN_ID:
        try: bot.send_message(ADMIN_ID, f"👤 **New User Alert!**\nID: `{uid}`")
        except: pass

    match = re.search(r'vid_([a-zA-Z0-9]+)', text)
    if match:
        fid = match.group(1)
        link_obj = links_col.find_one({"file_id": fid})
        if link_obj:
            u_data = users_col.find_one({"user_id": uid})
            if u_data and u_data.get('expiry', 0) > datetime.now().timestamp():
                bot.send_message(uid, f"✅ **Link Access Granted:**\n{link_obj['url']}")
            else:
                markup = InlineKeyboardMarkup()
                for mins, price in PLANS.items():
                    label = f"{int(mins)//1440} Day" if int(mins) >= 1440 else f"{mins} Min"
                    markup.add(InlineKeyboardButton(f"💳 {label} - ₹{price}", callback_data=f"p_{fid}_{mins}_{price}"))
                bot.send_message(uid, "🔒 **Prime Required!**\n\nIs file ko dekhne ke liye subscription lein:", reply_markup=markup)
            return
            
    if uid == ADMIN_ID:
        bot.send_message(uid, "👑 **ADMIN PANEL**\n/short - Create Link\n/stats - Check Users\n/broadcast - Message All\n/approve ID Days\n/deactivate ID")
    else: 
        bot.send_message(uid, "👋 Welcome! Buy Prime to access all links.")

# --- ADMIN COMMANDS ---
@bot.message_handler(commands=['broadcast'], func=lambda m: m.from_user.id == ADMIN_ID)
def broadcast_cmd(message):
    msg = bot.send_message(ADMIN_ID, "📢 Message bhejein:")
    bot.register_next_step_handler(msg, lambda m: [bot.send_message(u['user_id'], m.text) for u in users_col.find({})])

@bot.message_handler(commands=['approve'], func=lambda m: m.from_user.id == ADMIN_ID)
def manual_approve(message):
    try:
        _, tid, days = message.text.split()
        exp = int((datetime.now() + timedelta(days=int(days))).timestamp())
        users_col.update_one({"user_id": int(tid)}, {"$set": {"expiry": exp}}, upsert=True)
        bot.send_message(tid, "✅ **Prime Activated!** Admin ne aapka account approve kar diya hai.")
        bot.send_message(ADMIN_ID, f"✅ User {tid} approved for {days} days.")
    except: bot.send_message(ADMIN_ID, "❌ Use: `/approve ID Days`")

@bot.message_handler(commands=['deactivate'], func=lambda m: m.from_user.id == ADMIN_ID)
def deactivate_cmd(message):
    try:
        tid = int(message.text.split()[1])
        users_col.delete_one({"user_id": tid})
        bot.send_message(ADMIN_ID, f"🚫 User {tid} deactivated.")
    except: bot.send_message(ADMIN_ID, "❌ Use: `/deactivate ID`")

@bot.message_handler(commands=['stats'], func=lambda m: m.from_user.id == ADMIN_ID)
def stats_cmd(message):
    try:
        total = users_col.count_documents({})
        now = datetime.now().timestamp()
        active_users = list(users_col.find({"expiry": {"$gt": now}}))
        
        msg = f"📊 **Bot Stats:**\n\n👥 Total Database Users: `{total}`\n⚡ Active Prime Users: `{len(active_users)}`"
        if active_users:
            msg += "\n\n🆔 **Active IDs:**\n" + "\n".join([f"`{u['user_id']}`" for u in active_users[:30]])
            if len(active_users) > 30: msg += f"\n...and {len(active_users)-30} more."
        
        bot.send_message(ADMIN_ID, msg)
    except Exception as e:
        bot.send_message(ADMIN_ID, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🔗 Link bhejein:")
    bot.register_next_step_handler(msg, process_short)

def process_short(message):
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    bot.send_message(ADMIN_ID, f"✅ Link: https://t.me/{bot.get_me().username}?start=vid_{fid}")

# --- QR & AUTO-FILL ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, base_price = call.data.split('_')
    unique_price = f"{base_price}.{random.randint(10, 99)}"
    
    # Database mein transaction record save karna
    temp_pay_col.update_one(
        {"user_id": call.from_user.id}, 
        {"$set": {"amount": str(unique_price), "mins": mins, "fid": fid, "time": datetime.now()}}, 
        upsert=True
    )
    
    upi_url = f"upi://pay?pa={UPI_ID}&am={unique_price}&cu=INR&tn=PrimeSub"
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&data={urllib.parse.quote(upi_url)}&margin=10"
    
    caption = (
        f"💳 **Payment Invoice**\n\n"
        f"💵 Amount: `₹{unique_price}`\n"
        f"⏳ Time Limit: 15 Minutes\n\n"
        f"⚠️ **IMPORTANT:** Pura amount bhejein (Paise ke saath) varna auto-approval nahi hoga.\n\n"
        f"Payment ke baad 15-20 seconds wait karein."
    )
    bot.send_photo(call.message.chat.id, qr_api, caption=caption)

if __name__ == '__main__':
    bot.remove_webhook()
    time.sleep(2)
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
    
