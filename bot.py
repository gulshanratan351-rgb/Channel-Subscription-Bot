pay_data = temp_pay_col.find_one({"user_id": uid})
    if pay_data:
        bot.send_message(uid, "⏳ **Verification Chal Raha Hai...**\nAdmin aapka screenshot check kar rahe hain. 5-10 minute wait karein.")
        
        # Admin ko Approval buttons ke saath bhejna
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Approve ✅", callback_data=f"appr_{uid}"),
                   InlineKeyboardButton("Reject ❌", callback_data=f"reje_{uid}"))
        
        bot.send_photo(ADMIN_ID, message.photo[-1].file_id, 
                      caption=f"📩 **New Payment Alert!**\nUser ID: `{uid}`\nPlan Price: ₹{pay_data['price']}", reply_markup=markup)
    else:
        bot.send_message(uid, "❌ Pehle koi plan select karein (Start link par click karke).")

# --- ADMIN BUTTON CLICK ---
@bot.callback_query_handler(func=lambda call: call.data.startswith(('appr_', 'reje_')))
def admin_action(call):
    action, uid = call.data.split('_')
    uid = int(uid)
    
    if action == "appr":
        pay_data = temp_pay_col.find_one({"user_id": uid})
        if pay_data:
            # Expiry Set Karna
            exp = int((datetime.now() + timedelta(minutes=int(pay_data['mins']))).timestamp())
            users_col.update_one({"user_id": uid}, {"$set": {"expiry": exp}}, upsert=True)
            
            # User ko Link Deliver karna
            link_obj = links_col.find_one({"file_id": pay_data['fid']})
            if link_obj:
                bot.send_message(uid, f"✅ **Payment Approved!**\n\n🎁 **Aapka Link:** {link_obj['url']}")
            
            bot.edit_message_caption("✅ User Approved!", chat_id=ADMIN_ID, message_id=call.message.message_id)
            temp_pay_col.delete_one({"user_id": uid})
    else:
        bot.send_message(uid, "❌ Aapka screenshot reject ho gaya hai. Sahi photo bhein.")
        bot.edit_message_caption("❌ Rejected!", chat_id=ADMIN_ID, message_id=call.message.message_id)

# --- ADMIN COMMANDS ---
@bot.message_handler(commands=['short'], func=lambda m: m.from_user.id == ADMIN_ID)
def short_cmd(message):
    msg = bot.send_message(ADMIN_ID, "🔗 Link bhein jise short karna hai:")
    bot.register_next_step_handler(msg, process_short)

def process_short(message):
    fid = str(uuid.uuid4())[:8]
    links_col.insert_one({"file_id": fid, "url": message.text})
    bot.send_message(ADMIN_ID, f"✅ Done: https://t.me/{bot.get_me().username}?start=vid_{fid}")

if __name__ == '__main__':
    bot.remove_webhook()
    bot.set_webhook(url=f"{WEBHOOK_URL}/{BOT_TOKEN}")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))

