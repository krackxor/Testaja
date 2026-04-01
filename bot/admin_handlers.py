"""
╔══════════════════════════════════════════════════════════════════════╗
║       bot_helper/Handlers/admin_handlers.py — v3.1                  ║
║       Admin & System Command Handlers                                ║
╠══════════════════════════════════════════════════════════════════════╣
║  Commands: /start /time /restart /herokurestart /log /logs          ║
║            /stats /speedtest /tasklimit /cancel /ffmpeg             ║
║            /saveconfig /savewatermark /savethumb /changeconfig      ║
║            /clearconfigs /checksudo /addsudo /delsudo /renew        ║
║            /resetdb /changeconfig                                    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
from os import execl, remove
from os.path import exists
from subprocess import run as srun
from sys import argv, executable

# ── Third Party ───────────────────────────────────────────────────────
from telethon import Button, events

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Aria2.Aria2_Engine import Aria2, getDownloadByGid
from bot_helper.Database.User_Data import (
    get_data, new_user, change_task_limit, get_task_limit,
    saveoptions, ensure_user_data_structure,
)
from bot_helper.Others.Helper_Functions import (
    delete_all, export_env_file, get_config,
    get_env_dict, get_env_keys, get_logs_msg, getbotuptime,
)
from bot_helper.Others.SpeedTest import speedtest
from bot_helper.Process.Running_Process import remove_running_process
from bot_helper.Process.Running_Tasks import (
    get_ffmpeg_log_file, refresh_tasks, remove_from_working_task, get_user_id,
)
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

from .shared import (
    CMD_SUFFIX, LOGGER, SAVE_TO_DATABASE, TELETHON_CLIENT,
    ask_text, ask_watermark, ask_thumbnail_file, command, dw_file_from_url,
    get_mention, get_sudo_user_id, get_username, owner_checker,
    safe_reply, sudo_user_checker_event, sudo_users, user_auth_checker,
)

# ── Opsional Heroku ───────────────────────────────────────────────────
try:
    from heroku3 import from_key as heroku_from_key
    HEROKU_AVAILABLE = True
except ImportError:
    HEROKU_AVAILABLE = False
    LOGGER.warning("heroku3 tidak terinstall — /herokurestart tidak tersedia")


# ═══════════════════════════════════════════════════════════════════════
#  SYSTEM COMMANDS
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("start")))
async def _startmsg(event):
    text = f"Hai {get_mention(event)}, Saya Aktif! 🎬"
    await event.reply(text, buttons=[
        [Button.url("📢 Channel Resmi", "https://t.me/nik66x")],
        [Button.url("👨‍💻 Developer", "https://t.me/nik66")],
    ])


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("time"),
                                       func=lambda e: sudo_user_checker_event(e)))
async def _timecmd(event):
    await event.reply(f"♻ Bot Aktif Selama **{getbotuptime()}**")


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("stats"),
                                       func=lambda e: sudo_user_checker_event(e)))
async def _stats_msg(event):
    from bot_helper.Others.Helper_Functions import get_host_stats
    await event.reply(str(await get_host_stats()), parse_mode="html")


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("speedtest"),
                                       func=lambda e: sudo_user_checker_event(e)))
async def _speed_test(event):
    chat_id = event.message.chat.id
    reply   = await event.reply("⏳ Menjalankan Tes Kecepatan, Harap Tunggu...")
    # [FIX] speedtest() sekarang return dict — bukan tuple
    result  = await speedtest()
    await reply.delete()
    if result["success"]:
        if result["image_url"]:
            try:
                await TELETHON_CLIENT.send_file(
                    chat_id, file=result["image_url"],
                    caption=result["text"], reply_to=event.message,
                    allow_cache=False, parse_mode="html",
                )
                return
            except Exception:
                pass
        await event.reply(result["text"], parse_mode="html")
    else:
        await event.reply(result["text"])


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("restart"),
                                       func=lambda e: owner_checker(e)))
async def _restart(event):
    chat_id = event.message.chat.id
    reply   = await event.reply("♻ Memulai Ulang...")
    srun(["pkill", "-f", "aria2c|ffmpeg|rclone"])
    srun(["python3", "update.py"])
    with open(".restartmsg", "w") as f:
        f.truncate(0)
        f.write(f"{chat_id}\n{reply.id}\n")
    execl(executable, executable, *argv)


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("herokurestart"),
                                       func=lambda e: owner_checker(e)))
async def _heroku_restart(event):
    if not HEROKU_AVAILABLE:
        await event.reply("❗ heroku3 tidak terinstall.")
        return
    if not (Config.HEROKU_APP_NAME and Config.HEROKU_API_KEY):
        await event.reply("❗ HEROKU_APP_NAME atau HEROKU_API_KEY tidak ditemukan.")
        return
    chat_id    = event.message.chat.id
    heroku_con = heroku_from_key(Config.HEROKU_API_KEY)
    reply      = await event.reply("♻ Memulai Ulang Dyno Heroku...")
    with open(".restartmsg", "w") as f:
        f.truncate(0)
        f.write(f"{chat_id}\n{reply.id}\n")
    for dyno in heroku_con.app(Config.HEROKU_APP_NAME).dynos():
        dyno.restart()


# ═══════════════════════════════════════════════════════════════════════
#  LOG COMMANDS
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("log"),
                                       func=lambda e: sudo_user_checker_event(e)))
async def _log(event):
    user_id  = event.message.sender.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)
    log_file = "Logging.txt"
    if exists(log_file):
        await event.reply(str(get_logs_msg(log_file)))
    else:
        await event.reply("❗ Berkas Log Tidak Ditemukan")


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("logs"),
                                       func=lambda e: sudo_user_checker_event(e)))
async def _logs(event):
    chat_id  = event.message.chat.id
    user_id  = event.message.sender.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)
    log_file = "Logging.txt"
    if exists(log_file):
        try:
            await TELETHON_CLIENT.send_file(chat_id, file=log_file, allow_cache=False)
        except Exception as e:
            await event.reply(str(e))
    else:
        await event.reply("❗ Berkas Log Tidak Ditemukan")


# ═══════════════════════════════════════════════════════════════════════
#  TASK MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("tasklimit"),
                                       func=lambda e: owner_checker(e)))
async def _changetasklimit(event):
    chat_id = event.message.chat.id
    user_id = event.message.sender.id
    limit   = await ask_text(chat_id, user_id, event, 120, "Kirim Batas Tugas Baru", int)
    if limit:
        change_task_limit(int(limit))
        await refresh_tasks()
        await event.reply(f"✅ Batas Tugas Baru: **{get_task_limit()}**")


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("cancel"),
                                       func=lambda e: user_auth_checker(e)))
async def _cancel(event):
    user_id  = event.message.sender.id
    commands = event.message.message.split(" ")
    if len(commands) != 3:
        await safe_reply(event, "❗ Format: `/cancel aria|process <ID>`")
        return

    processx   = commands[1]
    process_id = commands[2]
    owner_id   = Config.OWNER_ID

    try:
        if processx == "aria":
            if dl := getDownloadByGid(process_id):
                if dl.listener().user_id == user_id or user_id == owner_id:
                    await Aria2.cancel_download(process_id)
                    await remove_from_working_task(dl.listener().process_id)
                    await safe_reply(event, "✅ Berhasil Dibatalkan.")
                else:
                    await safe_reply(event, "❗ Anda tidak punya izin membatalkan tugas ini.")
            else:
                await safe_reply(event, "❗ Tidak ada unduhan dengan ID ini.")
            return

        if processx == "process":
            add_uid = get_user_id(process_id)
            if add_uid and (add_uid == user_id or user_id == owner_id):
                ok = await remove_running_process(process_id)
                await remove_from_working_task(process_id)
                await safe_reply(event, "✅ Berhasil Dibatalkan." if ok else "❗ Proses tidak ditemukan.")
            elif user_id == owner_id:
                ok = await remove_running_process(process_id)
                await remove_from_working_task(process_id)
                await safe_reply(event, "✅ Berhasil Dibatalkan." if ok else "❗ Proses tidak ditemukan.")
            else:
                await safe_reply(event, "❗ Anda tidak punya izin membatalkan tugas ini.")

    except Exception as e:
        await safe_reply(event, str(e))


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("ffmpeg"),
                                       func=lambda e: user_auth_checker(e)))
async def _ffmpeg_log(event):
    chat_id  = event.message.chat.id
    commands = event.message.message.split(" ")
    if len(commands) != 3 or commands[1] != "log":
        await safe_reply(event, "❗ Format: `/ffmpeg log <process_id>`")
        return
    process_id = commands[2]
    try:
        log_file = await get_ffmpeg_log_file(process_id)
        if log_file:
            await TELETHON_CLIENT.send_file(chat_id, file=log_file, allow_cache=False)
        else:
            await safe_reply(event, "❗ Berkas Log Tidak Ditemukan")
    except Exception as e:
        await safe_reply(event, str(e))


# ═══════════════════════════════════════════════════════════════════════
#  CONFIG & MEDIA SAVE
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("saveconfig"),
                                       func=lambda e: user_auth_checker(e)))
async def _saverclone(event):
    user_id  = event.message.sender.id
    chat_id  = event.message.chat.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)
    r_config = f"./userdata/{user_id}_rclone.conf"
    text     = (
        "Konfigurasi Rclone Sudah Ada\n\nKirim Konfigurasi Baru untuk Mengganti."
        if exists(r_config)
        else "Konfigurasi Rclone Belum Ada\n\nKirim Konfigurasi untuk Disimpan."
    )
    link = False
    new_event = await ask_media_OR_url_local(event, chat_id, user_id, r_config, text)
    if not new_event:
        return

    if new_event.message.file:
        await new_event.download_media(file=r_config)
    else:
        link = str(new_event.message.message)
        ok = await dw_file_from_url(link, r_config)
        if ok:
            await saveoptions(user_id, "rclone_config_link", link, SAVE_TO_DATABASE)

    if not exists(r_config):
        await safe_reply(new_event, "❌ Gagal Mengunduh Berkas Konfigurasi.")
        return

    accounts = await get_config(r_config)
    if not accounts:
        from bot_helper.Others.Helper_Functions import delete_trash
        await delete_trash(r_config)
        await safe_reply(new_event, "❌ Berkas Konfigurasi Tidak Valid Atau Kosong.")
        return

    await saveoptions(user_id, "drive_name", accounts[0], SAVE_TO_DATABASE)
    if link:
        await saveoptions(user_id, "rclone_config_link", link, SAVE_TO_DATABASE)
    drive = get_data().get(user_id, {}).get("drive_name", accounts[0])
    await safe_reply(new_event,
        f"✅ Konfigurasi Berhasil Disimpan\n\n🔶 Menggunakan Drive **{drive}** untuk Mengunggah.")


async def ask_media_OR_url_local(event, chat_id, user_id, r_config, text):
    """Local wrapper untuk saveconfig."""
    from .shared import ask_media_OR_url
    new_event = await ask_media_OR_url(
        event, chat_id, user_id,
        [f"/saveconfig{CMD_SUFFIX}", "stop"], text, 120, "text/", True, False,
    )
    if new_event and new_event not in ["cancelled", "stopped"]:
        return new_event
    return None


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("savewatermark"),
                                       func=lambda e: user_auth_checker(e)))
async def _savewatermark(event):
    chat_id = event.message.chat.id
    user_id = event.message.sender.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)
    ok = await ask_watermark(event, chat_id, user_id, "savewatermark", False)
    await safe_reply(event, "✅ Watermark berhasil disimpan." if ok else "❗ Gagal Mendapatkan Watermark.")


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("savethumb"),
                                       func=lambda e: user_auth_checker(e)))
async def _savethumb(event):
    chat_id = event.message.chat.id
    user_id = event.message.sender.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)
    ok = await ask_thumbnail_file(event, chat_id, user_id, "savethumb")
    await safe_reply(event, "✅ Thumbnail berhasil disimpan." if ok else "❗ Gagal Mendapatkan Thumbnail.")


# ═══════════════════════════════════════════════════════════════════════
#  ENV & BOT CONFIG
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("changeconfig"),
                                       func=lambda e: owner_checker(e)))
async def _changeconfig(event):
    if not exists("config.env"):
        await safe_reply(event, "❗ Berkas `config.env` Tidak Ditemukan")
        return
    keys = get_env_keys("config.env")
    if not keys:
        await safe_reply(event, "❗ Tidak Ada Variabel Dalam Berkas `config.env`")
        return
    buttons = [[Button.inline(k, f"env_{k}")] for k in keys]
    buttons.append([Button.inline("⭕ Tutup", "close_settings")])
    await event.reply("Pilih Variabel untuk Diubah", buttons=buttons)


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("clearconfigs"),
                                       func=lambda e: owner_checker(e)))
async def _clearconfig(event):
    path = "./userdata/botconfig.env"
    if exists(path):
        remove(path)
        await safe_reply(event, "✅ Berhasil Dihapus")
    else:
        await safe_reply(event, "❗ Konfigurasi Tidak Ditemukan")


# ═══════════════════════════════════════════════════════════════════════
#  SUDO MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("checksudo"),
                                       func=lambda e: owner_checker(e)))
async def _checksudo(event):
    await event.reply(f"**Sudo Users:**\n`{sudo_users}`")


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("addsudo"),
                                       func=lambda e: owner_checker(e)))
async def _addsudo(event):
    chat_id  = event.message.chat.id
    user_id  = event.message.sender.id
    sudo_id  = await get_sudo_user_id(event)
    if not sudo_id:
        sudo_id = await ask_text(chat_id, user_id, event, 120, "Kirim ID Pengguna", int)
        if not sudo_id:
            return
    if sudo_id in sudo_users:
        await safe_reply(event, f"❗ ID sudah ada di Sudo.\n\n`{sudo_users}`")
        return
    sudo_users.append(sudo_id)
    _save_sudo_list()
    await safe_reply(event, f"✅ Berhasil Ditambahkan.\n\n`{sudo_users}`")


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("delsudo"),
                                       func=lambda e: owner_checker(e)))
async def _delsudo(event):
    chat_id  = event.message.chat.id
    user_id  = event.message.sender.id
    sudo_id  = await get_sudo_user_id(event)
    if not sudo_id:
        sudo_id = await ask_text(chat_id, user_id, event, 120, "Kirim ID Pengguna", int)
        if not sudo_id:
            return
    if sudo_id not in sudo_users:
        await safe_reply(event, f"❗ ID Tidak Ditemukan.\n\n`{sudo_users}`")
        return
    sudo_users.remove(sudo_id)
    _save_sudo_list()
    await safe_reply(event, f"✅ Berhasil Dihapus.\n\n`{sudo_users}`")


def _save_sudo_list() -> None:
    """Simpan sudo list ke botconfig.env."""
    if exists("./userdata/botconfig.env"):
        d = get_env_dict("./userdata/botconfig.env") or {}
    elif exists("config.env"):
        d = get_env_dict("config.env") or {}
    else:
        d = {}
    d["SUDO_USERS"] = " ".join(str(u) for u in sudo_users)
    export_env_file("./userdata/botconfig.env", d)


# ═══════════════════════════════════════════════════════════════════════
#  DATABASE & CLEANUP
# ═══════════════════════════════════════════════════════════════════════

@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("resetdb"),
                                       func=lambda e: owner_checker(e)))
async def _resetdb(event):
    await event.reply(
        "*️⃣ Anda yakin?\n\n🚫 Ini akan mereset seluruh basis data 🚫",
        buttons=[
            [Button.inline("Ya 🚫", "resetdb_True")],
            [Button.inline("Tidak 😓", "resetdb_False")],
            [Button.inline("⭕ Tutup", "close_settings")],
        ],
    )


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("renew"),
                                       func=lambda e: owner_checker(e)))
async def _renew(event):
    user_id = event.message.sender.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)
    await event.reply(
        "*️⃣ Anda yakin?\n\n🚫 Ini akan menghapus semua unduhan & watermark lokal 🚫",
        buttons=[
            [Button.inline("Ya 🚫", "renew_True")],
            [Button.inline("Tidak 😓", "renew_False")],
            [Button.inline("⭕ Tutup", "close_settings")],
        ],
    )


@TELETHON_CLIENT.on(events.NewMessage(incoming=True, pattern=command("settings"),
                                       func=lambda e: user_auth_checker(e)))
async def _settings(event):
    user_id = event.message.sender.id
    if user_id not in get_data():
        await new_user(user_id, SAVE_TO_DATABASE)
    await event.reply(
        f"⚙️ Hai {get_mention(event)} — Pilih Pengaturan Anda",
        buttons=[
            [Button.inline("👤 Profil Pengaturan", "profile_main")],
            [Button.inline("🎬 Pengaturan Media",   "settings_media")],
            [Button.inline("🤖 Pengaturan Umum & Tampilan", "settings_bot")],
            [Button.inline("⭕ Tutup Pengaturan", "close_settings")],
        ],
    )
