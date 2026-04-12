"""
╔══════════════════════════════════════════════════════════════════════╗
║                    bot/subtitle_handlers.py — v2.5                   ║
║        Auto Subtitle (AI Whisper) & Auto Translate Subtitle          ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v2.5:                                                     ║
║  [FIX] Menyesuaikan pemanggilan execute_unified_task agar selaras    ║
║        dengan Unified Engine v2.8 (Mendukung dynamic engine_name).   ║
║  [FIX CRITICAL] Ekstraksi audio via FFmpeg sebelum Whisper agar      ║
║                 tidak stuck/macet di tengah proses pembacaan file.   ║
║  [FIX CRITICAL] Mengganti download Aiogram dengan Pyrogram (MTProto) ║
║                 agar support file media hingga 2GB.                  ║
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

# [NEW v2.2] Import Mesin Kasir
from bot_helper.Process.point_manager import process_payment

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
    """[DEPRECATED] Fungsi lama untuk cek hari, dibiarkan sementara namun akan di-override oleh Sistem Poin."""
    if user_id == Config.OWNER_ID or user_id in Config.SUDO_USERS: return True
    return True # Semua orang kini dianggap VIP, pembatasnya adalah SALDO POIN.


# ═══════════════════════════════════════════════════════════════════════
#  WORKER: AUTO SUBTITLE (WHISPER AI) - VIA UNIFIED ENGINE
# ═══════════════════════════════════════════════════════════════════════

async def _core_autosub_logic(message: Message, ui, reply_msg: Message, lang_code: str, fname: str) -> None:
    """Fungsi inti Whisper AI yang telah terintegrasi dengan ProgressUI & Anti-Macet"""
    media_path = _tmp(f"media_{message.message_id}.mp4")
    audio_path = _tmp(f"audio_{message.message_id}.wav") # Tambahan file audio
    srt_path = _tmp(f"{fname}.srt")
    
    try:
        # 1. Download Media (MENGGUNAKAN PYROGRAM ANTI-LIMIT 2GB)
        await ui.update("📥 Mengunduh Media...", details="Mempersiapkan unduhan via Pyrogram (Anti-Limit)...")
        last_dl_edit = 0.0

        async def _dl_progress(current: int, total: int):
            nonlocal last_dl_edit
            now = time.time()
            # Update UI setiap 2 detik agar Telegram tidak memblokir bot
            if now - last_dl_edit >= 2.0 and total > 0:
                await ui.update(
                    status="📥 Mengunduh Media...", 
                    current=current, 
                    total=total, 
                    details="Mengambil file untuk dianalisis..."
                )
                last_dl_edit = now

        try:
            # Gunakan reply_msg.message_id karena media-nya ada di pesan yang di-reply
            pyro_msg = await Telegram.PYROGRAM_CLIENT.get_messages(reply_msg.chat.id, reply_msg.message_id)
            await Telegram.PYROGRAM_CLIENT.download_media(
                message=pyro_msg,
                file_name=media_path,
                progress=_dl_progress
            )
        except Exception as e:
            await ui.error(f"Gagal mengunduh file via Pyrogram: {e}")
            return

        if not os.path.exists(media_path): raise RuntimeError("Gagal mengunduh berkas media.")

        # 1.5 Ekstraksi Audio Eksplisit agar AI Whisper tidak macet membaca Video
        await ui.update("🎵 Mengekstrak Audio...", details="Memisahkan suara dari video agar AI 5x lebih cepat...")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", media_path, "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", audio_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc.communicate()
        
        # Gunakan audio_path jika ekstraksi berhasil, jika gagal fallback pakai media awal
        target_file_for_ai = audio_path if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0 else media_path

        # 2. Inisialisasi AI Whisper di latar belakang
        await ui.update("🧠 Memuat Model AI Whisper...", details="Memori sedang dialokasikan ke CPU, harap tunggu...")
        
        def init_whisper():
            try:
                # Catcher Error di dalam thread agar tidak silent crash
                model = WhisperModel("base", device="cpu", compute_type="int8")
                target_lang = None if lang_code == "auto" else lang_code
                return model.transcribe(target_file_for_ai, language=target_lang, beam_size=5)
            except Exception as e:
                LOGGER.error(f"Whisper Init Error: {e}")
                raise e
            
        segments_gen, info = await asyncio.to_thread(init_whisper)
        detected_lang = info.language
        duration = info.duration

        # 3. Proses Transkripsi (Generator Fetching secara Async)
        subs = pysrt.SubRipFile()
        last_edit = 0.0
        i = 1
        
        while True:
            try:
                # Mengambil chunk audio selanjutnya di latar belakang (Tidak memblokir loop)
                segment = await asyncio.to_thread(next, segments_gen)
            except StopIteration:
                break # Transkripsi selesai
            except Exception as e:
                LOGGER.error(f"Whisper chunk error: {e}")
                break
                
            item = pysrt.SubRipItem(
                index=i,
                start=pysrt.SubRipTime(seconds=segment.start),
                end=pysrt.SubRipTime(seconds=segment.end),
                text=segment.text.strip()
            )
            subs.append(item)
            i += 1
            
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
                
            # Beri napas event loop agar tombol dashboard merespons
            await asyncio.sleep(0.01)

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

    except Exception as e:
        # Tangkap semua error dan laporkan ke UI
        LOGGER.error(f"Error di AutoSub: {e}")
        await ui.error(f"Gagal memproses Auto Subtitle:\n{str(e)[:100]}")
    finally:
        _cleanup(media_path, audio_path, srt_path)


# ═══════════════════════════════════════════════════════════════════════
#  WORKER: AUTO TRANSLATE (DEEP TRANSLATOR) - VIA UNIFIED ENGINE
# ═══════════════════════════════════════════════════════════════════════

async def _core_autotranslate_logic(message: Message, ui, reply_msg: Message, target_lang: str, fname: str) -> None:
    """Fungsi inti Auto Translate yang telah terintegrasi dengan ProgressUI & Anti-Macet"""
    srt_in = _tmp(f"in_{message.message_id}.srt")
    srt_out = _tmp(f"{fname}_{target_lang}.srt")
    
    try:
        # 1. Download SRT
        await ui.update("📥 Mengunduh Subtitle...", details="Mengambil file .srt dari Telegram (Pyrogram)...")
        last_dl_edit = 0.0

        async def _dl_progress(current: int, total: int):
            nonlocal last_dl_edit
            now = time.time()
            if now - last_dl_edit >= 2.0 and total > 0:
                await ui.update(
                    status="📥 Mengunduh Subtitle...", 
                    current=current, 
                    total=total, 
                    details="Mengambil file .srt dari Telegram..."
                )
                last_dl_edit = now

        try:
            pyro_msg = await Telegram.PYROGRAM_CLIENT.get_messages(reply_msg.chat.id, reply_msg.message_id)
            await Telegram.PYROGRAM_CLIENT.download_media(
                message=pyro_msg,
                file_name=srt_in,
                progress=_dl_progress
            )
        except Exception as e:
            await ui.error(f"Gagal mengunduh file SRT via Pyrogram: {e}")
            return
            
        if not os.path.exists(srt_in): raise RuntimeError("Gagal mengunduh berkas SRT.")

        # 2. Parse & Inisialisasi Translator
        subs = await asyncio.to_thread(pysrt.open, srt_in)
        total_lines = len(subs)
        
        await ui.update("🌐 Menghubungkan ke Mesin Penerjemah...", details=f"Target: {target_lang.upper()} | Total: {total_lines} Baris")
        translator = GoogleTranslator(source='auto', target=target_lang)
        last_edit = 0.0

        # 3. Proses Translate Secara Async
        for i, sub in enumerate(subs, start=1):
            # Translasi dilakukan di background thread
            sub.text = await asyncio.to_thread(translator.translate, sub.text)
            
            # Beri napas event loop agar bot tidak macet (sangat penting untuk SRT > 500 baris)
            if i % 5 == 0:
                await asyncio.sleep(0.1)
            
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

    reply_msg = message.reply_to_message
    if not reply_msg or not (reply_msg.video or reply_msg.audio or reply_msg.voice or reply_msg.document):
        return await message.reply("❌ **Cara Pakai:**\nBalas (reply) sebuah Video atau Audio dengan perintah `/autosub{CMD_SUFFIX}`")

    await ensure_user_data_structure(user_id)

    # WIZARD STEP 1: LANGUAGE
    kb_lang = _make_reply_kb(["🔄 Auto Detect", "🇮🇩 Indonesian (id)", "🇬🇧 English (en)", "🇯🇵 Japanese (ja)", "❌ Batal"], 2)
    msg_lang = await message.reply("🗣️ **Pilih Bahasa Suara pada Video:**", reply_markup=kb_lang)
    
    try:
        resp_lang = await wait_for_message(chat_id, user_id, 60)
    except asyncio.TimeoutError:
        return await message.answer("❌ Waktu habis.", reply_markup=ReplyKeyboardRemove())
        
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
    
    try:
        resp_conf = await wait_for_message(chat_id, user_id, 60)
    except asyncio.TimeoutError:
        return await message.answer("❌ Waktu habis.", reply_markup=ReplyKeyboardRemove())
        
    await _clean_msgs(msg_conf, resp_conf)
    
    if not resp_conf or "batal" in (resp_conf.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    # MESIN KASIR: POTONG SALDO POIN
    await message.answer("🔄 Mengecek Saldo Poin...", reply_markup=ReplyKeyboardRemove())
    payment = await process_payment(user_id=user_id, command="autosub")
    
    if not payment["success"]:
        return await message.answer(payment["message"])
    else:
        temp_msg = await message.answer(payment["message"])

    # 🚀 JALANKAN VIA UNIFIED ENGINE
    target_media = reply_msg.video or reply_msg.document or reply_msg.audio
    fname = target_media.file_name if hasattr(target_media, 'file_name') else "media"
    if "." in fname: fname = fname.rsplit(".", 1)[0]
    
    # [FIX v2.5] Menambahkan engine_name khusus Whisper AI
    await execute_unified_task(
        message, 
        "AUTO SUBTITLE AI", 
        _core_autosub_logic, 
        reply_msg, 
        lang_code, 
        fname,
        engine_name="Whisper AI"
    )


@router.message(Command(f"autotranslate{CMD_SUFFIX}"))
async def autotranslate_handler(message: Message) -> None:
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if not HAS_TRANSLATOR or not HAS_WHISPER:
        return await message.reply("❌ **Library AI belum terinstall!**\nJalankan di server: `pip install pysrt deep-translator faster-whisper`")

    reply_msg = message.reply_to_message
    if not reply_msg or not reply_msg.document or not reply_msg.document.file_name.endswith(('.srt', '.ass')):
        return await message.reply("❌ **Cara Pakai:**\nBalas (reply) sebuah file `.srt` atau `.ass` dengan perintah `/autotranslate{CMD_SUFFIX}`")

    await ensure_user_data_structure(user_id)

    # WIZARD STEP 1: TARGET LANGUAGE
    kb_lang = _make_reply_kb(["🇮🇩 Indonesian (id)", "🇬🇧 English (en)", "🇯🇵 Japanese (ja)", "Kustom", "❌ Batal"], 3)
    msg_lang = await message.reply("🌐 **Pilih Bahasa Target (Terjemahan):**", reply_markup=kb_lang)
    
    try:
        resp_lang = await wait_for_message(chat_id, user_id, 60)
    except asyncio.TimeoutError:
        return await message.answer("❌ Waktu habis.", reply_markup=ReplyKeyboardRemove())
        
    await _clean_msgs(msg_lang, resp_lang)
    
    txt_lang = (resp_lang.text or "").lower()
    if not resp_lang or "batal" in txt_lang:
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    if "kustom" in txt_lang:
        msg_cust = await message.reply("Ketik kode bahasa target (misal: `ko` untuk Korea, `es` untuk Spanyol):", reply_markup=ReplyKeyboardRemove())
        try:
            resp_cust = await wait_for_message(chat_id, user_id, 60)
        except asyncio.TimeoutError:
            return await message.answer("❌ Waktu habis.", reply_markup=ReplyKeyboardRemove())
            
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
    
    try:
        resp_conf = await wait_for_message(chat_id, user_id, 60)
    except asyncio.TimeoutError:
        return await message.answer("❌ Waktu habis.", reply_markup=ReplyKeyboardRemove())
        
    await _clean_msgs(msg_conf, resp_conf)
    
    if not resp_conf or "batal" in (resp_conf.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    # MESIN KASIR: POTONG SALDO POIN
    await message.answer("🔄 Mengecek Saldo Poin...", reply_markup=ReplyKeyboardRemove())
    payment = await process_payment(user_id=user_id, command="autotranslate")
    
    if not payment["success"]:
        return await message.answer(payment["message"])
    else:
        temp_msg = await message.answer(payment["message"])

    # 🚀 JALANKAN VIA UNIFIED ENGINE
    fname = reply_msg.document.file_name.rsplit(".", 1)[0]
    
    # [FIX v2.5] Menambahkan engine_name khusus Google Translator
    await execute_unified_task(
        message, 
        "AUTO TRANSLATE", 
        _core_autotranslate_logic, 
        reply_msg, 
        lang_code, 
        fname,
        engine_name="Google Deep Translator"
    )
