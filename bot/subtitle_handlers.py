"""
╔══════════════════════════════════════════════════════════════════════╗
║                    bot/subtitle_handlers.py — v2.0                   ║
║        Auto Subtitle (AI Whisper) & Auto Translate Subtitle          ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v2.0:                                                     ║
║  [INTEGRATION] Menggunakan Unified_Engine untuk Antrean & UI         ║
║  [UX PREMIUM] Progress Bar tersentralisasi & real-time ETA.          ║
║  [CLEANUP] Menghapus sistem tracking lama yang membebani memori.     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import os
import time
from datetime import datetime

from aiogram import Router, F
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

from bot_helper.Database.User_Data import get_data, ensure_user_data_structure
from bot_helper.Telegram.Telegram_Client import Telegram
from bot_helper.Process.Unified_Engine import execute_unified_task
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
#  WORKER: AUTO SUBTITLE (WHISPER AI) - VIA UNIFIED ENGINE
# ═══════════════════════════════════════════════════════════════════════

async def _core_autosub_logic(message: Message, ui, reply_msg: Message, lang_code: str, fname: str) -> None:
    """Fungsi inti Whisper AI yang telah terintegrasi dengan ProgressUI"""
    media_path = _tmp(f"media_{message.message_id}.mp4")
    srt_path = _tmp(f"{fname}.srt")
    
    try:
        # 1. Download Media
        await ui.update("📥 Mengunduh Media...", details="Mengambil file untuk dianalisis...")
        target_media = reply_msg.video or reply_msg.audio or reply_msg.voice or reply_msg.document
        await Telegram.AIOGRAM_BOT.download(target_media, destination=media_path)
        if not os.path.exists(media_path): raise RuntimeError("Gagal mengunduh berkas media.")

        # 2. Inisialisasi AI Whisper
        await ui.update("🧠 Memuat Model AI Whisper...", details="Memori sedang dialokasikan ke CPU, harap tunggu...")
        
        def run_whisper():
            model = WhisperModel("base", device="cpu", compute_type="int8")
            target_lang = None if lang_code == "auto" else lang_code
            return model.transcribe(media_path, language=target_lang, beam_size=5)
            
        segments, info = await asyncio.to_thread(run_whisper)
        detected_lang = info.language
        duration = info.duration

        # 3. Proses Transkripsi & Build SRT
        subs = pysrt.SubRipFile()
        last_edit = 0.0
        
        for i, segment in enumerate(segments, start=1):
            item = pysrt.SubRipItem(
                index=i,
                start=pysrt.SubRipTime(seconds=segment.start),
                end=pysrt.SubRipTime(seconds=segment.end),
                text=segment.text.strip()
            )
            subs.append(item)
            
            # Update Progress Bar setiap 2 detik via UI Manager
            now = time.time()
            if now - last_edit >= 2.0:
                short_text = segment.text.strip()
                if len(short_text) > 40: short_text = short_text[:40] + "..."
                
                await ui.update(
                    status="✍️ AI Sedang Mengetik...",
                    current=segment.end,
                    total=max(duration, 1.0),
                    details=f"Bahasa: {detected_lang.upper()}\n📝 \"{short_text}\""
                )
                last_edit = now

        # 4. Simpan & Kirim
        await ui.update("💾 Menyimpan File...", details="Menyusun format SubRip (.srt)...")
        await asyncio.to_thread(subs.save, srt_path, encoding='utf-8')
        
        await ui.update("📤 Mengunggah Hasil...", details="Mengirim file ke Telegram...")
        await Telegram.AIOGRAM_BOT.send_document(
            chat_id=message.chat.id,
            document=FSInputFile(srt_path),
            caption=f"✅ **Auto Subtitle Selesai!**\n\n🗣️ **Deteksi Bahasa:** `{detected_lang.upper()}`\n\n_File .srt ini bisa Anda gunakan di video player, diedit via bot, atau di-hardmux._",
            reply_to_message_id=reply_msg.message_id
        )
        
        await ui.finish(f"✅ <b>Auto Subtitle Berhasil!</b>\nDeteksi Bahasa: <code>{detected_lang.upper()}</code>")

    finally:
        _cleanup(media_path, srt_path)


# ═══════════════════════════════════════════════════════════════════════
#  WORKER: AUTO TRANSLATE (DEEP TRANSLATOR) - VIA UNIFIED ENGINE
# ═══════════════════════════════════════════════════════════════════════

async def _core_autotranslate_logic(message: Message, ui, reply_msg: Message, target_lang: str, fname: str) -> None:
    """Fungsi inti Auto Translate yang telah terintegrasi dengan ProgressUI"""
    srt_in = _tmp(f"in_{message.message_id}.srt")
    srt_out = _tmp(f"{fname}_{target_lang}.srt")
    
    try:
        # 1. Download SRT
        await ui.update("📥 Mengunduh Subtitle...", details="Mengambil file .srt dari Telegram...")
        await Telegram.AIOGRAM_BOT.download(reply_msg.document, destination=srt_in)
        if not os.path.exists(srt_in): raise RuntimeError("Gagal mengunduh berkas SRT.")

        # 2. Parse & Inisialisasi Translator
        subs = await asyncio.to_thread(pysrt.open, srt_in)
        total_lines = len(subs)
        
        await ui.update("🌐 Menghubungkan ke Mesin Penerjemah...", details=f"Target: {target_lang.upper()} | Total: {total_lines} Baris")
        translator = GoogleTranslator(source='auto', target=target_lang)
        last_edit = 0.0

        # 3. Proses Translate
        for i, sub in enumerate(subs, start=1):
            sub.text = translator.translate(sub.text)
            
            # Update Progress Bar setiap 2 detik via UI Manager
            if time.time() - last_edit >= 2.0 or i == total_lines:
                short_text = sub.text
                if len(short_text) > 40: short_text = short_text[:40] + "..."
                
                await ui.update(
                    status="🔄 Menerjemahkan Teks...",
                    current=i,
                    total=total_lines,
                    details=f"Target: {target_lang.upper()}\n📝 \"{short_text}\""
                )
                last_edit = time.time()

        # 4. Simpan & Kirim
        await ui.update("💾 Menyimpan File...", details="Menyusun file .srt terjemahan...")
        await asyncio.to_thread(subs.save, srt_out, encoding='utf-8')
        
        await ui.update("📤 Mengunggah Hasil...", details="Mengirim file ke Telegram...")
        await Telegram.AIOGRAM_BOT.send_document(
            chat_id=message.chat.id,
            document=FSInputFile(srt_out),
            caption=f"✅ **Translate Subtitle Selesai!**\n\n🌐 **Bahasa Target:** `{target_lang.upper()}`",
            reply_to_message_id=reply_msg.message_id
        )
        
        await ui.finish(f"✅ <b>Proses Translate Berhasil!</b>\nTarget: <code>{target_lang.upper()}</code>")

    finally:
        _cleanup(srt_in, srt_out)


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
    else: lang_code = "auto"

    # WIZARD STEP 2: CONFIRMATION
    kb_conf = _make_reply_kb(["✅ Mulai Transkripsi", "❌ Batal"], 2)
    conf_txt = (
        f"**✍️ KONFIRMASI AUTO SUBTITLE**\n\n"
        f"🧠 **Engine:** `Whisper AI`\n"
        f"🗣️ **Bahasa:** `{lang_code.upper()}`\n"
        f"🎯 **Output:** `File .srt`\n\n"
        f"Lanjutkan? Proses ini mungkin memakan waktu tergantung durasi video."
    )
    msg_conf = await message.reply(conf_txt, reply_markup=kb_conf)
    resp_conf = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_conf, resp_conf)
    
    if not resp_conf or "batal" in (resp_conf.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    # Hapus keyboard menu
    await message.answer("✅ Mengonfirmasi pesanan...", reply_markup=ReplyKeyboardRemove())

    # 🚀 JALANKAN VIA UNIFIED ENGINE
    target_media = reply_msg.video or reply_msg.document or reply_msg.audio
    fname = target_media.file_name if hasattr(target_media, 'file_name') else "media"
    if "." in fname: fname = fname.rsplit(".", 1)[0]
    
    await execute_unified_task(message, "AUTO SUBTITLE AI", _core_autosub_logic, reply_msg, lang_code, fname)


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
        f"Lanjutkan?"
    )
    msg_conf = await message.reply(conf_txt, reply_markup=kb_conf)
    resp_conf = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_conf, resp_conf)
    
    if not resp_conf or "batal" in (resp_conf.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    await message.answer("✅ Mengonfirmasi pesanan...", reply_markup=ReplyKeyboardRemove())

    # 🚀 JALANKAN VIA UNIFIED ENGINE
    fname = reply_msg.document.file_name.rsplit(".", 1)[0]
    await execute_unified_task(message, "AUTO TRANSLATE", _core_autotranslate_logic, reply_msg, lang_code, fname)
