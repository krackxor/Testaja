"""
╔══════════════════════════════════════════════════════════════════════╗
║                    bot_helper/Handlers/subtitle_handlers.py — v1.0   ║
║        Auto Subtitle (AI Whisper) & Auto Translate Subtitle          ║
╠══════════════════════════════════════════════════════════════════════╣
║  Fitur Utama:                                                        ║
║  • /autosub : Transkripsi Audio/Video menjadi file .srt              ║
║  • /autotranslate : Terjemahkan file .srt ke bahasa apapun           ║
║                                                                      ║
║  CHANGELOG v1.0:                                                     ║
║  [UX PREMIUM] Implementasi API Warna Tombol Native Telegram 9.4+     ║
║  [UX PREMIUM] Progress Bar Real-Time saat AI sedang mengetik.        ║
║  [UX PREMIUM] Interactive Wizard & Kotak Konfirmasi (Summary Box).   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import os
import time
from datetime import datetime
from typing import Optional

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramBadRequest

from bot_helper.Database.User_Data import get_data, ensure_user_data_structure, get_task_limit
from bot_helper.Others.Helper_Functions import get_human_size, get_readable_time
from bot_helper.Process.Process_Status import ProcessStatus, get_progress_bar_string
from bot_helper.Process.Running_Process import append_running_process, check_running_process, remove_running_process
from bot_helper.Process.Running_Tasks import working_task, working_task_lock, queued_task, queued_task_lock
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config
from bot.shared import wait_for_message, CMD_SUFFIX

# ── Dynamic Imports (Pencegah Error jika library belum diinstall) ──
try:
    import pysrt
    from deep_translator import GoogleTranslator
    HAS_TRANSLATOR = True
except ImportError:
    HAS_TRANSLATOR = False

try:
    from faster_whisper import WhisperModel
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

LOGGER = Config.LOGGER
router = Router()

TEMP_DIR = "./temp/subtitles/"
os.makedirs(TEMP_DIR, exist_ok=True)
QUEUE_TIMEOUT = 7200

# ═══════════════════════════════════════════════════════════════════════
#  HELPERS & UI (COLOR BUTTONS ENABLED)
# ═══════════════════════════════════════════════════════════════════════

async def _clean_msgs(*msgs):
    for m in msgs:
        if m:
            try: await m.delete()
            except Exception: pass

def _make_reply_kb(options: list, row_width: int = 2) -> ReplyKeyboardMarkup:
    """Membuat Reply Keyboard dengan mudah dan warna otomatis (Native Telegram)."""
    kb = []
    row = []
    for opt in options:
        # Auto-Color Logic
        if "Batal" in opt or "❌" in opt:
            btn_style = "danger"
        elif "Ya" in opt or "✅" in opt or "Mulai" in opt:
            btn_style = "success"
        else:
            btn_style = "primary"
            
        row.append(KeyboardButton(text=opt, style=btn_style))
        if len(row) == row_width:
            kb.append(row); row = []
    if row: kb.append(row)
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)

async def _safe_edit(msg: Message, text: str, buttons=None) -> None:
    try:
        if buttons: await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else: await msg.edit_text(text)
    except TelegramBadRequest: pass
    except Exception: pass

def _tmp(name: str) -> str: return os.path.join(TEMP_DIR, name)

def _cleanup(*paths: str) -> None:
    for p in paths:
        if p and os.path.exists(p):
            try: os.remove(p)
            except OSError: pass

def _is_vip(user_id: int) -> bool:
    if user_id == Config.OWNER_ID or user_id in Config.SUDO_USERS: return True
    expiry_str = get_data().get(user_id, {}).get("premium_expiry_date")
    if not expiry_str: return False
    try: return datetime.now(datetime.fromisoformat(str(expiry_str)).tzinfo) < datetime.fromisoformat(str(expiry_str))
    except Exception: return False


# ═══════════════════════════════════════════════════════════════════════
#  WORKER: AUTO SUBTITLE (WHISPER AI)
# ═══════════════════════════════════════════════════════════════════════

async def _autosub_worker(process_status: ProcessStatus, original_message: Message, reply_msg: Message, lang_code: str, status_msg: Message) -> None:
    media_path = _tmp(f"media_{process_status.process_id}.mp4")
    srt_path = _tmp(f"{process_status.file_name or 'subtitle'}.srt")
    t0 = time.time()
    
    try:
        # 1. Download Media
        process_status.update_process_message(f"⏳ 🔽 **Mengunduh media untuk dianalisis...**\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
        await _safe_edit(status_msg, process_status.status_message)
        
        target_media = reply_msg.video or reply_msg.audio or reply_msg.voice or reply_msg.document
        await Telegram.AIOGRAM_BOT.download(target_media, destination=media_path)
        if not os.path.exists(media_path): raise RuntimeError("Gagal mengunduh berkas media.")

        # 2. Inisialisasi AI Whisper
        process_status.update_process_message(f"⏳ 🧠 **Memuat Model AI Whisper...**\n_Memori sedang dialokasikan, harap tunggu._")
        await _safe_edit(status_msg, process_status.status_message)
        
        def run_whisper():
            # Menggunakan model 'base' agar aman untuk CPU server. Bisa diganti 'small' jika RAM > 4GB.
            model = WhisperModel("base", device="cpu", compute_type="int8")
            target_lang = None if lang_code == "auto" else lang_code
            segments, info = model.transcribe(media_path, language=target_lang, beam_size=5)
            return segments, info
            
        segments, info = await asyncio.to_thread(run_whisper)
        detected_lang = info.language
        duration = info.duration

        # 3. Proses Transkripsi & Build SRT
        subs = pysrt.SubRipFile()
        last_edit = 0.0
        
        # Iterasi segmen yang dihasilkan AI
        for i, segment in enumerate(segments, start=1):
            if not check_running_process(process_status.process_id): raise asyncio.CancelledError("Dibatalkan")
            
            # Buat item SRT
            item = pysrt.SubRipItem(
                index=i,
                start=pysrt.SubRipTime(seconds=segment.start),
                end=pysrt.SubRipTime(seconds=segment.end),
                text=segment.text.strip()
            )
            subs.append(item)
            
            # Update Progress Bar setiap 2 detik
            now = time.time()
            if now - last_edit >= 2.0:
                pct = min(1.0, segment.end / max(duration, 1.0))
                bar = get_progress_bar_string(int(pct * 100), 100)
                process_status.update_process_message(f"⏳ ✍️ **AI Sedang Mengetik...**\n\n🗣️ Bahasa: `{detected_lang.upper()}`\n{bar} {pct*100:.1f}%\n\n📝 _\"{segment.text.strip()}\"_\n\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
                asyncio.create_task(_safe_edit(status_msg, process_status.status_message))
                last_edit = now

        # 4. Simpan & Kirim
        process_status.update_process_message(f"⏳ 💾 **Menyimpan file Subtitle...**")
        await _safe_edit(status_msg, process_status.status_message)
        
        await asyncio.to_thread(subs.save, srt_path, encoding='utf-8')
        
        elapsed = get_readable_time(time.time() - t0)
        await Telegram.AIOGRAM_BOT.send_document(
            chat_id=original_message.chat.id,
            document=FSInputFile(srt_path),
            caption=f"✅ **Auto Subtitle Selesai!**\n\n🗣️ **Deteksi Bahasa:** `{detected_lang.upper()}`\n⏱️ **Waktu Proses:** `{elapsed}`\n\n_File .srt ini bisa Anda gunakan di video player atau di-hardmux via bot._",
            reply_to_message_id=original_message.message_id
        )
        await _safe_edit(status_msg, f"✅ **Proses Auto Subtitle Berhasil!** ({elapsed})")

    except asyncio.CancelledError: await _safe_edit(status_msg, "❌ **Auto Subtitle Dibatalkan.**")
    except Exception as e:
        LOGGER.error(f"❌ AutoSub worker error: {e}", exc_info=True)
        await _safe_edit(status_msg, f"❌ **Error Auto Subtitle:**\n`{str(e)[:400]}`")
    finally:
        _cleanup(media_path, srt_path)
        await remove_running_process(process_status.process_id)
        async with working_task_lock:
            for task in list(working_task):
                ps = task.get("process_status")
                if ps and ps.process_id == process_status.process_id:
                    working_task.remove(task); break


# ═══════════════════════════════════════════════════════════════════════
#  WORKER: AUTO TRANSLATE (DEEP TRANSLATOR)
# ═══════════════════════════════════════════════════════════════════════

async def _autotranslate_worker(process_status: ProcessStatus, original_message: Message, reply_msg: Message, target_lang: str, status_msg: Message) -> None:
    srt_in = _tmp(f"in_{process_status.process_id}.srt")
    srt_out = _tmp(f"{process_status.file_name or 'translated'}_{target_lang}.srt")
    t0 = time.time()
    
    try:
        # 1. Download Media
        process_status.update_process_message(f"⏳ 🔽 **Mengunduh file SRT...**")
        await _safe_edit(status_msg, process_status.status_message)
        await Telegram.AIOGRAM_BOT.download(reply_msg.document, destination=srt_in)
        if not os.path.exists(srt_in): raise RuntimeError("Gagal mengunduh berkas SRT.")

        # 2. Parse & Translate
        subs = await asyncio.to_thread(pysrt.open, srt_in)
        total_lines = len(subs)
        
        process_status.update_process_message(f"⏳ 🌐 **Menghubungkan ke Mesin Penerjemah...**\nTarget: `{target_lang.upper()}`\nTotal Baris: `{total_lines}`")
        await _safe_edit(status_msg, process_status.status_message)
        
        translator = GoogleTranslator(source='auto', target=target_lang)
        last_edit = 0.0

        def _translate_batch():
            for i, sub in enumerate(subs, start=1):
                if not check_running_process(process_status.process_id): raise asyncio.CancelledError("Dibatalkan")
                sub.text = translator.translate(sub.text)
                
                # Report progress via global list trick to avoid nested async blocking
                if time.time() - last_edit >= 2.0 or i == total_lines:
                    yield i, sub.text

        # Iterate translated lines
        for current_idx, current_text in _translate_batch():
            pct = current_idx / max(total_lines, 1)
            bar = get_progress_bar_string(int(pct * 100), 100)
            process_status.update_process_message(f"⏳ 🔄 **Menerjemahkan Teks...**\nTarget: `{target_lang.upper()}`\n\n[{bar}] {pct*100:.1f}%\nBaris: `{current_idx}/{total_lines}`\n\n📝 _\"{current_text}\"_\n\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
            asyncio.create_task(_safe_edit(status_msg, process_status.status_message))
            last_edit = time.time()

        # 3. Simpan & Kirim
        await asyncio.to_thread(subs.save, srt_out, encoding='utf-8')
        
        elapsed = get_readable_time(time.time() - t0)
        await Telegram.AIOGRAM_BOT.send_document(
            chat_id=original_message.chat.id,
            document=FSInputFile(srt_out),
            caption=f"✅ **Translate Subtitle Selesai!**\n\n🌐 **Bahasa Target:** `{target_lang.upper()}`\n⏱️ **Waktu Proses:** `{elapsed}`",
            reply_to_message_id=original_message.message_id
        )
        await _safe_edit(status_msg, f"✅ **Proses Translate Subtitle Berhasil!** ({elapsed})")

    except asyncio.CancelledError: await _safe_edit(status_msg, "❌ **Translate Subtitle Dibatalkan.**")
    except Exception as e:
        LOGGER.error(f"❌ AutoTranslate worker error: {e}", exc_info=True)
        await _safe_edit(status_msg, f"❌ **Error Auto Translate:**\n`{str(e)[:400]}`")
    finally:
        _cleanup(srt_in, srt_out)
        await remove_running_process(process_status.process_id)
        async with working_task_lock:
            for task in list(working_task):
                ps = task.get("process_status")
                if ps and ps.process_id == process_status.process_id:
                    working_task.remove(task); break


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"autosub{CMD_SUFFIX}"))
async def autosub_handler(message: Message) -> None:
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if not HAS_WHISPER or not HAS_TRANSLATOR:
        return await message.reply("❌ **Library AI belum terinstall!**\nJalankan di server: `pip install pysrt deep-translator faster-whisper`")

    if not _is_vip(user_id):
        return await message.reply("👑 **Fitur Eksklusif VIP**\nAuto Subtitle AI membutuhkan CPU tinggi. Fitur ini hanya untuk member Premium.")

    reply_msg = message.reply_to_message
    if not reply_msg or not (reply_msg.video or reply_msg.audio or reply_msg.voice or reply_msg.document):
        return await message.reply("❌ **Cara Pakai:**\nBalas (reply) sebuah Video atau Audio dengan perintah `/autosub{CMD_SUFFIX}`")

    await ensure_user_data_structure(user_id)

    # WIZARD STEP 1: LANGUAGE
    kb_lang = _make_reply_kb(["🔄 Auto Detect", "🇮🇩 Indonesian (id)", "🇬🇧 English (en)", "🇯🇵 Japanese (ja)", "❌ Batal"], 2)
    msg_lang = await message.reply("🗣️ **Pilih Bahasa Suara pada Video:**", reply_markup=kb_lang)
    resp_lang = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_lang, resp_lang)
    
    txt_lang = (resp_lang.text or "").lower()
    if not resp_lang or "batal" in txt_lang:
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    if "auto" in txt_lang: lang_code = "auto"
    elif "id" in txt_lang: lang_code = "id"
    elif "en" in txt_lang: lang_code = "en"
    elif "ja" in txt_lang: lang_code = "ja"
    else: lang_code = "auto" # Fallback

    # WIZARD STEP 2: CONFIRMATION
    kb_conf = _make_reply_kb(["✅ Mulai Transkripsi", "❌ Batal"], 2)
    conf_txt = (
        f"**✍️ KONFIRMASI AUTO SUBTITLE**\n\n"
        f"🧠 **Engine:** `Whisper AI`\n"
        f"🗣️ **Bahasa:** `{lang_code.upper()}`\n"
        f"🎯 **Output:** `File .srt`\n\n"
        "Lanjutkan? Proses ini mungkin memakan waktu tergantung durasi video."
    )
    msg_conf = await message.reply(conf_txt, reply_markup=kb_conf)
    resp_conf = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_conf, resp_conf)
    
    if not resp_conf or "batal" in (resp_conf.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    await message.answer("⏳ ✅ Menyiapkan AI Whisper...", reply_markup=ReplyKeyboardRemove())

    # START TASK
    target_media = reply_msg.video or reply_msg.document or reply_msg.audio
    fname = target_media.file_name if hasattr(target_media, 'file_name') else "media"
    if "." in fname: fname = fname.rsplit(".", 1)[0]
    
    ps = ProcessStatus(user_id, chat_id, message.from_user.username or "", message.from_user.first_name or str(user_id), message, "AutoSubtitle", "Telegram")
    ps.file_name = fname
    
    init_text = f"⏳ ✍️ **Memulai Auto Subtitle...**\n**File:** `{fname}`\n**ID:** `{ps.process_id}`\n`/cancel{CMD_SUFFIX} process {ps.process_id}`"
    kb_action = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Batal", callback_data=f"ac_cancel_{user_id}_{ps.process_id}", style="danger")]])
    status_msg = await message.answer(init_text, reply_markup=kb_action)
    
    # Masukkan ke Antrean Task
    task_wrapper = {"process_status": ps, "functions": [], "_autosub": True}
    async with working_task_lock:
        working_task.append(task_wrapper); await append_running_process(ps.process_id)
    
    asyncio.create_task(_autosub_worker(ps, message, reply_msg, lang_code, status_msg))


@router.message(Command(f"autotranslate{CMD_SUFFIX}"))
async def autotranslate_handler(message: Message) -> None:
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if not HAS_TRANSLATOR or not HAS_WHISPER:
        return await message.reply("❌ **Library AI belum terinstall!**\nJalankan di server: `pip install pysrt deep-translator faster-whisper`")

    if not _is_vip(user_id):
        return await message.reply("👑 **Fitur Eksklusif VIP**\nFitur ini hanya untuk member Premium.")

    reply_msg = message.reply_to_message
    if not reply_msg or not reply_msg.document or not reply_msg.document.file_name.endswith(('.srt', '.ass')):
        return await message.reply("❌ **Cara Pakai:**\nBalas (reply) sebuah file `.srt` atau `.ass` dengan perintah `/autotranslate{CMD_SUFFIX}`")

    await ensure_user_data_structure(user_id)

    # WIZARD STEP 1: TARGET LANGUAGE
    kb_lang = _make_reply_kb(["🇮🇩 Indonesian (id)", "🇬🇧 English (en)", "🇯🇵 Japanese (ja)", "Kustom", "❌ Batal"], 3)
    msg_lang = await message.reply("🌐 **Pilih Bahasa Target (Terjemahan):**", reply_markup=kb_lang)
    resp_lang = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_lang, resp_lang)
    
    txt_lang = (resp_lang.text or "").lower()
    if not resp_lang or "batal" in txt_lang:
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    if "kustom" in txt_lang:
        msg_cust = await message.reply("Ketik kode bahasa target (misal: `ko` untuk Korea, `es` untuk Spanyol):", reply_markup=ReplyKeyboardRemove())
        resp_cust = await wait_for_message(chat_id, user_id, 60)
        await _clean_msgs(msg_cust, resp_cust)
        if not resp_cust or "batal" in (resp_cust.text or "").lower():
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        lang_code = resp_cust.text.strip().lower()
    else:
        if "id" in txt_lang: lang_code = "id"
        elif "en" in txt_lang: lang_code = "en"
        elif "ja" in txt_lang: lang_code = "ja"
        else: lang_code = "en"

    # WIZARD STEP 2: CONFIRMATION
    kb_conf = _make_reply_kb(["✅ Mulai Translate", "❌ Batal"], 2)
    conf_txt = (
        f"**🌐 KONFIRMASI AUTO TRANSLATE**\n\n"
        f"📁 **File:** `{reply_msg.document.file_name}`\n"
        f"🎯 **Target:** `{lang_code.upper()}`\n\n"
        "Lanjutkan?"
    )
    msg_conf = await message.reply(conf_txt, reply_markup=kb_conf)
    resp_conf = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_conf, resp_conf)
    
    if not resp_conf or "batal" in (resp_conf.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    await message.answer("⏳ ✅ Menyiapkan Mesin Penerjemah...", reply_markup=ReplyKeyboardRemove())

    # START TASK
    fname = reply_msg.document.file_name.rsplit(".", 1)[0]
    ps = ProcessStatus(user_id, chat_id, message.from_user.username or "", message.from_user.first_name or str(user_id), message, "AutoTranslate", "Telegram")
    ps.file_name = fname
    
    init_text = f"⏳ 🌐 **Memulai Auto Translate...**\n**File:** `{fname}`\n**ID:** `{ps.process_id}`\n`/cancel{CMD_SUFFIX} process {ps.process_id}`"
    kb_action = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Batal", callback_data=f"ac_cancel_{user_id}_{ps.process_id}", style="danger")]])
    status_msg = await message.answer(init_text, reply_markup=kb_action)
    
    # Masukkan ke Antrean Task
    task_wrapper = {"process_status": ps, "functions": [], "_autotrans": True}
    async with working_task_lock:
        working_task.append(task_wrapper); await append_running_process(ps.process_id)
    
    asyncio.create_task(_autotranslate_worker(ps, message, reply_msg, lang_code, status_msg))
