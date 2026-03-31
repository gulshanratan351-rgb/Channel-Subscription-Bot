import os, telebot, urllib.parse, uuid, datetime, re, threading, random
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
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['sub_management']
users_col = db['users']
links_col = db['short_links']
temp_pay_col = db['temp_payments']

# Plans: 7 Days (100), 1 Month (200), 3 Months (400)
PLANS = {"10080": "100", "43200": "200", "129600": "400"}
app = Flask(__name__)

@app.route('/')
def home(): 
    return "Bot is Online!"

@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def telegram_webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return "OK", 200
    return "Forbidden", 403

@bot.message_handler(commands=['start'])
def start_handler(message):
    uid = message.from_user.id
    text = message.text
    match = re.search(r'vid_([a-zA-Z0-9]+)', text)
    
    if match:
        fid = match.group(1)
        u_data = users_col.find_one({"user_id": uid})
        if u_data and u_data.get('expiry', 0) > datetime.now().timestamp():
            link_obj = links_col.find_one({"file_id": fid})
            if link_obj:
                bot.send_message(uid, f"✅ **Aapka Link:**\n{link_obj['url']}")
            return
        else:
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("💳 7 Days - ₹100", callback_data=f"p_{fid}_10080_100"))
            markup.add(InlineKeyboardButton("💳 1 Month - ₹200", callback_data=f"p_{fid}_43200_200"))
            markup.add(InlineKeyboardButton("💳 3 Months - ₹400", callback_data=f"p_{fid}_129600_400"))
            bot.send_message(uid, "🔒 **Prime Membership Required!**\n\nNiche se plan select karein aur screenshot bhein.", reply_markup=markup)
            return

    if uid == ADMIN_ID:
        bot.send_message(uid, "👑 **ADMIN PANEL**\n/short - Create Link\n/stats - Check Users")
    else:
        bot.send_message(uid, "👋 Movie link par click karke start karein.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, price = call.data.split('_')
    temp_pay_col.update_one({"user_id": call.from_user.id}, {"$set": {"mins": mins, "fid": fid, "price": price}}, upsert=True)
    upi_url = f"upi://pay?pa={UPI_ID}&am={price}&cu=INR"
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_url)}"
    bot.send_photo(call.message.chat.id, qr_api, caption=f"💰 **Amount: ₹{price}**\n\n⚠️ **Screenshot bhein:** Payment karne ke baad uska screenshot yahan bhein.")

@bot.message_handler(content_types=['photo'])
def handle_screenshot(message):
    uid = message.from_user.id
    if uid == ADMIN_ID:
        return
    pay_data = temp_pay_col.find_one({"user_id": uid})
    if pay_data:
        bot.send_message(uid, "⏳ **Checking...** Admin verify kar rahe hain.")
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Approve ✅", callback_data=f"appr_{uid}"),
                   InlineKeyboardButton("Reject ❌", callback_data=f"reje_{uid}"))
        bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"📩 **New Payment!**\nUser ID: `{uid}`\nPlan: ₹{pay_data['price']}", reply_markup=markup)
    else:
        bot.send_message(uid, "❌ Pehle koi plan select karein.")

@bot.callback_query_handler(func=lambda call: call.data.startswith(('appr_', 'reje_')))
def admin_approval(call):
    action, uid = call.data.split('_')
    uid = int(uid)
    if action == "appr":
        pay_data = temp_pay_col.find_one({"user_id": uid})
        if pay_data:
            exp = int((datetime.now() + timedelta(minutes=int(pay_data['mins']))).timestamp())
            users_col.update_one({"user_id": uid}, {"$set": {"expiry": exp}}, upsert=True)
            link_obj = links_col.find_one({"file_id": pay_data['fid']})
            link_msg = f"\n🎁 **Aapka Link:** {link_obj['url']}" if link_obj else ""
            bot.send_message(uid, f"✅ **Approved!** Prime active ho gaya.{link_msg}")
            bot.edit_message_caption("✅ Approved!", chat_id=ADMIN_ID, message_id=call.message.message_id)
            temp_pay_col.delete_one({"user_id": uid})
    else:
        bot.send_message(uid, "❌ Reject ho gaya. Sahi screenshot bhein.")
        bot.edit_message_caption("❌ Rejected!", chat_id=ADMIN_ID, message_id=call.message.message_id)

@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🔗 Link bhein:")
    bot.register_next_step_handler(msg, process_short)

def process_short(message):
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    bot.send_message(ADMIN_ID, f"✅ Done: https://t.me/{bot.get_me().username}?start=vid_{fid}")

if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
    
