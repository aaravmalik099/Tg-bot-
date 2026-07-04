import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient
from bson.objectid import ObjectId

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================================
# ⚙️ CONFIGURATION & VARIABLES SECTION
# ==========================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# Database Setup
client = MongoClient(MONGO_URL)
db = client['tg_material_bot']
users_col = db['users']
material_col = db['materials']

# Admin State Tracker
admin_states = {}

# ==========================================================
# 🛡️ MIDDLEWARE / UTILITY FUNCTIONS SECTION
# ==========================================================
async def is_subscribed(bot, user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        return False

async def send_material_file(bot, chat_id, file_data):
    try:
        if file_data["file_type"] == "document":
            await bot.send_document(chat_id=chat_id, document=file_data["file_id"], caption=file_data["file_name"])
        elif file_data["file_type"] == "photo":
            await bot.send_photo(chat_id=chat_id, photo=file_data["file_id"], caption=file_data["file_name"])
        elif file_data["file_type"] == "video":
            await bot.send_video(chat_id=chat_id, video=file_data["file_id"], caption=file_data["file_name"])
    except Exception as e:
        logger.error(f"Error sending file: {e}")

# ==========================================================
# 👥 USER COMMANDS SECTION
# ==========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    if not users_col.find_one({"user_id": user_id}):
        users_col.insert_one({"user_id": user_id, "username": user.username, "name": user.first_name})

    if not await is_subscribed(context.bot, user_id):
        keyboard = [
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}")],
            [InlineKeyboardButton("🔄 Verify Me", callback_data="verify")]
        ]
        await update.message.reply_text(
            f"❌ Aapne abhi tak join nahi kiya. Pehle upar diye channel ko join karein!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    await show_main_menu(update.message, user.first_name)

async def show_main_menu(message_obj, name):
    keyboard = [
        [InlineKeyboardButton("🗂️ View Categories", callback_data="view_cats")],
        [InlineKeyboardButton("👤 My Profile", callback_data="my_profile"), 
         InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")]
    ]
    await message_obj.reply_text(
        f"🔥 Hello {name}! Welcome to Main Menu.\n\nAapko jo bhi PDF, Video ya Notes chahiye, aap unka Naam chat me likh kar direct search kar sakte hain!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(context.bot, update.effective_user.id): return
    await show_categories_menu(update.message, is_edit=False)

async def show_categories_menu(message_obj, is_edit=True):
    categories = material_col.distinct("category")
    if not categories:
        keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")]]
        msg = "🗂️ Abhi tak koi category nahi banayi gayi hai."
        if is_edit: await message_obj.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else: await message_obj.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    keyboard = [[InlineKeyboardButton(f"📂 {cat}", callback_data=f"cat_{cat}")] for cat in categories]
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")])
    
    if is_edit: await message_obj.edit_message_text("📂 Niche di gayi categories me se chunein:", reply_markup=InlineKeyboardMarkup(keyboard))
    else: await message_obj.reply_text("📂 Niche di gayi categories me se chunein:", reply_markup=InlineKeyboardMarkup(keyboard))

# ==========================================================
# 👑 ADMIN PANEL & MANAGEMENT SECTION
# ==========================================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    keyboard = [
        [InlineKeyboardButton("📂 Manage All Content", callback_data="manage_files")],
        [InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")]
    ]
    await update.message.reply_text("👑 *Admin Control Panel:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def manage_files_list(query):
    files = list(material_col.find({}))
    if not files:
        keyboard = [[InlineKeyboardButton("🏠 Back to Admin", callback_data="admin_home")]]
        await query.edit_message_text("🗂️ Database khali hai.", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    keyboard = []
    for f in files:
        status_icon = "🟢" if f.get("status", "live") == "live" else "🔴"
        keyboard.append([InlineKeyboardButton(f"{status_icon} [{f['category']}-{f.get('subject','General')}] {f['file_name']}", callback_data=f"editfile_{f['_id']}")])
    
    keyboard.append([InlineKeyboardButton("🏠 Back to Admin", callback_data="admin_home")])
    await query.edit_message_text("📂 *Manage Content (Click to Edit/Toggle Status):*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def edit_file_options(query, file_id):
    file = material_col.find_one({"_id": ObjectId(file_id)})
    if not file: return
    
    current_status = file.get("status", "live")
    toggle_text = "🔴 Hide From Users" if current_status == "live" else "🟢 Make It Live"
    toggle_data = f"toggle_{file_id}_{'hide' if current_status == 'live' else 'live'}"

    keyboard = [
        [InlineKeyboardButton(toggle_text, callback_data=toggle_data)],
        [InlineKeyboardButton("🗑️ Delete Permanently", callback_data=f"del_{file_id}")],
        [InlineKeyboardButton("🔙 Back to List", callback_data="manage_files")]
    ]
    await query.edit_message_text(
        f"📝 *Managing Content:*\n\n📄 Name: `{file['file_name']}`\n📂 Category: `{file['category']}`\n📚 Subject: `{file.get('subject','None')}`\n⚡ Status: `{'🟢 LIVE' if current_status == 'live' else '🔴 HIDDEN'}`", 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode="Markdown"
    )

# ==========================================================
# 🎛️ CALLBACK QUERY HANDLING
# ==========================================================
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "verify":
        if await is_subscribed(context.bot, user_id):
            await query.message.delete()
            await show_main_menu(query.message, query.from_user.first_name)

    elif query.data == "go_home":
        keyboard = [[InlineKeyboardButton("🗂️ View Categories", callback_data="view_cats")],
                    [InlineKeyboardButton("👤 My Profile", callback_data="my_profile"), InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")]]
        await query.edit_message_text(f"🔥 Hello {query.from_user.first_name}! Welcome to Main Menu.", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "admin_home" and user_id == ADMIN_ID:
        keyboard = [[InlineKeyboardButton("📂 Manage All Content", callback_data="manage_files")], [InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")]]
        await query.edit_message_text("👑 *Admin Control Panel:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "manage_files" and user_id == ADMIN_ID:
        await manage_files_list(query)

    elif query.data.startswith("editfile_") and user_id == ADMIN_ID:
        await edit_file_options(query, query.data.split("_")[1])

    elif query.data.startswith("toggle_") and user_id == ADMIN_ID:
        _, file_id, new_status = query.data.split("_")
        status_val = "live" if new_status == "live" else "hidden"
        material_col.update_one({"_id": ObjectId(file_id)}, {"$set": {"status": status_val}})
        await query.answer(f"Status Updated to {status_val.upper()}!")
        await edit_file_options(query, file_id)

    elif query.data.startswith("del_") and user_id == ADMIN_ID:
        material_col.delete_one({"_id": ObjectId(query.data.split("_")[1])})
        await query.answer("🗑️ Content Deleted!")
        await manage_files_list(query)

    elif query.data == "bot_stats":
        total_users = users_col.count_documents({})
        total_files = material_col.count_documents({})
        back_target = "admin_home" if user_id == ADMIN_ID else "go_home"
        await query.edit_message_text(f"📊 *Bot Status:*\n\n👥 Total Users: {total_users}\n📂 Total Files: {total_files}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data=back_target)]]), parse_mode="Markdown")

    elif query.data == "my_profile":
        await query.edit_message_text(f"👤 *Profile:*\n\n📝 Name: {query.from_user.first_name}\n🆔 ID: {user_id}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")]]), parse_mode="Markdown")

    elif query.data == "view_cats":
        await show_categories_menu(query.message, is_edit=True)

    elif query.data.startswith("cat_"):
        cat_name = query.data.split("_")[1]
        subjects = material_col.distinct("subject", {"category": cat_name, "status": "live"})
        
        if not subjects:
            await query.edit_message_text(f"❌ {cat_name} me abhi koi live subjects nahi hain.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="view_cats")]]))
            return
            
        keyboard = [[InlineKeyboardButton(f"📚 {sub}", callback_data=f"sub_{cat_name}_{sub}")] for sub in subjects]
        keyboard.append([InlineKeyboardButton("🔙 Back to Categories", callback_data="view_cats")])
        await query.edit_message_text(f"📂 *Category: {cat_name}*\n\nSubject select karein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data.startswith("sub_"):
        _, cat_name, sub_name = query.data.split("_")
        materials = list(material_col.find({"category": cat_name, "subject": sub_name, "status": "live"}))
        
        if not materials:
            await query.edit_message_text("❌ Is section me abhi koi live content nahi hai.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"cat_{cat_name}")]]))
            return

        keyboard = [[InlineKeyboardButton(f"📥 {mat['file_name']}", callback_data=f"sendfile_{mat['_id']}")] for mat in materials]
        keyboard.append([InlineKeyboardButton("🔙 Back to Subjects", callback_data=f"cat_{cat_name}")])
        await query.edit_message_text(f"📚 *{cat_name} ➡️ {sub_name}*:\n\nDownload karne ke liye click karein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data.startswith("sendfile_"):
        file_data = material_col.find_one({"_id": ObjectId(query.data.split("_")[1])})
        if file_data and file_data.get("status", "live") == "live":
            await send_material_file(context.bot, user_id, file_data)
        else:
            await context.bot.send_message(chat_id=user_id, text="❌ Sorry, ye content abhi live nahi hai ya remove ho gaya hai.")

    # Admin Upload Routing
    elif query.data.startswith("admin_cat_") and user_id == ADMIN_ID:
        category = query.data.replace("admin_cat_", "")
        admin_states[user_id]["category"] = category
        
        # Ask for Subject Now
        keyboard = [
            [InlineKeyboardButton("📐 Maths", callback_data="admin_sub_Maths"), InlineKeyboardButton("🌍 GK/GS", callback_data="admin_sub_GK")],
            [InlineKeyboardButton("🧠 Reasoning", callback_data="admin_sub_Reasoning"), InlineKeyboardButton("🔤 English", callback_data="admin_sub_English")],
            [InlineKeyboardButton("📝 Others", callback_data="admin_sub_Others")]
        ]
        await query.edit_message_text(f"📂 Category *{category}* select ho gayi.\n\nAb iska *Subject* select kijiye:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data.startswith("admin_sub_") and user_id == ADMIN_ID:
        subject = query.data.replace("admin_sub_", "")
        file_data = admin_states.get(user_id)
        
        if file_data:
            file_data["subject"] = subject
            file_data["status"] = "live" # Default state is live
            inserted = material_col.insert_one(file_data)
            await query.edit_message_text(f"✅ *Successfully Saved!* \n\n📂 Cat: `{file_data['category']}`\n📚 Sub: `{subject}`\n📄 Name: `{file_data['file_name']}`\n🔢 Code: `/file_{inserted.inserted_id}`", parse_mode="Markdown")
            admin_states.pop(user_id, None)

# ==========================================================
# 📢 ADMIN BROADCAST & UPLOAD HANDLERS
# ==========================================================
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("Format: `/broadcast Your Message`", parse_mode="Markdown")
        return

    broadcast_text = update.message.text.split(None, 1)[1]
    all_users = users_col.find({})
    success, failed = 0, 0
    status_msg = await update.message.reply_text("⏳ Broadcasting...")
    
    for user in all_users:
        try:
            await context.bot.send_message(chat_id=user["user_id"], text=broadcast_text)
            success += 1
            await asyncio.sleep(0.05)
        except Exception: failed += 1
            
    await status_msg.edit_text(f"📢 *Broadcast Report:*\n\n✅ Success: `{success}`\n❌ Failed: `{failed}`", parse_mode="Markdown")

async def handle_admin_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await handle_user_search(update, context)
        return

    message = update.message
    file_id, file_name, file_type = None, "Unnamed", None

    if message.document: file_id, file_name, file_type = message.document.file_id, message.document.file_name, "document"
    elif message.photo: file_id, file_name, file_type = message.photo[-1].file_id, message.caption or "Photo Note", "photo"
    elif message.video: file_id, file_name, file_type = message.video.file_id, message.video.file_name or message.caption or "Video Note", "video"

    if file_id:
        admin_states[user_id] = {"file_id": file_id, "file_name": file_name, "file_type": file_type}
        keyboard = [
            [InlineKeyboardButton("📚 SSC", callback_data="admin_cat_SSC"), InlineKeyboardButton("🏛️ UPSC", callback_data="admin_cat_UPSC")],
            [InlineKeyboardButton("💻 Banking", callback_data="admin_cat_Banking"), InlineKeyboardButton("🧪 NEET/JEE", callback_data="admin_cat_NEET_JEE")]
        ]
        await message.reply_text("📥 *Material mila!* Iski *Main Category* chunein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ==========================================================
# 🔍 USER SMART SEARCH
# ==========================================================
async def handle_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_subscribed(context.bot, user_id): return

    search_query = update.message.text
    if search_query.startswith("/file_"):
        try:
            file_data = material_col.find_one({"_id": ObjectId(search_query.replace("/file_", ""))})
            if file_data and file_data.get("status", "live") == "live":
                await send_material_file(context.bot, user_id, file_data)
            else: await update.message.reply_text("❌ File live nahi hai ya delete ho chuki hai.")
        except Exception: await update.message.reply_text("❌ Invalid Code.")
        return

    # Search only live files
    results = material_col.find({"file_name": {"$regex": search_query, "$options": "i"}, "status": "live"})
    count = material_col.count_documents({"file_name": {"$regex": search_query, "$options": "i"}, "status": "live"})

    if count == 0:
        await update.message.reply_text(f"🔍 '{search_query}' ke liye koi live material nahi mila.")
    else:
        text = f"🔍 *Search Results ({count}):*\n\n"
        for mat in results:
            text += f"🔹 /file_{mat['_id']} - {mat['file_name']} ({mat.get('subject','')})\n"
        await update.message.reply_text(text, parse_mode="Markdown")

# ==========================================================
# 🚀 SYSTEM STARTUP & MENU CONFIGURATION
# ==========================================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # ⭐ CLEAN USER-ONLY MENU CONFIGURATION ⭐
    user_commands = [
        ("start", "🚀 Restart/Start Bot"),
        ("categories", "🗂️ View Subjects & Content"),
        ("home", "🏠 Main Dashboard")
    ]
    loop = asyncio.get_event_loop()
    loop.run_until_complete(app.bot.set_my_commands(user_commands))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("home", start))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CallbackQueryHandler(button_click))
    
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, handle_admin_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_search))

    app.run_polling()

if __name__ == '__main__':
    main()
