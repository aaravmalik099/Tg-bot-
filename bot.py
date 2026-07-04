import os
import logging
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

# Admin State Tracker (To track what admin is uploading)
admin_states = {}

# ==========================================================
# 🛡️ MIDDLEWARE / UTILITY FUNCTIONS SECTION
# ==========================================================
async def is_subscribed(bot, user_id):
    """Checks if the user is subscribed to the mandatory channel."""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        return False

# Function to safely send stored files
async def send_material_file(bot, chat_id, file_data):
    if file_data["file_type"] == "document":
        await bot.send_document(chat_id=chat_id, document=file_data["file_id"], caption=file_data["file_name"])
    elif file_data["file_type"] == "photo":
        await bot.send_photo(chat_id=chat_id, photo=file_data["file_id"], caption=file_data["file_name"])
    elif file_data["file_type"] == "video":
        await bot.send_video(chat_id=chat_id, video=file_data["file_id"], caption=file_data["file_name"])

# ==========================================================
# 👥 USER COMMANDS SECTION (Start, Verify, Main Menu)
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
        f"🔥 Hello {name}! Welcome to Main Menu.\n\nAapko jo bhi PDF, Video, Notes chahiye, aap unka Naam chat me type karke search kar sakte hain!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def edit_to_main_menu(query, name):
    keyboard = [
        [InlineKeyboardButton("🗂️ View Categories", callback_data="view_cats")],
        [InlineKeyboardButton("👤 My Profile", callback_data="my_profile"), 
         InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")]
    ]
    await query.edit_message_text(
        f"🔥 Hello {name}! Welcome to Main Menu.\n\nAapko jo bhi PDF, Video, Notes chahiye, aap unka Naam chat me type karke search kar sakte hain!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==========================================================
# 🎛️ CALLBACK QUERY SECTION (Navigation Enhanced)
# ==========================================================
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "verify":
        if await is_subscribed(context.bot, user_id):
            await query.message.delete()
            await show_main_menu(query.message, query.from_user.first_name)
        else:
            await context.bot.send_message(chat_id=user_id, text="❌ Mujhe abhi bhi aap channel me nahi dikhe. Dubara join karein aur Verify dabayein.")

    elif query.data == "go_home":
        await edit_to_main_menu(query, query.from_user.first_name)

    elif query.data == "bot_stats":
        total_users = users_col.count_documents({})
        total_files = material_col.count_documents({})
        keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")]]
        await query.edit_message_text(f"📊 *Bot Live Status:*\n\n👥 Total Users: {total_users}\n📂 Total Files Uploaded: {total_files}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "my_profile":
        keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")]]
        await query.edit_message_text(f"👤 *Aapki Profile:*\n\n📝 Name: {query.from_user.first_name}\n🆔 ID: {user_id}\n🔗 Username: @{query.from_user.username}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data == "view_cats":
        categories = material_col.distinct("category")
        if not categories:
            keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")]]
            await query.edit_message_text("🗂️ Abhi tak koi category nahi banayi gayi hai. Admin jald hi material upload karenge!", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        
        keyboard = [[InlineKeyboardButton(cat, callback_data=f"cat_{cat}")] for cat in categories]
        keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")]) # Home button inside category list
        await query.edit_message_text("📂 Niche di gayi categories me se chunein:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data.startswith("cat_"):
        category_name = query.data.split("_")[1]
        materials = list(material_col.find({"category": category_name}))
        
        if not materials:
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="view_cats")]]
            await query.edit_message_text(f"❌ {category_name} me abhi koi file nahi hai.", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        keyboard = []
        for mat in materials:
            keyboard.append([InlineKeyboardButton(f"📥 {mat['file_name']}", callback_data=f"sendfile_{mat['_id']}")])
        
        # Dual Navigation: Back and Home Buttons
        keyboard.append([
            InlineKeyboardButton("🔙 Back to Categories", callback_data="view_cats"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")
        ])
        await query.edit_message_text(f"📚 *Category: {category_name}*\n\nFile download karne ke liye niche button par click karein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif query.data.startswith("sendfile_"):
        file_obj_id = query.data.split("_")[1]
        try:
            file_data = material_col.find_one({"_id": ObjectId(file_obj_id)})
            if file_data:
                await send_material_file(context.bot, user_id, file_data)
            else:
                await context.bot.send_message(chat_id=user_id, text="❌ File nahi mili ya delete ho gayi hai.")
        except Exception as e:
            logger.error(f"Error sending file via button: {e}")

    elif query.data.startswith("admin_cat_"):
        if user_id != ADMIN_ID: return
        category = query.data.replace("admin_cat_", "")
        file_data = admin_states.get(user_id)
        
        if file_data:
            file_data["category"] = category
            inserted = material_col.insert_one(file_data)
            await query.message.reply_text(f"✅ *Success!* File database me save ho gayi.\n\n📂 Category: {category}\n📝 Name: {file_data['file_name']}\n🔢 Short Code: `/file_{inserted.inserted_id}`", parse_mode="Markdown")
            admin_states.pop(user_id, None)

# ==========================================================
# 📂 ADMIN MATERIAL UPLOAD SECTION
# ==========================================================
async def handle_admin_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await handle_user_search(update, context)
        return

    message = update.message
    file_id = None
    file_name = "Unnamed File"
    file_type = None

    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name
        file_type = "document"
    elif message.photo:
        file_id = message.photo[-1].file_id
        file_name = message.caption if message.caption else "Photo Note"
        file_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        file_name = message.video.file_name if message.video.file_name else (message.caption if message.caption else "Video Note")
        file_type = "video"

    if file_id:
        admin_states[user_id] = {
            "file_id": file_id,
            "file_name": file_name,
            "file_type": file_type
        }
        
        keyboard = [
            [InlineKeyboardButton("📚 SSC", callback_data="admin_cat_SSC"), InlineKeyboardButton("🏛️ UPSC", callback_data="admin_cat_UPSC")],
            [InlineKeyboardButton("💻 Banking", callback_data="admin_cat_Banking"), InlineKeyboardButton("🧪 NEET/JEE", callback_data="admin_cat_NEET_JEE")],
            [InlineKeyboardButton("📝 Others", callback_data="admin_cat_Others")]
        ]
        await message.reply_text(
            f"📥 *Material Received!*\n\n📄 Name: `{file_name}`\n\nAb niche diye gaye buttons me se iski *Category* select karein:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

# ==========================================================
# 🔍 USER SEARCH & FILE DELIVERY SECTION
# ==========================================================
async def handle_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not await is_subscribed(context.bot, user_id):
        await start(update, context)
        return

    search_query = update.message.text
    
    if search_query.startswith("/file_"):
        try:
            file_obj_id = search_query.replace("/file_", "")
            file_data = material_col.find_one({"_id": ObjectId(file_obj_id)})
            
            if file_data:
                await send_material_file(context.bot, user_id, file_data)
            else:
                await update.message.reply_text("❌ File nahi mili ya delete ho gayi hai.")
        except Exception:
            await update.message.reply_text("❌ Invalid File Code.")
        return

    results = material_col.find({"file_name": {"$regex": search_query, "$options": "i"}})
    count = material_col.count_documents({"file_name": {"$regex": search_query, "$options": "i"}})

    if count == 0:
        await update.message.reply_text(f"🔍 '{search_query}' ke liye koi material nahi mila. Kripya sahi spelling type karein.")
    else:
        text = f"🔍 *Search Results ({count}):*\n\n📥 File download karne ke liye niche code par click karein:\n\n"
        for mat in results:
            text += f"🔹 /file_{mat['_id']} - {mat['file_name']}\n"
        await update.message.reply_text(text, parse_mode="Markdown")

# ==========================================================
# 🚀 MAIN APPLICATION START
# ==========================================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_click))
    
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, handle_admin_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_search))
    app.add_handler(CommandHandler("file", handle_user_search))

    app.run_polling()

if __name__ == '__main__':
    main()

