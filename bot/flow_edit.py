"""
FSM Video Editing Suite untuk STUDIO KHOIRUL v2.0
Enhanced UX dengan Unified Design System
Selaras dengan Dashboard & Production Flow
"""

import asyncio
from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

# Import dari ui_dashboard yang sudah improved
from bot.ui_dashboard import VIDEO_EDIT_TEXT, get_back_cancel_kb, safe_edit_message
from bot_helper.Process.Process_Status import ProcessStatus
from bot_helper.Process.Running_Tasks import add_task
from bot_helper.Others.Names import Names

# Router untuk editing flow
edit_router = Router(name="flow_edit")

# ==========================================
# 1. VISUAL CONSTANTS (Selaras dengan dashboard)
# ==========================================

BORDER_PRIMARY = "━━━━━━━━━━━━━━━━━━━"
BORDER_SUBTLE = "─────────────────────"
TOP_LEFT, TOP_RIGHT = "╭", "╮"
BOTTOM_LEFT, BOTTOM_RIGHT = "╰", "╯"

# Tool Categories
TOOL_CATEGORIES = {
    "compression": {
        "icon": "🗜️",
        "label": "Compression & Format",
        "tools": [
            ("🗜️ Compress", "tool_compress"),
            ("🔄 Convert", "tool_convert"),
            ("🔗 Merge", "tool_merge"),
        ]
    },
    "trimming": {
        "icon": "✂️",
        "label": "Trimming & Cutting",
        "tools": [
            ("🎞️ Trim", "tool_trim"),
            ("✂️ Split", "tool_split"),
            ("🔪 Cut", "tool_cut"),
        ]
    },
    "cropping": {
        "icon": "📐",
        "label": "Cropping & Rotation",
        "tools": [
            ("📐 Crop", "tool_crop"),
            ("🎬 Autocrop", "tool_autocrop"),
            ("🔃 Rotate", "tool_rotate"),
        ]
    },
    "muxing": {
        "icon": "📌",
        "label": "Muxing Options",
        "tools": [
            ("📌 Hardmux", "tool_hardmux"),
            ("📝 Softmux", "tool_softmux"),
            ("♻️ Remux", "tool_softremux"),
        ]
    },
    "audio": {
        "icon": "🎵",
        "label": "Audio & Metadata",
        "tools": [
            ("🎵 Extract Audio", "tool_extract"),
            ("🏷️ Metadata", "tool_changemetadata"),
            ("ℹ️ MediaInfo", "tool_mediainfo"),
        ]
    },
    "advanced": {
        "icon": "⚙️",
        "label": "Advanced Tools",
        "tools": [
            ("©️ Watermark", "tool_watermark"),
            ("📸 Screenshot", "tool_genss"),
            ("🎞️ Sample", "tool_gensample"),
        ]
    }
}

# ==========================================
# 2. STATE DEFINITIONS (FSM)
# ==========================================

class VideoEditState(StatesGroup):
    waiting_for_video = State()
    browsing_categories = State()
    choosing_tool = State()
    waiting_for_param = State()

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================

def get_progress_bar(percentage: int, width: int = 12) -> str:
    """Generate progress bar"""
    filled = int((percentage / 100) * width)
    empty = width - filled
    return f"[{'▓' * filled}{'░' * empty}]"

def get_category_tools_kb(category_key: str) -> InlineKeyboardMarkup:
    """Get keyboard for specific tool category"""
    category = TOOL_CATEGORIES.get(category_key, {})
    tools = category.get("tools", [])
    
    kb = []
    for label, callback in tools:
        kb.append([InlineKeyboardButton(text=label, callback_data=callback)])
    
    kb.append([InlineKeyboardButton(text="↩️ Back to Categories", callback_data="edit_categories")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_all_tools_kb() -> InlineKeyboardMarkup:
    """Get keyboard with all tool categories"""
    kb = []
    for category_key, category_info in TOOL_CATEGORIES.items():
        icon = category_info.get("icon")
        label = category_info.get("label")
        kb.append([InlineKeyboardButton(
            text=f"{icon} {label}",
            callback_data=f"edit_category_{category_key}"
        )])
    
    kb.append([InlineKeyboardButton(text="❌ Cancel", callback_data="action_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_cancel_only_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Back", callback_data="edit_categories"),
         InlineKeyboardButton(text="❌ Cancel", callback_data="action_cancel")]
    ])

# ==========================================
# 4. ACTIVATE EDIT MODE
# ==========================================

@edit_router.callback_query(F.data == "menu_vid_edit")
async def trigger_edit_mode(callback: CallbackQuery, state: FSMContext):
    """Start video editing mode"""
    await state.set_state(VideoEditState.waiting_for_video)
    
    text = f"""
<b>{TOP_LEFT}─ VIDEO EDITING SUITE ─{TOP_RIGHT}</b>

📎 Kirimkan atau teruskan video yang ingin Anda edit
   Sistem akan mendeteksi file secara otomatis

<code>✓ Support: MP4, MKV, AVI, MOV, WebM</code>
<code>✓ Size: hingga 2GB per file</code>

{BORDER_PRIMARY}
<i>Tunggu panel alat muncul setelah upload video 👇</i>

<b>{BOTTOM_LEFT}─────────────────────{BOTTOM_RIGHT}</b>
"""
    
    await safe_edit_message(callback.message, text, get_back_cancel_kb())
    await callback.answer("📹 Mode editor aktif!", show_alert=False)

# ==========================================
# 5. CATCH VIDEO FILE
# ==========================================

@edit_router.message(VideoEditState.waiting_for_video, F.video | F.document)
async def catch_video_for_edit(message: Message, state: FSMContext):
    """Capture video and show category menu"""
    
    garbage = [message.message_id]
    
    # Get file info
    if message.video:
        file_name = message.video.file_name or "video.mp4"
        file_size = message.video.file_size
    elif message.document:
        file_name = message.document.file_name or "file"
        file_size = message.document.file_size
    else:
        file_name = "Unknown"
        file_size = 0
    
    size_mb = round(file_size / (1024 * 1024), 2)
    
    # Store original message
    await state.update_data(original_message=message, garbage=garbage)
    
    # Show file info & category selection
    text = f"""
<b>{TOP_LEFT}─ FILE RECEIVED ─{TOP_RIGHT}</b>

📹 <b>Video Information:</b>
  📄 Name: <code>{file_name[:40]}</code>
  💾 Size: <code>{size_mb} MB</code>

{BORDER_SUBTLE}

<b>🎛 Select Tool Category:</b>

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
    
    sent_msg = await message.reply(text, reply_markup=get_all_tools_kb(), parse_mode="HTML")
    garbage.append(sent_msg.message_id)
    
    await state.update_data(garbage=garbage)
    await state.set_state(VideoEditState.browsing_categories)

# ==========================================
# 6. BROWSE TOOL CATEGORIES
# ==========================================

@edit_router.callback_query(VideoEditState.browsing_categories, F.data.startswith("edit_category_"))
async def show_category_tools(callback: CallbackQuery, state: FSMContext):
    """Show tools in selected category"""
    
    category_key = callback.data.replace("edit_category_", "")
    category = TOOL_CATEGORIES.get(category_key)
    
    if not category:
        await callback.answer("❌ Category not found", show_alert=True)
        return
    
    icon = category.get("icon")
    label = category.get("label")
    
    text = f"""
<b>{TOP_LEFT}─ {icon} {label.upper()} ─{TOP_RIGHT}</b>

{BORDER_SUBTLE}

<i>Select the tool you want to use:</i>

<b>{BOTTOM_LEFT}────────────────────{BOTTOM_RIGHT}</b>
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_category_tools_kb(category_key),
        parse_mode="HTML"
    )
    await state.set_state(VideoEditState.choosing_tool)
    await callback.answer()

@edit_router.callback_query(F.data == "edit_categories")
async def back_to_categories(callback: CallbackQuery, state: FSMContext):
    """Go back to category selection"""
    
    data = await state.get_data()
    file_name = "Unknown"
    size_mb = 0
    
    if data.get("original_message"):
        msg = data.get("original_message")
        if msg.video:
            file_name = msg.video.file_name or "video.mp4"
            size_mb = round(msg.video.file_size / (1024 * 1024), 2)
        elif msg.document:
            file_name = msg.document.file_name or "file"
            size_mb = round(msg.document.file_size / (1024 * 1024), 2)
    
    text = f"""
<b>{TOP_LEFT}─ FILE RECEIVED ─{TOP_RIGHT}</b>

📹 <b>Video Information:</b>
  📄 Name: <code>{file_name[:40]}</code>
  💾 Size: <code>{size_mb} MB</code>

{BORDER_SUBTLE}

<b>🎛 Select Tool Category:</b>

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_all_tools_kb(),
        parse_mode="HTML"
    )
    await state.set_state(VideoEditState.browsing_categories)
    await callback.answer()

# ==========================================
# 7. PROCESS SELECTED TOOL
# ==========================================

@edit_router.callback_query(VideoEditState.choosing_tool, F.data.startswith("tool_"))
async def process_selected_tool(callback: CallbackQuery, state: FSMContext):
    """Handle tool selection and parameter input"""
    
    tool_selected = callback.data.replace("tool_", "")
    data = await state.get_data()
    
    # Tools requiring additional parameters
    tools_with_params = {
        "trim": {
            "prompt": "⏱️ Enter trim parameters (Format: <code>HH:MM:SS HH:MM:SS</code>)",
            "help": "Start time and duration\n<i>Example: 00:01:00 00:00:30</i>"
        },
        "split": {
            "prompt": "⏰ Split duration (Format: <code>HH:MM:SS</code>)",
            "help": "Duration of each segment\n<i>Example: 00:05:00</i>"
        },
        "crop": {
            "prompt": "📐 Crop dimensions (Format: <code>Width:Height</code>)",
            "help": "Output resolution\n<i>Example: 1080:1920</i>"
        },
        "rotate": {
            "prompt": "🔄 Rotation angle (Format: <code>0|90|180|270</code>)",
            "help": "Rotate video\n<i>Example: 90</i>"
        },
        "watermark": {
            "prompt": "📸 Send watermark image",
            "help": "Upload image file or photo\n<i>Supported: PNG, JPG</i>"
        }
    }
    
    if tool_selected in tools_with_params:
        # Show parameter input interface
        param_info = tools_with_params[tool_selected]
        
        text = f"""
<b>{TOP_LEFT}─ PARAMETER INPUT ─{TOP_RIGHT}</b>

<b>🔧 Tool:</b> <code>{tool_selected.upper()}</code>

{param_info["prompt"]}

{BORDER_SUBTLE}

{param_info["help"]}

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
        
        await state.update_data(selected_tool=tool_selected)
        await state.set_state(VideoEditState.waiting_for_param)
        await callback.message.edit_text(text, reply_markup=get_cancel_only_kb(), parse_mode="HTML")
    else:
        # No params needed - execute directly
        original_message = data.get("original_message")
        garbage = data.get("garbage", [])
        
        await state.clear()
        await run_ffmpeg_engine(callback.message, original_message, tool_selected, garbage, param=None)
    
    await callback.answer()

# ==========================================
# 8. CAPTURE PARAMETERS
# ==========================================

@edit_router.message(VideoEditState.waiting_for_param)
async def catch_parameter_and_execute(message: Message, state: FSMContext):
    """Capture parameter input and start processing"""
    
    data = await state.get_data()
    original_message = data.get("original_message")
    tool_selected = data.get("selected_tool")
    garbage = data.get("garbage", [])
    
    # Add user's parameter message to garbage
    garbage.append(message.message_id)
    
    # Extract parameter (text or file)
    param_value = message.text or getattr(message.document, "file_id", "Unknown")
    
    # Show processing status
    process_text = f"""
<b>{TOP_LEFT}─ PROCESSING ─{TOP_RIGHT}</b>

⏳ <b>Initializing {tool_selected.upper()}</b>

{get_progress_bar(20, 12)} 20%
<i>Validating parameters...</i>

{BORDER_SUBTLE}
"""
    
    msg = await message.reply(process_text, parse_mode="HTML")
    garbage.append(msg.message_id)
    
    await state.clear()
    await run_ffmpeg_engine(msg, original_message, tool_selected, garbage, param=param_value)

# ==========================================
# 9. FFMPEG EXECUTION ENGINE
# ==========================================

async def run_ffmpeg_engine(
    bot_message: Message,
    original_message: Message,
    tool_selected: str,
    garbage: list,
    param: str = None
):
    """Execute video processing task with progress feedback"""
    
    try:
        user_id = original_message.from_user.id
        chat_id = original_message.chat.id
        username = original_message.from_user.username or ""
        first_name = original_message.from_user.first_name or str(user_id)
        
        # Inject parameter into message if provided
        if param:
            fake_command = f"/{tool_selected} {param}"
            original_message = original_message.model_copy(
                update={"text": fake_command, "caption": fake_command}
            )
        
        # Show initialization status
        init_text = f"""
<b>{TOP_LEFT}─ INITIALIZING ─{TOP_RIGHT}</b>

🔧 <b>Tool:</b> <code>{tool_selected.upper()}</code>
👤 <b>User:</b> <code>{first_name}</code>

{get_progress_bar(35, 12)} 35%
<i>Setting up processing engine...</i>

{BORDER_SUBTLE}
<i>Task added to queue. Processing will begin shortly...</i>

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
        
        await safe_edit_message(bot_message, init_text)
        
        # Create ProcessStatus object
        process_name = getattr(Names, tool_selected, tool_selected)
        
        ps = ProcessStatus(
            user_id=user_id,
            chat_id=chat_id,
            username=username,
            first_name=first_name,
            message=original_message,
            process_name=process_name,
            source_type="Telegram"
        )
        
        # Attach garbage messages for cleanup
        ps.garbage_messages = garbage
        
        # Create and add task
        task = {"process_status": ps, "functions": [("telegram", original_message)]}
        await add_task(task)
        
        # Show queued status
        queue_text = f"""
<b>{TOP_LEFT}─ TASK QUEUED ─{TOP_RIGHT}</b>

✅ <b>Operation:</b> <code>{tool_selected.upper()}</code>
⏳ <b>Status:</b> <code>Queued</code>

{get_progress_bar(100, 12)} 100%
<i>Waiting in processing queue...</i>

{BORDER_SUBTLE}

You'll receive a notification when:
  📊 Processing starts
  ⚙️ Processing completes
  ✅ File is ready for download

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
        
        # Wait a moment before showing final status
        await asyncio.sleep(1)
        await safe_edit_message(bot_message, queue_text)
        
        # Delete loading message after showing queue status
        try:
            await asyncio.sleep(3)
            await bot_message.delete()
        except:
            pass
        
    except Exception as e:
        error_text = f"""
<b>{TOP_LEFT}─ ERROR ─{TOP_RIGHT}</b>

❌ <b>Failed to create task</b>

<code>{str(e)[:200]}</code>

{BORDER_SUBTLE}
<i>Please try again or contact support.</i>

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
        
        try:
            await safe_edit_message(bot_message, error_text)
        except:
            await bot_message.reply(error_text, parse_mode="HTML")

# ==========================================
# 10. GLOBAL CANCEL
# ==========================================

@edit_router.callback_query(F.data == "action_cancel")
async def global_cancel(callback: CallbackQuery, state: FSMContext):
    """Cancel editing operation"""
    
    current_state = await state.get_state()
    
    if current_state is not None:
        await state.clear()
        cancel_msg = "❌ Operation cancelled. Returning to dashboard..."
    else:
        cancel_msg = "✕ Closed."
    
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    
    await callback.answer(cancel_msg, show_alert=False)

# ==========================================
# 11. EXPORT
# ==========================================

__all__ = ["edit_router"]
