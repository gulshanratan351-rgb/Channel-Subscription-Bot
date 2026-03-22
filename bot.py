import os, telebot, urllib.parse, uuid, datetime
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread

# --- SERVER KEEP-ALIVE ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

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
utr_col = db['used_utrs']

PLANS = {"1440": "29", "10080": "99", "43200": "199"}

# --- ADMIN COMMANDS ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    uid = message.from_user.id
    args = message.text.split()
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
                bot.send_message(uid, "🔒 **Prime Required!**\nPay once to access all links:", reply_markup=markup)
        return
    if uid == ADMIN_ID:
        bot.send_message(uid, "👑 **ADMIN PANEL**\n/short, /stats, /broadcast, /deactivate")
    else:
        bot.send_message(uid, "👋 Welcome! Use a file link to start.")

@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🔗 Send File Link:")
    bot.register_next_step_handler(msg, lambda m: process_short(m))

def process_short(message):
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    bot.send_message(ADMIN_ID, f"✅ Link: `https://t.me/{bot.get_me().username}?start=vid_{fid}`", parse_mode="Markdown")

@bot.message_handler(commands=['stats'], func=lambda m: m.from_user.id == ADMIN_ID)
def stats_cmd(message):
    active = users_col.count_documents({"expiry": {"$gt": datetime.now().timestamp()}})
    bot.send_message(ADMIN_ID, f"📊 Active Users: `{active}`")

@bot.message_handler(commands=['deactivate'], func=lambda m: m.from_user.id == ADMIN_ID)
def deact_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🚫 Send User ID:")
    bot.register_next_step_handler(msg, lambda m: (users_col.delete_one({"user_id": int(m.text)}), bot.send_message(ADMIN_ID, "Done")))

@bot.message_handler(commands=['broadcast'], func=lambda m: m.from_user.id == ADMIN_ID)
def bc_cmd(message):
    msg = bot.send_message(ADMIN_ID, "📢 Send Message:")
    bot.register_next_step_handler(msg, do_bc)

def do_bc(message):
    for u in users_col.find({}):
        try: bot.copy_message(u['user_id'], ADMIN_ID, message.message_id)
        except: pass
    bot.send_message(ADMIN_ID, "✅ Sent!")

# --- PAYMENT ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, price = call.data.split('_')
    qr = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(f'upi://pay?pa={UPI_ID}&am={price}&cu=INR')}"
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Enter UTR", callback_data=f"utr_{fid}_{mins}")]])
    bot.send_photo(call.message.chat.id, qr, caption=f"💰 Pay ₹{price} & Enter UTR", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('utr_'))
def ask_utr(call):
    msg = bot.send_message(call.message.chat.id, "⌨️ Enter 12-digit UTR:")
    bot.register_next_step_handler(msg, verify_utr, call.data.split('_')[1], call.data.split('_')[2])

def verify_utr(message, fid, mins):
    utr = message.text.strip()
    if utr_col.find_one({"utr": utr}) or not utr.isdigit():
        bot.send_message(message.chat.id, "❌ Invalid or Used UTR!")
        return
    utr_col.insert_one({"utr": utr, "user_id": message.from_user.id})
    exp = int((datetime.now() + timedelta(minutes=int(mins))).timestamp())
    users_col.update_one({"user_id": message.from_user.id}, {"$set": {"expiry": exp, "warned": False}}, upsert=True)
    bot.send_message(message.chat.id, "🥳 Verified! Access Granted.")
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Cancel Access", callback_data=f"block_{message.from_user.id}")]])
    bot.send_message(ADMIN_ID, f"🔔 New Sale!\nID: `{message.from_user.id}`\nUTR: `{utr}`", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('block_'))
def block_btn(call):
    users_col.delete_one({"user_id": int(call.data.split('_')[1])})
    bot.answer_callback_query(call.id, "Revoked!")

# --- SCHEDULER ---
def check_subs():
    now = datetime.now().timestamp()
    warn_time = (datetime.now() + timedelta(minutes=10)).timestamp()
    for u in users_col.find({"expiry": {"$lte": warn_time, "$gt": now}, "warned": {"$ne": True}}):
        try: bot.send_message(u['user_id'], "⚠️ 10 mins left!"); users_col.update_one({"_id":u["_id"]},{"$set":{"warned":True}})
        except: pass
    users_col.delete_many({"expiry": {"$lte": now}})

if __name__ == '__main__':
    keep_alive()
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_subs, 'interval', minutes=1)
    scheduler.start()
    bot.infinity_polling()
    
