"""
╔══════════════════════════════════════════════════════════════════════╗
║                              main.py                                 ║
║                    Encoder1 Bot — v3.1 (Trinity Update)              ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [NEW]      Menggunakan asyncio.run() native Python 3.11             ║
║  [NEW]      Aiogram dp.start_polling() sebagai main loop             ║
║  [FIX]      Setup Bot Commands dipindah dari Telethon ke Aiogram     ║
║  [FIX]      Inisialisasi semua client (Telethon & Pyrogram) async    ║
║  [IMPROVE]  Penanganan error restart message lebih aman (split string)║
║  [IMPROVE]  Parsing commands.txt pakai split("-", 1) agar deskripsi  ║
║             yang mengandung tanda "-" tidak error.                   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
from os import remove
from os.path import exists

# ── Aiogram ───────────────────────────────────────────────────────────
from aiogram.types import BotCommand

# ── Internal ──────────────────────────────────────────────────────────
from config.config import Config
from bot_helper.Aria2.Aria2_Engine import start_listener
from bot_helper.Telegram.Telegram_Client import Telegram

# Coba pasang uvloop untuk akselerasi (jika di Linux/VPS)
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

#////////////////////////////////////Variables////////////////////////////////////#
DATA = Config.DATA
sudo_users = Config.SUDO_USERS
LOGGER = Config.LOGGER

###############------Load_Plugins------###############
# Cukup panggil bot.start, karena file ini sudah mengatur semua impor handler
import bot.start

###############------Set_Bot_Commands-----###############
async def set_bot_commands(command_file):
    """Setup bot commands menggunakan Aiogram (Lebih modern & cepat)."""
    LOGGER.info("🔶 Setting Up Bot Commands via Aiogram")
    try:
        with open(command_file, "r", encoding="utf-8") as f:
            # Pakai maxsplit=1 agar deskripsi yang mengandung strip '-' tidak terpotong
            commands_data = [x.split("-", 1) for x in f.read().strip().split("\n") if "-" in x]
            
        commands = []
        for cmd, desc in commands_data:
            commands.append(
                BotCommand(
                    command=cmd.strip(),
                    description=desc.strip()
                )
            )
            
        # Register command ke Telegram via Aiogram
        await Telegram.AIOGRAM_BOT.set_my_commands(commands)
        LOGGER.info("✅ Commands Setup Successfully")
    except Exception as e:
        LOGGER.error(f"❗ Failed To Setup Commands: {str(e)}")

###############------Check_Restart------###############
async def check_restart(restart_file):
    try:
        with open(restart_file, "r") as f:
            # split() untuk menghindari error jika ada spasi/newline berlebih
            chat, msg_id = map(int, f.read().split())
        remove(restart_file)
        await Telegram.TELETHON_CLIENT.edit_message(chat, msg_id, '✅ Restarted Successfully')
    except Exception as e:
        LOGGER.info(f"🧩 Error While Updating Restart Message: {e}")

###############------Start_User_Session------###############
async def start_user_account():
    LOGGER.info("🔶 Starting Telethon User Session")
    await Telegram.TELETHON_USER_CLIENT.start()
    user = await Telegram.TELETHON_USER_CLIENT.get_me()
    first_name = user.first_name
    
    if not user.premium:
        LOGGER.info(f"⛔ User Account {first_name} Don't Have Telegram Premium, 2GB Limit Will Be Used.")
    else:
        LOGGER.info(f"💎 Telegram Premium Found For User {first_name}")
        
    LOGGER.info(f'🔒 Session For {first_name} Started Successfully! 🔒')

###############------Main_Async_Loop------###############
async def main():
    LOGGER.info("⚡ Starting Trinity Clients (Aiogram + Telethon + Pyrogram) ⚡")

    # 1. Start Telethon Bot
    LOGGER.info("🔶 Starting Telethon Bot")
    await Telegram.TELETHON_CLIENT.start(bot_token=Config.TOKEN)
    telethon_bot = await Telegram.TELETHON_CLIENT.get_me()
    LOGGER.info(f"✅ @{telethon_bot.username} (Telethon) Started Successfully!")

    # 2. Check Restart Notification
    LOGGER.info("🔶 Checking For Restart Notification")
    if exists(".restartmsg"):
        await check_restart(".restartmsg")
    elif Config.RESTART_NOTIFY_ID:
        try:
            await Telegram.TELETHON_CLIENT.send_message(Config.RESTART_NOTIFY_ID, "⚡ Bot Started Successfully ⚡")
        except Exception as e:
            LOGGER.info(f"❗ Failed To Send Restart Notification: {e}")

    # 3. Start Pyrogram
    if Config.USE_PYROGRAM and Telegram.PYROGRAM_CLIENT:
        LOGGER.info("🔶 Starting Pyrogram Bot")
        await Telegram.PYROGRAM_CLIENT.start()
        pyrogram_bot = await Telegram.PYROGRAM_CLIENT.get_me()
        LOGGER.info(f"✅ @{pyrogram_bot.username} (Pyrogram) Started Successfully!")
    else:
        LOGGER.info("🔶 Not Starting Pyrogram bot")

    # 4. Start User Session (Khusus Upload > 2GB)
    if Telegram.TELETHON_USER_CLIENT:
        await start_user_account()
    else:
        LOGGER.info("🔶 Not Starting User Session")

    # 5. Start Aria2 Engine
    start_listener()

    # 6. Set Bot Commands
    if exists("commands.txt") and Config.AUTO_SET_BOT_CMDS:
        await set_bot_commands("commands.txt")
    else:
        LOGGER.info("🔶 Not Setting Up Bot Commands")

    LOGGER.info("⚡ Bot By Sahil Nolia (Upgraded to Trinity Architecture) ⚡")

    # 7. Start Aiogram Polling (Ini akan menahan loop agar script terus berjalan)
    LOGGER.info("🔶 Starting Aiogram Polling...")
    # drop_pending_updates=True mencegah bot memproses spam pesan lama saat bot mati
    await Telegram.AIOGRAM_DP.start_polling(Telegram.AIOGRAM_BOT, drop_pending_updates=True)


if __name__ == "__main__":
    try:
        # Menjalankan fungsi asinkron utama (Sesuai best practice Python 3.11)
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        LOGGER.info("🛑 Bot Stopped Manually.")
