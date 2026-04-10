"""
╔══════════════════════════════════════════════════════════════════════╗
║                    main.py — v3.5 (Unified Engine Edition)           ║
║         Encoder1 Bot — v3.5 (Studio Khoirul Premium Update)          ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v3.5:                                                     ║
║  [FIX CRITICAL] Reorder Routers: Memindahkan `bot.callbacks` ke      ║
║                 urutan PALING BAWAH untuk mencegah masalah           ║
║                 'Router Black Hole' (Tombol macet/stuck).            ║
║  [NEW] Integrasi bot_helper.Process.Unified_Engine                   ║
║  [FIX] Inisialisasi antrean Semaphore global saat startup.           ║
║  [FIX] Sinkronisasi data antrean Dashboard dengan Engine.            ║
║  [IMPROVE] Middleware Waiter Catcher diprioritaskan paling awal.     ║
║  [IMPROVE] Logika Auto-Router cerdas (Deteksi router & ui_router).   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import os
from os import remove
from os.path import exists

# ── Aiogram ───────────────────────────────────────────────────────────
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, Message
from aiogram import BaseMiddleware

# ── Internal ──────────────────────────────────────────────────────────
from config.config import Config
from bot_helper.Aria2.Aria2_Engine import start_listener, Aria2
from bot_helper.Telegram.Telegram_Client import Telegram
from bot.shared import resolve_waiter

# [CRITICAL] Import Unified Engine agar Semaphore diinisialisasi sejak awal
import bot_helper.Process.Unified_Engine 

# Import fungsi auto-cleaner
from bot_helper.Process.Running_Tasks import clear_all_trash_on_startup

# Coba pasang uvloop untuk akselerasi (jika di Linux/VPS)
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

# ////////////////////////////////////Variables//////////////////////////////////// #
DATA = Config.DATA
sudo_users = Config.SUDO_USERS
LOGGER = Config.LOGGER

###############------Load_Plugins------###############
# Memuat semua modul bot untuk registrasi Router
import bot.start
import bot.admin_handlers
import bot.vip_handlers
import bot.media_handlers
import bot.advanced_media_handlers
import bot.callbacks
import bot.Gameplay
import bot.AutoClip
import bot.MovieRecap
import bot.YTUpload
import bot.subtitle_handlers
import bot.subtitle_editor 
import bot.ui_dashboard 

# Import task background
try:
    from bot.Gameplay import auto_clean_temp_dir
except ImportError:
    auto_clean_temp_dir = None

# ═══════════════════════════════════════════════════════════════════════
#  GLOBAL MESSAGE CATCHER (UNTUK INLINE WAITER)
# ═══════════════════════════════════════════════════════════════════════
class WaiterCatcherMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data: dict):
        # Cek apakah ada fungsi yang sedang menunggu balasan dari user ini via bot/shared.py
        if resolve_waiter(event):
            # Jika pesan ditangkap oleh waiter, jangan teruskan ke handler lain
            return None 
        return await handler(event, data)


###############------Set_Bot_Commands-----###############
async def set_bot_commands(command_file):
    """Setup bot commands menggunakan Aiogram."""
    LOGGER.info("🔶 Setting Up Bot Commands via Aiogram")
    try:
        if not exists(command_file):
            return
            
        with open(command_file, "r", encoding="utf-8") as f:
            lines = f.read().strip().split("\n")
            commands_data = [x.split("-", 1) for x in lines if "-" in x]
            
        commands = []
        for cmd, desc in commands_data:
            commands.append(
                BotCommand(
                    command=cmd.strip().replace("/", ""), 
                    description=desc.strip()
                )
            )
            
        await Telegram.AIOGRAM_BOT.set_my_commands(commands)
        LOGGER.info("✅ Commands Setup Successfully")
    except Exception as e:
        LOGGER.error(f"❗ Failed To Setup Commands: {str(e)}")

###############------Check_Restart------###############
async def check_restart(restart_file):
    try:
        if exists(restart_file):
            with open(restart_file, "r") as f:
                content = f.read().split()
                if len(content) >= 2:
                    chat, msg_id = map(int, content[:2])
                    await Telegram.TELETHON_CLIENT.edit_message(chat, msg_id, '✅ Restarted Successfully')
            remove(restart_file)
    except Exception as e:
        LOGGER.info(f"🧩 Error While Updating Restart Message: {e}")

###############------Start_User_Session------###############
async def start_user_account():
    LOGGER.info("🔶 Starting Telethon User Session")
    try:
        await Telegram.TELETHON_USER_CLIENT.start()
        user = await Telegram.TELETHON_USER_CLIENT.get_me()
        
        if not user.premium:
            LOGGER.info(f"⛔ Account {user.first_name} No Premium, 2GB Limit active.")
        else:
            LOGGER.info(f"💎 Telegram Premium Found For User {user.first_name}")
            
        LOGGER.info(f'🔒 Session For {user.first_name} Started Successfully!')
    except Exception as e:
        LOGGER.error(f"❗ Failed to start user session: {e}")

###############------Main_Async_Loop------###############
async def main():
    LOGGER.info("⚡ Starting Trinity Clients (Aiogram + Telethon + Pyrogram) ⚡")

    # ─── PEMBERSIHAN FILE SISA (STARTUP CLEANUP) ───
    await clear_all_trash_on_startup()

    # Mendaftarkan Middleware Global (Urutan sangat krusial)
    Telegram.AIOGRAM_DP.message.outer_middleware(WaiterCatcherMiddleware())

    # ─── AUTO-LOADER ROUTERS (URUTAN DIPERBAIKI) ───
    # [FIX CRITICAL] bot.callbacks DIPINDAHKAN KE PALING BAWAH!
    modules_to_include = [
        bot.ui_dashboard,   # Dashboard didahulukan
        bot.admin_handlers, bot.vip_handlers, bot.media_handlers,
        bot.advanced_media_handlers, bot.Gameplay, bot.AutoClip, 
        bot.MovieRecap, bot.YTUpload, bot.subtitle_handlers, 
        bot.subtitle_editor, 
        bot.callbacks       # <-- CALLBACKS HARUS PALING BAWAH
    ]
    
    loaded_routers = 0
    for mod in modules_to_include:
        router_obj = getattr(mod, 'router', None) or getattr(mod, 'ui_router', None)
        if router_obj:
            Telegram.AIOGRAM_DP.include_router(router_obj)
            loaded_routers += 1
            LOGGER.info(f"✅ Router Attached: {mod.__name__}")
    
    LOGGER.info(f"🔗 Total {loaded_routers} Aiogram Routers Successfully Linked!")

    # 1. Start Telethon Bot
    LOGGER.info("🔶 Starting Telethon Bot")
    await Telegram.TELETHON_CLIENT.start(bot_token=Config.TOKEN)
    telethon_bot = await Telegram.TELETHON_CLIENT.get_me()
    LOGGER.info(f"✅ @{telethon_bot.username} (Telethon) Started!")

    # 2. Check Restart Notification
    if exists(".restartmsg"):
        await check_restart(".restartmsg")
    elif Config.RESTART_NOTIFY_ID:
        try:
            await Telegram.TELETHON_CLIENT.send_message(Config.RESTART_NOTIFY_ID, "⚡ Bot Started Successfully ⚡")
        except Exception as e:
            LOGGER.info(f"❗ Restart Notification Failed: {e}")

    # 3. Start Pyrogram
    if Config.USE_PYROGRAM and Telegram.PYROGRAM_CLIENT:
        LOGGER.info("🔶 Starting Pyrogram Bot")
        await Telegram.PYROGRAM_CLIENT.start()
        pyrogram_bot = await Telegram.PYROGRAM_CLIENT.get_me()
        LOGGER.info(f"✅ @{pyrogram_bot.username} (Pyrogram) Started!")

    # 4. Start User Session (Khusus Upload > 2GB)
    if Telegram.TELETHON_USER_CLIENT:
        await start_user_account()

    # 5. Start Aria2 Engine
    LOGGER.info("🔶 Starting Aria2 Engine")
    Aria2.initialize()
    start_listener()

    # 6. Set Bot Commands
    if exists("commands.txt") and Config.AUTO_SET_BOT_CMDS:
        await set_bot_commands("commands.txt")

    # 7. Start Auto-Cleaner Background Task
    if auto_clean_temp_dir:
        LOGGER.info("🧹 Starting Auto-Cleaner Background Task...")
        asyncio.create_task(auto_clean_temp_dir("./temp/", max_age_hours=24))

    LOGGER.info("🚀 UNIFIED ENGINE READY: System Production Online!")

    # 8. Start Aiogram Polling
    await Telegram.AIOGRAM_DP.start_polling(Telegram.AIOGRAM_BOT, drop_pending_updates=True)


if __name__ == "__main__":
    try:
        # Menjalankan fungsi asinkron utama sesuai Python 3.11
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        LOGGER.info("🛑 Bot Stopped Manually.")
