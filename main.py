from config.config import Config
from bot_helper.Aria2.Aria2_Engine import start_listener
from bot_helper.Telegram.Telegram_Client import Telegram
from os.path import exists
from os import remove
from telethon.functions import bots
from telethon.types import BotCommand, BotCommandScopeDefault

#////////////////////////////////////Variables////////////////////////////////////#
DATA = Config.DATA
sudo_users = Config.SUDO_USERS
LOGGER = Config.LOGGER

###############------Load_Plugins------###############
# Cukup panggil bot.start, karena file ini sudah mengatur semua impor handler
import bot.start

###############------Get_Client_Details-----###############
async def get_me(client):
    return await client.get_me()

###############------Set_Bot_Commands-----###############
async def set_bot_commands(command_file):
        LOGGER.info("🔶Setting Up Bot Commands")
        try:
                with open(command_file, "r", encoding="utf-8") as f:
                            commands_data = [x.split("-") for x in f.read().split("\n")]
                commands = []
                for i in range(len(commands_data)):
                    commands.append(BotCommand(
                                                command=commands_data[i][0].strip(),
                                                description=commands_data[i][1].strip()
                                            ))
                result = await Telegram.TELETHON_CLIENT(bots.SetBotCommandsRequest(
                                            scope=BotCommandScopeDefault(),
                                            lang_code='en',
                                            commands=commands
                                        ))
                LOGGER.info(f"🔶Commands Setup Result: {str(result)}")
        except Exception as e:
                LOGGER.info(f"❗Failed To Setup Result: {str(e)}")
        return

###############------Check_Restart------###############
async def check_restart(restart_file):
    try:
        with open(restart_file) as f:
            chat, msg_id = map(int, f)
        remove(restart_file)
        await Telegram.TELETHON_CLIENT.edit_message(chat, msg_id, '✅Restarted Successfully')
    except Exception as e:
        LOGGER.info("🧩Error While Updating Restart Message:\n\n", e)
    return

###############------Start_User_Session------###############
def start_user_account():
    Telegram.TELETHON_USER_CLIENT.start()
    user = Telegram.TELETHON_CLIENT.loop.run_until_complete(get_me(Telegram.TELETHON_USER_CLIENT))
    first_name = user.first_name
    if not user.premium:
        LOGGER.info(f"⛔User Account {first_name} Don't Have Telegram Premium, 2GB Limit Will Be Used For Telegram Uploading.")
    else:
        LOGGER.info(f"💎Telegram Premium Found For  User {first_name}")
    LOGGER.info(f'🔒Session For {first_name} Started Successfully!🔒')
    return

###############------Restart_Notification------###############
async def notify_restart(RESTART_NOTIFY_ID):
    try:
        await Telegram.TELETHON_CLIENT.send_message(RESTART_NOTIFY_ID, "⚡Bot Started Successfully⚡")
    except Exception as e:
        LOGGER.info("❗Failed To Send Restart Notification ", e)
    return

if __name__ == "__main__":
    LOGGER.info("🔶Starting Telethon Bot")
    Telegram.TELETHON_CLIENT.start(bot_token=Config.TOKEN)
    telethob_bot = Telegram.TELETHON_CLIENT.loop.run_until_complete(get_me(Telegram.TELETHON_CLIENT))
    
    LOGGER.info("🔶Checking For Restart Notification")
    if exists(".restartmsg"):
        Telegram.TELETHON_CLIENT.loop.run_until_complete(check_restart(".restartmsg"))
    elif Config.RESTART_NOTIFY_ID:
        Telegram.TELETHON_CLIENT.loop.run_until_complete(notify_restart(Config.RESTART_NOTIFY_ID))
        
    if Config.USE_PYROGRAM:
        LOGGER.info("🔶Starting Pyrogram Bot")
        pyrogram_bot = Telegram.PYROGRAM_CLIENT.start()
        LOGGER.info(f'✅Pyrogram Session For @{pyrogram_bot.get_me().username} Started Successfully!✅')
    else:
        LOGGER.info("🔶Not Starting Pyrogram bot")
        
    if Telegram.TELETHON_USER_CLIENT:
        start_user_account()
    else:
        LOGGER.info("🔶Not Starting User Session")
        
    start_listener()
    
    if exists("commands.txt") and Config.AUTO_SET_BOT_CMDS:
        Telegram.TELETHON_CLIENT.loop.run_until_complete(set_bot_commands("commands.txt"))
    else:
        LOGGER.info("🔶Not Setting Up Bot Commands")
        
    LOGGER.info(f'✅@{telethob_bot.username} Started Successfully!✅')
    LOGGER.info(f"⚡Bot By Sahil Nolia⚡")
    Telegram.TELETHON_CLIENT.run_until_disconnected()
