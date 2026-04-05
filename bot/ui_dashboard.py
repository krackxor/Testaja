"""
UI Dashboard Template for STUDIO KHOIRUL (Aiogram 3.x)
Versi: FULL APP NAVIGATION
Fitur: Safe Edit, Grid Layout, Admin Checks, Navigation System, Semua Layar Lengkap
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

VIDEO_EDIT_TEXT = """
<blockquote>✂️ <b>𝐕𝐈𝐃𝐄𝐎 𝐄𝐃𝐈𝐓𝐈𝐍𝐆 𝐒𝐔𝐈𝐓𝐄</b>
━━━━━━━━━━━━━━━━━━━━━━
Professional video manipulation tools.

<b>Tersedia:</b>
• Autocrop (Hapus Bilah Hitam)
• Konversi Resolusi (480p, 720p, dll)
• Ekstrak Audio/Subtitle
• Pemotong Video (Split)
━━━━━━━━━━━━━━━━━━━━━━
📥 <b>Aksi Diperlukan:</b>
<i>Silakan kirim atau teruskan (forward) video yang ingin Anda edit ke obrolan ini!</i></blockquote>
"""

DOWNLOADER_TEXT = """
<blockquote>📥 <b>𝐔𝐍𝐈𝐕𝐄𝐑𝐒𝐀𝐋 𝐃𝐎𝐖𝐍𝐋𝐎𝐀𝐃𝐄𝐑</b>
━━━━━━━━━━━━━━━━━━━━━━
Download file dari berbagai sumber langsung ke Cloud Vault Anda.

<b>Mendukung:</b>
• Direct Links (Aria2 Engine)
• Torrent / Magnet
• YouTube / Media Links
━━━━━━━━━━━━━━━━━━━━━━
🔗 <b>Aksi Diperlukan:</b>
<i>Silakan kirimkan link atau URL yang ingin Anda unduh!</i></blockquote>
"""

VIP_SYSTEM_TEXT = """
<blockquote>👑 <b>𝐕𝐈𝐏  &  𝐁𝐈𝐋𝐋𝐈𝐍𝐆 𝐒𝐘𝐒𝐓𝐄𝐌</b>
━━━━━━━━━━━━━━━━━━━━━━
Status Akun: <b>VIP PRO</b> 💎
Masa Aktif: <code>Lifetime</code>
Sisa Saldo / Kredit: <code>150 Credits</code>

<b>Keuntungan Anda:</b>
✅ Upload File > 2GB (Premium Session)
✅ Prioritas Antrean Render (No Limit)
✅ Akses Model AI Khusus
━━━━━━━━━━━━━━━━━━━━━━</blockquote>
"""

SETTINGS_TEXT = """
<blockquote>⚙️ <b>𝐏𝐑𝐄𝐅𝐄𝐑𝐄𝐍𝐂𝐄𝐒  &  𝐒𝐄𝐓𝐓𝐈𝐍𝐆𝐒</b>
━━━━━━━━━━━━━━━━━━━━━━
Sesuaikan cara kerja bot untuk akun Anda.
━━━━━━━━━━━━━━━━━━━━━━</blockquote>
"""

HELP_TEXT = """
<blockquote>❓ <b>𝐇𝐄𝐋𝐏  &  𝐒𝐔𝐏𝐏𝐎𝐑𝐓</b>
━━━━━━━━━━━━━━━━━━━━━━
Selamat datang di Pusat Bantuan Studio Khoirul.
Jika Anda menemukan kendala, hubungi Admin atau baca panduan di bawah ini.
━━━━━━━━━━━━━━━━━━━━━━</blockquote>
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
    try:
        await message.edit_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
        return True
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return False
        raise e

def check_is_admin(user_id: int) -> bool:
    """Ganti dengan list ID Telegram kamu yang asli"""
    admin_ids = [123456789] # <-- UPDATE ID ADMIN DI SINI
    return user_id in admin_ids

# ==========================================
# 3. KEYBOARD BUILDERS
# ==========================================

def get_main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🎬 Video Production", callback_data="menu_vid_prod"),
         InlineKeyboardButton(text="✂️ Video Editing", callback_data="menu_vid_edit")],
        [InlineKeyboardButton(text="📥 Downloader", callback_data="menu_download"),
         InlineKeyboardButton(text="🎮 Asset Manager", callback_data="menu_assets")],
        [InlineKeyboardButton(text="⚙️ Settings", callback_data="menu_settings"),
         InlineKeyboardButton(text="👑 VIP System", callback_data="menu_vip")]
    ]
    if is_admin:
        kb.append([InlineKeyboardButton(text="💻 System Tools", callback_data="menu_admin"),
                   InlineKeyboardButton(text="❓ Help", callback_data="menu_help")])
    else:
        kb.append([InlineKeyboardButton(text="❓ Help", callback_data="menu_help")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_video_prod_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Text to Video", callback_data="prod_t2v"),
         InlineKeyboardButton(text="🖼️ Image to Video", callback_data="prod_i2v")],
        [InlineKeyboardButton(text="🎙️ Audio Driven", callback_data="prod_audio"),
         InlineKeyboardButton(text="🎭 Clone / Deepfake", callback_data="prod_clone")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="menu_main"),
         InlineKeyboardButton(text="❌ Cancel", callback_data="action_cancel")]
    ])

def get_back_cancel_kb() -> InlineKeyboardMarkup:
    """Keyboard standar untuk kembali ke menu utama"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="menu_main")],
        [InlineKeyboardButton(text="❌ Close Dashboard", callback_data="action_cancel")]
    ])

def get_settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☁️ Rclone Drive", callback_data="set_rclone"),
         InlineKeyboardButton(text="🎛 Convert Quality", callback_data="set_quality")],
        [InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="menu_main")]
    ])

def get_admin_tools_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Server Stats", callback_data="admin_stats"),
         InlineKeyboardButton(text="👥 User List", callback_data="admin_users")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="menu_main")]
    ])

# ==========================================
# 4. CALLBACK HANDLERS (ROUTING)
# ==========================================

@ui_router.callback_query(F.data == "menu_main")
async def handler_menu_main(callback: CallbackQuery):
    is_admin = check_is_admin(callback.from_user.id)
    text = MAIN_DASHBOARD_TEXT.format(name=callback.from_user.first_name)
    await safe_edit_message(callback.message, text, get_main_menu_kb(is_admin))
    await callback.answer()

@ui_router.callback_query(F.data == "menu_vid_prod")
async def handler_video_prod(callback: CallbackQuery):
    await safe_edit_message(callback.message, VIDEO_PROD_TEXT, get_video_prod_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_vid_edit")
async def handler_video_edit(callback: CallbackQuery):
    await safe_edit_message(callback.message, VIDEO_EDIT_TEXT, get_back_cancel_kb())
    await callback.answer("Silakan kirimkan video yang ingin diedit!", show_alert=False)

@ui_router.callback_query(F.data == "menu_download")
async def handler_download(callback: CallbackQuery):
    await safe_edit_message(callback.message, DOWNLOADER_TEXT, get_back_cancel_kb())
    await callback.answer("Siap mengunduh! Kirimkan link-nya.", show_alert=False)

@ui_router.callback_query(F.data == "menu_vip")
async def handler_vip(callback: CallbackQuery):
    await safe_edit_message(callback.message, VIP_SYSTEM_TEXT, get_back_cancel_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_settings")
async def handler_settings(callback: CallbackQuery):
    await safe_edit_message(callback.message, SETTINGS_TEXT, get_settings_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_assets")
async def handler_assets(callback: CallbackQuery):
    text = "<blockquote>🎮 <b>𝐀𝐒𝐒𝐄𝐓 𝐌𝐀𝐍𝐀𝐆𝐄𝐑</b>\n━━━━━━━━━━━━━━━━━━━━━━\nFitur manajemen file sedang dalam pengembangan (Coming Soon).\n━━━━━━━━━━━━━━━━━━━━━━</blockquote>"
    await safe_edit_message(callback.message, text, get_back_cancel_kb())
    await callback.answer("Coming soon!", show_alert=False)

@ui_router.callback_query(F.data == "menu_help")
async def handler_help(callback: CallbackQuery):
    await safe_edit_message(callback.message, HELP_TEXT, get_back_cancel_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_admin")
async def handler_admin_tools(callback: CallbackQuery):
    if not check_is_admin(callback.from_user.id):
        await callback.answer("⛔ Akses ditolak! Anda bukan Admin.", show_alert=True)
        return
    await safe_edit_message(callback.message, ADMIN_TOOLS_TEXT, get_admin_tools_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "action_cancel")
async def handler_action_cancel(callback: CallbackQuery):
    try:
        await callback.message.delete()
        await callback.answer("❌ Dashboard ditutup.", show_alert=False)
    except TelegramBadRequest:
        await callback.answer("Gagal menutup dashboard.", show_alert=True)

# Command contoh untuk memunculkan Dashboard pertama kali
@ui_router.message(F.text == "/dashboard")
@ui_router.message(F.text == "/start") # Dashboard otomatis muncul saat di-/start
async def cmd_dashboard(message: Message):
    is_admin = check_is_admin(message.from_user.id)
    text = MAIN_DASHBOARD_TEXT.format(name=message.from_user.first_name)
    markup = get_main_menu_kb(is_admin)
    await message.answer(text=text, reply_markup=markup, parse_mode="HTML")
