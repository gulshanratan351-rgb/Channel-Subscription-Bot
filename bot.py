import os
import telebot
from pymongo import MongoClient
from flask import Flask
from threading import Thread
import re
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- 1. RENDER PORT BINDING (Isse 'Port Error' nahi aayega) ---
app = Flask('')
@app.route('/')
def home(): return "Bot is Online!"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- 2. CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) 

bot = telebot.TeleBot(TOKEN)
client = MongoClient(MONGO_URI)
db = client['subscription_bot']

# --- 3. ADMIN COMMANDS (/add aur /channels) ---

@bot.message_handler(commands=['start'])
def start(message):
    if message.from_user.id == ADMIN_ID:
        bot.reply_to(message, "✅ **Admin Mode Active!**\n/add - Setup\n/channels - List")
    else:
        bot.reply_to(message, "Welcome! Payment karke **Screenshot** yahan bhejien.")

@bot.message_handler(commands=['add'])
def add_init(message):
    if message.from_user.id != ADMIN_ID: return
    msg = bot.reply_to(message, "Channel se message **FORWARD** karein.")
    bot.register_next_step_handler(msg, process_step_1)

def process_step_1(message):
    if message.forward_from_chat:
        c_id, c_name = message.forward_from_chat.id, message.forward_from_chat.title
        msg = bot.reply_to(message, f"Detected: {c_name}\nPlans bhejein (Min:Price).")
        bot.register_next_step_handler(msg, process_step_2, c_id, c_name)

def process_step_2(message, c_id, c_name):
    pattern = r'(\d+)\s*[:]\s*(\d+)'
    plans = {m[0]: m[1] for m in re.findall(pattern, message.text)}
    if plans:
        db.channels.update_one({'channel_id': c_id}, {'$set': {'name': c_name, 'plans': plans}}, upsert=True)
        bot_user = bot.get_me().username
        link = f"https://t.me/{bot_user}?start=sub_{abs(c_id)}"
        bot.send_message(message.chat.id, f"✅ **Setup Done!**\nLink: `{link}`", parse_mode="Markdown")
    else:
        bot.reply_to(message, "❌ Format galat hai!")

# --- 4. SCREENSHOT PROBLEM FIX (Ye wala part screenshot handle karega) ---

@bot.message_handler(content_types=['photo'])
def handle_screenshot(message):
    if message.from_user.id == ADMIN_ID: return # Admin photo bheje toh kuch na ho
    
    uid = message.from_user.id
    uname = message.from_user.first_name
    
    # Buttons for Admin
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Approve", callback_data=f"app_{uid}"),
               InlineKeyboardButton("❌ Reject", callback_data=f"rej_{uid}"))
    
    # Admin ko screenshot bhejna
    bot.send_photo(ADMIN_ID, message.photo[-1].file_id, 
                   caption=f"📩 **New Payment Request**\nFrom: {uname}\nID: `{uid}`", 
                   reply_markup=markup)
    
    bot.reply_to(message, "⏳ Screenshot Admin ko bhej diya gaya hai. Approval ka wait karein.")

# --- 5. BUTTON CLICKS (Approve/Reject) ---

@bot.callback_query_handler(func=lambda call: True)
def handle_approval(call):
    action, target_id = call.data.split("_")
    target_id = int(target_id)
    
    if action == "app":
        bot.send_message(target_id, "✅ **Approved!**\n\nAb aap channel join kar sakte hain. [APNI_LINK_DALEIN]")
        bot.edit_message_caption("✅ **Status: Approved**", chat_id=ADMIN_ID, message_id=call.message.message_id)
    else:
        bot.send_message(target_id, "❌ **Rejected!**\nAdmin ne aapka screenshot invalid bataya hai.")
        bot.edit_message_caption("❌ **Status: Rejected**", chat_id=ADMIN_ID, message_id=call.message.message_id)

if __name__ == "__main__":
    keep_alive()
    bot.infinity_polling()
    
