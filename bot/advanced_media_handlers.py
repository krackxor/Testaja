"""
╔══════════════════════════════════════════════════════════════════════╗
║    bot_helper/Handlers/advanced_media_handlers.py — v3.1             ║
║    Advanced Media Handlers (Aiogram 3.x / Inline Waiter)             ║
╠══════════════════════════════════════════════════════════════════════╣
║  Commands: /trim /split /cut /rotate /crop /autocrop                 ║
║            /extension /extract /mediainfo                            ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [FIX HIGH] Inline Keyboard → Reply Keyboard pada /trim /split dll   ║
║             agar tombol merespons instan karena InlineKeyboardMarkup ║
║             tidak ditangkap oleh wait_for_message()!                 ║
║  [FIX HIGH] Extract & Mediainfo Bypass: File native Telegram akan    ║
║             diunduh instan tanpa mengantre, bebas risiko stuck!      ║
║  [FIX HIGH] Implementasi CMD_SUFFIX pada semua Command filter        ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
from json import loads as json_loads
from os.path import exists
from shutil import rmtree

# ── Third Party ───────────────────────────────────────────────────────
from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE as asyncioPIPE
from aiogram import Router
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Aria2.Aria2_Engine import Aria2
from bot_helper.Database.User_Data import get_data, new_user
from bot_helper.Others.Helper_Functions import (
    get_human_size, seconds_to_readable_str, time_string_to_seconds,
)
from bot_helper.Others.Names import Names
from bot_helper.Process.Process_Status import ProcessStatus
from bot_helper.Process.Running_Tasks import add_task, working_task, queued_task
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

from .shared import (
    CMD_SUFFIX, LOGGER, SAVE_TO_DATABASE,
    build_task, get_link, get_thumbnail, get_username,
    safe_reply, submit_task, update_status_message, user_auth_checker, vip_check,
    wait_for_message 
)

import re as _re

router = Router()

# ═══════════════════════════════════════════════════════════════════════
#  TIME VALIDATION
# ═══════════════════════════════════════════════════════════════════════

def is_valid_time_format(time_str: str) -> bool:
    try:
        parts = list(map(int, time_str.strip().split(":")))
        if len(parts) > 3 or len(parts) == 0: return False
        for i, p in enumerate(parts):
            if i > 0 and (p < 0 or p > 59): return False
        return True
    except (ValueError, TypeError): return False

def parse_single_cut_range(text: str):
    parts = text.strip().split("-", 1)
    if len(parts) != 2:
        parts = text.strip().rsplit("-", 1)
        if len(parts) != 2: return None
    start_str, end_str = parts[0].strip(), parts[1].strip()
    if not is_valid_time_format(start_str) or not is_valid_time_format(end_str): return None
    s, e = time_string_to_seconds(start_str), time_string_to_seconds(end_str)
    if s >= e: return None
    return (s, e)


# ═══════════════════════════════════════════════════════════════════════
#  /trim
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"trim{CMD_SUFFIX}"))
async def _trim_video(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    video_event_for_task, orig_duration = None, 0

    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("Kirim Video atau URL yang ingin di-trim.")
            resp = await wait_for_message(chat_id, user_id, 120)
            if resp.video or resp.document: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await ask_msg.edit_text("Input tidak valid. Dibatalkan.")
        except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis, proses dibatalkan.")

    video_event_for_task = link
    if not isinstance(link, str) and (link.video or link.document):
        vid_obj = link.video or link.document
        orig_duration = getattr(vid_obj, 'duration', 0)

    orig_str = seconds_to_readable_str(orig_duration) if orig_duration else "Tidak Diketahui"

    try:
        ask_st = await message.reply("Masukkan **Waktu Mulai** (Start Time).\nFormat: `HH:MM:SS` atau `MM:SS`")
        st_res = await wait_for_message(chat_id, user_id, 300)
        if not is_valid_time_format(st_res.text or ""): return await ask_st.edit_text("❌ Format waktu mulai tidak valid. Dibatalkan.")

        ask_et = await message.reply("Masukkan **Waktu Selesai** (End Time).\nFormat: `HH:MM:SS` atau `MM:SS`")
        et_res = await wait_for_message(chat_id, user_id, 300)
        if not is_valid_time_format(et_res.text or ""): return await ask_et.edit_text("❌ Format waktu selesai tidak valid. Dibatalkan.")

        start_time, end_time = (st_res.text or "").strip(), (et_res.text or "").strip()
        start_sec, end_sec   = time_string_to_seconds(start_time), time_string_to_seconds(end_time)

        if start_sec >= end_sec: return await ask_et.edit_text("❌ Waktu selesai harus lebih besar dari waktu mulai.")
        if orig_duration > 0 and end_sec > orig_duration: return await ask_et.edit_text(f"❌ Waktu selesai melebihi durasi video (`{orig_str}`).")

        dur_str = seconds_to_readable_str(end_sec - start_sec)
        
        # [FIX HIGH] Menggunakan Reply Keyboard agar merespons secara INSTAN!
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="✅ Mulai Pangkas"), KeyboardButton(text="❌ Batal")]
        ], resize_keyboard=True, one_time_keyboard=True)
        
        conf_msg = await message.reply(
            f"**✂️ KONFIRMASI PANGKAS VIDEO**\n\n"
            f"⏳ Durasi Asli: `{orig_str}`\n"
            f"🎬 Waktu Mulai: `{start_time}`\n"
            f"🏁 Waktu Selesai: `{end_time}`\n"
            f"✂️ Hasil: `{dur_str}`\n\n"
            "Lanjutkan?",
            reply_markup=kb
        )
        
        press = await wait_for_message(chat_id, user_id, 120)
        
        if "batal" in (press.text or "").lower():
             return await message.reply("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
             
        await message.reply("✅ Mempersiapkan proses...", reply_markup=ReplyKeyboardRemove())
        
    except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis, proses dibatalkan.")
    except Exception as e:
        LOGGER.error(f"/trim conversation error: {e}", exc_info=True)
        return await safe_reply(message, f"❌ Error: `{e}`")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.trim, custom_file_name)
    ps.trim_start, ps.trim_end = start_time, end_time
    await get_thumbnail(ps, [f"/trim{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  /split
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"split{CMD_SUFFIX}"))
async def _split_video(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    video_event_for_task, orig_duration = None, 0

    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("Kirim Video atau URL yang ingin dibagi (split).")
            resp = await wait_for_message(chat_id, user_id, 120)
            if resp.video or resp.document: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await ask_msg.edit_text("Input tidak valid. Dibatalkan.")
        except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")

    video_event_for_task = link
    if not isinstance(link, str) and (link.video or link.document):
        vid_obj = link.video or link.document
        orig_duration = getattr(vid_obj, 'duration', 0)

    orig_str = seconds_to_readable_str(orig_duration) if orig_duration else "Tidak Diketahui"
    split_mode = split_value = None

    try:
        # [FIX HIGH] Menggunakan Reply Keyboard agar instan
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="⏱ Berdasarkan Durasi"), KeyboardButton(text="🔢 Berdasarkan Jumlah Bagian")],
            [KeyboardButton(text="📦 Berdasarkan Ukuran Berkas"), KeyboardButton(text="❌ Batal")]
        ], resize_keyboard=True, one_time_keyboard=True)
        
        mode_msg = await message.reply("**Pilih Mode Pembagian Video:**", reply_markup=kb)
        
        press = await wait_for_message(chat_id, user_id, 300)
        cb = (press.text or "").lower()
        
        if "batal" in cb:
            return await message.reply("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())

        split_mode = "parts" 
        if "durasi" in cb: split_mode = "duration"
        elif "ukuran" in cb: split_mode = "size"
        
        ask_val = await message.reply(f"Masukkan nilai pembagian:", reply_markup=ReplyKeyboardRemove())
        val_res = await wait_for_message(chat_id, user_id, 120)
        if not (val_res.text or "").isdigit(): return await ask_val.edit_text("Input tidak valid. Dibatalkan.")
        split_value = int(val_res.text)

        info = f"Menjadi `{split_value}` bagian"
        
        kb2 = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="✅ Mulai Bagi"), KeyboardButton(text="❌ Batal")]
        ], resize_keyboard=True, one_time_keyboard=True)
        
        conf_msg = await message.reply(
            f"**✂️ KONFIRMASI PEMBAGIAN VIDEO**\n\n"
            f"⏳ Durasi Asli: `{orig_str}`\n"
            f"⚙️ Mode: `{split_mode.capitalize()}`\n"
            f"📊 Pengaturan: {info}\n\nLanjutkan?",
            reply_markup=kb2
        )
        
        press2 = await wait_for_message(chat_id, user_id, 120)
        if "batal" in (press2.text or "").lower():
            return await message.reply("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        await message.reply("✅ Mempersiapkan pembagian...", reply_markup=ReplyKeyboardRemove())
        
    except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")
    except Exception as e:
        LOGGER.error(f"/split error: {e}", exc_info=True)
        return await safe_reply(message, f"❌ Error: `{e}`")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.split, custom_file_name)
    ps.split_mode, ps.split_value = split_mode, split_value
    await get_thumbnail(ps, [f"/split{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  /cut
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"cut{CMD_SUFFIX}"))
async def _cut_video(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    video_event_for_task   = None

    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("Kirim Video atau URL yang bagiannya ingin dibuang.")
            resp = await wait_for_message(chat_id, user_id, 120)
            if resp.video or resp.document: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await ask_msg.edit_text("Input tidak valid. Dibatalkan.")
        except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")

    video_event_for_task = link
    cut_ranges = []

    async def _menu_text():
        body  = "**Segmen yang akan Dibuang:**\n"
        if not cut_ranges: body += "*(Belum ada)*\n"
        else:
            for s, e in cut_ranges: body += f"• `{seconds_to_readable_str(s)}` - `{seconds_to_readable_str(e)}`\n"
        return "**✂️ Potong Segmen Video**\n\n" + body

    try:
        menu_msg = await message.reply(await _menu_text())
        while True:
            ask_cut = await message.reply("Kirim rentang waktu yang akan dibuang. (Atau balas `Selesai`)\n**Format:** `MM:SS-MM:SS`")
            resp = await wait_for_message(chat_id, user_id, 600)
            txt = (resp.text or "").lower()
            
            if txt == "selesai":
                if not cut_ranges: return await message.reply("Tidak ada segmen. Dibatalkan.")
                await menu_msg.edit_text("✅ Mempersiapkan proses cut...")
                break
                
            parsed = parse_single_cut_range(resp.text or "")
            if parsed:
                cut_ranges.append(parsed)
                await ask_cut.delete()
                await menu_msg.edit_text(await _menu_text())
            else:
                err = await message.reply("⚠️ Format tidak valid. Coba lagi.")
                await asyncio.sleep(2)
                await err.delete()

    except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")
    except Exception as e:
        LOGGER.error(f"/cut error: {e}", exc_info=True)
        return await safe_reply(message, f"❌ Error: `{e}`")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.cut, custom_file_name)
    ps.cut_ranges = cut_ranges
    await get_thumbnail(ps, [f"/cut{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  /rotate
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"rotate{CMD_SUFFIX}"))
async def _rotate_video(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    video_event_for_task   = None

    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("Kirim Video atau URL yang ingin diputar/dibalik.")
            resp = await wait_for_message(chat_id, user_id, 120)
            if resp.video or resp.document: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await ask_msg.edit_text("Input tidak valid. Dibatalkan.")
        except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")

    video_event_for_task = link
    rotate_option = None

    try:
        ask_rt = await message.reply("Masukkan derajat rotasi (`45` atau `-45`) atau filter FFmpeg kustom.\nContoh: `45`, `hflip,vflip`, `transpose=1` (90°)")
        resp = await wait_for_message(chat_id, user_id, 120)
        inp  = (resp.text or "").strip()
        try:
            angle = float(inp)
            rotate_option = f"rotate={angle}*PI/180"
        except ValueError: rotate_option = inp
            
        await ask_rt.edit_text(f"✅ Filter: `{rotate_option}`. Mempersiapkan...")

    except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")
    except Exception as e:
        LOGGER.error(f"/rotate error: {e}", exc_info=True)
        return await safe_reply(message, f"❌ Error: `{e}`")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.rotate, custom_file_name)
    ps.rotate_option = rotate_option
    await get_thumbnail(ps, [f"/rotate{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  /crop
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"crop{CMD_SUFFIX}"))
async def _crop_video(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    video_event_for_task, crop_params = None, None

    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("Kirim Video atau URL yang ingin di-crop.")
            resp = await wait_for_message(chat_id, user_id, 120)
            if resp.video or resp.document: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await ask_msg.edit_text("Input tidak valid atau bukan video. Dibatalkan.")
        except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")

    video_event_for_task = link

    try:
        ask_crop = await message.reply("Masukkan parameter Crop FFmpeg.\nContoh: `in_w:in_w*9/16` (Layar Lebar) atau `1280:720:0:0` (Kustom)")
        resp = await wait_for_message(chat_id, user_id, 120)
        crop_params = f"crop={(resp.text or '').strip()}"
        await ask_crop.edit_text(f"✅ Parameter: `{crop_params}`. Mempersiapkan...")
        
    except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")
    except Exception as e:
        LOGGER.error(f"/crop error: {e}", exc_info=True)
        return await safe_reply(message, f"❌ Error: `{e}`")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.crop, custom_file_name)
    ps.crop_params = crop_params
    await get_thumbnail(ps, [f"/crop{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  /autocrop
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"autocrop{CMD_SUFFIX}"))
async def _autocrop_video(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    video_event_for_task   = None

    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("Kirim Video atau URL untuk autocrop.")
            resp = await wait_for_message(chat_id, user_id, 120)
            if resp.video or resp.document: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await ask_msg.edit_text("Input tidak valid. Dibatalkan.")
        except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")

    video_event_for_task = link

    try:
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Ya"), KeyboardButton(text="Batal")]], resize_keyboard=True, one_time_keyboard=True)
        menu_msg = await message.reply("**✨ Autocrop** akan otomatis membuang black bars dari video. Lanjutkan?", reply_markup=kb)
        resp = await wait_for_message(chat_id, user_id, 120)
        
        if "batal" in (resp.text or "").lower(): return await message.reply("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        await message.reply("✅ Mempersiapkan autocrop...", reply_markup=ReplyKeyboardRemove())
        
    except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")
    except Exception as e:
        LOGGER.error(f"/autocrop error: {e}", exc_info=True)
        return await safe_reply(message, f"❌ Error: `{e}`")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.autocrop, custom_file_name)
    await get_thumbnail(ps, [f"/autocrop{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(message)
    

# ═══════════════════════════════════════════════════════════════════════
#  /extension
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"extension{CMD_SUFFIX}"))
async def _extension_changer(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    video_event_for_task, new_extension = None, None

    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("Kirim file (video/audio/subtitle) yang ekstensinya ingin diubah.")
            resp = await wait_for_message(chat_id, user_id, 120)
            if resp.document or resp.video or resp.audio: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await ask_msg.edit_text("Input tidak valid. Dibatalkan.")
        except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")

    video_event_for_task = link

    file_type = "unknown"
    if not isinstance(link, str) and (link.document or link.video or link.audio):
        doc = link.document or link.video or link.audio
        mime, name = doc.mime_type or "", getattr(doc, 'file_name', '') or ""
        if "video" in mime:   file_type = "video"
        elif "audio" in mime: file_type = "audio"
        elif any(name.endswith(e) for e in [".srt", ".ass", ".vtt", ".sub"]): file_type = "subtitle"

    if file_type == "unknown": return await safe_reply(message, "❌ Jenis file tidak didukung.")

    try:
        ask_ext = await message.reply(f"Anda mengirim berkas **{file_type}**. Kirim ekstensi baru (tanpa titik, contoh: `mp4` atau `mkv`):")
        resp = await wait_for_message(chat_id, user_id, 120)
        new_extension = (resp.text or "").strip().lstrip(".")
        await ask_ext.edit_text(f"✅ Berkas akan diubah ke `.{new_extension}`. Mempersiapkan...")
        
    except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")
    except Exception as e:
        LOGGER.error(f"/extension error: {e}", exc_info=True)
        return await safe_reply(message, f"❌ Error: `{e}`")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.extension, custom_file_name)
    ps.new_extension = new_extension
    await get_thumbnail(ps, [f"/extension{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  /extract
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"extract{CMD_SUFFIX}"))
async def _extract_streams(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    video_event_for_task   = None

    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("Kirim Video atau URL yang stream-nya ingin diekstrak.")
            resp = await wait_for_message(chat_id, user_id, 120)
            if resp.video or resp.document: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await ask_msg.edit_text("Input tidak valid. Dibatalkan.")
        except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")

    video_event_for_task = link
    dling_msg = await message.reply("🔽 Mengunduh berkas untuk dianalisis...")

    async def _download_temp():
        from bot_helper.Others.Names import Names as N_
        import time
        temp_ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, N_.pre_download)
        
        # [FIX HIGH] Bypass antrean untuk file Telegram agar unduhan instan dan anti-stuck!
        if not isinstance(link, str):
            target = link.video or link.document
            dest = f"{temp_ps.dir}/{target.file_name or 'video.mp4'}"
            await Telegram.AIOGRAM_BOT.download(target, destination=dest)
            temp_ps.append_dw_files(dest)
            return dest, temp_ps

        # Download jika URL menggunakan Antrean
        funcs = [["Aria", Aria2.add_aria2c_download, [link, temp_ps, False, False, False, False]]]
        await add_task({"process_status": temp_ps, "functions": funcs})
        
        waited = 0
        while any(t["process_status"].process_id == temp_ps.process_id for t in working_task + list(queued_task)):
            if waited > 3600: break
            await asyncio.sleep(2)
            waited += 2
        return (temp_ps.send_files[-1] if temp_ps.send_files else None), temp_ps

    input_file, temp_ps = await _download_temp()

    if not input_file or not exists(input_file):
        await dling_msg.edit_text("❌ Gagal mengunduh berkas.")
        try: await asyncio.to_thread(rmtree, temp_ps.dir, ignore_errors=True)
        except Exception: pass
        return
    await dling_msg.delete()

    try:
        proc = await create_subprocess_exec("ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", input_file, stdout=asyncioPIPE)
        stdout, _ = await proc.communicate()
        all_streams = json_loads(stdout.decode("utf-8", "replace")).get("streams", [])
    except Exception as e: return await safe_reply(message, f"❌ Gagal menganalisis video: `{e}`")

    audio_subs = [s for s in all_streams if s.get("codec_type") == "audio"]
    sub_subs   = [s for s in all_streams if s.get("codec_type") == "subtitle"]

    if not audio_subs and not sub_subs: return await safe_reply(message, "❌ Tidak ada stream audio/subtitle.")

    selected = []
    try:
        ask_ex = await message.reply("Masukkan Index Stream yang ingin diekstrak (contoh: `1` atau `2,3`).\n(Balas dengan angka index)")
        resp = await wait_for_message(chat_id, user_id, 120)
        selected = [int(i) for i in (resp.text or "").split(",") if i.strip().isdigit()]
        await ask_ex.edit_text("✅ Mempersiapkan ekstraksi...")
    except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")
    except Exception as e:
        LOGGER.error(f"/extract error: {e}", exc_info=True)
        return await safe_reply(message, f"❌ Error: `{e}`")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.extract, custom_file_name)
    ps.extract_maps = [f"0:{s}" for s in selected]
    ps.move_send_files(temp_ps.send_files)
    try: await asyncio.to_thread(rmtree, temp_ps.dir, ignore_errors=True)
    except Exception: pass

    final_task = {"process_status": ps, "functions": []}
    await submit_task(final_task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  /mediainfo
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"mediainfo{CMD_SUFFIX}"))
async def _media_info(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, _ = await get_link(message)
    video_event_for_task = None

    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("Kirim berkas media atau URL untuk analisis.")
            resp = await wait_for_message(chat_id, user_id, 120)
            if resp.video or resp.document or resp.audio: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await ask_msg.edit_text("Input tidak valid. Dibatalkan.")
        except asyncio.TimeoutError: return await safe_reply(message, "⏱ Waktu habis.")

    video_event_for_task = link
    dling_msg = await message.reply("🔽 Mengunduh berkas...")

    async def _download_temp():
        from bot_helper.Others.Names import Names as N_
        import time
        temp_ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, N_.pre_download)
        
        # [FIX HIGH] Bypass antrean untuk file Telegram
        if not isinstance(link, str):
            target = link.video or link.document or link.audio
            dest = f"{temp_ps.dir}/{target.file_name or 'media.mp4'}"
            await Telegram.AIOGRAM_BOT.download(target, destination=dest)
            temp_ps.append_dw_files(dest)
            return dest, temp_ps.dir

        funcs = [["Aria", Aria2.add_aria2c_download, [link, temp_ps, False, False, False, False]]]
        await add_task({"process_status": temp_ps, "functions": funcs})
        
        waited = 0
        while any(t["process_status"].process_id == temp_ps.process_id for t in working_task + list(queued_task)):
            if waited > 3600: break
            await asyncio.sleep(2)
            waited += 2
        return (temp_ps.send_files[-1] if temp_ps.send_files else None), temp_ps.dir

    input_file, temp_dir = await _download_temp()
    if not input_file or not exists(input_file):
        await dling_msg.edit_text("❌ Gagal mengunduh berkas.")
        if temp_dir:
            try:
                await asyncio.to_thread(rmtree, temp_dir, ignore_errors=True)
            except Exception:
                pass
        return

    await dling_msg.edit_text("🔍 Menganalisis berkas...")

    try:
        proc = await create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", "-show_chapters", input_file,
            stdout=asyncioPIPE, stderr=asyncioPIPE,
        )
        stdout, _ = await proc.communicate()
        media_info = json_loads(stdout.decode("utf-8", "replace"))

        fname       = input_file.split("/")[-1]
        fmt         = media_info.get("format", {})
        duration    = float(fmt.get("duration", 0))
        size        = int(fmt.get("size", 0))
        bit_rate    = int(float(fmt.get("bit_rate", 0)))

        txt  = f"❏ **`{fname}`**\n\n"
        txt += f"├ **Ukuran**: {get_human_size(size)}\n"
        txt += f"├ **Durasi**: {seconds_to_readable_str(int(duration))}\n"
        txt += f"├ **Bitrate**: {int(bit_rate/1000)} kb/s\n"
        txt += f"└ **Wadah**: `{fmt.get('format_name','N/A').upper()}`\n\n"

        for s in media_info.get("streams", []):
            ct      = s.get("codec_type")
            si      = s.get("index")
            codec   = s.get("codec_name", "N/A")
            lang    = s.get("tags", {}).get("language", "und")
            title_  = s.get("tags", {}).get("title")
            sbr     = int(float(s.get("bit_rate", 0)))
            if ct == "video":
                txt += f"🎬 **Video (#{si})**\n"
                txt += f"├ **Codec**: `{codec.upper()}`\n"
                txt += f"├ **Resolusi**: {s.get('width')}x{s.get('height')}\n"
                txt += f"├ **Bitrate**: {int(sbr/1000)} kb/s\n"
                txt += f"└ **FPS**: {s.get('r_frame_rate','N/A')}\n\n"
            elif ct == "audio":
                txt += f"🎧 **Audio (#{si})**\n"
                txt += f"├ **Bahasa**: `{lang.upper()}`\n"
                txt += f"├ **Codec**: `{codec.upper()}`\n"
                txt += f"├ **Channel**: `{s.get('channel_layout','N/A')}`\n"
                txt += f"└ **Bitrate**: {int(sbr/1000)} kb/s\n\n"
            elif ct == "subtitle":
                txt += f"📖 **Subtitle (#{si})**\n"
                txt += f"├ **Bahasa**: `{lang.upper()}`\n"
                if title_:
                    txt += f"├ **Judul**: `{title_}`\n"
                txt += f"└ **Codec**: `{codec.upper()}`\n\n"

        for ch in media_info.get("chapters", []):
            s_t = seconds_to_readable_str(int(float(ch.get("start_time", 0))))
            e_t = seconds_to_readable_str(int(float(ch.get("end_time", 0))))
            ct_ = ch.get("tags", {}).get("title", f"Chapter {ch.get('id')}")
            txt += f"🔖 `{s_t}` - `{e_t}`: `{ct_}`\n"

        if len(txt) > 4096:
            path = f"{temp_dir}/mediainfo.txt"
            def write_file():
                with open(path, "w", encoding="utf-8") as f:
                    f.write(txt.replace("**", "").replace("`", ""))
            await asyncio.to_thread(write_file)
            await dling_msg.delete()
            await Telegram.AIOGRAM_BOT.send_document(chat_id, document=FSInputFile(path),
                                          caption=f"📄 MediaInfo untuk `{fname}`",
                                          reply_to_message_id=message.message_id)
        else:
            await dling_msg.edit_text(txt, parse_mode="Markdown")

    except Exception as e:
        await dling_msg.edit_text(f"❌ Error saat analisis: `{e}`")
        LOGGER.error(f"/mediainfo error: {e}", exc_info=True)
    finally:
        if temp_dir:
            try:
                await asyncio.to_thread(rmtree, temp_dir, ignore_errors=True)
            except Exception:
                pass
