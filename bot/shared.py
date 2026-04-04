"""
╔══════════════════════════════════════════════════════════════════════╗
║         bot_helper/Handlers/shared.py — v3.1                         ║
║         Shared utilities, helpers, dan base functions (Aiogram)      ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [NEW] Migrasi total ke Aiogram 3.x (Message objects)                ║
║  [NEW] Sistem "Inline Waiter" (_waiters dict) pengganti              ║
║        Telethon conversation untuk tanya-jawab interaktif.           ║
║  [FIX] `message.message` diganti menjadi `message.text`              ║
║  [FIX] `message.file` diganti ke pengecekan document/video/photo     ║
║  [FIX] Inline Button syntax Aiogram                                  ║
║  [FIX] Menambahkan kembali get_sudo_user_id untuk kompatibilitas     ║
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
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

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
LOGGER           = Config.LOGGER
SAVE_TO_DATABASE = Config.SAVE_TO_DATABASE
CMD_SUFFIX       = Config.CMD_SUFFIX
BOT_USERNAME     = Config.BOT_USERNAME
owner_id         = Config.OWNER_ID
sudo_users       = Config.SUDO_USERS
allowed_chats    = Config.ALLOWED_CHATS
auth_chat        = Config.AUTH_GROUP_ID

# ── State ─────────────────────────────────────────────────────────────
status_update      = {}
status_update_lock = Lock()

# Buat direktori userdata jika belum ada
if not isdir("./userdata"):
    makedirs("./userdata")


# ═══════════════════════════════════════════════════════════════════════
#  AIOGRAM INLINE WAITER (PENGGANTI TELETHON CONVERSATION)
# ═══════════════════════════════════════════════════════════════════════
# Dictionary untuk melacak siapa yang sedang ditunggu balasannya
_waiters = {}

async def wait_for_message(chat_id: int, user_id: int, timeout: int) -> Message:
    """Fungsi ajaib pengganti conv.wait_event milik Telethon."""
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    _waiters[(chat_id, user_id)] = fut
    try:
        # Menunggu sampai interceptor memberikan hasil atau timeout
        msg = await asyncio.wait_for(fut, timeout=timeout)
        return msg
    finally:
        _waiters.pop((chat_id, user_id), None)

def resolve_waiter(message: Message) -> bool:
    """Jika fungsi ini mengembalikan True, berarti pesan ditangkap oleh conversation."""
    key = (message.chat.id, message.from_user.id)
    if key in _waiters and not _waiters[key].done():
        _waiters[key].set_result(message)
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════
#  PATTERN BUILDER (TETAP DIPERTAHANKAN JIKA DIBUTUHKAN)
# ═══════════════════════════════════════════════════════════════════════

def command(cmd: str):
    return re.compile(r"[/!.]" + cmd + f"{CMD_SUFFIX}(?:@)?({BOT_USERNAME})?")


# ═══════════════════════════════════════════════════════════════════════
#  AUTH HELPERS
# ═══════════════════════════════════════════════════════════════════════

def get_sudo_user_id() -> list:
    """Mengembalikan daftar ID pengguna yang memiliki akses sudo."""
    return sudo_users

async def user_auth_checker(message: Message) -> bool:
    """Check apakah user boleh menggunakan bot."""
    if message.chat.type == 'private':
        return True
    sender_id = message.from_user.id
    return (
        sender_id in sudo_users
        or sender_id in allowed_chats
        or sender_id == owner_id
        or message.chat.id == auth_chat
    )

def sudo_user_checker_event(message: Message) -> bool:
    return message.from_user.id in sudo_users or message.from_user.id == owner_id

def sudo_user_checker_id(user_id: int) -> bool:
    return user_id in sudo_users or user_id == owner_id

def owner_checker(message: Message) -> bool:
    return message.from_user.id == owner_id

async def is_vip_or_admin(user_id: int) -> bool:
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

async def vip_check(message: Message) -> bool:
    user_id = message.from_user.id
    if await is_vip_or_admin(user_id):
        return True
    await safe_reply(message, _VIP_DENIED_MSG)
    return False


# ═══════════════════════════════════════════════════════════════════════
#  SAFE REPLY
# ═══════════════════════════════════════════════════════════════════════

async def safe_reply(message: Message, text: str, reply_markup=None, parse_mode=None) -> None:
    try:
        kwargs = {}
        if reply_markup:
            kwargs["reply_markup"] = reply_markup
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        await message.reply(text, **kwargs)
    except Exception as e:
        LOGGER.debug(f"safe_reply failed: {e}")

async def safe_edit(message: Message, text: str, reply_markup=None) -> None:
    try:
        kwargs = {}
        if reply_markup:
            kwargs["reply_markup"] = reply_markup
        await message.edit_text(text, **kwargs)
    except Exception as e:
        LOGGER.debug(f"safe_edit failed: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  USER HELPERS
# ═══════════════════════════════════════════════════════════════════════

def get_mention(message: Message) -> str:
    first = message.from_user.first_name
    uid   = message.from_user.id
    return f"[{first}](tg://user?id={uid})"

def get_username(message: Message) -> str | bool:
    un = message.from_user.username
    return un if un else False

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

async def get_link(message: Message):
    custom_file_name = False
    msg_text = message.text or message.caption or ""

    if "|" in msg_text:
        ext_data = msg_text.split("|")
        custom_file_name = str(ext_data[-1]).strip()
        commands = ext_data[0].strip().split(" ")
    else:
        commands = msg_text.split(" ")

    if len(commands) == 2:
        if str(commands[1]).startswith("http") or is_magnet(commands[1]):
            return commands[1], custom_file_name
        return "invalid", custom_file_name

    # Cek jika mereply ke sebuah pesan
    if message.reply_to_message:
        replied_msg = message.reply_to_message
        has_media = replied_msg.document or replied_msg.video or replied_msg.photo
        if not has_media:
            txt = replied_msg.text or replied_msg.caption or ""
            if txt.startswith("http") or is_magnet(txt):
                return txt, custom_file_name
            return "invalid", custom_file_name
        return replied_msg, custom_file_name

    return False, custom_file_name

async def get_custom_name(message: Message) -> str | bool:
    msg_text = message.text or message.caption or ""
    if "|" in msg_text:
        parts = msg_text.split("|")
        return str(parts[-1]).strip()
    return False

async def get_url_from_message(message: Message):
    if message.document or message.video or message.photo:
        return message
    return str(message.text)


# ═══════════════════════════════════════════════════════════════════════
#  CONVERSATION HELPERS (AIOGRAM WAITER IMPLEMENTATION)
# ═══════════════════════════════════════════════════════════════════════

async def ask_text(chat_id, user_id, message: Message, timeout, text_msg, text_type, include_list=False):
    ask = await message.reply(f"*️⃣ {text_msg} [{timeout} detik]")
    try:
        new_msg = await wait_for_message(chat_id, user_id, timeout)
    except asyncio.TimeoutError:
        await safe_edit(ask, "🔃 Waktu Habis! Tugas Telah Dibatalkan.")
        return False
        
    msg_txt = new_msg.text or ""
    try:
        if not include_list:
            return text_type(msg_txt)
        val = text_type(msg_txt)
        if val not in include_list:
            await safe_reply(new_msg, "❌ Input Tidak Valid")
            return False
        return new_msg
    except Exception:
        await safe_reply(new_msg, "❌ Input Tidak Valid")
        return False

async def ask_text_event(chat_id, user_id, message: Message, timeout, text_msg, message_hint=False):
    msg = f"*️⃣ {text_msg} [{timeout} detik]"
    if message_hint:
        msg += f"\n\n{message_hint}"
    ask = await message.reply(msg)
    try:
        return await wait_for_message(chat_id, user_id, timeout)
    except asyncio.TimeoutError:
        await safe_edit(ask, "🔃 Waktu Habis! Tugas Telah Dibatalkan.")
        return False

async def ask_text_list(chat_id, user_id, message: Message, timeout, text_msg, include_list):
    ask = await message.reply(f"*️⃣ {text_msg} [{timeout} detik]")
    try:
        new_msg = await wait_for_message(chat_id, user_id, timeout)
        if (new_msg.text or "") in include_list:
            return new_msg
        await safe_reply(new_msg, "❌ Pilihan tidak valid.")
        return False
    except asyncio.TimeoutError:
        await safe_edit(ask, "🔃 Waktu Habis! Tugas Telah Dibatalkan.")
        return False

async def ask_media_OR_url(
    message: Message, chat_id, user_id, keywords, text_msg, timeout, mtype, s_handle,
    allow_magnet=True, allow_url=True, message_hint=False, allow_command=False, stop_on_url=True,
):
    msg = f"*️⃣ {text_msg} [{timeout} detik]"
    if message_hint:
        msg += f"\n\n{message_hint}"
    ask = await message.reply(msg)
    
    try:
        new_msg = await wait_for_message(chat_id, user_id, timeout)
    except asyncio.TimeoutError:
        await safe_edit(ask, "🔃 Waktu Habis! Tugas Telah Dibatalkan.")
        return False

    has_media = new_msg.document or new_msg.video or new_msg.photo
    if has_media:
        # Cek mime_type jika disyaratkan (hanya berlaku untuk document/video)
        doc = new_msg.document or new_msg.video
        if mtype and doc and doc.mime_type and not doc.mime_type.startswith(mtype):
            await safe_reply(new_msg, f"❗[{doc.mime_type}] Ini bukan berkas yang valid.")
            return False
        return new_msg

    txt = new_msg.text or ""
    if txt == "stop":
        if s_handle:
            await safe_edit(ask, "✅ Tugas Dihentikan")
        return "stopped"
    if txt == "cancel":
        await safe_edit(ask, "✅ Tugas Dibatalkan")
        return "cancelled"
    if txt.startswith("http"):
        if allow_url:
            return new_msg
        await safe_reply(ask, "❌ Tautan HTTP Tidak Diizinkan.")
        return "stopped" if stop_on_url else "pass"
    if is_magnet(txt):
        if allow_magnet:
            return new_msg
        await safe_reply(ask, "❌ Tautan Magnet Tidak Diizinkan.")
        return "stopped" if stop_on_url else "pass"
    if allow_command and txt.startswith("/"):
        await safe_reply(ask, f"❗ Anda sudah memulai tugas {txt}.")
        return "pass"
        
    await safe_reply(ask, f"❌ Input salah atau perintah tertimpa. Kirim ulang perintah {txt}")
    return "cancelled"


async def ask_url(
    message: Message, chat_id, user_id, keywords, text_msg, timeout, s_handle,
    allow_magnet=True, allow_url=True, message_hint=False, allow_command=False, stop_on_url=True,
):
    return await ask_media_OR_url(
        message, chat_id, user_id, keywords, text_msg, timeout, None, s_handle,
        allow_magnet, allow_url, message_hint, allow_command, stop_on_url
    )


async def get_thumbnail(process_status, keywords, timeout) -> None:
    user_id = process_status.user_id
    chat_id = process_status.chat_id
    if not get_data().get(user_id, {}).get("custom_thumbnail"):
        return

    ask = await process_status.event.reply(f"*️⃣ Kirim Thumbnail [{timeout} detik]")
    try:
        new_msg = await wait_for_message(chat_id, user_id, timeout)
    except asyncio.TimeoutError:
        await safe_edit(ask, "🔃 Waktu Habis!")
        return

    has_media = new_msg.document or new_msg.photo
    if has_media:
        target_media = new_msg.photo[-1] if new_msg.photo else new_msg.document
        if new_msg.document and not (new_msg.document.mime_type or "").startswith("image/"):
            await safe_reply(new_msg, "❗ Ini bukan thumbnail yang valid.")
            return
    elif new_msg.text == "pass":
        await safe_edit(ask, "✅ Thumbnail Dilewati")
        return
    else:
        await safe_reply(ask, "❗ Gagal memproses thumbnail.")
        return

    dest_path = f"{process_status.dir}/{process_status.process_id}.jpg"
    await Telegram.AIOGRAM_BOT.download(target_media, destination=dest_path)
    process_status.set_custom_thumbnail(dest_path)


async def ask_watermark(message: Message, chat_id, user_id, cmd, wt_check, all_handle=False) -> bool:
    watermark_path = f"./userdata/{user_id}_watermark.jpg"
    watermark_exists = isfile(watermark_path)

    if watermark_exists and wt_check:
        return True

    text = (
        "Watermark Sudah Ada\n\n🔷 Kirim Gambar Watermark Baru untuk Mengganti."
        if watermark_exists
        else "Watermark Belum Ada\n\n🔶 Kirim Gambar Watermark untuk Disimpan."
    )
    new_msg = await ask_media_OR_url(
        message, chat_id, user_id, [f"/{cmd}{CMD_SUFFIX}", "stop"], text, 120, "image/", True, False, False,
    )
    if new_msg and new_msg not in ["cancelled", "stopped"]:
        target_media = new_msg.photo[-1] if new_msg.photo else new_msg.document
        await Telegram.AIOGRAM_BOT.download(target_media, destination=watermark_path)
        if isfile(watermark_path):
            return True
            
    if all_handle and new_msg:
        await safe_reply(new_msg, "❗ Gagal Mendapatkan Watermark.")
    return False


async def ask_thumbnail_file(message: Message, chat_id, user_id, cmd) -> bool:
    thumb_path = f"./userdata/{user_id}_Thumbnail.jpg"
    text = (
        "Thumbnail Sudah Ada\n\n🔷 Kirim Thumbnail Baru untuk Mengganti."
        if isfile(thumb_path)
        else "Thumbnail Belum Ada\n\n🔶 Kirim Thumbnail untuk Disimpan."
    )
    new_msg = await ask_media_OR_url(
        message, chat_id, user_id, [f"/{cmd}{CMD_SUFFIX}", "stop"], text, 120, "image/", True, False, False,
    )
    if new_msg and new_msg not in ["cancelled", "stopped"]:
        target_media = new_msg.photo[-1] if new_msg.photo else new_msg.document
        await Telegram.AIOGRAM_BOT.download(target_media, destination=thumb_path)
        if isfile(thumb_path):
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════
#  TASK BUILDER HELPER
# ═══════════════════════════════════════════════════════════════════════

def build_task(process_status: ProcessStatus, link) -> dict:
    task = {"process_status": process_status, "functions": []}
    if isinstance(link, str):
        task["functions"].append([
            "Aria", Aria2.add_aria2c_download, [link, process_status, False, False, False, False],
        ])
    else:
        task["functions"].append(["TG", [link]])
    return task

async def submit_task(task: dict) -> None:
    create_task(add_task(task))

def finalize_multi_tasks(process_status: ProcessStatus) -> None:
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

async def update_status_message(message: Message) -> None:
    reply   = await message.reply("⏳ Harap Tunggu")
    chat_id = message.chat.id
    user_id = message.from_user.id

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

    # Tombol Inline Aiogram
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭕ Tutup", callback_data="close_settings")]
    ])

    while True:
        status_message = await get_status_message(reply)
        if not status_message:
            await safe_edit(reply, _idle_text(), reply_markup=keyboard)
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
            await reply.edit_text(status_message, reply_markup=keyboard)
        except TelegramBadRequest: # Aiogram exception jika edit pesan tidak berubah
            pass
        except Exception as e:
            LOGGER.debug(f"status update error: {e}")
            break

        await asyncio.sleep(user_cfg.get("update_time", 7))

    LOGGER.info("Status update selesai")
