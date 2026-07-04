import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommandScopeChat
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient
from bson.objectid import ObjectId

# Logging Configuration
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# Database Initialization
client = MongoClient(MONGO_URL)
db = client['tg_material_bot']
users_col = db['users']
material_col = db['materials']

# State Memory for Admin Actions
admin_states = {}

async def is_subscribed(bot, user_id):
    """Checks if the user is a member of the mandatory update channel."""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        return False

async def send_material_file(bot, chat_id, file_data):
    """Dispatches saved media or documents securely to users."""
    try:
        if file_data["file_type"] == "document":
            await bot.send_document(chat_id=chat_id, document=file_data["file_id"], caption=file_data["file_name"])
        elif file_data["file_type"] == "photo":
            await bot.send_photo(chat_id=chat_id, photo=file_data["file_id"], caption=file_data["file_name"])
        elif file_data["file_type"] == "video":
            await bot.send_video(chat_id=chat_id, video=file_data["file_id"], caption=file_data["file_name"])
    except Exception as e:
        logger.error(f"Error sending file: {e}")

async def setup_menus(application: Application):
    """Sets role-specific bot command menus dynamically via scopes on startup."""
    bot = application.bot
    try:
        user_commands = [
            ("start", "🚀 Start Bot"),
            ("categories", "🗂️ View Categories"),
            ("home", "🏠 Main Dashboard")
        ]
        await bot.set_my_commands(user_commands)
        
        if ADMIN_ID != 0:
            admin_commands = [
                ("start", "🚀 Start Bot"),
                ("categories", "🗂️ View Categories"),
                ("home", "🏠 Main Dashboard"),
                ("admin", "👑 Admin Panel"),
                ("broadcast", "📢 Broadcast Message")
            ]
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
        logger.info("Bot commands menu registered successfully.")
    except Exception as e:
        logger.error(f"Error setting menus: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered on /start or /home command."""
    user = update.effective_user
    user_id = user.id
    
    if not users_col.find_one({"user_id": user_id}):
        users_col.insert_one({"user_id": user_id, "username": user.username, "name": user.first_name})

    if not await is_subscribed(context.bot, user_id):
        keyboard = [
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}")],
            [InlineKeyboardButton("🔄 Verify Me", callback_data="verify")]
        ]
        await update.message.reply_text("❌ Pehle upar diye channel ko join karein!", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    await show_main_menu(update.message, user.first_name, is_edit=False)

async def show_main_menu(message_obj, name, is_edit=True):
    """Renders the top level dashboard."""
    keyboard = [
        [InlineKeyboardButton("🗂️ View Categories", callback_data="view_cats")],
        [InlineKeyboardButton("👤 My Profile", callback_data="my_profile"), InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")]
    ]
    text = f"🔥 Hello {name}! Welcome to Main Menu.\n\nAapko jo bhi PDF, Video ya Notes chahiye, aap unka Naam chat me likh kar direct search kar sakte hain!"
    if is_edit:
        # FIXED: Changed edit_message_text to edit_text for Message object
        await message_obj.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message_obj.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(context.bot, update.effective_user.id): return
    await show_categories_menu(update.message, is_edit=False)

async def show_categories_menu(message_obj, is_edit=True):
    """Renders all categories dynamically."""
    categories = material_col.distinct("category", {"status": "live"})
    if not categories:
        keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")]]
        msg = "🗂️ Abhi tak koi category nahi banayi gayi hai."
        # FIXED: Changed edit_message_text to edit_text for Message object
        if is_edit: await message_obj.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else: await message_obj.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    keyboard = [[InlineKeyboardButton(f"📂 {cat}", callback_data=f"vcat_{cat}")] for cat in categories]
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")])
    # FIXED: Changed edit_message_text to edit_text for Message object
    if is_edit: await message_obj.edit_text("📂 Niche di gayi categories me se chunein:", reply_markup=InlineKeyboardMarkup(keyboard))
    else: await message_obj.reply_text("📂 Niche di gayi categories me se chunein:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Renders administrative operations dashboard."""
    if update.effective_user.id != ADMIN_ID: return
    keyboard = [
        [InlineKeyboardButton("📂 Manage All Content", callback_data="manage_files")],
        [InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")]
    ]
    await update.message.reply_text("👑 *Admin Control Panel:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def manage_files_list(query):
    """Lists files inside admin interface."""
    files = list(material_col.find({}))
    if not files:
        await query.edit_message_text("🗂️ Database khali hai.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Back to Admin", callback_data="admin_home")]]))
        return

    keyboard = []
    for f in files:
        status_icon = "🟢" if f.get("status", "live") == "live" else "🔴"
        keyboard.append([InlineKeyboardButton(f"{status_icon} [{f['category']}-{f.get('subject','General')}] {f['file_name']}", callback_data=f"editfile_{f['_id']}")])
    keyboard.append([InlineKeyboardButton("🏠 Back to Admin", callback_data="admin_home")])
    await query.edit_message_text("📂 *Manage Content (Click to edit):*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def edit_file_options(query, file_id):
    """Interactive individual settings configuration panel for files."""
    file = material_col.find_one({"_id": ObjectId(file_id)})
    if not file: return
    current_status = file.get("status", "live")
    toggle_text = "🔴 Hide From Users" if current_status == "live" else "🟢 Make It Live"
    
    keyboard = [
        [InlineKeyboardButton(toggle_text, callback_data=f"toggle_{file_id}")],
        [InlineKeyboardButton("📦 Transfer File", callback_data=f"move_{file_id}"), InlineKeyboardButton("👯 Copy File", callback_data=f"copy_{file_id}")],
        [InlineKeyboardButton("🗑️ Delete Permanently", callback_data=f"del_{file_id}")],
        [InlineKeyboardButton("🔙 Back to List", callback_data="manage_files")]
    ]
    await query.edit_message_text(f"📝 *Managing:* `{file['file_name']}`\n📂 Cat: `{file['category']}` | 📚 Sub: `{file.get('subject','General')}`\n⚡ Status: `{current_status.upper()}`", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Central processing module for high-speed callback handling."""
    query = update.callback_query
    user_id = query.from_user.id
    
    await query.answer()

    try:
        if query.data == "verify":
            if await is_subscribed(context.bot, user_id):
                try:
                    await query.message.delete()
                except Exception: pass
                await show_main_menu(query.message, query.from_user.first_name, is_edit=False)

        elif query.data == "go_home":
            await show_main_menu(query.message, query.from_user.first_name, is_edit=True)

        elif query.data == "admin_home" and user_id == ADMIN_ID:
            keyboard = [[InlineKeyboardButton("📂 Manage All Content", callback_data="manage_files")], [InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")]]
            await query.edit_message_text("👑 *Admin Control Panel:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data == "manage_files" and user_id == ADMIN_ID:
            await manage_files_list(query)

        elif query.data.startswith("editfile_") and user_id == ADMIN_ID:
            fid = query.data.replace("editfile_", "")
            await edit_file_options(query, fid)

        elif query.data.startswith("toggle_") and user_id == ADMIN_ID:
            fid = query.data.replace("toggle_", "")
            f = material_col.find_one({"_id": ObjectId(fid)})
            if f:
                nst = "hidden" if f.get("status", "live") == "live" else "live"
                material_col.update_one({"_id": ObjectId(fid)}, {"$set": {"status": nst}})
                await edit_file_options(query, fid)

        elif query.data.startswith("del_") and user_id == ADMIN_ID:
            fid = query.data.replace("del_", "")
            material_col.delete_one({"_id": ObjectId(fid)})
            await manage_files_list(query)

        elif (query.data.startswith("move_") or query.data.startswith("copy_")) and user_id == ADMIN_ID:
            mode, fid = query.data.split("_", 1)
            admin_states[user_id] = {"action": mode, "fid": fid}
            keyboard = [
                [InlineKeyboardButton("📚 SSC", callback_data="tcat_SSC"), InlineKeyboardButton("🏛️ UPSC", callback_data="tcat_UPSC")],
                [InlineKeyboardButton("💻 Banking", callback_data="tcat_Banking"), InlineKeyboardButton("🧪 NEET/JEE", callback_data="tcat_NEET_JEE")]
            ]
            await query.edit_message_text("🎯 Target **Main Category** select kijiye:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data.startswith("tcat_") and user_id == ADMIN_ID:
            tcat = query.data.replace("tcat_", "")
            if user_id in admin_states:
                admin_states[user_id]["target_cat"] = tcat
                keyboard = [
                    [InlineKeyboardButton("📐 Maths", callback_data="tsub_Maths"), InlineKeyboardButton("🌍 GK/GS", callback_data="tsub_GK")],
                    [InlineKeyboardButton("🧠 Reasoning", callback_data="tsub_Reasoning"), InlineKeyboardButton("🔤 English", callback_data="tsub_English")]
                ]
                await query.edit_message_text(f"Category *{tcat}* done. Target **Subject** chunein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data.startswith("tsub_") and user_id == ADMIN_ID:
            tsub = query.data.replace("tsub_", "")
            state = admin_states.get(user_id)
            if state:
                orig_file = material_col.find_one({"_id": ObjectId(state["fid"])})
                if orig_file:
                    if state["action"] == "move":
                        material_col.update_one({"_id": ObjectId(state["fid"])}, {"$set": {"category": state["target_cat"], "subject": tsub, "status": "live"}})
                    elif state["action"] == "copy":
                        new_doc = orig_file.copy()
                        del new_doc["_id"]
                        new_doc["category"] = state["target_cat"]
                        new_doc["subject"] = tsub
                        material_col.insert_one(new_doc)
                admin_states.pop(user_id, None)
            await manage_files_list(query)

        elif query.data == "bot_stats":
            total_users = users_col.count_documents({})
            total_files = material_col.count_documents({})
            back = "admin_home" if user_id == ADMIN_ID else "go_home"
            await query.edit_message_text(f"📊 *Bot Status:*\n\n👥 Users: {total_users}\n📂 Files: {total_files}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data=back)]]), parse_mode="Markdown")

        elif query.data == "my_profile":
            await query.edit_message_text(f"👤 *Profile:*\n📝 Name: {query.from_user.first_name}\n🆔 ID: {user_id}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")]]), parse_mode="Markdown")

        elif query.data == "view_cats":
            await show_categories_menu(query.message, is_edit=True)

        elif query.data.startswith("vcat_"):
            cat_name = query.data.replace("vcat_", "")
            subjects = material_col.distinct("subject", {"category": cat_name, "status": "live"})
            if not subjects:
                await query.edit_message_text(f"❌ {cat_name} me koi live subjects nahi hain.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="view_cats")]]))
                return
            keyboard = [[InlineKeyboardButton(f"📚 {sub}", callback_data=f"vsub_{cat_name}__{sub}")] for sub in subjects]
            keyboard.append([InlineKeyboardButton("🔙 Back to Categories", callback_data="view_cats")])
            await query.edit_message_text(f"📂 *Category: {cat_name}*\nSubject chunein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data.startswith("vsub_"):
            payload = query.data.replace("vsub_", "")
            cat_name, sub_name = payload.split("__")
            materials = list(material_col.find({"category": cat_name, "subject": sub_name, "status": "live"}))
            if not materials:
                await query.edit_message_text("❌ Khali hai.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"vcat_{cat_name}")]]))
                return
            keyboard = [[InlineKeyboardButton(f"📥 {mat['file_name']}", callback_data=f"sfile_{mat['_id']}")] for mat in materials]
            keyboard.append([InlineKeyboardButton("🔙 Back to Subjects", callback_data=f"vcat_{cat_name}")])
            await query.edit_message_text(f"📚 *{cat_name} ➡️ {sub_name}*:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data.startswith("sfile_"):
            fid = query.data.replace("sfile_", "")
            file_data = material_col.find_one({"_id": ObjectId(fid)})
            if file_data and file_data.get("status", "live") == "live":
                await send_material_file(context.bot, user_id, file_data)

        elif query.data.startswith("acat_") and user_id == ADMIN_ID:
            category = query.data.replace("acat_", "")
            if user_id in admin_states:
                admin_states[user_id]["category"] = category
                keyboard = [
                    [InlineKeyboardButton("📐 Maths", callback_data="asub_Maths"), InlineKeyboardButton("🌍 GK/GS", callback_data="asub_GK")],
                    [InlineKeyboardButton("🧠 Reasoning", callback_data="asub_Reasoning"), InlineKeyboardButton("🔤 English", callback_data="asub_English")]
                ]
                await query.edit_message_text(f"Category *{category}* done. Select **Subject**:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data.startswith("asub_") and user_id == ADMIN_ID:
            subject = query.data.replace("asub_", "")
            file_data = admin_states.get(user_id)
            if file_data:
                file_data["subject"] = subject
                file_data["status"] = "live"
                material_col.insert_one(file_data)
                await query.edit_message_text("✅ *Successfully Saved!*", parse_mode="Markdown")
                admin_states.pop(user_id, None)
                
    except Exception as e:
        logger.error(f"Error handling button click callback: {e}", exc_info=True)

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a broadcast message to all users."""
    if update.effective_user.id != ADMIN_ID: return
    if not context.args: return
    broadcast_text = update.message.text.split(None, 1)[1]
    all_users = users_col.find({})
    for user in all_users:
        try:
            await context.bot.send_message(chat_id=user["user_id"], text=broadcast_text)
            await asyncio.sleep(0.05)
        except Exception: pass
    await update.message.reply_text("📢 Broadcast Done!")

async def handle_admin_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Intercepts media documents specifically for admin upload streams."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return
    
    message = update.message
    file_id, file_name, file_type = None, "Unnamed", None
    if message.document: file_id, file_name, file_type = message.document.file_id, message.document.file_name, "document"
    elif message.photo: file_id, file_name, file_type = message.photo[-1].file_id, message.caption or "Photo Note", "photo"
    elif message.video: file_id, file_name, file_type = message.video.file_id, message.video.file_name or message.caption or "Video Note", "video"

    if file_id:
        admin_states[user_id] = {"file_id": file_id, "file_name": file_name, "file_type": file_type}
        keyboard = [
            [InlineKeyboardButton("📚 SSC", callback_data="acat_SSC"), InlineKeyboardButton("🏛️ UPSC", callback_data="acat_UPSC")],
            [InlineKeyboardButton("💻 Banking", callback_data="acat_Banking"), InlineKeyboardButton("🧪 NEET/JEE", callback_data="acat_NEET_JEE")]
        ]
        await message.reply_text("📥 *Material mila!* Iski *Main Category* chunein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text query searches specifically for non-command messages."""
    user_id = update.effective_user.id
    if not await is_subscribed(context.bot, user_id): return
    
    search_query = update.message.text
    if search_query.startswith("/"): return 

    results = material_col.find({"file_name": {"$regex": search_query, "$options": "i"}, "status": "live"})
    count = material_col.count_documents({"file_name": {"$regex": search_query, "$options": "i"}, "status": "live"})
    if count == 0:
        await update.message.reply_text(f"🔍 '{search_query}' ke liye koi live material nahi mila.")
    else:
        text = f"🔍 *Search Results ({count}):*\n\n"
        for mat in results:
            text += f"🔹 /file_{mat['_id']} - {mat['file_name']} ({mat.get('subject','')})\n"
        await update.message.reply_text(text, parse_mode="Markdown")

async def handle_file_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles direct file links clicked from search results."""
    user_id = update.effective_user.id
    if not await is_subscribed(context.bot, user_id): return
    
    msg_text = update.message.text
    if msg_text.startswith("/file_"):
        file_id_str = msg_text.replace("/file_", "")
        try:
            file_data = material_col.find_one({"_id": ObjectId(file_id_str)})
            if file_data and file_data.get("status", "live") == "live":
                await send_material_file(context.bot, user_id, file_data)
            else:
                await update.message.reply_text("❌ Yeh file ab available nahi hai ya hide kar di gayi hai.")
        except Exception as e:
            logger.error(f"Error handling direct file link: {e}")
            await update.message.reply_text("❌ Invalid File ID.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs unexpected exceptions."""
    logger.error("Exception while handling an update:", exc_info=context.error)
# Command handler for users to request files
@app.on_message(filters.command("request") & filters.private)
async def request_file(client, message):
    # Check if the user has provided a file name along with the command
    if len(message.command) < 2:
        await message.reply_text(
            "**Please provide the file name!**\n"
            "Example: `/request Class 12 Physics Notes`"
        )
        return

    # Extract the requested file name
    file_request_name = message.text.split(None, 1)[1]
    user_info = f"👤 **Name:** {message.from_user.first_name}\n🆔 **ID:** `{message.from_user.id}`"
    
    # Prepare the alert message for the admin
    admin_msg = (
        "🚨 **New File Request Received!**\n\n"
        f"📂 **File Name:** {file_request_name}\n\n"
        f"👥 **Requested By:**\n{user_info}"
    )

    try:
        # Forward the request to your ADMIN_ID (already defined in your code)
        await client.send_message(chat_id=ADMIN_ID, text=admin_msg)
        
        # Send confirmation to the user
        await message.reply_text(
            "✅ **Your request has been sent to the admin!**\n"
            "As soon as the material is available, it will be uploaded to the bot."
        )
    except Exception as e:
        await message.reply_text("❌ Something went wrong. Please try again later.")
        print(f"Request error: {e}")

def main():
    """Starts the bot."""
    app = Application.builder().token(BOT_TOKEN).post_init(setup_menus).build()

    # Handlers Mapping with Structured Priorities
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("home", start))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    
    app.add_handler(CallbackQueryHandler(button_click))
    
    app.add_handler(MessageHandler(filters.Regex(r'^/file_[a-fA-F0-9]{24}$'), handle_file_link))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, handle_admin_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_search))

    app.add_error_handler(error_handler)
    app.run_polling()

if __name__ == '__main__':
    main()
