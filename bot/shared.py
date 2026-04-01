"""
╔══════════════════════════════════════════════════════════════════════╗
║         bot_helper/Handlers/shared.py — v3.1                        ║
║         Shared utilities, helpers, dan base functions               ║
╠══════════════════════════════════════════════════════════════════════╣
║  Berisi semua helper yang dipakai bersama oleh semua handler:       ║
║  - VIP/auth checks                                                  ║
║  - Task builder helper                                              ║
║  - safe_reply, command pattern                                      ║
║  - Conversation helpers (ask_text, ask_media, dll)                  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import re
from asyncio import Lock, create_task
from datetime import datetime
from os import makedirs
from os.path import isdir, isfile
from re import findall
from shutil import rmtree
from time import time

# ── Third Party ───────────────────────────────────────────────────────
import requests as _requests
from telethon import Button, events
from telethon.errors.rpcerrorlist import MessageIdInvalidError

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Aria2.Aria2_Engine import Aria2
from bot_helper.Database.User_Data import (
    get_data, get_fresh_user_data, new_user,
    ensure_user_data_structure, get_task_limit,
)
from bot_helper.Others.Helper_Functions import (
    botStartTime, gen_random_string, get_current_time,
    get_human_size, get_readable_time,
)
from bot_helper.Others.Names import Names
from bot_helper.Process.Process_Status import ProcessStatus
from bot_helper.Process.Running_Tasks import (
    add_task, get_queued_tasks_len, get_status_message,
)
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config
from psutil import cpu_percent, disk_usage, virtual_memory

# ── Konstanta ─────────────────────────────────────────────────────────
LOGGER          = Config.LOGGER
SAVE_TO_DATABASE = Config.SAVE_TO_DATABASE
CMD_SUFFIX      = Config.CMD_SUFFIX
BOT_USERNAME    = Config.BOT_USERNAME
owner_id        = Config.OWNER_ID
sudo_users      = Config.SUDO_USERS
allowed_chats   = Config.ALLOWED_CHATS
auth_chat       = Config.AUTH_GROUP_ID
TELETHON_CLIENT = Telegram.TELETHON_CLIENT

# ── State ─────────────────────────────────────────────────────────────
status_update      = {}
status_update_lock = Lock()

# Buat direktori userdata jika belum ada
if not isdir("./userdata"):
    makedirs("./userdata")


# ═══════════════════════════════════════════════════════════════════════
#  PATTERN BUILDER
# ═══════════════════════════════════════════════════════════════════════

def command(cmd: str):
    """Build regex pattern untuk command handler dengan CMD_SUFFIX."""
    return re.compile(r"[/!.]" + cmd + f"{CMD_SUFFIX}(?:@)?({BOT_USERNAME})?")


# ═══════════════════════════════════════════════════════════════════════
#  AUTH HELPERS
# ═══════════════════════════════════════════════════════════════════════

def user_auth_checker(event) -> bool:
    """
    Check apakah user boleh menggunakan bot.
    PM: semua user boleh (VIP check di dalam handler).
    Grup: hanya sudo/owner/auth_chat.
    """
    if event.is_private:
        return True
    sender_id = event.message.sender.id
    return (
        sender_id in sudo_users
        or sender_id in allowed_chats
        or sender_id == owner_id
        or event.chat_id == auth_chat
    )


def sudo_user_checker_event(event) -> bool:
    return event.message.sender.id in sudo_users or event.message.sender.id == owner_id


def sudo_user_checker_id(user_id: int) -> bool:
    return user_id in sudo_users or user_id == owner_id


def owner_checker(event) -> bool:
    return event.message.sender.id == owner_id


async def is_vip_or_admin(user_id: int) -> bool:
    """
    Check VIP/admin status user.
    [FIX] Bare except → typed exception + LOGGER.debug
    """
    if user_id == owner_id or user_id in sudo_users:
        return True

    user_data = await get_fresh_user_data(user_id)
    if not user_data:
        return False

    expiry_str = user_data.get("premium_expiry_date")
    if expiry_str:
        try:
            expiry = datetime.fromisoformat(str(expiry_str))
            if expiry > datetime.now():
                return True
        except (ValueError, TypeError) as e:
            LOGGER.debug(f"is_vip_or_admin parse error user={user_id}: {e}")

    return False


_VIP_DENIED_MSG = (
    "❗ **Akses Ditolak** ❗\n\n"
    "Perintah ini khusus untuk pengguna **VIP**.\n"
    "Silakan donasi dan verifikasi via `/verify` untuk mendapatkan akses."
)


async def vip_check(event) -> bool:
    """Return True jika user boleh lanjut, False + reply jika tidak."""
    user_id = event.message.sender.id
    if await is_vip_or_admin(user_id):
        return True
    await safe_reply(event, _VIP_DENIED_MSG)
    return False


# ═══════════════════════════════════════════════════════════════════════
#  SAFE REPLY
# ═══════════════════════════════════════════════════════════════════════

async def safe_reply(event_or_msg, text: str, buttons=None, parse_mode=None) -> None:
    """
    Reply tanpa crash jika message expired/deleted.
    [NEW] Helper yang dipakai semua handler.
    """
    try:
        kwargs = {}
        if buttons:
            kwargs["buttons"] = buttons
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        await event_or_msg.reply(text, **kwargs)
    except Exception as e:
        LOGGER.debug(f"safe_reply failed: {e}")


async def safe_edit(msg, text: str, buttons=None) -> None:
    """Edit message tanpa crash."""
    try:
        kwargs = {}
        if buttons:
            kwargs["buttons"] = buttons
        await msg.edit(text, **kwargs)
    except Exception as e:
        LOGGER.debug(f"safe_edit failed: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  USER HELPERS
# ═══════════════════════════════════════════════════════════════════════

def get_mention(event) -> str:
    first = event.message.sender.first_name
    uid   = event.message.sender.id
    return f"[{first}](tg://user?id={uid})"


def get_username(event) -> str | bool:
    try:
        un = event.message.sender.username
        return un if un else False
    except Exception:
        return False


def is_magnet(url: str) -> bool:
    return bool(findall(r"magnet:\?xt=urn:btih:[a-zA-Z0-9]*", url))


def create_direc(direc: str) -> None:
    if not isdir(direc):
        makedirs(direc)


def check_file(loc: str, file_name: str) -> str:
    if isfile(f"{loc}/{file_name}"):
        return f"{loc}/{gen_random_string(5)}_{file_name}"
    return f"{loc}/{file_name}"


# ═══════════════════════════════════════════════════════════════════════
#  ASYNC FILE DOWNLOAD
# ═══════════════════════════════════════════════════════════════════════

async def dw_file_from_url(url: str, filename: str) -> bool:
    """
    Download file dari URL ke disk.
    [FIX] Async via asyncio.to_thread — tidak block event loop.
    """
    def _download():
        r = _requests.get(url, allow_redirects=True, stream=True, timeout=30)
        r.raise_for_status()
        with open(filename, "wb") as fd:
            for chunk in r.iter_content(chunk_size=1024 * 10):
                if chunk:
                    fd.write(chunk)

    try:
        await asyncio.to_thread(_download)
        return True
    except Exception as e:
        LOGGER.error(f"dw_file_from_url error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════
#  LINK PARSER
# ═══════════════════════════════════════════════════════════════════════

async def get_link(event):
    """
    Parse link atau file dari command event.

    Returns:
        (link_or_event, custom_file_name)
        link = "invalid" | False | str URL | message_object
    """
    custom_file_name = False
    msg = event.message.message

    if "|" in msg:
        ext_data = msg.split("|")
        custom_file_name = str(ext_data[-1]).strip()
        commands = ext_data[0].strip().split(" ")
    else:
        commands = msg.split(" ")

    if len(commands) == 2:
        if str(commands[1]).startswith("http") or is_magnet(commands[1]):
            return commands[1], custom_file_name
        return "invalid", custom_file_name

    if event.reply_to_msg_id:
        msg_object = await TELETHON_CLIENT.get_messages(
            event.message.chat.id, ids=event.reply_to_msg_id
        )
        if not msg_object.file:
            txt = str(msg_object.message)
            if txt.startswith("http") or is_magnet(txt):
                return txt, custom_file_name
            return "invalid", custom_file_name
        return msg_object, custom_file_name

    return False, custom_file_name


async def get_custom_name(event) -> str | bool:
    if "|" in event.message.message:
        parts = event.message.message.split("|")
        return str(parts[-1]).strip()
    return False


async def get_url_from_message(new_event):
    if new_event.message.file:
        return new_event
    return str(new_event.message.message)


async def get_sudo_user_id(event) -> int | bool:
    if event.reply_to_msg_id:
        reply = await TELETHON_CLIENT.get_messages(
            event.message.chat.id, ids=event.reply_to_msg_id
        )
        return reply.from_id.user_id
    return False


# ═══════════════════════════════════════════════════════════════════════
#  CONVERSATION HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def ask_text(chat_id, user_id, event, timeout, message, text_type, include_list=False):
    """Tanya input teks dari user, opsional validasi type dan list."""
    async with TELETHON_CLIENT.conversation(chat_id) as conv:
        handle = conv.wait_event(
            events.NewMessage(chats=chat_id, incoming=True, from_users=[user_id],
                              func=lambda e: e.message.message),
            timeout=timeout,
        )
        ask = await event.reply(f"*️⃣ {message} [{timeout} detik]")
        try:
            new_event = await handle
        except Exception as e:
            await safe_edit(ask, "🔃 Waktu Habis! Tugas Telah Dibatalkan.")
            LOGGER.debug(f"ask_text timeout: {e}")
            return False
        try:
            if not include_list:
                return text_type(new_event.message.message)
            val = text_type(new_event.message.message)
            if val not in include_list:
                await safe_reply(new_event, "❌ Input Tidak Valid")
                return False
            return new_event
        except Exception:
            await safe_reply(new_event, "❌ Input Tidak Valid")
            return False


async def ask_text_event(chat_id, user_id, event, timeout, message, message_hint=False):
    """Tanya input teks, return message event (bukan parsed value)."""
    async with TELETHON_CLIENT.conversation(chat_id) as conv:
        handle = conv.wait_event(
            events.NewMessage(chats=chat_id, incoming=True, from_users=[user_id],
                              func=lambda e: e.message.message),
            timeout=timeout,
        )
        msg = f"*️⃣ {message} [{timeout} detik]"
        if message_hint:
            msg += f"\n\n{message_hint}"
        ask = await event.reply(msg)
        try:
            return await handle
        except Exception as e:
            await safe_edit(ask, "🔃 Waktu Habis! Tugas Telah Dibatalkan.")
            LOGGER.debug(f"ask_text_event timeout: {e}")
            return False


async def ask_text_list(chat_id, user_id, event, timeout, message, include_list):
    """Tanya user dengan list valid responses."""
    async with TELETHON_CLIENT.conversation(chat_id) as conv:
        handle = conv.wait_event(
            events.NewMessage(chats=chat_id, incoming=True, from_users=[user_id],
                              func=lambda e: str(e.message.message) in include_list),
            timeout=timeout,
        )
        ask = await event.reply(f"*️⃣ {message} [{timeout} detik]")
        try:
            return await handle
        except Exception as e:
            await safe_edit(ask, "🔃 Waktu Habis! Tugas Telah Dibatalkan.")
            LOGGER.debug(f"ask_text_list timeout: {e}")
            return False


async def ask_media_OR_url(
    event, chat_id, user_id, keywords, message, timeout, mtype, s_handle,
    allow_magnet=True, allow_url=True, message_hint=False, allow_command=False, stop_on_url=True,
):
    """Tunggu media atau URL dari user."""
    async with TELETHON_CLIENT.conversation(chat_id) as conv:
        handle = conv.wait_event(
            events.NewMessage(
                chats=chat_id, incoming=True, from_users=[user_id],
                func=lambda e: (
                    e.message.file
                    or str(e.message.message) in keywords
                    or str(e.message.message).startswith("http")
                ),
            ),
            timeout=timeout,
        )
        msg = f"*️⃣ {message} [{timeout} detik]"
        if message_hint:
            msg += f"\n\n{message_hint}"
        ask = await event.reply(msg)
        try:
            new_event = await handle
        except Exception:
            await safe_edit(ask, "🔃 Waktu Habis! Tugas Telah Dibatalkan.")
            return False

        if new_event.message.file:
            if mtype and not str(new_event.message.file.mime_type).startswith(mtype):
                await safe_reply(new_event,
                    f"❗[{new_event.message.file.mime_type}] Ini bukan berkas yang valid.")
                return False
            return new_event

        txt = str(new_event.message.message)
        if txt == "stop":
            if s_handle:
                await safe_edit(ask, "✅ Tugas Dihentikan")
            return "stopped"
        if txt == "cancel":
            await safe_edit(ask, "✅ Tugas Dibatalkan")
            return "cancelled"
        if txt.startswith("http"):
            if allow_url:
                return new_event
            await safe_reply(ask, "❌ Tautan HTTP Tidak Diizinkan.")
            return "stopped" if stop_on_url else "pass"
        if is_magnet(txt):
            if allow_magnet:
                return new_event
            await safe_reply(ask, "❌ Tautan Magnet Tidak Diizinkan.")
            return "stopped" if stop_on_url else "pass"
        if allow_command:
            await safe_reply(ask, f"❗ Anda sudah memulai tugas {txt.replace('/', '')}.")
            return "pass"
        await safe_reply(ask,
            f"❌ Anda sudah memulai tugas {txt.replace('/', '')}. Kirim ulang perintah {txt}")
        return "cancelled"


async def ask_url(
    event, chat_id, user_id, keywords, message, timeout, s_handle,
    allow_magnet=True, allow_url=True, message_hint=False, allow_command=False, stop_on_url=True,
):
    """Tunggu URL atau magnet dari user."""
    async with TELETHON_CLIENT.conversation(chat_id) as conv:
        handle = conv.wait_event(
            events.NewMessage(
                chats=chat_id, incoming=True, from_users=[user_id],
                func=lambda e: (
                    str(e.message.message) in keywords
                    or str(e.message.message).startswith("http")
                    or is_magnet(str(e.message.message))
                ),
            ),
            timeout=timeout,
        )
        msg = f"*️⃣ {message} [{timeout} detik]"
        if message_hint:
            msg += f"\n\n{message_hint}"
        ask = await event.reply(msg)
        try:
            new_event = await handle
        except Exception:
            await safe_edit(ask, "🔃 Waktu Habis! Tugas Telah Dibatalkan.")
            return False

        txt = str(new_event.message.message)
        if txt == "stop":
            if s_handle:
                await safe_edit(ask, "✅ Tugas Dihentikan")
            return "stopped"
        if txt == "cancel":
            await safe_edit(ask, "✅ Tugas Dibatalkan")
            return "cancelled"
        if txt.startswith("http"):
            if allow_url:
                return new_event
            await safe_reply(ask, "❌ Tautan HTTP Tidak Diizinkan.")
            return "stopped" if stop_on_url else "pass"
        if is_magnet(txt):
            if allow_magnet:
                return new_event
            await safe_reply(ask, "❌ Tautan Magnet Tidak Diizinkan.")
            return "stopped" if stop_on_url else "pass"
        if allow_command:
            await safe_reply(ask, f"❗ Anda sudah memulai tugas {txt.replace('/', '')}.")
            return "pass"
        await safe_reply(ask,
            f"❌ Anda sudah memulai tugas {txt.replace('/', '')}. Kirim ulang perintah {txt}")
        return "cancelled"


async def get_thumbnail(process_status, keywords, timeout) -> None:
    """Tanya thumbnail jika user punya custom_thumbnail aktif."""
    user_id = process_status.user_id
    if not get_data().get(user_id, {}).get("custom_thumbnail"):
        return

    async with TELETHON_CLIENT.conversation(process_status.chat_id) as conv:
        handle = conv.wait_event(
            events.NewMessage(
                chats=process_status.chat_id, incoming=True, from_users=[user_id],
                func=lambda e: e.message.media or str(e.message.message) in keywords,
            ),
            timeout=timeout,
        )
        ask = await process_status.event.reply(f"*️⃣ Kirim Thumbnail [{timeout} detik]")
        try:
            new_event = await handle
        except Exception as e:
            await safe_edit(ask, "🔃 Waktu Habis!")
            LOGGER.debug(f"get_thumbnail timeout: {e}")
            return

        if new_event.message.media:
            mime = str(new_event.message.file.mime_type)
            if not mime.startswith("image/"):
                await safe_reply(new_event, f"❗[{mime}] Ini bukan thumbnail yang valid.")
                return
        elif new_event.message.message == "pass":
            await safe_edit(ask, "✅ Thumbnail Dilewati")
            return
        else:
            await safe_reply(ask,
                f"❗ Kirim ulang perintah {str(new_event.message.message)}")
            return

        custom_thumb = await new_event.download_media(
            file=f"{process_status.dir}/{process_status.process_id}.jpg"
        )
        process_status.set_custom_thumbnail(custom_thumb)


async def ask_watermark(event, chat_id, user_id, cmd, wt_check, all_handle=False) -> bool:
    """Ask atau verify watermark image."""
    watermark_path = f"./userdata/{user_id}_watermark.jpg"
    watermark_exists = isfile(watermark_path)

    if watermark_exists and wt_check:
        return True

    text = (
        "Watermark Sudah Ada\n\n🔷 Kirim Gambar Watermark Baru untuk Mengganti."
        if watermark_exists
        else "Watermark Belum Ada\n\n🔶 Kirim Gambar Watermark untuk Disimpan."
    )
    new_event = await ask_media_OR_url(
        event, chat_id, user_id,
        [f"/{cmd}{CMD_SUFFIX}", "stop"], text, 120, "image/", True, False, False,
    )
    if new_event and new_event not in ["cancelled", "stopped"]:
        await TELETHON_CLIENT.download_media(new_event.message, watermark_path)
        if isfile(watermark_path):
            return True
    if all_handle and new_event:
        await safe_reply(new_event, "❗ Gagal Mendapatkan Watermark.")
    return False


async def ask_thumbnail_file(event, chat_id, user_id, cmd) -> bool:
    """Simpan thumbnail user."""
    thumb_path = f"./userdata/{user_id}_Thumbnail.jpg"
    text = (
        "Thumbnail Sudah Ada\n\n🔷 Kirim Thumbnail Baru untuk Mengganti."
        if isfile(thumb_path)
        else "Thumbnail Belum Ada\n\n🔶 Kirim Thumbnail untuk Disimpan."
    )
    new_event = await ask_media_OR_url(
        event, chat_id, user_id,
        [f"/{cmd}{CMD_SUFFIX}", "stop"], text, 120, "image/", True, False, False,
    )
    if new_event and new_event not in ["cancelled", "stopped"]:
        await TELETHON_CLIENT.download_media(new_event.message, thumb_path)
        if isfile(thumb_path):
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════
#  TASK BUILDER HELPER
# ═══════════════════════════════════════════════════════════════════════

def build_task(process_status: ProcessStatus, link) -> dict:
    """
    [NEW] Helper terpusat untuk build task dict — menggantikan duplikasi
    di 15+ handler.

    Args:
        process_status: ProcessStatus object
        link: str URL, magnet string, atau Telethon message object

    Returns:
        task dict siap dipakai dengan add_task()
    """
    task = {"process_status": process_status, "functions": []}
    if isinstance(link, str):
        task["functions"].append([
            "Aria",
            Aria2.add_aria2c_download,
            [link, process_status, False, False, False, False],
        ])
    else:
        task["functions"].append(["TG", [link]])
    return task


async def submit_task(task: dict) -> None:
    """Submit task ke queue system."""
    create_task(add_task(task))


def finalize_multi_tasks(process_status: ProcessStatus) -> None:
    """
    Sort multi_tasks sehingga Convert selalu paling akhir
    (pola yang sama di semua media handler).
    """
    tasks = process_status.multi_tasks
    final_non_convert = [t for t in tasks if t.process_type != Names.convert]
    final_convert     = [t for t in tasks if t.process_type == Names.convert]
    ordered = final_non_convert + final_convert

    process_status.replace_multi_tasks(ordered)
    total = len(ordered) + 1
    process_status.change_multi_tasks_no(total)
    for t in ordered:
        t.change_multi_tasks_no(total)


# ═══════════════════════════════════════════════════════════════════════
#  STATUS MESSAGE
# ═══════════════════════════════════════════════════════════════════════

async def update_status_message(event) -> None:
    """
    Tampilkan dan update status pesan secara live.
    [FIX] Duplikasi antara update_status_message() dan _status() dihapus
          — cukup satu fungsi ini yang dipakai keduanya.
    """
    reply   = await event.reply("⏳ Harap Tunggu")
    chat_id = event.message.chat.id
    user_id = event.message.sender.id

    status_update_id = gen_random_string(5)
    async with status_update_lock:
        if chat_id not in status_update:
            status_update[chat_id] = {}
        status_update[chat_id].clear()
        status_update[chat_id]["update_id"] = status_update_id

    await asyncio.sleep(2)

    def _idle_text() -> str:
        return (
            f"Tidak Ada Proses Berjalan!\n\n"
            f"**CPU:** {cpu_percent()}% | **BEBAS:** {get_human_size(disk_usage('/').free)}\n"
            f"**RAM:** {virtual_memory().percent}% | **AKTIF:** {get_readable_time(time() - botStartTime)}\n"
            f"**ANTRIAN:** {get_queued_tasks_len()} | **BATAS TUGAS:** {get_task_limit()}"
        )

    while True:
        status_message = await get_status_message(reply)
        if not status_message:
            await safe_edit(reply, _idle_text())
            break

        if status_update.get(chat_id, {}).get("update_id") != status_update_id:
            await reply.delete()
            break

        user_cfg = get_data().get(user_id, {})
        if user_cfg.get("show_stats"):
            status_message += (
                f"**CPU:** {cpu_percent()}% | **BEBAS:** {get_human_size(disk_usage('/').free)}\n"
                f"**RAM:** {virtual_memory().percent}% | "
                f"**AKTIF:** {get_readable_time(time() - botStartTime)}\n"
            )
        if user_cfg.get("show_time"):
            status_message += f"**Waktu Saat Ini:** {get_current_time()}\n"
        status_message += f"**ANTRIAN:** {get_queued_tasks_len()} | **BATAS TUGAS:** {get_task_limit()}"

        try:
            await reply.edit(
                status_message,
                buttons=[[Button.inline("⭕ Tutup", "close_settings")]],
            )
        except MessageIdInvalidError:
            break
        except Exception as e:
            LOGGER.debug(f"status update error: {e}")

        await asyncio.sleep(user_cfg.get("update_time", 7))

    LOGGER.info("Status update selesai")
