# ==========================================================
# ⚙️ ADMIN PANEL & FILE MANAGEMENT SECTION (New!)
# ==========================================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    keyboard = [
        [InlineKeyboardButton("📂 Manage All Files", callback_data="manage_files")],
        [InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")]
    ]
    await update.message.reply_text("👑 *Admin Control Panel:*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def manage_files_list(query, page=0):
    files = list(material_col.find({}))
    if not files:
        await query.edit_message_text("🗂️ Database khali hai.")
        return

    keyboard = []
    for f in files:
        keyboard.append([InlineKeyboardButton(f"✏️ {f['file_name']}", callback_data=f"editfile_{f['_id']}")])
    
    keyboard.append([InlineKeyboardButton("🏠 Back to Admin", callback_data="admin_home")])
    await query.edit_message_text("📂 *Manage Files (Click to Edit/Delete):*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def edit_file_options(query, file_id):
    file = material_col.find_one({"_id": ObjectId(file_id)})
    if not file: return
    
    keyboard = [
        [InlineKeyboardButton("🗑️ Delete File", callback_data=f"del_{file_id}")],
        [InlineKeyboardButton("🔙 Back to List", callback_data="manage_files")]
    ]
    await query.edit_message_text(f"📝 *Editing:* {file['file_name']}\n\nKya karna chahte hain?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# [Update button_click function to include these cases]
# Add these lines inside your existing button_click function:
# -----------------------------------------------------------
# elif query.data == "admin_home":
#     await query.edit_message_text("👑 *Admin Control Panel:*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📂 Manage All Files", callback_data="manage_files")], [InlineKeyboardButton("📊 Bot Stats", callback_data="bot_stats")]]))
# elif query.data == "manage_files":
#     await manage_files_list(query)
# elif query.data.startswith("editfile_"):
#     await edit_file_options(query, query.data.split("_")[1])
# elif query.data.startswith("del_"):
#     material_col.delete_one({"_id": ObjectId(query.data.split("_")[1])})
#     await query.answer("✅ File Deleted!")
#     await manage_files_list(query)
