import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient

BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@your_channel")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))

client = MongoClient(MONGO_URL)
db = client["AdvancedBotDB"]
users_col = db["users"]
files_col = db["files"]

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def is_subscribed(context, user_id):
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['creator', 'administrator', 'member']:
            return True
        return False
    except Exception:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not users_col.find_one({"user_id": user.id}):
        users_col.insert_one({"user_id": user.id, "username": user.username, "downloads": 0})
        
    if not await is_subscribed(context, user.id):
        keyboard = [
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}")],
            [InlineKeyboardButton("🔄 Verify Me", callback_data="verify_sub")]
        ]
        await update.message.reply_text(
            f"👋 Welcome {user.first_name}!\n\n⚠️ Bot ko use karne ke liye aapko humare channel ko join karna hoga.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    await send_main_menu(update.message, user.first_name)

async def send_main_menu(message_obj, name):
    keyboard = [
        [InlineKeyboardButton("📂 View Categories", callback_data="view_cats")],
        [InlineKeyboardButton("👤 My Profile", callback_data="profile"), InlineKeyboardButton("📊 Bot Stats", callback_data="stats")]
    ]
    await message_obj.reply_text(
        f"🔥 **Hello {name}! Welcome to Main Menu.**\n\nAapko jo bhi PDF, Video, Notes, ya Books chahiye, aap seedhe unka **Naam** chat me type karke search kar sakte hain!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def admin_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ **Error:** Kisi bhi file (PDF/Video) par reply karke ye command chalao!")
        return
    try:
        args = " ".join(context.args).split("|")
        category = args[0].strip().lower()
        tag = args[1].strip().lower()
        caption = args[2].strip()
    except Exception:
        await update.message.reply_text("❌ **Format Galat Hai!**\nUse karein: `/upload Category | Tag | Pure Caption`\n\nExample: `/upload notes | physics | Class 12 Physics Chapter 1 PDF`", parse_mode="Markdown")
        return

    rep = update.message.reply_to_message
    file_id = None
    file_name = caption

    if rep.document: file_id = rep.document.file_id
    elif rep.video: file_id = rep.video.file_id
    elif rep.audio: file_id = rep.audio.file_id
    elif rep.photo: file_id = rep.photo[-1].file_id

    if not file_id:
        await update.message.reply_text("❌ Ye file type supported nahi hai.")
        return

    files_col.insert_one({
        "file_id": file_id,
        "category": category,
        "tag": tag,
        "file_name": file_name.lower(),
        "display_name": file_name
    })
    await update.message.reply_text("✅ File successfully database me save ho gayi hai!")

async def search_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_subscribed(context, user_id):
        await update.message.reply_text("⚠️ Pehle channel join karke /start karein.")
        return
    query = update.message.text.strip().lower()
    results = list(files_col.find({"$or": [{"file_name": {"$regex": query}}, {"tag": query}]}).limit(5))
    if not results:
        await update.message.reply_text("😔 Maaf kijiyega, aapke search ke mutabik koi file nahi mili.")
        return
    await update.message.reply_text("🔍 **Aapke Search Results:**", parse_mode="Markdown")
    for file in results:
        keyboard = [[InlineKeyboardButton("📥 Download File", callback_data=f"dl_{file['_id']}")]]
        await update.message.reply_text(f"📄 **{file['display_name']}**\n🏷️ Category: {file['category'].upper()}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "verify_sub":
        if await is_subscribed(context, user_id):
            await query.message.delete()
            await send_main_menu(query.message, query.from_user.first_name)
        else:
            await query.message.reply_text("❌ Aapne abhi tak join nahi kiya. Pehle upar diye channel ko join karein!")
    elif data == "profile":
        u_data = users_col.find_one({"user_id": user_id}) or {"downloads": 0}
        text = f"👤 **Aapka Profile**\n\n🆔 User ID: `{user_id}`\n📥 Total Downloads: {u_data.get('downloads', 0)}\n⚡ Plan: Free User"
        keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="back_home")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "stats":
        total_u = users_col.count_documents({})
        total_f = files_col.count_documents({})
        text = f"📊 **Bot Real-time Statistics**\n\n👥 Total Active Users: {total_u}\n📁 Total Files Stored: {total_f}"
        keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="back_home")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "view_cats":
        cats = files_col.distinct("category")
        if not cats:
            keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="back_home")]]
            await query.edit_message_text("📂 Abhi koi categories available nahi hain.", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        keyboard = []
        for cat in cats:
            keyboard.append([InlineKeyboardButton(f"📁 {cat.upper()}", callback_data=f"cat_{cat}")])
        keyboard.append([InlineKeyboardButton("🔙 Main Menu", callback_data="back_home")])
        await query.edit_message_text("📂 **Available Categories:**\nNiche kisi ek par click karke files dekhein.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data.startswith("cat_"):
        selected_cat = data.split("_")[1]
        cat_files = list(files_col.find({"category": selected_cat}).limit(10))
        await query.message.reply_text(f"📂 **Category: {selected_cat.upper()} ki files:**")
        for file in cat_files:
            kb = [[InlineKeyboardButton("📥 Download", callback_data=f"dl_{file['_id']}")]]
            await query.message.reply_text(f"📄 {file['display_name']}", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("dl_"):
        from bson.objectid import ObjectId
        file_obj_id = data.split("_")[1]
        file_data = files_col.find_one({"_id": ObjectId(file_obj_id)})
        if file_data:
            await context.bot.send_document(chat_id=user_id, document=file_data["file_id"], caption=f"✅ Mana aapki requested file ready hai:\n**{file_data['display_name']}**", parse_mode="Markdown")
            users_col.update_one({"user_id": user_id}, {"$inc": {"downloads": 1}})
        else:
            await query.message.reply_text("❌ File data corrupt ho chuka hai ya delete ho gaya hai.")
    elif data == "back_home":
        keyboard = [
            [InlineKeyboardButton("📂 View Categories", callback_data="view_cats")],
            [InlineKeyboardButton("👤 My Profile", callback_data="profile"), InlineKeyboardButton("📊 Bot Stats", callback_data="stats")]
        ]
        await query.edit_message_text(f"🔥 **Main Menu**\n\nApna option select karein ya search karne ke liye text type karein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("upload", admin_upload))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_files))
    print("🚀 Bot Started...")
    app.run_polling()

if __name__ == '__main__':
    main()
