"""
╔══════════════════════════════════════════════════════════════════════╗
║       bot/admin_handlers.py — v3.3                                   ║
║       Admin & System Command Handlers (Aiogram 3.x)                  ║
╠══════════════════════════════════════════════════════════════════════╣
║  Commands: /start /time /restart /herokurestart /log /logs           ║
║            /stats /speedtest /tasklimit /cancel /ffmpeg              ║
║            /saveconfig /savewatermark /savethumb /changeconfig       ║
║            /clearconfigs /checksudo /addsudo /delsudo /renew         ║
║            /resetdb /changeconfig /settings                          ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG:                                                          ║
║  [UX PREMIUM] Menerapkan Reply Keyboard Singkat ("✅ Ya", "❌ Batal")║
║  [UX PREMIUM] Menerapkan Auto-Delete agar chat tetap bersih & rapi.  ║
║  [UX PREMIUM] Menerapkan Kotak Konfirmasi (Summary Box) pada fitur   ║
║                krusial seperti /resetdb, /renew, dan /saveconfig.    ║
║  [FIX HIGH] Implementasi CMD_SUFFIX pada semua dekorator Command     ║
║  [FIX HIGH] Gunakan asyncio.to_thread pada subprocess srun (restart) ║
║  [FIX HIGH] Memperbaiki error parse_mode pada perintah /log          ║
║  [UPDATE] Konsistensi UI, Ikon, Timeout, dan Batal selaras 100%.     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
from os import execl, remove
from os.path import exists
from subprocess import run as srun
from sys import argv, executable

# ── Aiogram ───────────────────────────────────────────────────────────
from aiogram import Router
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Aria2.Aria2_Engine import Aria2, getDownloadByGid
from bot_helper.Database.User_Data import (
    get_data, new_user, change_task_limit, get_task_limit,
    saveoptions, ensure_user_data_structure, resetdatabase
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
    CMD_SUFFIX, LOGGER, SAVE_TO_DATABASE,
    ask_watermark, ask_thumbnail_file, dw_file_from_url,
    get_mention, get_username, owner_checker,
    safe_reply, sudo_user_checker_event, sudo_users, user_auth_checker,
    wait_for_message
)

# ── Opsional Heroku ───────────────────────────────────────────────────
try:
    from heroku3 import from_key as heroku_from_key
    HEROKU_AVAILABLE = True
except ImportError:
    HEROKU_AVAILABLE = False
    LOGGER.warning("heroku3 tidak terinstall — /herokurestart tidak tersedia")

# Inisialisasi Router Aiogram
router = Router()

# ═══════════════════════════════════════════════════════════════════════
#  UI & CLEANUP HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def _clean_msgs(*msgs):
    """Menghapus pesan untuk menjaga chat tetap rapi."""
    for m in msgs:
        if m:
            try: await m.delete()
            except Exception: pass

def _make_reply_kb(options: list, row_width: int = 2) -> ReplyKeyboardMarkup:
    """Membuat Reply Keyboard dengan mudah."""
    kb = []
    row = []
    for opt in options:
        row.append(KeyboardButton(text=opt))
        if len(row) == row_width:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)

async def get_sudo_user_id(message: Message) -> int | bool:
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id
    return False


# ═══════════════════════════════════════════════════════════════════════
#  SYSTEM COMMANDS
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"start{CMD_SUFFIX}"))
async def _startmsg(message: Message):
    text = f"Hai {get_mention(message)}, Saya Aktif! 🎬"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Channel Resmi", url="https://t.me/nik66x")],
        [InlineKeyboardButton(text="👨‍💻 Developer", url="https://t.me/nik66")],
    ])
    await message.reply(text, reply_markup=kb)


@router.message(Command(f"time{CMD_SUFFIX}"))
async def _timecmd(message: Message):
    if not sudo_user_checker_event(message): return
    await message.reply(f"♻ Bot Aktif Selama **{getbotuptime()}**")


@router.message(Command(f"stats{CMD_SUFFIX}"))
async def _stats_msg(message: Message):
    if not sudo_user_checker_event(message): return
    from bot_helper.Others.Helper_Functions import get_host_stats
    await message.reply(str(await get_host_stats()), parse_mode="HTML")


@router.message(Command(f"speedtest{CMD_SUFFIX}"))
async def _speed_test(message: Message):
    if not sudo_user_checker_event(message): return
    reply = await message.reply("⏳ Menjalankan Tes Kecepatan, Harap Tunggu...")
    try:
        result = await speedtest()
        await reply.delete()
        if result["success"]:
            if result["image_url"]:
                try:
                    await message.reply_photo(photo=result["image_url"], caption=result["text"], parse_mode="HTML")
                    return
                except Exception: pass
            await message.reply(result["text"], parse_mode="HTML")
        else:
            await message.reply(result["text"])
    except Exception as e:
        await reply.edit_text(f"❌ **Gagal menjalankan Speedtest.**\nError: `{e}`\n\n💡 Pastikan modul `speedtest-cli` sudah terinstal di server Anda.")


@router.message(Command(f"restart{CMD_SUFFIX}"))
async def _restart(message: Message):
    if not owner_checker(message): return
    chat_id = message.chat.id
    reply   = await message.reply("♻ Memulai Ulang...")
    await asyncio.to_thread(srun, ["pkill", "-f", "aria2c|ffmpeg|rclone"])
    await asyncio.to_thread(srun, ["python3", "update.py"])
    with open(".restartmsg", "w") as f:
        f.truncate(0)
        f.write(f"{chat_id}\n{reply.message_id}\n")
    execl(executable, executable, *argv)


@router.message(Command(f"herokurestart{CMD_SUFFIX}"))
async def _heroku_restart(message: Message):
    if not owner_checker(message): return
    if not HEROKU_AVAILABLE:
        return await message.reply("❗ heroku3 tidak terinstall.")
    if not (Config.HEROKU_APP_NAME and Config.HEROKU_API_KEY):
        return await message.reply("❗ HEROKU_APP_NAME atau HEROKU_API_KEY tidak ditemukan.")
    chat_id    = message.chat.id
    heroku_con = heroku_from_key(Config.HEROKU_API_KEY)
    reply      = await message.reply("♻ Memulai Ulang Dyno Heroku...")
    with open(".restartmsg", "w") as f:
        f.truncate(0)
        f.write(f"{chat_id}\n{reply.message_id}\n")
    for dyno in heroku_con.app(Config.HEROKU_APP_NAME).dynos():
        dyno.restart()


# ═══════════════════════════════════════════════════════════════════════
#  LOG COMMANDS
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"log{CMD_SUFFIX}"))
async def _log(message: Message):
    if not sudo_user_checker_event(message): return
    user_id = message.from_user.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)
    log_file = "Logging.txt"
    if exists(log_file): 
        # [FIX] Matikan parse_mode dan batasi teks agar Telegram tidak error
        log_text = str(get_logs_msg(log_file))
        if len(log_text) > 4000:
            log_text = log_text[-4000:] # Batas aman Telegram
        await message.reply(log_text, parse_mode=None)
    else: 
        await message.reply("❗ Berkas Log Tidak Ditemukan")


@router.message(Command(f"logs{CMD_SUFFIX}"))
async def _logs(message: Message):
    if not sudo_user_checker_event(message): return
    chat_id, user_id = message.chat.id, message.from_user.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)
    log_file = "Logging.txt"
    if exists(log_file):
        try: await Telegram.AIOGRAM_BOT.send_document(chat_id, document=FSInputFile(log_file))
        except Exception as e: await message.reply(f"❌ Error: {e}")
    else:
        await message.reply("❗ Berkas Log Tidak Ditemukan")


# ═══════════════════════════════════════════════════════════════════════
#  TASK MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"tasklimit{CMD_SUFFIX}"))
async def _changetasklimit(message: Message):
    if not owner_checker(message): return
    chat_id, user_id = message.chat.id, message.from_user.id
    
    kb = _make_reply_kb(["❌ Batal"], 1)
    ask_msg = await message.reply("🔢 Kirim Batas Tugas Baru (Angka):", reply_markup=kb)
    resp = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ask_msg, resp)
    
    if not resp:
        return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    
    if "batal" in (resp.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    if not (resp.text or "").isdigit():
        return await message.answer("❌ Harap kirimkan angka yang valid.", reply_markup=ReplyKeyboardRemove())

    limit = int(resp.text)
    change_task_limit(limit)
    await refresh_tasks()
    await message.answer(f"✅ Batas Tugas Baru: **{get_task_limit()}**", reply_markup=ReplyKeyboardRemove())


@router.message(Command(f"cancel{CMD_SUFFIX}"))
async def _cancel(message: Message):
    if not await user_auth_checker(message): return
    user_id  = message.from_user.id
    commands = (message.text or "").split(" ")
    if len(commands) != 3:
        return await safe_reply(message, f"❗ Format: `/cancel{CMD_SUFFIX} aria|process <ID>`")

    processx, process_id, owner_id = commands[1], commands[2], Config.OWNER_ID

    try:
        if processx == "aria":
            if dl := getDownloadByGid(process_id):
                if dl.listener().user_id == user_id or user_id == owner_id:
                    await Aria2.cancel_download(process_id)
                    await remove_from_working_task(dl.listener().process_id)
                    await safe_reply(message, "✅ Berhasil Dibatalkan.")
                else: await safe_reply(message, "❗ Anda tidak punya izin membatalkan tugas ini.")
            else: await safe_reply(message, "❗ Tidak ada unduhan dengan ID ini.")
            return

        if processx == "process":
            add_uid = get_user_id(process_id)
            if add_uid == user_id or user_id == owner_id:
                ok = await remove_running_process(process_id)
                await remove_from_working_task(process_id)
                await safe_reply(message, "✅ Berhasil Dibatalkan." if ok else "❗ Proses tidak ditemukan.")
            else: await safe_reply(message, "❗ Anda tidak punya izin membatalkan tugas ini.")

    except Exception as e: await safe_reply(message, str(e))


@router.message(Command(f"ffmpeg{CMD_SUFFIX}"))
async def _ffmpeg_log(message: Message):
    if not await user_auth_checker(message): return
    chat_id  = message.chat.id
    commands = (message.text or "").split(" ")
    if len(commands) != 3 or commands[1] != "log":
        return await safe_reply(message, f"❗ Format: `/ffmpeg{CMD_SUFFIX} log <process_id>`")
        
    process_id = commands[2]
    try:
        log_file = await get_ffmpeg_log_file(process_id)
        if log_file: await Telegram.AIOGRAM_BOT.send_document(chat_id, document=FSInputFile(log_file))
        else: await safe_reply(message, "❗ Berkas Log Tidak Ditemukan")
    except Exception as e: await safe_reply(message, str(e))


# ═══════════════════════════════════════════════════════════════════════
#  CONFIG & MEDIA SAVE
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"saveconfig{CMD_SUFFIX}"))
async def _saverclone(message: Message):
    if not await user_auth_checker(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)
        
    r_config = f"./userdata/{user_id}_rclone.conf"
    status = "Sudah Ada (Akan Ditimpa)" if exists(r_config) else "Belum Ada"
    
    kb = _make_reply_kb(["❌ Batal"], 1)
    ask_txt = f"**⚙️ SETUP RCLONE**\n\nStatus: `{status}`\n\nKirim file `rclone.conf` atau URL konfigurasinya:"
    ask_msg = await message.reply(ask_txt, reply_markup=kb)
    
    resp = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ask_msg, resp)
    
    if not resp:
        return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    if "batal" in (resp.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    link = False
    process_msg = await message.answer("⏳ Sedang memproses konfigurasi...", reply_markup=ReplyKeyboardRemove())

    if resp.document:
        await Telegram.AIOGRAM_BOT.download(resp.document, destination=r_config)
    else:
        link = str(resp.text)
        ok = await dw_file_from_url(link, r_config)
        if ok: await saveoptions(user_id, "rclone_config_link", link, SAVE_TO_DATABASE)

    if not exists(r_config):
        return await process_msg.edit_text("❌ Gagal Mengunduh Berkas Konfigurasi.")

    accounts = await get_config(r_config)
    if not accounts:
        from bot_helper.Others.Helper_Functions import delete_trash
        await delete_trash(r_config)
        return await process_msg.edit_text("❌ Berkas Konfigurasi Tidak Valid Atau Kosong.")

    await saveoptions(user_id, "drive_name", accounts[0], SAVE_TO_DATABASE)
    if link: await saveoptions(user_id, "rclone_config_link", link, SAVE_TO_DATABASE)
    drive = get_data().get(user_id, {}).get("drive_name", accounts[0])
    await process_msg.edit_text(f"✅ Konfigurasi Berhasil Disimpan\n\n🔶 Menggunakan Drive **{drive}** untuk Mengunggah.")


@router.message(Command(f"savewatermark{CMD_SUFFIX}"))
async def _savewatermark(message: Message):
    if not await user_auth_checker(message): return
    chat_id, user_id = message.chat.id, message.from_user.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)
    ok = await ask_watermark(message, chat_id, user_id, "savewatermark", False)
    await message.answer("✅ Watermark berhasil disimpan." if ok else "❌ Gagal Mendapatkan Watermark.", reply_markup=ReplyKeyboardRemove())


@router.message(Command(f"savethumb{CMD_SUFFIX}"))
async def _savethumb(message: Message):
    if not await user_auth_checker(message): return
    chat_id, user_id = message.chat.id, message.from_user.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)
    ok = await ask_thumbnail_file(message, chat_id, user_id, "savethumb")
    await message.answer("✅ Thumbnail berhasil disimpan." if ok else "❌ Gagal Mendapatkan Thumbnail.", reply_markup=ReplyKeyboardRemove())


# ═══════════════════════════════════════════════════════════════════════
#  ENV & BOT CONFIG
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"changeconfig{CMD_SUFFIX}"))
async def _changeconfig(message: Message):
    if not owner_checker(message): return
    if not exists("config.env"):
        return await safe_reply(message, "❗ Berkas `config.env` Tidak Ditemukan")
    keys = get_env_keys("config.env")
    if not keys:
        return await safe_reply(message, "❗ Tidak Ada Variabel Dalam Berkas `config.env`")
        
    kb_layout, row = [], []
    for k in keys:
        row.append(InlineKeyboardButton(text=k, callback_data=f"env_{k}"))
        if len(row) == 2:
            kb_layout.append(row)
            row = []
    if row: kb_layout.append(row)
    kb_layout.append([InlineKeyboardButton(text="⭕ Tutup", callback_data="close_settings")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=kb_layout)
    await message.reply("Pilih Variabel untuk Diubah", reply_markup=kb)


@router.message(Command(f"clearconfigs{CMD_SUFFIX}"))
async def _clearconfig(message: Message):
    if not owner_checker(message): return
    path = "./userdata/botconfig.env"
    if exists(path):
        remove(path)
        await safe_reply(message, f"✅ Berhasil Dihapus. Silakan jalankan `/restart{CMD_SUFFIX}` agar perubahan diterapkan.")
    else: await safe_reply(message, "❗ Konfigurasi Tidak Ditemukan")


# ═══════════════════════════════════════════════════════════════════════
#  SUDO MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"checksudo{CMD_SUFFIX}"))
async def _checksudo(message: Message):
    if not owner_checker(message): return
    await message.reply(f"**Sudo Users:**\n`{sudo_users}`")


@router.message(Command(f"addsudo{CMD_SUFFIX}"))
async def _addsudo(message: Message):
    if not owner_checker(message): return
    chat_id, user_id = message.chat.id, message.from_user.id
    sudo_id = await get_sudo_user_id(message)
    
    if not sudo_id:
        kb = _make_reply_kb(["❌ Batal"], 1)
        ask_msg = await message.reply("👤 Kirim ID Pengguna Telegram (Angka):", reply_markup=kb)
        resp = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(ask_msg, resp)
        
        if not resp:
            return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        if "batal" in (resp.text or "").lower():
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        if not (resp.text or "").isdigit():
            return await message.answer("❌ ID tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        sudo_id = int(resp.text)
            
    if sudo_id in sudo_users:
        return await message.answer(f"❗ ID sudah ada di Sudo.\n\n`{sudo_users}`", reply_markup=ReplyKeyboardRemove())
        
    sudo_users.append(sudo_id)
    _save_sudo_list()
    await message.answer(f"✅ Berhasil Ditambahkan.\n\n`{sudo_users}`", reply_markup=ReplyKeyboardRemove())


@router.message(Command(f"delsudo{CMD_SUFFIX}"))
async def _delsudo(message: Message):
    if not owner_checker(message): return
    chat_id, user_id = message.chat.id, message.from_user.id
    sudo_id = await get_sudo_user_id(message)
    
    if not sudo_id:
        kb = _make_reply_kb(["❌ Batal"], 1)
        ask_msg = await message.reply("👤 Kirim ID Pengguna Telegram (Angka):", reply_markup=kb)
        resp = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(ask_msg, resp)
        
        if not resp:
            return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        if "batal" in (resp.text or "").lower():
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        if not (resp.text or "").isdigit():
            return await message.answer("❌ ID tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        sudo_id = int(resp.text)
            
    if sudo_id not in sudo_users:
        return await message.answer(f"❗ ID Tidak Ditemukan.\n\n`{sudo_users}`", reply_markup=ReplyKeyboardRemove())
        
    sudo_users.remove(sudo_id)
    _save_sudo_list()
    await message.answer(f"✅ Berhasil Dihapus.\n\n`{sudo_users}`", reply_markup=ReplyKeyboardRemove())


def _save_sudo_list() -> None:
    """Simpan sudo list ke botconfig.env."""
    if exists("./userdata/botconfig.env"): d = get_env_dict("./userdata/botconfig.env") or {}
    elif exists("config.env"): d = get_env_dict("config.env") or {}
    else: d = {}
    d["SUDO_USERS"] = " ".join(str(u) for u in sudo_users)
    export_env_file("./userdata/botconfig.env", d)


# ═══════════════════════════════════════════════════════════════════════
#  DATABASE & CLEANUP
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"resetdb{CMD_SUFFIX}"))
async def _resetdb(message: Message):
    if not owner_checker(message): return
    chat_id, user_id = message.chat.id, message.from_user.id
    
    kb = _make_reply_kb(["✅ Ya", "❌ Batal"], 2)
    conf_txt = (
        f"**⚠️ KONFIRMASI RESET DATABASE**\n\n"
        f"🗑️ Tindakan: `Menghapus seluruh data pengguna dan pengaturan dari database.`\n\n"
        "Lanjutkan?"
    )
    conf_msg = await message.reply(conf_txt, reply_markup=kb)
    resp = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(conf_msg, resp)
    
    if not resp:
        return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    if "batal" in (resp.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    if "ya" in (resp.text or "").lower():
        ok = await resetdatabase(SAVE_TO_DATABASE)
        await message.answer(f"✅ Format Data {'Berhasil' if ok else 'Gagal Dijalankan'}", reply_markup=ReplyKeyboardRemove())


@router.message(Command(f"renew{CMD_SUFFIX}"))
async def _renew(message: Message):
    if not owner_checker(message): return
    chat_id, user_id = message.chat.id, message.from_user.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)
        
    kb = _make_reply_kb(["✅ Ya", "❌ Batal"], 2)
    conf_txt = (
        f"**🧹 KONFIRMASI PEMBERSIHAN (RENEW)**\n\n"
        f"🗑️ Tindakan: `Menghapus semua file unduhan sementara dan watermark lokal.`\n\n"
        "Lanjutkan?"
    )
    conf_msg = await message.reply(conf_txt, reply_markup=kb)
    resp = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(conf_msg, resp)
    
    if not resp:
        return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    if "batal" in (resp.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    if "ya" in (resp.text or "").lower():
        if exists(Config.DOWNLOAD_DIR):
            await delete_all(Config.DOWNLOAD_DIR)
            await message.answer(f"✅ Seluruh Berkas Sementara pada folder {Config.DOWNLOAD_DIR} Berhasil Dihancurkan", reply_markup=ReplyKeyboardRemove())
        else:
            await message.answer("✅ Server Bersih: Tidak ada sampah berkas sementara.", reply_markup=ReplyKeyboardRemove())


@router.message(Command(f"settings{CMD_SUFFIX}"))
async def _settings(message: Message):
    if not await user_auth_checker(message): return
    user_id = message.from_user.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Profil Pengaturan", callback_data="profile_main")],
        [InlineKeyboardButton(text="🎬 Pengaturan Media",   callback_data="settings_media")],
        [InlineKeyboardButton(text="🤖 Pengaturan Umum & Tampilan", callback_data="settings_bot")],
        [InlineKeyboardButton(text="⭕ Tutup Pengaturan", callback_data="close_settings")],
    ])
    await message.reply(f"⚙️ Hai {get_mention(message)} — Pilih Pengaturan Anda", reply_markup=kb)
