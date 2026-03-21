import os
import telebot
import urllib.parse
import uuid
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
def home(): return "Bot is running!"

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
CONTACT_USERNAME = os.getenv('CONTACT_USERNAME')

bot = telebot.TeleBot(BOT_TOKEN)
client = MongoClient(MONGO_URI)
db = client['sub_management']
channels_col = db['channels']
users_col = db['users']
settings_col = db['settings']
links_col = db['short_links'] # New collection for file links

# --- ADMIN COMMANDS ---

@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    args = message.text.split()

    # --- AGAR USER FILE LINK SE AAYA HAI ---
    if len(args) > 1 and args[1].startswith('vid_'):
        file_id = args[1].replace('vid_', '')
        link_data = links_col.find_one({"file_id": file_id})
        
        if link_data:
            # Check if User has active Prime
            u_data = users_col.find_one({"user_id": user_id})
            now = datetime.now().timestamp()
            
            if u_data and u_data.get('expiry', 0) > now:
                # Prime hai toh seedha link do
                bot.send_message(user_id, f"✅ **Prime Access Active!**\n\n🍿 Aapki File: {link_data['url']}\n\nEnjoy your movie!")
            else:
                # Prime nahi hai toh Pay karne ko bolo
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("💳 Pay ₹29 for 1 Day Access", callback_data=f"paynow_{file_id}"))
                bot.send_message(user_id, "🔒 **Access Denied!**\n\nYe file dekhne ke liye aapko Prime membership chahiye.\n\nEk baar pay karein aur **24 Ghante tak saare links** access karein!", reply_markup=markup)
        return

    # Default Start for Admin/User
    if user_id == ADMIN_ID:
        msg = "👑 **Admin Panel**\n\n/short - Create Prime Link for File\n/setlink - Set Main File Bot Link\n/stats - Check Users"
        bot.send_message(message.chat.id, msg, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "👋 Welcome! Subscribe to our prime to get access to all files.")

# --- LINK SHORTENER LOGIC ---

@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_process(message):
    sent = bot.send_message(ADMIN_ID, "🔗 Apne **File Store Bot** ka link bhejo jise Prime banana hai:")
    bot.register_next_step_handler(sent, save_short_link)

def save_short_link(message):
    url = message.text
    if "t.me/" not in url:
        bot.send_message(ADMIN_ID, "❌ Invalid Link! Please try /short again.")
        return
    
    file_id = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": file_id, "url": url})
    
    prime_link = f"https://t.me/{bot.get_me().username}?start=vid_{file_id}"
    bot.send_message(ADMIN_ID, f"✅ **Prime Link Created!**\n\nIse apne channel par dalo:\n`{prime_link}`", parse_mode="Markdown")

@bot.message_handler(commands=['setlink'], func=lambda m: m.from_user.id == ADMIN_ID)
def set_main_link(message):
    sent = bot.send_message(ADMIN_ID, "📧 Send main File Bot link:")
    bot.register_next_step_handler(sent, lambda m: [settings_col.update_one({"id":"cfg"},{"$set":{"link":m.text}},upsert=True), bot.send_message(ADMIN_ID, "✅ Saved!")])

# --- PAYMENT SYSTEM (FIXED QR) ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('paynow_'))
def show_payment(call):
    file_id = call.data.split('_')[1]
    price = "29" # Fixed price for 1 day
    
    # QR Encoding Fix
    upi_url = f"upi://pay?pa={UPI_ID}&pn=DvPrime&am={price}&cu=INR"
    encoded_upi = urllib.parse.quote(upi_url)
    qr_code = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={encoded_upi}"
    
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ I Have Paid", callback_data=f"paid_{file_id}")]])
    bot.send_photo(call.message.chat.id, qr_code, caption=f"💰 **Pay ₹{price} for 24h Access**\n\nUPI: `{UPI_ID}`\n\nPayment ke baad screenshot bhejein.", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('paid_'))
def ask_screenshot(call):
    file_id = call.data.split('_')[1]
    sent = bot.send_message(call.message.chat.id, "📸 Please send the **Payment Screenshot** now.")
    bot.register_next_step_handler(sent, admin_verify, file_id)

def admin_verify(message, file_id):
    if message.content_type != 'photo': return
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Approve", callback_data=f"app_{message.from_user.id}_{file_id}"), 
                                    InlineKeyboardButton("❌ Reject", callback_data=f"rej_{message.from_user.id}")]])
    bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=f"🔔 **New Payment!**\nUser: {message.from_user.id}\nFile ID: {file_id}", reply_markup=markup)
    bot.send_message(message.chat.id, "⌛ Verification pending... Admin will approve soon.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('app_'))
def final_approval(call):
    _, u_id, f_id = call.data.split('_')
    # 24 Hours (1440 Min) Expiry
    expiry_ts = int((datetime.now() + timedelta(days=1)).timestamp())
    users_col.update_one({"user_id": int(u_id)}, {"$set": {"expiry": expiry_ts}}, upsert=True)
    
    # Get the file link they wanted
    f_data = links_col.find_one({"file_id": f_id})
    file_url = f_data['url'] if f_data else "Link Expired"
    
    bot.send_message(int(u_id), f"🥳 **Payment Approved!**\n\n🌟 24 Ghante tak saare links open ho gaye hain.\n\n🔗 Aapki File: {file_url}")
    bot.edit_message_caption("✅ Approved!", call.message.chat.id, call.message.message_id)

# --- AUTO KICK / EXPIRY LOGIC ---

def kick_expired_members():
    now = datetime.now().timestamp()
    # Hum bas database se unka record clean kar denge, 
    # taki agali baar wo link click karein toh pay maange.
    users_col.delete_many({"expiry": {"$lte": now}})

if __name__ == '__main__':
    keep_alive()
    scheduler = BackgroundScheduler()
    scheduler.add_job(kick_expired_members, 'interval', minutes=5)
    scheduler.start()
    bot.infinity_polling()
    
