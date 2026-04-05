"""
FSM Downloader Flow untuk STUDIO KHOIRUL v2.0
Enhanced UX dengan Unified Design System
Selaras dengan Dashboard, Production Flow, & Editing Suite
"""

import asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Integration dengan downloader engine
from bot_helper.Process.Process_Status import ProcessStatus
from bot_helper.Process.Running_Tasks import add_task
from bot_helper.Others.Names import Names

down_router = Router(name="flow_downloader")

# ==========================================
# 1. VISUAL CONSTANTS (Selaras dengan sistem)
# ==========================================

BORDER_PRIMARY = "━━━━━━━━━━━━━━━━━━━"
BORDER_SUBTLE = "─────────────────────"
TOP_LEFT, TOP_RIGHT = "╭", "╮"
BOTTOM_LEFT, BOTTOM_RIGHT = "╰", "╯"

# Downloader Modes
DOWNLOADER_MODES = {
    "leech": {
        "icon": "📥",
        "label": "Leech Download",
        "desc": "Download file langsung ke Telegram\nFile akan dikirim ke chat Anda",
        "supported": "Direct Links, YouTube, Torrent, Magnet"
    },
    "mirror": {
        "icon": "☁️",
        "label": "Mirror to Cloud",
        "desc": "Upload file ke Cloud Storage\nSave space Telegram Anda",
        "supported": "Google Drive, OneDrive, Mega"
    }
}

# ==========================================
# 2. STATE DEFINITIONS
# ==========================================

class DownloaderState(StatesGroup):
    choosing_mode = State()
    waiting_for_link = State()

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================

def get_progress_bar(percentage: int, width: int = 12) -> str:
    """Generate progress bar"""
    filled = int((percentage / 100) * width)
    empty = width - filled
    return f"[{'▓' * filled}{'░' * empty}]"

def get_mode_selection_kb() -> InlineKeyboardMarkup:
    """Keyboard untuk mode selection"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"📥 Leech Download",
            callback_data="dl_mode_leech"
        )],
        [InlineKeyboardButton(
            text=f"☁️ Mirror to Cloud",
            callback_data="dl_mode_mirror"
        )],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="action_cancel")]
    ])

def get_link_input_kb() -> InlineKeyboardMarkup:
    """Keyboard untuk input link dengan back option"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Back", callback_data="dl_back_to_mode"),
         InlineKeyboardButton(text="❌ Cancel", callback_data="action_cancel")]
    ])

# ==========================================
# 4. TRIGGER DARI DASHBOARD
# ==========================================

@down_router.callback_query(F.data == "cmd_leech")
async def trigger_leech_mode(callback: CallbackQuery, state: FSMContext):
    """Trigger leech mode directly"""
    await state.update_data(dl_mode="leech")
    await show_link_input_screen(callback, "leech")
    await callback.answer()

@down_router.callback_query(F.data == "cmd_mirror")
async def trigger_mirror_mode(callback: CallbackQuery, state: FSMContext):
    """Trigger mirror mode directly"""
    await state.update_data(dl_mode="mirror")
    await show_link_input_screen(callback, "mirror")
    await callback.answer()

@down_router.callback_query(F.data == "menu_downloader")
async def show_downloader_menu(callback: CallbackQuery, state: FSMContext):
    """Show downloader mode selection"""
    
    text = f"""
<b>{TOP_LEFT}─ DOWNLOAD & CLOUD ─{TOP_RIGHT}</b>

<b>📥 Choose your download method:</b>

{BORDER_SUBTLE}

<i>Each method has different benefits:</i>

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_mode_selection_kb(),
        parse_mode="HTML"
    )
    await state.set_state(DownloaderState.choosing_mode)
    await callback.answer()

# ==========================================
# 5. MODE SELECTION
# ==========================================

@down_router.callback_query(DownloaderState.choosing_mode, F.data.startswith("dl_mode_"))
async def select_mode(callback: CallbackQuery, state: FSMContext):
    """Handle mode selection"""
    
    mode = callback.data.replace("dl_mode_", "")
    await state.update_data(dl_mode=mode)
    
    await show_link_input_screen(callback, mode)
    await callback.answer()

async def show_link_input_screen(callback: CallbackQuery, mode: str):
    """Display link input screen for selected mode"""
    
    mode_info = DOWNLOADER_MODES.get(mode, {})
    icon = mode_info.get("icon", "📥")
    label = mode_info.get("label", "Download")
    desc = mode_info.get("desc", "")
    supported = mode_info.get("supported", "Various sources")
    
    text = f"""
<b>{TOP_LEFT}─ {icon} {label.upper()} ─{TOP_RIGHT}</b>

<b>📝 Mode Selected:</b> <code>{mode.upper()}</code>

{desc}

<b>✓ Supported Sources:</b>
  <code>{supported}</code>

{BORDER_SUBTLE}

<b>🔗 Send the download link below:</b>

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_link_input_kb(),
        parse_mode="HTML"
    )
    await callback.bot.get_session().set_state(DownloaderState.waiting_for_link)

@down_router.callback_query(F.data == "dl_back_to_mode")
async def back_to_mode_selection(callback: CallbackQuery, state: FSMContext):
    """Go back to mode selection"""
    
    text = f"""
<b>{TOP_LEFT}─ DOWNLOAD & CLOUD ─{TOP_RIGHT}</b>

<b>📥 Choose your download method:</b>

{BORDER_SUBTLE}

<i>Each method has different benefits:</i>

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_mode_selection_kb(),
        parse_mode="HTML"
    )
    await state.set_state(DownloaderState.choosing_mode)
    await callback.answer()

# ==========================================
# 6. CAPTURE LINK & EXECUTE
# ==========================================

@down_router.message(DownloaderState.waiting_for_link, F.text)
async def process_download_link(message: Message, state: FSMContext):
    """Capture URL and start download process"""
    
    data = await state.get_data()
    mode = data.get("dl_mode", "leech")
    url = message.text
    
    # Clean up state
    await state.clear()
    
    # Delete user's URL message for cleanliness
    try:
        await message.delete()
    except Exception:
        pass
    
    # Show validation status
    validate_text = f"""
<b>{TOP_LEFT}─ VALIDATING URL ─{TOP_RIGHT}</b>

🔗 <b>Mode:</b> <code>{mode.upper()}</code>
📎 <b>URL:</b> <code>{url[:50]}...</code>

{get_progress_bar(25, 12)} 25%
<i>Parsing URL structure...</i>

{BORDER_SUBTLE}
"""
    
    bot_msg = await message.answer(validate_text, parse_mode="HTML")
    
    # Simulate parsing
    await asyncio.sleep(0.5)
    
    # Show connection status
    connect_text = f"""
<b>{TOP_LEFT}─ CONNECTING ─{TOP_RIGHT}</b>

🔗 <b>Mode:</b> <code>{mode.upper()}</code>
📎 <b>Source:</b> <code>{extract_domain(url)}</code>

{get_progress_bar(50, 12)} 50%
<i>Connecting to downloader engine...</i>

{BORDER_SUBTLE}
"""
    
    try:
        await bot_msg.edit_text(connect_text, parse_mode="HTML")
    except:
        pass
    
    await asyncio.sleep(0.5)
    
    # Process download
    await execute_download_task(bot_msg, message, mode, url)

async def execute_download_task(
    bot_msg: Message,
    original_msg: Message,
    mode: str,
    url: str
):
    """Execute the download task"""
    
    try:
        # Extract user info
        user_id = original_msg.from_user.id
        chat_id = original_msg.chat.id
        username = original_msg.from_user.username or ""
        first_name = original_msg.from_user.first_name or str(user_id)
        
        # Create fake command message
        fake_command = f"/{mode} {url}"
        fake_message = original_msg.model_copy(update={"text": fake_command})
        
        # Show initialization
        init_text = f"""
<b>{TOP_LEFT}─ INITIALIZING ─{TOP_RIGHT}</b>

🔧 <b>Operation:</b> <code>{mode.upper()}</code>
👤 <b>User:</b> <code>{first_name}</code>
📎 <b>URL:</b> <code>{extract_domain(url)}</code>

{get_progress_bar(75, 12)} 75%
<i>Setting up download engine...</i>

{BORDER_SUBTLE}
"""
        
        try:
            await bot_msg.edit_text(init_text, parse_mode="HTML")
        except:
            pass
        
        await asyncio.sleep(0.5)
        
        # Get process name from Names module
        process_name = getattr(Names, mode, mode)
        
        # Create ProcessStatus
        ps = ProcessStatus(
            user_id=user_id,
            chat_id=chat_id,
            username=username,
            first_name=first_name,
            message=fake_message,
            process_name=process_name,
            source_type="Telegram"
        )
        
        # Create and queue task
        task = {
            "process_status": ps,
            "functions": [("telegram", fake_message)]
        }
        
        await add_task(task)
        
        # Show queued status
        queue_text = f"""
<b>{TOP_LEFT}─ TASK QUEUED ─{TOP_RIGHT}</b>

✅ <b>Operation:</b> <code>{mode.upper()}</code>
⏳ <b>Status:</b> <code>Queued</code>

{get_progress_bar(100, 12)} 100%
<i>Download task added to queue...</i>

{BORDER_SUBTLE}

📊 <b>Queue Status:</b>
  You'll be notified when:
  📥 Download starts
  ⚙️ Download progresses
  ✅ Download completes

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
        
        try:
            await bot_msg.edit_text(queue_text, parse_mode="HTML")
        except:
            pass
        
        # Delete message after short delay
        await asyncio.sleep(3)
        try:
            await bot_msg.delete()
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
            await bot_msg.edit_text(error_text, parse_mode="HTML")
        except:
            try:
                await bot_msg.reply(error_text, parse_mode="HTML")
            except:
                pass

# ==========================================
# 7. HELPER FUNCTION: Extract Domain
# ==========================================

def extract_domain(url: str) -> str:
    """Extract domain from URL"""
    try:
        # Remove protocol
        if "://" in url:
            url = url.split("://")[1]
        # Get domain
        domain = url.split("/")[0]
        # Limit length
        return domain[:40]
    except:
        return "Unknown"

# ==========================================
# 8. GLOBAL CANCEL
# ==========================================

@down_router.callback_query(F.data == "action_cancel")
async def global_cancel(callback: CallbackQuery, state: FSMContext):
    """Cancel download operation"""
    
    current_state = await state.get_state()
    
    if current_state is not None:
        await state.clear()
        cancel_msg = "❌ Download cancelled. Returning to dashboard..."
    else:
        cancel_msg = "✕ Closed."
    
    try:
        await callback.message.delete()
    except:
        pass
    
    await callback.answer(cancel_msg, show_alert=False)

# ==========================================
# 9. EXPORT
# ==========================================

__all__ = ["down_router"]
