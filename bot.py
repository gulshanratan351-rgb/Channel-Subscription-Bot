import os, telebot, urllib.parse, uuid, datetime
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread

# --- RENDER KEEP-ALIVE ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online and Heavy!"

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
settings_col = db['settings']

# --- DEFAULT PLANS ---
PLANS = {
    "1440": "29",    # 1 Day
    "10080": "99",   # 7 Days
    "43200": "199"   # 30 Days
}

# --- MIDDLEWARE / CHECKER ---
def is_prime(user_id):
    u = users_col.find_one({"user_id": user_id})
    if u and u.get('expiry', 0) > datetime.now().timestamp():
        return True
    return False

# --- COMMANDS ---

@bot.message_handler(commands=['start'])
def start_handler(message):
    uid = message.from_user.id
    args = message.text.split()

    # 🎥 FILE ACCESS LOGIC
    if len(args) > 1 and args[1].startswith('vid_'):
        fid = args[1].replace('vid_', '')
        link_obj = links_col.find_one({"file_id": fid})
        
        if link_obj:
            if is_prime(uid):
                bot.send_message(uid, f"✅ **Access Granted!**\n\n🍿 Your Movie: {link_obj['url']}", disable_web_page_preview=False)
            else:
                markup = InlineKeyboardMarkup()
                for mins, price in PLANS.items():
                    label = f"{int(mins)//1440} Day" if int(mins) >= 1440 else f"{mins} Min"
                    markup.add(InlineKeyboardButton(f"💳 {label} - ₹{price}", callback_data=f"p_{fid}_{mins}_{price}"))
                bot.send_message(uid, "🔒 **This File is for Prime Members Only!**\n\nPay once and access all movies for the duration of your plan.", reply_markup=markup)
        return

    # 👑 ADMIN PANEL
    if uid == ADMIN_ID:
        panel = (
            "👑 **DV PRIME ADMIN PANEL**\n\n"
            "📝 `/short` - Create a new Prime movie link\n"
            "📊 `/stats` - View active subscribers\n"
            "📢 `/broadcast` - Send message to all users\n"
            "⚙️ `/setlink` - Set your main File Store Bot link"
        )
        bot.send_message(uid, panel, parse_mode="Markdown")
    else:
        bot.send_message(uid, "👋 Welcome! Click on a movie link from our channel to get started.")

# --- ADMIN FEATURES ---

@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🔗 Please send the **File Store Bot** link for this movie:")
    bot.register_next_step_handler(msg, process_short)

def process_short(message):
    if not message.text or "t.me" not in message.text:
        bot.send_message(ADMIN_ID, "❌ Invalid link. Try `/short` again.")
        return
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text, "created_at": datetime.now()})
    p_link = f"https://t.me/{bot.get_me().username}?start=vid_{fid}"
    bot.send_message(ADMIN_ID, f"✅ **Prime Link Created!**\n\nLink: `{p_link}`\n\nPost this in your channel.", parse_mode="Markdown")

@bot.message_handler(commands=['stats'], func=lambda m: m.from_user.id == ADMIN_ID)
def stats_cmd(message):
    total = users_col.count_documents({})
    active = users_col.count_documents({"expiry": {"$gt": datetime.now().timestamp()}})
    bot.send_message(ADMIN_ID, f"📊 **Bot Statistics**\n\nTotal Users: `{total}`\nActive Prime: `{active}`", parse_mode="Markdown")

@bot.message_handler(commands=['broadcast'], func=lambda m: m.from_user.id == ADMIN_ID)
def broadcast_cmd(message):
    msg = bot.send_message(ADMIN_ID, "📢 Send the message you want to broadcast to ALL users:")
    bot.register_next_step_handler(msg, do_broadcast)

def do_broadcast(message):
    users = users_col.find({})
    count = 0
    for u in users:
        try:
            bot.copy_message(u['user_id'], ADMIN_ID, message.message_id)
            count += 1
        except: pass
    bot.send_message(ADMIN_ID, f"✅ Broadcast sent to {count} users.")

# --- PAYMENT FLOW ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('p_'))
def handle_pay(call):
    _, fid, mins, price = call.data.split('_')
    upi_url = f"upi://pay?pa={UPI_ID}&pn=DvPrime&am={price}&cu=INR"
    qr_api = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(upi_url)}"
    
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ I Have Paid", callback_data=f"paid_{fid}_{mins}")]])
    bot.send_photo(call.message.chat.id, qr_api, caption=f"💰 **Total: ₹{price}**\n\nScan the QR and send the screenshot for approval.\n\nUPI: `{UPI_ID}`", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('paid_'))
def wait_ss(call):
    _, fid, mins = call.data.split('_')
    msg = bot.send_message(call.message.chat.id, "📸 Please upload your **Payment Screenshot** now:")
    bot.register_next_step_handler(msg, verify_with_admin, fid, mins)

def verify_with_admin(message, fid, mins):
    if message.content_type != 'photo':
        bot.send_message(message.chat.id, "❌ That's not a photo. Please try again.")
        return
    
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"app_{message.from_user.id}_{mins}_{fid}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"rej_{message.from_user.id}")]
    ])
    bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"🔔 **New Payment!**\nUser ID: `{message.from_user.id}`\nPlan: {mins} Mins", reply_markup=markup)
    bot.send_message(message.chat.id, "⌛ Verification sent! Please wait for admin approval.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('app_'))
def admin_approve(call):
    _, uid, mins, fid = call.data.split('_')
    exp = int((datetime.now() + timedelta(minutes=int(mins))).timestamp())
    users_col.update_one({"user_id": int(uid)}, {"$set": {"expiry": exp}}, upsert=True)
    
    # Send confirmation and the link they were looking for
    link_obj = links_col.find_one({"file_id": fid})
    f_url = link_obj['url'] if link_obj else "the file store"
    
    bot.send_message(int(uid), f"🥳 **Payment Approved!**\n\nYour access is active for {int(mins)//1440} day(s).\n\n🍿 Link: {f_url}")
    bot.edit_message_caption("✅ User Approved", call.message.chat.id, call.message.message_id)

# --- AUTO CLEANUP ---
def cleanup():
    now = datetime.now().timestamp()
    users_col.delete_many({"expiry": {"$lte": now}})

if __name__ == '__main__':
    keep_alive()
    scheduler = BackgroundScheduler()
    scheduler.add_job(cleanup, 'interval', minutes=10)
    scheduler.start()
    bot.infinity_polling()
    
