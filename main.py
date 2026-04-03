"""
╔══════════════════════════════════════════════════════════════════════╗
║                    main.py                                           ║
║            Encoder1 Bot — v3.1 (Trinity Update)                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [NEW]      Menggunakan asyncio.run() native Python 3.11             ║
║  [NEW]      Aiogram dp.start_polling() sebagai main loop             ║
║  [NEW]      Global Message Catcher untuk fitur "Inline Waiter"       ║
║  [FIX]      Setup Bot Commands dipindah dari Telethon ke Aiogram     ║
║  [FIX]      Inisialisasi semua client (Telethon & Pyrogram) async    ║
║  [FIX]      Jalur import shared.py disesuaikan ke folder bot/        ║
║  [IMPROVE]  Penanganan error restart message lebih aman (split string)║
║  [IMPROVE]  Parsing commands.txt pakai split("-", 1)                 ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import os
from os import remove
from os.path import exists

# ── Aiogram ───────────────────────────────────────────────────────────
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, Message
from aiogram.middlewares.base import BaseMiddleware

# ── Internal ──────────────────────────────────────────────────────────
from config.config import Config
from bot_helper.Aria2.Aria2_Engine import start_listener
from bot_helper.Telegram.Telegram_Client import Telegram

# [FIX] Import shared.py dari folder bot/ sesuai struktur file Anda
from bot.shared import resolve_waiter

# [FIX] Import router dari media_handlers di folder bot/
from bot.media_handlers import router as media_router

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
# Baris ini memuat handler Telethon lama dari bot/start.py
import bot.start

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
        with open(restart_file, "r") as f:
            content = f.read().split()
            if len(content) >= 2:
                chat, msg_id = map(int, content[:2])
                await Telegram.TELETHON_CLIENT.edit_message(chat, msg_id, '✅ Restarted Successfully')
        if exists(restart_file):
            remove(restart_file)
    except Exception as e:
        LOGGER.info(f"🧩 Error While Updating Restart Message: {e}")

###############------Start_User_Session------###############
async def start_user_account():
    LOGGER.info("🔶 Starting Telethon User Session")
    try:
        await Telegram.TELETHON_USER_CLIENT.start()
        user = await Telegram.TELETHON_USER_CLIENT.get_me()
        first_name = user.first_name
        
        if not user.premium:
            LOGGER.info(f"⛔ Account {first_name} No Premium, 2GB Limit active.")
        else:
            LOGGER.info(f"💎 Telegram Premium Found For User {first_name}")
            
        LOGGER.info(f'🔒 Session For {first_name} Started Successfully!')
    except Exception as e:
        LOGGER.error(f"❗ Failed to start user session: {e}")

###############------Main_Async_Loop------###############
async def main():
    LOGGER.info("⚡ Starting Trinity Clients (Aiogram + Telethon + Pyrogram) ⚡")

    # Mendaftarkan Middleware dan Router ke Dispatcher Utama
    Telegram.AIOGRAM_DP.message.outer_middleware(WaiterCatcherMiddleware())
    Telegram.AIOGRAM_DP.include_router(media_router)

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
    start_listener()

    # 6. Set Bot Commands
    if exists("commands.txt") and Config.AUTO_SET_BOT_CMDS:
        await set_bot_commands("commands.txt")

    LOGGER.info("⚡ Bot Upgraded to Trinity Architecture (v3.1) ⚡")

    # 7. Start Aiogram Polling
    LOGGER.info("🔶 Starting Aiogram Polling...")
    await Telegram.AIOGRAM_DP.start_polling(Telegram.AIOGRAM_BOT, drop_pending_updates=True)


if __name__ == "__main__":
    try:
        # Menjalankan fungsi asinkron utama sesuai Python 3.11
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        LOGGER.info("🛑 Bot Stopped Manually.")
