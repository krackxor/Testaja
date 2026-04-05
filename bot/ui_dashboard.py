"""
UI Dashboard Template for STUDIO KHOIRUL (Aiogram 3.x)
Versi: FULL APP NAVIGATION (Trinity v3.1 Edition)
Fitur: One-Click Execution, Massive Grid Layout, Dynamic Routing
"""

import asyncio
from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest

# Ambil data admin otomatis dari Config
from config.config import Config

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
<i>Pilih modul workspace di bawah ini:</i></blockquote>
"""

CATEGORY_TEXT = """
<blockquote>{icon} <b>{title}</b>
━━━━━━━━━━━━━━━━━━━━━━
{desc}
━━━━━━━━━━━━━━━━━━━━━━
<i>Pilih fitur yang ingin digunakan:</i></blockquote>
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
    return user_id in Config.SUDO_USERS

def get_back_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="menu_main")],
        [InlineKeyboardButton(text="❌ Close Dashboard", callback_data="action_cancel")]
    ])

# ==========================================
# 3. KEYBOARD BUILDERS
# ==========================================

def get_main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(text="🎬 Studio Produksi", callback_data="menu_studio"),
         InlineKeyboardButton(text="✂️ Video Editing", callback_data="menu_vid_edit")],
        [InlineKeyboardButton(text="🎮 Manajemen Aset", callback_data="menu_assets"),
         InlineKeyboardButton(text="📥 Unduh & Cloud", callback_data="menu_downloader")],
        [InlineKeyboardButton(text="⚙️ Pengaturan Bot", callback_data="menu_settings"),
         InlineKeyboardButton(text="👑 Sistem VIP", callback_data="menu_vip")]
    ]
    if is_admin:
        kb.append([InlineKeyboardButton(text="💻 Admin Tools", callback_data="menu_admin")])
    
    kb.append([InlineKeyboardButton(text="❌ Tutup Panel", callback_data="action_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_studio_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Recap Film", callback_data="cmd_recap"), InlineKeyboardButton(text="✂️ Auto Clip", callback_data="cmd_clip")],
        [InlineKeyboardButton(text="🔴 Verdict", callback_data="cmd_verdict"), InlineKeyboardButton(text="🟡 Top Tier", callback_data="cmd_toptier")],
        [InlineKeyboardButton(text="⚫ Lore", callback_data="cmd_lore"), InlineKeyboardButton(text="🟣 Radar", callback_data="cmd_radar")],
        [InlineKeyboardButton(text="⚡ Patch", callback_data="cmd_patch"), InlineKeyboardButton(text="📻 Archives", callback_data="cmd_archives")],
        [InlineKeyboardButton(text="▶️ YouTube Upload", callback_data="cmd_ytupload")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="menu_main")]
    ])

def get_editor_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗜 Compress", callback_data="cmd_compress"), InlineKeyboardButton(text="🔄 Convert", callback_data="cmd_convert"), InlineKeyboardButton(text="🔗 Merge", callback_data="cmd_merge")],
        [InlineKeyboardButton(text="🎞 Trim", callback_data="cmd_trim"), InlineKeyboardButton(text="✂️ Split", callback_data="cmd_split"), InlineKeyboardButton(text="🔪 Cut", callback_data="cmd_cut")],
        [InlineKeyboardButton(text="📐 Crop", callback_data="cmd_crop"), InlineKeyboardButton(text="🎬 Autocrop", callback_data="cmd_autocrop"), InlineKeyboardButton(text="🔃 Rotate", callback_data="cmd_rotate")],
        [InlineKeyboardButton(text="📌 Hardmux", callback_data="cmd_hardmux"), InlineKeyboardButton(text="📝 Softmux", callback_data="cmd_softmux"), InlineKeyboardButton(text="♻️ Remux", callback_data="cmd_softremux")],
        [InlineKeyboardButton(text="🎵 Extract", callback_data="cmd_extract"), InlineKeyboardButton(text="🗂 Extension", callback_data="cmd_extension"), InlineKeyboardButton(text="🔢 Index", callback_data="cmd_changeindex")],
        [InlineKeyboardButton(text="🏷 Metadata", callback_data="cmd_changemetadata"), InlineKeyboardButton(text="ℹ️ MediaInfo", callback_data="cmd_mediainfo")],
        [InlineKeyboardButton(text="©️ Watermark", callback_data="cmd_watermark"), InlineKeyboardButton(text="📸 Screenshot", callback_data="cmd_genss"), InlineKeyboardButton(text="🎞 Sample", callback_data="cmd_gensample")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="menu_main")]
    ])

def get_assets_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Gameplay", callback_data="cmd_addgameplay"), InlineKeyboardButton(text="📋 List Gameplay", callback_data="cmd_listgameplay")],
        [InlineKeyboardButton(text="🗑 Del Gameplay", callback_data="cmd_deletegameplay"), InlineKeyboardButton(text="🔊 Add SFX", callback_data="cmd_addsfx")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="menu_main")]
    ])

def get_downloader_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Leech", callback_data="cmd_leech"), InlineKeyboardButton(text="☁️ Mirror", callback_data="cmd_mirror")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="menu_main")]
    ])

def get_settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Profil Pengaturan", callback_data="profile_main")],
        [InlineKeyboardButton(text="🎬 Pengaturan Media", callback_data="settings_media")],
        [InlineKeyboardButton(text="🤖 Pengaturan Bot", callback_data="settings_bot")],
        [InlineKeyboardButton(text="©️ Save Watermark", callback_data="cmd_savewatermark"), InlineKeyboardButton(text="🖼 Save Thumb", callback_data="cmd_savethumb")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="menu_main")]
    ])

def get_vip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 Cek Status VIP", callback_data="cmd_myvip")],
        [InlineKeyboardButton(text="💳 Verifikasi Trakteer", callback_data="cmd_verify")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="menu_main")]
    ])

def get_admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Status Tasks", callback_data="cmd_status"), InlineKeyboardButton(text="🚀 Speedtest", callback_data="cmd_speedtest")],
        [InlineKeyboardButton(text="⏱ Uptime", callback_data="cmd_time"), InlineKeyboardButton(text="📊 Server Stats", callback_data="cmd_stats")],
        [InlineKeyboardButton(text="🗒 Lihat Log", callback_data="cmd_log"), InlineKeyboardButton(text="📁 Unduh Log", callback_data="cmd_logs")],
        [InlineKeyboardButton(text="🧹 Renew Server", callback_data="cmd_renew"), InlineKeyboardButton(text="💥 Reset DB", callback_data="cmd_resetdb")],
        [InlineKeyboardButton(text="👮 Cek Sudo", callback_data="cmd_checksudo"), InlineKeyboardButton(text="🔄 Restart", callback_data="cmd_restart")],
        [InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="menu_main")]
    ])

# ==========================================
# 4. NAVIGATION HANDLERS
# ==========================================

@ui_router.callback_query(F.data == "menu_main")
async def nav_main(callback: CallbackQuery):
    is_admin = check_is_admin(callback.from_user.id)
    text = MAIN_DASHBOARD_TEXT.format(name=callback.from_user.first_name)
    await safe_edit_message(callback.message, text, get_main_menu_kb(is_admin))
    await callback.answer()

@ui_router.callback_query(F.data == "menu_studio")
async def nav_studio(callback: CallbackQuery):
    text = CATEGORY_TEXT.format(icon="🎬", title="𝐒𝐓𝐔𝐃𝐈𝐎 𝐏𝐑𝐎𝐃𝐔𝐊𝐒𝐈 & 𝐀𝐈", desc="Produksi video otomatis menggunakan kekuatan AI & Scripting.")
    await safe_edit_message(callback.message, text, get_studio_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_assets")
async def nav_assets(callback: CallbackQuery):
    text = CATEGORY_TEXT.format(icon="🎮", title="𝐌𝐀𝐍𝐀𝐉𝐄𝐌𝐄𝐍 𝐀𝐒𝐄𝐓", desc="Kelola video gameplay dan efek suara kustom untuk produksi.")
    await safe_edit_message(callback.message, text, get_assets_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_downloader")
async def nav_downloader(callback: CallbackQuery):
    text = CATEGORY_TEXT.format(icon="📥", title="𝐔𝐍𝐃𝐔𝐇 & 𝐂𝐋𝐎𝐔𝐃", desc="Download file ke Telegram atau Drive.")
    await safe_edit_message(callback.message, text, get_downloader_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_settings")
async def nav_settings(callback: CallbackQuery):
    text = CATEGORY_TEXT.format(icon="⚙️", title="𝐏𝐄𝐍𝐆𝐀𝐓𝐔𝐑𝐀𝐍", desc="Sesuaikan profil, kualitas konversi, dan default file.")
    await safe_edit_message(callback.message, text, get_settings_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_vip")
async def nav_vip(callback: CallbackQuery):
    text = CATEGORY_TEXT.format(icon="👑", title="𝐒𝐈𝐒𝐓𝐄𝐌 𝐕𝐈𝐏", desc="Cek masa aktif VIP atau klaim benefit.")
    await safe_edit_message(callback.message, text, get_vip_kb())
    await callback.answer()

@ui_router.callback_query(F.data == "menu_admin")
async def nav_admin(callback: CallbackQuery):
    if not check_is_admin(callback.from_user.id):
        return await callback.answer("⛔ Akses ditolak!", show_alert=True)
    text = CATEGORY_TEXT.format(icon="💻", title="𝐒𝐘𝐒𝐓𝐄𝐌 𝐓𝐎𝐎𝐋𝐒", desc="Kontrol penuh atas server, antrean, dan database.")
    await safe_edit_message(callback.message, text, get_admin_kb())
    await callback.answer()

# ==========================================
# 5. [NEW] UNIVERSAL COMMAND CATCHER (ONE-CLICK EXECUTION)
# ==========================================
@ui_router.callback_query(F.data.startswith("cmd_"))
async def catch_all_commands(callback: CallbackQuery):
    command_name = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id
    
    # ─── DAFTAR PERINTAH INSTAN (Tanpa Input Tambahan) ───
    instant_commands = [
        "speedtest", "status", "time", "stats", "restart", 
        "renew", "myvip", "log", "checksudo", "logs"
    ]
    
    if command_name in instant_commands:
        # Pengecekan Sudo untuk perintah admin instan
        if command_name in ["speedtest", "restart", "renew", "log", "logs"] and not check_is_admin(user_id):
            return await callback.answer("⛔ Perintah ini hanya untuk Admin!", show_alert=True)
            
        await callback.answer(f"🚀 Menjalankan /{command_name}...", show_alert=False)
        
        # Buat objek Message palsu agar bisa diterima oleh handler lama
        fake_msg = callback.message
        fake_msg.from_user = callback.from_user
        fake_msg.text = f"/{command_name}"
        
        # Import Handlers secara dinamis
        from bot.admin_handlers import _speedtest, _status, _time, _stats, _restart, _renew, _log, _logs
        from bot.vip_handlers import _myvip, _checksudo
        
        handlers = {
            "speedtest": _speedtest, "status": _status, "time": _time, "stats": _stats,
            "restart": _restart, "renew": _renew, "myvip": _myvip, "log": _log,
            "checksudo": _checksudo, "logs": _logs
        }
        
        if command_name in handlers:
            # Sembunyikan dashboard sebelum eksekusi agar tidak menumpuk
            await callback.message.delete()
            return await handlers[command_name](fake_msg)

    # ─── JIKA BUKAN INSTAN: Tampilkan Panduan ───
    instruction_text = f"""<blockquote>💡 <b>𝐌𝐎𝐃𝐔𝐋 𝐀𝐊𝐓𝐈𝐅: <code>/{command_name}</code></b>
━━━━━━━━━━━━━━━━━━━━━━
Modul ini memerlukan input file atau parameter.
Silakan kirimkan File/Link ke obrolan ini, lalu gunakan perintah <code>/{command_name}</code>.
━━━━━━━━━━━━━━━━━━━━━━</blockquote>"""

    await safe_edit_message(callback.message, instruction_text, get_back_cancel_kb())
    await callback.answer()

# ==========================================
# 6. GLOBAL CANCEL & START
# ==========================================
@ui_router.callback_query(F.data == "action_cancel")
async def handler_action_cancel(callback: CallbackQuery):
    try: await callback.message.delete()
    except: pass
    await callback.answer("Dashboard ditutup.")

@ui_router.message(F.text.in_(["/dashboard", "/start"]))
async def cmd_dashboard(message: Message):
    is_admin = check_is_admin(message.from_user.id)
    text = MAIN_DASHBOARD_TEXT.format(name=message.from_user.first_name)
    await message.answer(text=text, reply_markup=get_main_menu_kb(is_admin), parse_mode="HTML")
