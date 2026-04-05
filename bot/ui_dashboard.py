"""
UI Dashboard Template for STUDIO KHOIRUL (Aiogram 3.x)
Fitur: Safe Edit, Grid Layout, Admin Checks, Navigation System
"""

import asyncio
from aiogram import Router, F, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest

# Inisialisasi Router untuk UI
ui_router = Router(name="ui_dashboard")

# ==========================================
# 1. CONSTANTS & TEXT TEMPLATES (HTML Mode)
# ==========================================

MAIN_DASHBOARD_TEXT = """
<blockquote>🎬 <b>𝐒 𝐓 𝐔 𝐃 𝐈 𝐎  𝐊 𝐇 𝐎 𝐈 𝐑 𝐔 𝐋</b>
━━━━━━━━━━━━━━━━━━━━━━
Welcome back, <b>{name}</b> 👑 <code>[ VIP PRO ]</code>

🟢 <b>Core System:</b> <code>Optimal</code>
⚡ <b>Active Queue:</b> <code>0 / 3 Tasks</code>
💾 <b>Cloud Vault:</b> <code>45% Used (4.5GB)</code>
━━━━━━━━━━━━━━━━━━━━━━
<i>Select a workspace module to begin:</i></blockquote>
"""

VIDEO_PROD_TEXT = """
<blockquote>🎬 <b>𝐕𝐈𝐃𝐄𝐎 𝐏𝐑𝐎𝐃𝐔𝐂𝐓𝐈𝐎𝐍</b>
━━━━━━━━━━━━━━━━━━━━━━
Create AI-generated content from scratch.

💡 <i>Smart Suggestion: Try the new Cinematic AI model for 4K rendering.</i>
━━━━━━━━━━━━━━━━━━━━━━
<i>Select an engine:</i></blockquote>
"""

ADMIN_TOOLS_TEXT = """
<blockquote>💻 <b>𝐒𝐘𝐒𝐓𝐄𝐌 𝐓𝐎𝐎𝐋𝐒 (Admin Only)</b>
━━━━━━━━━━━━━━━━━━━━━━
Akses kontrol penuh ke server dan pengguna.
━━━━━━━━━━━━━━━━━━━━━━</blockquote>
"""

# ==========================================
# 2. HELPER FUNCTIONS
# ==========================================

async def safe_edit_message(message: Message, text: str, reply_markup: InlineKeyboardMarkup = None) -> bool:
    """
    Fungsi aman untuk mengedit pesan.
    Menghindari crash jika teks dan markup sama persis ("message is not modified").
    """
    try:
        await message.edit_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
        return True
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            # Abaikan error jika pesan memang tidak berubah
            return False
        # Raise error lain yang tidak terduga
        raise e

def check_is_admin(user_id: int) -> bool:
    """Fungsi dummy untuk mengecek status admin (Ganti dengan logika DB kamu)"""
    admin_ids = [123456789] # Masukkan ID kamu di sini
    return user_id in admin_ids

# ==========================================
# 3. KEYBOARD BUILDERS
# ==========================================

def get_main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Membangun keyboard utama dengan layout grid 2 kolom"""
    kb = [
        [
            InlineKeyboardButton(text="🎬 Video Production", callback_data="menu_vid_prod"),
            InlineKeyboardButton(text="✂️ Video Editing", callback_data="menu_vid_edit")
        ],
        [
            InlineKeyboardButton(text="📥 Downloader", callback_data="menu_download"),
            InlineKeyboardButton(text="🎮 Asset Manager", callback_data="menu_assets")
        ],
        [
            InlineKeyboardButton(text="⚙️ Settings", callback_data="menu_settings"),
            InlineKeyboardButton(text="👑 VIP System", callback_data="menu_vip")
        ]
    ]
    
    # Render tombol khusus Admin
    if is_admin:
        kb.append([
            InlineKeyboardButton(text="💻 System Tools", callback_data="menu_admin"),
            InlineKeyboardButton(text="❓ Help", callback_data="menu_help")
        ])
    else:
        kb.append([
            InlineKeyboardButton(text="❓ Help", callback_data="menu_help")
        ])
        
    return InlineKeyboardMarkup(inline_keyboard=kb)


def get_video_prod_kb() -> InlineKeyboardMarkup:
    """Submenu untuk Video Production"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Text to Video", callback_data="prod_t2v"),
            InlineKeyboardButton(text="🖼️ Image to Video", callback_data="prod_i2v")
        ],
        [
            InlineKeyboardButton(text="🎙️ Audio Driven", callback_data="prod_audio"),
            InlineKeyboardButton(text="🎭 Clone / Deepfake", callback_data="prod_clone")
        ],
        [
            InlineKeyboardButton(text="⬅️ Back", callback_data="menu_main"),
            InlineKeyboardButton(text="🏠 Home", callback_data="menu_main"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="action_cancel")
        ]
    ])

def get_admin_tools_kb() -> InlineKeyboardMarkup:
    """Submenu untuk Admin"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Server Stats", callback_data="admin_stats")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="menu_main")]
    ])

# ==========================================
# 4. CALLBACK HANDLERS
# ==========================================

@ui_router.callback_query(F.data == "menu_main")
async def handler_menu_main(callback: CallbackQuery):
    """Menangani tombol Home / Back ke Main Menu"""
    is_admin = check_is_admin(callback.from_user.id)
    text = MAIN_DASHBOARD_TEXT.format(name=callback.from_user.first_name)
    markup = get_main_menu_kb(is_admin)
    
    await safe_edit_message(callback.message, text, markup)
    await callback.answer() # Hilangkan ikon loading di tombol


@ui_router.callback_query(F.data == "menu_vid_prod")
async def handler_video_prod(callback: CallbackQuery):
    """Menangani klik masuk ke Video Production"""
    markup = get_video_prod_kb()
    await safe_edit_message(callback.message, VIDEO_PROD_TEXT, markup)
    await callback.answer()


@ui_router.callback_query(F.data == "menu_admin")
async def handler_admin_tools(callback: CallbackQuery):
    """Menangani akses menu Admin dengan proteksi ganda"""
    if not check_is_admin(callback.from_user.id):
        await callback.answer("⛔ Akses ditolak! Anda bukan Admin.", show_alert=True)
        return

    markup = get_admin_tools_kb()
    await safe_edit_message(callback.message, ADMIN_TOOLS_TEXT, markup)
    await callback.answer()


@ui_router.callback_query(F.data == "action_cancel")
async def handler_action_cancel(callback: CallbackQuery):
    """Menangani tombol Cancel, biasanya menghapus pesan dashboard"""
    try:
        await callback.message.delete()
        await callback.answer("❌ Tindakan dibatalkan.", show_alert=False)
    except TelegramBadRequest:
        await callback.answer("Gagal menghapus pesan.", show_alert=True)


# Command contoh untuk memunculkan Dashboard pertama kali
@ui_router.message(F.text == "/dashboard")
async def cmd_dashboard(message: Message):
    is_admin = check_is_admin(message.from_user.id)
    text = MAIN_DASHBOARD_TEXT.format(name=message.from_user.first_name)
    markup = get_main_menu_kb(is_admin)
    
    await message.answer(text=text, reply_markup=markup, parse_mode="HTML")
