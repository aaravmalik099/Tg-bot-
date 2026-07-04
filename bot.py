# ==========================================
# SECTION 1: IMPORTS & MODULES
# ==========================================
import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommandScopeChat
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from pymongo import MongoClient
from bson.objectid import ObjectId

# ==========================================
# SECTION 2: LOGGING CONFIGURATION
# ==========================================
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# SECTION 3: ENVIRONMENT VARIABLES
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# ==========================================
# SECTION 4: DATABASE INITIALIZATION
# ==========================================
client = MongoClient(MONGO_URL)
db = client['tg_material_bot']
users_col = db['users']
material_col = db['materials']
co_admins_col = db['co_admins']  # New collection to persist multi-user upload permissions

# State Memory for Actions & Conversations
admin_states = {}
user_states = {}  # Tracks conversational flow like waiting for material request name

# ==========================================
# SECTION 5: HELPER FUNCTIONS & MIDDLEWARES
# ==========================================
async def is_subscribed(bot, user_id):
    """Checks if the user is a member of the mandatory update channel."""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        return False

def is_admin_or_co_admin(user_id):
    """Checks if the user is either the main owner or an approved contributor."""
    if user_id == ADMIN_ID:
        return True
    return co_admins_col.find_one({"user_id": user_id}) is not None

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
            ("start", "🚀 Start Bot / Dashboard"),
            ("categories", "🗂️ View Categories"),
            ("home", "🏠 Main Menu"),
            ("request", "📥 Request Extra Material")
        ]
        await bot.set_my_commands(user_commands)
        
        if ADMIN_ID != 0:
            admin_commands = [
                ("start", "🚀 Start Bot"),
                ("categories", "🗂️ View Categories"),
                ("home", "🏠 Main Dashboard"),
                ("request", "📥 Request Material"),
                ("admin", "👑 Admin Panel"),
                ("broadcast", "📢 Broadcast Message"),
                ("addcoadmin", "➕ Add Co-Admin"),
                ("removecoadmin", "➖ Remove Co-Admin"),
                ("coadmins", "👥 List Co-Admins")
            ]
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
        logger.info("Bot commands menu registered successfully.")
    except Exception as e:
        logger.error(f"Error setting menus: {e}")

# ==========================================
# SECTION 6: USER CORE COMMAND HANDLERS
# ==========================================
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
    """Renders the top level highly polished dashboard."""
    keyboard = [
        [InlineKeyboardButton("🗂️ View Categories", callback_data="view_cats")],
        [InlineKeyboardButton("👤 My Profile", callback_data="my_profile"), InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")],
        [InlineKeyboardButton("📢 More Channels", callback_data="more_channels"), InlineKeyboardButton("🤖 More Bots", callback_data="more_bots")]
    ]
    
    text = (
        f"📚 **Welcome {name} to the Ultimate Study Dashboard!** ✨\n\n"
        f"Yahan aapko aapki padhai ke liye sabhi important **PDFs, Hand-written Notes, Question Banks aur Videos** bilkul free milenge! 🚀\n\n"
        f"💡 **Kaise search karein?**\n"
        f"• Aap seedhe chat me kisi bhi subject ya chapter ka naam (e.g., *Physics Notes*) likh kar bhej sakte hain, bot use automatically dhoodh lega!\n"
        f"• Ya fir niche diye gaye **View Categories** option ka use karke systematic tariqe se padh sakte hain.\n\n"
        f"📥 **Kuch alag se chahiye?**\n"
        f"Agar koi material na mile, toh chat me `/request` likh kar direct humse maang sakte hain!\n\n"
        f"🎯 *Padhte rahiye, badhte rahiye!*"
    )
    
    if is_edit:
        await message_obj.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await message_obj.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_subscribed(context.bot, update.effective_user.id): return
    await show_categories_menu(update.message, is_edit=False)

async def show_categories_menu(message_obj, is_edit=True):
    """Renders all categories dynamically."""
    categories = material_col.distinct("category", {"status": "live"})
    if not categories:
        keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")]]
        msg = "🗂️ Abhi tak koi category nahi banayi gayi hai."
        if is_edit: await message_obj.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else: await message_obj.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    keyboard = [[InlineKeyboardButton(f"📂 {cat}", callback_data=f"vcat_{cat}")] for cat in categories]
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="go_home")])
    if is_edit: await message_obj.edit_text("📂 Niche di gayi categories me se chunein:", reply_markup=InlineKeyboardMarkup(keyboard))
    else: await message_obj.reply_text("📂 Niche di gayi categories me se chunein:", reply_markup=InlineKeyboardMarkup(keyboard))

# ==========================================
# SECTION 7: USER CONVERSATIONAL REQUEST SYSTEM
# ==========================================
async def request_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiates conversation flow or handles direct arguments for admin forwarding."""
    user_id = update.effective_user.id
    if not await is_subscribed(context.bot, user_id): return

    if len(context.args) < 1:
        # User only typed /request, switch them to listening mode
        user_states[user_id] = "waiting_for_request"
        await update.message.reply_text(
            "📝 **Aapko kaunse extra notes ya study material chahiye?**\n\n"
            "Kripya us book, subject ya notes ka naam niche type karke send karein. Aapki request seedhe Admin panel tak pahunchayi jayegi!",
            parse_mode='Markdown'
        )
        return
    
    # User directly typed the material alongside command, process immediately
    file_request_name = " ".join(context.args)
    await process_and_send_request(update, context, user_id, file_request_name)

async def process_and_send_request(update, context, user_id, file_request_name):
    """Core request processing and dispatching engine to primary admin."""
    user = update.effective_user
    user_info = f"{user.first_name} (ID: `{user_id}` | Username: @{user.username or 'None'})"
    
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🔔 **[NEW REQUEST RECEIVED]**\n\n👤 **From User:** {user_info}\n📂 **Requested Material:** {file_request_name}\n\n"
                 f"ℹ️ *Aap unhe directly provide kar sakte hain ya database me upload kar sakte hain.*",
            parse_mode='Markdown'
        )
        await update.message.reply_text(
            "✅ **Aapki request safaltapoorvak Admin tak pahunch gayi hai!**\n\n"
            "Jaise hi yeh material humare paas available hoga, ise upload kar diya jayega. Tab tak aap baaki dashboard materials se padhai jari rakh sakte hain! 👍",
            parse_mode='Markdown'
        )
        # Clear request conversation state safely
        user_states.pop(user_id, None)
    except Exception as e:
        logger.error(f"Error in dispatching request to admin: {e}")
        await update.message.reply_text("❌ Upsee! Request bhejte samay kuch dikkat aayi. Kripya baad me try karein.")

# ==========================================
# SECTION 8: ADMINISTRATIVE MANAGEMENT (MULTI-USER SUPPORT)
# ==========================================
async def add_co_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enables primary admin to authorize multiple contributors."""
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("❌ Please provide a Telegram User ID.\nExample: `/addcoadmin 123456789`", parse_mode="Markdown")
        return
    try:
        co_id = int(context.args[0])
        if co_admins_col.find_one({"user_id": co_id}):
            await update.message.reply_text("⚠️ Yeh user pehle se hi Co-Admin list me shamil hai.")
            return
        co_admins_col.insert_one({"user_id": co_id})
        await update.message.reply_text(f"✅ User ID `{co_id}` ko safely **Co-Admin** bana diya gaya hai! Ab yeh bhi files upload kar sakte hain.", parse_mode="Markdown")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID. Kripya sirf digits ka istemal karein.")

async def remove_co_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enables primary admin to revoke contributor access instantly."""
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("❌ Please provide a Telegram User ID.\nExample: `/removecoadmin 123456789`", parse_mode="Markdown")
        return
    try:
        co_id = int(context.args[0])
        res = co_admins_col.delete_one({"user_id": co_id})
        if res.deleted_count > 0:
            await update.message.reply_text(f"✅ User ID `{co_id}` se Co-Admin permissions wapas le li gayi hain.")
        else:
            await update.message.reply_text("❌ Yeh User ID Co-Admin list me nahi mili.")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID format.")

async def list_co_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists all active authorized co-admins/contributors."""
    if update.effective_user.id != ADMIN_ID: return
    co_list = list(co_admins_col.find({}))
    if not co_list:
        await update.message.reply_text("👥 Abhi tak koi extra Co-Admin nahi banaya gaya hai.")
        return
    msg = "👑 **Current Authorized Co-Admins:**\n\n"
    for idx, co in enumerate(co_list, 1):
        msg += f"{idx}. ID: `{co['user_id']}`\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Renders administrative operations dashboard for primary & co-admins."""
    if not is_admin_or_co_admin(update.effective_user.id): return
    keyboard = [
        [InlineKeyboardButton("📂 Manage All Content", callback_data="manage_files")],
        [InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")]
    ]
    await update.message.reply_text("👑 *Admin & Contributor Control Panel:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

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

# ==========================================
# SECTION 9: INLINE CALLBACK ENGINE
# ==========================================
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

        elif query.data == "more_channels":
            keyboard = [
                [InlineKeyboardButton("📢 Join Update Channel", url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="go_home")]
            ]
            await query.edit_message_text(
                "📢 **Hamare Dusre Channels & Groups:**\n\n"
                "Niche diye gaye links ko join karke aap daily quizzes, important announcements aur direct discussion group se jud sakte hain. Check out now! 👇",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

        elif query.data == "more_bots":
            keyboard = [
                [InlineKeyboardButton("🤖 Main Study Bot", url=f"https://t.me/{context.bot.username}")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="go_home")]
            ]
            await query.edit_message_text(
                "🤖 **Hamare Future AI & Automation Bots:**\n\n"
                "Aane wale samay me hum aur bhi behtareen tools (Jaise Quiz Bots, Automated Doubt Solvers, aur Custom AI Assistants) launch karne wale hain. Un sabki direct list aapko yahan dekhne ko milegi! Stay tuned! 🔥",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )

        elif query.data == "admin_home" and is_admin_or_co_admin(user_id):
            keyboard = [[InlineKeyboardButton("📂 Manage All Content", callback_data="manage_files")], [InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")]]
            await query.edit_message_text("👑 *Admin Control Panel:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data == "manage_files" and is_admin_or_co_admin(user_id):
            await manage_files_list(query)

        elif query.data.startswith("editfile_") and is_admin_or_co_admin(user_id):
            fid = query.data.replace("editfile_", "")
            await edit_file_options(query, fid)

        elif query.data.startswith("toggle_") and is_admin_or_co_admin(user_id):
            fid = query.data.replace("toggle_", "")
            f = material_col.find_one({"_id": ObjectId(fid)})
            if f:
                nst = "hidden" if f.get("status", "live") == "live" else "live"
                material_col.update_one({"_id": ObjectId(fid)}, {"$set": {"status": nst}})
                await edit_file_options(query, fid)

        elif query.data.startswith("del_") and is_admin_or_co_admin(user_id):
            fid = query.data.replace("del_", "")
            material_col.delete_one({"_id": ObjectId(fid)})
            await manage_files_list(query)

        elif (query.data.startswith("move_") or query.data.startswith("copy_")) and is_admin_or_co_admin(user_id):
            mode, fid = query.data.split("_", 1)
            admin_states[user_id] = {"action": mode, "fid": fid}
            keyboard = [
                [InlineKeyboardButton("📚 SSC", callback_data="tcat_SSC"), InlineKeyboardButton("🏛️ UPSC", callback_data="tcat_UPSC")],
                [InlineKeyboardButton("💻 Banking", callback_data="tcat_Banking"), InlineKeyboardButton("🧪 NEET/JEE", callback_data="tcat_NEET_JEE")]
            ]
            await query.edit_message_text("🎯 Target **Main Category** select kijiye:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data.startswith("tcat_") and is_admin_or_co_admin(user_id):
            tcat = query.data.replace("tcat_", "")
            if user_id in admin_states:
                admin_states[user_id]["target_cat"] = tcat
                keyboard = [
                    [InlineKeyboardButton("📐 Maths", callback_data="tsub_Maths"), InlineKeyboardButton("🌍 GK/GS", callback_data="tsub_GK")],
                    [InlineKeyboardButton("🧠 Reasoning", callback_data="tsub_Reasoning"), InlineKeyboardButton("🔤 English", callback_data="tsub_English")]
                ]
                await query.edit_message_text(f"Category *{tcat}* done. Target **Subject** chunein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data.startswith("tsub_") and is_admin_or_co_admin(user_id):
            tsub = query.data.replace("tsub_", "")
            state = admin_states.get(user_id)
            if state:
                orig_file = material_col.find_one({"_id": ObjectId(state["fid"])})
                if orig_file:
                    if state["action"] == "move":
                        material_col.update_one({"_id": ObjectId(state["fid"])}, {"$set": {"category": state["target_cat"], "subject": tsub}})
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
            back = "admin_home" if is_admin_or_co_admin(user_id) else "go_home"
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

        elif query.data.startswith("acat_") and is_admin_or_co_admin(user_id):
            category = query.data.replace("acat_", "")
            if user_id in admin_states:
                admin_states[user_id]["category"] = category
                keyboard = [
                    [InlineKeyboardButton("📐 Maths", callback_data="asub_Maths"), InlineKeyboardButton("🌍 GK/GS", callback_data="asub_GK")],
                    [InlineKeyboardButton("🧠 Reasoning", callback_data="asub_Reasoning"), InlineKeyboardButton("🔤 English", callback_data="asub_English")]
                ]
                await query.edit_message_text(f"Category *{category}* done. Select **Subject**:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif query.data.startswith("asub_") and is_admin_or_co_admin(user_id):
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

# ==========================================
# SECTION 10: COMMUNICATIONS & SYSTEM LOGIC
# ==========================================
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a broadcast message to all users (Strictly Main Admin only)."""
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
    """Intercepts media documents specifically for authorized admin/co-admin upload streams."""
    user_id = update.effective_user.id
    if not is_admin_or_co_admin(user_id): return
    
    message = update.message
    file_id, file_name, file_type = None, "Unnamed", None
    if message.document: 
        file_id, file_name, file_type = message.document.file_id, message.document.file_name, "document"
    elif message.photo: 
        file_id, file_name, file_type = message.photo[-1].file_id, message.caption or "Photo Note", "photo"
    elif message.video: 
        file_id, file_name, file_type = message.video.file_id, message.video.file_name or message.caption or "Video Note", "video"

    if file_id:
        admin_states[user_id] = {"file_id": file_id, "file_name": file_name, "file_type": file_type}
        keyboard = [
            [InlineKeyboardButton("📚 SSC", callback_data="acat_SSC"), InlineKeyboardButton("🏛️ UPSC", callback_data="acat_UPSC")],
            [InlineKeyboardButton("💻 Banking", callback_data="acat_Banking"), InlineKeyboardButton("🧪 NEET/JEE", callback_data="acat_NEET_JEE")]
        ]
        await message.reply_text("📥 *Material mila!* Iski *Main Category* chunein:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_user_incoming_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming text queries; routes safely between material requests and standard lookups."""
    user_id = update.effective_user.id
    if not await is_subscribed(context.bot, user_id): return
    
    incoming_text = update.message.text
    if incoming_text.startswith("/"): return 

    # Route 1: If the user is currently in a conversation flow trying to type out a manual request
    if user_states.get(user_id) == "waiting_for_request":
        await process_and_send_request(update, context, user_id, incoming_text)
        return

    # Route 2: Standard Material Search Query Processing
    results = list(material_col.find({"file_name": {"$regex": incoming_text, "$options": "i"}, "status": "live"}))
    count = len(results)
    
    if count == 0:
        await update.message.reply_text(
            f"🔍 '{incoming_text}' ke liye abhi koi live material nahi mila.\n\n"
            f"💡 Agar aapko yeh material urgently chahiye, toh aap `/request {incoming_text}` likh kar direct humse maang sakte hain!"
        )
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

# ==========================================
# SECTION 11: MAIN APPLICATION INITIALIZER
# ==========================================
def main():
    """Starts the bot application and registers handlers safely."""
    app = Application.builder().token(BOT_TOKEN).post_init(setup_menus).build()

    # User & Core Control Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("home", start))
    app.add_handler(CommandHandler("categories", cmd_categories))
    app.add_handler(CommandHandler("request", request_file))
    
    # Primary Admin Exclusive Management Commands
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("addcoadmin", add_co_admin))
    app.add_handler(CommandHandler("removecoadmin", remove_co_admin))
    app.add_handler(CommandHandler("coadmins", list_co_admins))
    
    # Callback Query Handler
    app.add_handler(CallbackQueryHandler(button_click))
    
    # Message Handlers mapped accurately via Regex/Filters
    app.add_handler(MessageHandler(filters.Regex(r'^/file_[a-fA-F0-9]{24}$'), handle_file_link))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, handle_admin_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_incoming_messages))

    # Error Handler
    app.add_error_handler(error_handler)
    
    # Start Polling
    app.run_polling()

if __name__ == '__main__':
    main()
