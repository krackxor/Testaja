"""
╔══════════════════════════════════════════════════════════════════════╗
║    bot/advanced_media_handlers.py                                    ║
║    Advanced Media Handlers (Aiogram 3.x / Inline Waiter)             ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v4.2:                                                     ║
║  [RESTORED] Mengembalikan 100% kode asli (tanpa ada yang terhapus).  ║
║  [NEW] INTEGRASI SISTEM POIN! Memotong saldo sebelum eksekusi task.  ║
║  [UX PREMIUM] Implementasi API Warna Tombol Native Telegram 9.4+     ║
║  [UX PREMIUM] Standardisasi Hierarki Emoji (❌ Error, ⏳ Proses).      ║
║  [UX PREMIUM] Penambahan Ikon Konteks pada perintah input file.      ║
║  [UX PREMIUM] Menambahkan Kotak Konfirmasi Detail di SEMUA perintah  ║
║  [UX PREMIUM] Menerapkan Auto-Delete agar chat tetap bersih & rapi.  ║
║  [UX PREMIUM] Menerapkan Reply Keyboard pendek yang konsisten.       ║
║  [FIX HIGH] Extract & Mediainfo Bypass (Instan Download native TG)   ║
║  [UPDATE] Konsistensi Ikon, Teks Batal, dan Timeout selaras 100%.    ║
║  [HOTFIX] /extract Terintegrasi: Bisa ekstrak Audio, Subtitle,       ║
║            Thumbnail HD, dan ZIP Frames dalam SATU MENU!             ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import time
import os
import shutil
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
from bot_helper.Database.User_Data import get_data, new_user, get_user_balance
from bot_helper.Others.Helper_Functions import (
    get_human_size, seconds_to_readable_str, time_string_to_seconds,
)
from bot_helper.Others.Names import Names
from bot_helper.Process.Process_Status import ProcessStatus
from bot_helper.Process.Running_Tasks import add_task, working_task, queued_task
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

# [NEW v4.2] Import Mesin Kasir Poin
from bot_helper.Process.point_manager import process_payment

from .shared import (
    CMD_SUFFIX, LOGGER, SAVE_TO_DATABASE,
    build_task, get_link, get_thumbnail, get_username,
    safe_reply, submit_task, update_status_message, user_auth_checker, vip_check,
    wait_for_message 
)

import re as _re

router = Router()

# ═══════════════════════════════════════════════════════════════════════
#  UI & CLEANUP HELPERS (COLOR BUTTONS ENABLED)
# ═══════════════════════════════════════════════════════════════════════

async def _clean_msgs(*msgs):
    """Menghapus pesan untuk menjaga chat tetap rapi."""
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
        elif "Ya" in opt or "✅" in opt:
            btn_style = "success"
        else:
            btn_style = "primary"
            
        row.append(KeyboardButton(text=opt, style=btn_style))
        
        if len(row) == row_width:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)

def _get_fname(link, custom_file_name: str) -> str:
    """Helper untuk mendapatkan nama file cantik untuk ditampilkan."""
    if custom_file_name: return custom_file_name
    if isinstance(link, str): return "Tautan / URL"
    doc = getattr(link, "document", None) or getattr(link, "video", None) or getattr(link, "audio", None)
    return getattr(doc, "file_name", "Berkas Media")

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

    if link == "invalid": return await safe_reply(message, "❌ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("✂️ Kirim Video atau URL yang ingin di-trim.")
            resp = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_msg) 
            if resp.video or resp.document: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await message.answer("❌ Input tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        except asyncio.TimeoutError: return await safe_reply(message, "❌ Waktu habis. Dibatalkan.")

    video_event_for_task = link
    fname = _get_fname(link, custom_file_name)
    if not isinstance(link, str) and (link.video or link.document):
        vid_obj = link.video or link.document
        orig_duration = getattr(vid_obj, 'duration', 0)

    orig_str = seconds_to_readable_str(orig_duration) if orig_duration else "Tidak Diketahui"

    try:
        kb_start = _make_reply_kb(["00:00", "❌ Batal"], 2)
        ask_st = await message.reply("Masukkan **Waktu Mulai** (Start Time).\nFormat: `HH:MM:SS` atau `MM:SS`", reply_markup=kb_start)
        st_res = await wait_for_message(chat_id, user_id, 300)
        await _clean_msgs(ask_st, st_res)
        
        if "batal" in (st_res.text or "").lower():
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        if not is_valid_time_format(st_res.text or ""): 
            return await message.answer("❌ Format waktu mulai tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())

        kb_end = _make_reply_kb([orig_str if orig_duration else "Kustom", "❌ Batal"], 2)
        ask_et = await message.reply("Masukkan **Waktu Selesai** (End Time).\nFormat: `HH:MM:SS` atau `MM:SS`", reply_markup=kb_end)
        et_res = await wait_for_message(chat_id, user_id, 300)
        await _clean_msgs(ask_et, et_res)
        
        if "batal" in (et_res.text or "").lower():
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        end_time_txt = et_res.text
        if end_time_txt == "Kustom":
            ask_cust = await message.reply("Ketik waktu selesai:", reply_markup=ReplyKeyboardRemove())
            cust_res = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_cust, cust_res)
            end_time_txt = cust_res.text
            
        if not is_valid_time_format(end_time_txt or ""): 
            return await message.answer("❌ Format waktu selesai tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())

        start_time, end_time = (st_res.text or "").strip(), (end_time_txt or "").strip()
        start_sec, end_sec   = time_string_to_seconds(start_time), time_string_to_seconds(end_time)

        if start_sec >= end_sec: 
            return await message.answer("❌ Waktu selesai harus lebih besar dari waktu mulai.", reply_markup=ReplyKeyboardRemove())
        if orig_duration > 0 and end_sec > orig_duration: 
            return await message.answer(f"❌ Waktu selesai melebihi durasi video (`{orig_str}`).", reply_markup=ReplyKeyboardRemove())

        dur_str = seconds_to_readable_str(end_sec - start_sec)
        
        kb_conf = _make_reply_kb(["✅ Pangkas", "❌ Batal"], 2)
        conf_txt = (
            f"**✂️ KONFIRMASI PANGKAS VIDEO**\n\n"
            f"🎬 File: `{fname}`\n"
            f"⏳ Durasi Asli: `{orig_str}`\n"
            f"⏱️ Waktu Mulai: `{start_time}`\n"
            f"🏁 Waktu Selesai: `{end_time}`\n"
            f"✂️ Hasil Durasi: `{dur_str}`\n\n"
            "Lanjutkan?"
        )
        conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
        press = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(conf_msg, press)
        
        if "batal" in (press.text or "").lower():
             return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
             
        # [NEW v4.2] MESIN KASIR: POTONG SALDO POIN
        payment = await process_payment(user_id=user_id, command="trim")
        if not payment["success"]:
            return await message.answer(payment["message"], reply_markup=ReplyKeyboardRemove())
            
        await message.answer(f"⏳ ✅ Mempersiapkan proses trim...\n{payment['message']}", reply_markup=ReplyKeyboardRemove())
        
    except asyncio.TimeoutError: return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        LOGGER.error(f"/trim conversation error: {e}", exc_info=True)
        return await message.answer(f"❌ Error: `{e}`", reply_markup=ReplyKeyboardRemove())

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.trim, custom_file_name)
    ps.trim_start, ps.trim_end = start_time, end_time
    ps.custom_watermark = {"enabled": False} # Bypass Setting Global
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

    if link == "invalid": return await safe_reply(message, "❌ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("🪓 Kirim Video atau URL yang ingin dibagi (split).")
            resp = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_msg) 
            if resp.video or resp.document: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await message.answer("❌ Input tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        except asyncio.TimeoutError: return await safe_reply(message, "❌ Waktu habis. Dibatalkan.")

    video_event_for_task = link
    fname = _get_fname(link, custom_file_name)
    if not isinstance(link, str) and (link.video or link.document):
        vid_obj = link.video or link.document
        orig_duration = getattr(vid_obj, 'duration', 0)

    orig_str = seconds_to_readable_str(orig_duration) if orig_duration else "Tidak Diketahui"
    split_mode = split_value = None

    try:
        kb_mode = _make_reply_kb(["⏱ Durasi", "🔢 Bagian", "📦 Ukuran", "❌ Batal"], 2)
        mode_msg = await message.reply("**Pilih Mode Pembagian Video:**", reply_markup=kb_mode)
        press = await wait_for_message(chat_id, user_id, 300)
        await _clean_msgs(mode_msg, press)
        
        cb = (press.text or "").lower()
        if "batal" in cb: return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())

        split_mode = "parts" 
        if "durasi" in cb: split_mode = "duration"
        elif "ukuran" in cb: split_mode = "size"
        
        kb_val = _make_reply_kb(["2", "3", "4", "Kustom", "❌ Batal"], 3)
        ask_val = await message.reply(f"Masukkan nilai pembagian:", reply_markup=kb_val)
        val_res = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(ask_val, val_res)
        
        val_txt = val_res.text.lower()
        if "batal" in val_txt: return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        if "kustom" in val_txt:
            ask_cust = await message.reply("Ketik angka pembagian:", reply_markup=ReplyKeyboardRemove())
            cust_res = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_cust, cust_res)
            val_txt = cust_res.text
            
        if not val_txt.isdigit(): return await message.answer("❌ Input tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        split_value = int(val_txt)

        info = f"Menjadi `{split_value}` bagian"
        
        kb_conf = _make_reply_kb(["✅ Bagi", "❌ Batal"], 2)
        conf_txt = (
            f"**🪓 KONFIRMASI PEMBAGIAN VIDEO**\n\n"
            f"🎬 File: `{fname}`\n"
            f"⏳ Durasi Asli: `{orig_str}`\n"
            f"⚙️ Mode: `{split_mode.capitalize()}`\n"
            f"📊 Target: `{info}`\n\n"
            "Lanjutkan?"
        )
        conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
        press2 = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(conf_msg, press2)
        
        if "batal" in (press2.text or "").lower():
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        # [NEW v4.2] MESIN KASIR: POTONG SALDO POIN
        payment = await process_payment(user_id=user_id, command="split")
        if not payment["success"]:
            return await message.answer(payment["message"], reply_markup=ReplyKeyboardRemove())
            
        await message.answer(f"⏳ ✅ Mempersiapkan proses pembagian...\n{payment['message']}", reply_markup=ReplyKeyboardRemove())
        
    except asyncio.TimeoutError: return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        LOGGER.error(f"/split error: {e}", exc_info=True)
        return await safe_reply(message, f"❌ Error: `{e}`")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.split, custom_file_name)
    ps.split_mode, ps.split_value = split_mode, split_value
    ps.custom_watermark = {"enabled": False} # Bypass Setting Global
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
    video_event_for_task, orig_duration = None, 0

    if link == "invalid": return await safe_reply(message, "❌ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("🔪 Kirim Video atau URL yang bagiannya ingin dibuang.")
            resp = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_msg) 
            if resp.video or resp.document: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await message.answer("❌ Input tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        except asyncio.TimeoutError: return await safe_reply(message, "❌ Waktu habis. Dibatalkan.")

    video_event_for_task = link
    fname = _get_fname(link, custom_file_name)
    if not isinstance(link, str) and (link.video or link.document):
        vid_obj = link.video or link.document
        orig_duration = getattr(vid_obj, 'duration', 0)
    orig_str = seconds_to_readable_str(orig_duration) if orig_duration else "Tidak Diketahui"
    cut_ranges = []

    def _menu_text():
        body  = "**Segmen yang akan Dibuang:**\n"
        if not cut_ranges: body += "*(Belum ada)*\n"
        else:
            for s, e in cut_ranges: body += f"• `{seconds_to_readable_str(s)}` - `{seconds_to_readable_str(e)}`\n"
        return "**✂️ Potong Segmen Video**\n\n" + body

    try:
        menu_msg = await message.reply(_menu_text())
        kb_cut = _make_reply_kb(["✅ Selesai", "❌ Batal"], 2)
        
        while True:
            ask_cut = await message.reply("Kirim rentang waktu yang akan dibuang.\n**Format:** `MM:SS-MM:SS`", reply_markup=kb_cut)
            resp = await wait_for_message(chat_id, user_id, 600)
            txt = (resp.text or "").lower()
            await _clean_msgs(ask_cut, resp)
            
            if "batal" in txt:
                await _clean_msgs(menu_msg)
                return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
                
            if "selesai" in txt:
                if not cut_ranges: 
                    await _clean_msgs(menu_msg)
                    return await message.answer("❌ Tidak ada segmen yang dipotong. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
                
                kb_conf = _make_reply_kb(["✅ Potong", "❌ Batal"], 2)
                conf_txt = (
                    f"**✂️ KONFIRMASI POTONG SEGMEN**\n\n"
                    f"🎬 File: `{fname}`\n"
                    f"⏳ Durasi Asli: `{orig_str}`\n"
                    f"🗑️ Segmen Dibuang: `{len(cut_ranges)} bagian`\n\n"
                    "Lanjutkan?"
                )
                conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
                press2 = await wait_for_message(chat_id, user_id, 120)
                await _clean_msgs(menu_msg, conf_msg, press2)
                
                if "batal" in (press2.text or "").lower():
                    return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
                    
                # [NEW v4.2] MESIN KASIR: POTONG SALDO POIN
                payment = await process_payment(user_id=user_id, command="cut")
                if not payment["success"]:
                    return await message.answer(payment["message"], reply_markup=ReplyKeyboardRemove())
                    
                await message.answer(f"⏳ ✅ Mempersiapkan proses potong...\n{payment['message']}", reply_markup=ReplyKeyboardRemove())
                break
                
            parsed = parse_single_cut_range(resp.text or "")
            if parsed:
                cut_ranges.append(parsed)
                await menu_msg.edit_text(_menu_text())
            else:
                err = await message.reply("❌ Format tidak valid. Coba lagi.")
                await asyncio.sleep(2)
                await _clean_msgs(err)

    except asyncio.TimeoutError: return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        LOGGER.error(f"/cut error: {e}", exc_info=True)
        return await safe_reply(message, f"❌ Error: `{e}`")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.cut, custom_file_name)
    ps.cut_ranges = cut_ranges
    ps.custom_watermark = {"enabled": False} # Bypass Setting Global
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

    if link == "invalid": return await safe_reply(message, "❌ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("🔃 Kirim Video atau URL yang ingin diputar/dibalik.")
            resp = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_msg) 
            if resp.video or resp.document: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await message.answer("❌ Input tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        except asyncio.TimeoutError: return await safe_reply(message, "❌ Waktu habis. Dibatalkan.")

    video_event_for_task = link
    fname = _get_fname(link, custom_file_name)
    rotate_option = None

    try:
        kb_rot = _make_reply_kb(["90", "-90", "180", "hflip", "vflip", "Kustom", "❌ Batal"], 3)
        ask_rt = await message.reply("Pilih derajat rotasi atau balik (flip):", reply_markup=kb_rot)
        resp = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(ask_rt, resp)
        
        inp = (resp.text or "").strip()
        if "batal" in inp.lower(): return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
        if "kustom" in inp.lower():
            ask_cust = await message.reply("Kirim derajat rotasi (misal `45`) atau filter kustom:", reply_markup=ReplyKeyboardRemove())
            cust_res = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_cust, cust_res)
            inp = cust_res.text.strip()
            
        try:
            angle = float(inp)
            rotate_option = f"rotate={angle}*PI/180"
        except ValueError: 
            rotate_option = inp
            
        kb_conf = _make_reply_kb(["✅ Putar", "❌ Batal"], 2)
        conf_txt = (
            f"**🔃 KONFIRMASI ROTASI VIDEO**\n\n"
            f"🎬 File: `{fname}`\n"
            f"📐 Filter: `{rotate_option}`\n\n"
            "Lanjutkan?"
        )
        conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
        press2 = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(conf_msg, press2)
        
        if "batal" in (press2.text or "").lower():
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        # [NEW v4.2] MESIN KASIR: POTONG SALDO POIN
        payment = await process_payment(user_id=user_id, command="rotate")
        if not payment["success"]:
            return await message.answer(payment["message"], reply_markup=ReplyKeyboardRemove())
            
        await message.answer(f"⏳ ✅ Mempersiapkan rotasi video...\n{payment['message']}", reply_markup=ReplyKeyboardRemove())

    except asyncio.TimeoutError: return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        LOGGER.error(f"/rotate error: {e}", exc_info=True)
        return await safe_reply(message, f"❌ Error: `{e}`")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.rotate, custom_file_name)
    ps.rotate_option = rotate_option
    ps.custom_watermark = {"enabled": False} # Bypass Setting Global
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

    if link == "invalid": return await safe_reply(message, "❌ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("📐 Kirim Video atau URL yang ingin di-crop.")
            resp = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_msg) 
            if resp.video or resp.document: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await message.answer("❌ Input tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        except asyncio.TimeoutError: return await safe_reply(message, "❌ Waktu habis. Dibatalkan.")

    video_event_for_task = link
    fname = _get_fname(link, custom_file_name)

    try:
        kb_crop = _make_reply_kb(["Lanskap (16:9)", "Potret (9:16)", "Persegi (1:1)", "Kustom", "❌ Batal"], 2)
        ask_crop = await message.reply("Pilih format Rasio Crop:", reply_markup=kb_crop)
        resp = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(ask_crop, resp)
        
        txt = (resp.text or "").strip()
        if "batal" in txt.lower(): return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
        if "Lanskap" in txt: crop_params = "crop=iw:iw*9/16"
        elif "Potret" in txt: crop_params = "crop=ih*9/16:ih"
        elif "Persegi" in txt: crop_params = "crop=min(iw\,ih):min(iw\,ih)"
        else:
            ask_cust = await message.reply("Kirim parameter crop kustom FFmpeg (contoh: `1280:720:0:0`):", reply_markup=ReplyKeyboardRemove())
            cust_res = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_cust, cust_res)
            crop_params = f"crop={cust_res.text.strip()}"
            
        kb_conf = _make_reply_kb(["✅ Crop", "❌ Batal"], 2)
        conf_txt = (
            f"**📐 KONFIRMASI CROP VIDEO**\n\n"
            f"🎬 File: `{fname}`\n"
            f"📐 Parameter: `{crop_params}`\n\n"
            "Lanjutkan?"
        )
        conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
        press2 = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(conf_msg, press2)
        
        if "batal" in (press2.text or "").lower():
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        # [NEW v4.2] MESIN KASIR: POTONG SALDO POIN
        payment = await process_payment(user_id=user_id, command="crop")
        if not payment["success"]:
            return await message.answer(payment["message"], reply_markup=ReplyKeyboardRemove())
            
        await message.answer(f"⏳ ✅ Mempersiapkan proses crop...\n{payment['message']}", reply_markup=ReplyKeyboardRemove())
        
    except asyncio.TimeoutError: return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        LOGGER.error(f"/crop error: {e}", exc_info=True)
        return await safe_reply(message, f"❌ Error: `{e}`")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.crop, custom_file_name)
    ps.crop_params = crop_params
    ps.custom_watermark = {"enabled": False} # Bypass Setting Global
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

    if link == "invalid": return await safe_reply(message, "❌ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("🎬 Kirim Video atau URL untuk autocrop.")
            resp = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_msg) 
            if resp.video or resp.document: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await message.answer("❌ Input tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        except asyncio.TimeoutError: return await safe_reply(message, "❌ Waktu habis. Dibatalkan.")

    video_event_for_task = link
    fname = _get_fname(link, custom_file_name)

    try:
        kb_conf = _make_reply_kb(["✅ Autocrop", "❌ Batal"], 2)
        conf_txt = (
            f"**✨ KONFIRMASI AUTOCROP**\n\n"
            f"🎬 File: `{fname}`\n"
            f"🗑️ Tindakan: `Menghapus bilah hitam (black bars).`\n\n"
            "Lanjutkan?"
        )
        menu_msg = await message.reply(conf_txt, reply_markup=kb_conf)
        resp = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(menu_msg, resp)
        
        if "batal" in (resp.text or "").lower(): return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
        # [NEW v4.2] MESIN KASIR: POTONG SALDO POIN
        payment = await process_payment(user_id=user_id, command="autocrop")
        if not payment["success"]:
            return await message.answer(payment["message"], reply_markup=ReplyKeyboardRemove())
            
        await message.answer(f"⏳ ✅ Mempersiapkan autocrop...\n{payment['message']}", reply_markup=ReplyKeyboardRemove())
        
    except asyncio.TimeoutError: return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        LOGGER.error(f"/autocrop error: {e}", exc_info=True)
        return await safe_reply(message, f"❌ Error: `{e}`")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.autocrop, custom_file_name)
    ps.custom_watermark = {"enabled": False} # Bypass Setting Global
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

    if link == "invalid": return await safe_reply(message, "❌ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("📁 Kirim file (video/audio/subtitle) yang ekstensinya ingin diubah.")
            resp = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_msg) 
            if resp.document or resp.video or resp.audio: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await message.answer("❌ Input tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        except asyncio.TimeoutError: return await safe_reply(message, "❌ Waktu habis. Dibatalkan.")

    video_event_for_task = link
    fname = _get_fname(link, custom_file_name)

    file_type = "unknown"
    if not isinstance(link, str) and (link.document or link.video or link.audio):
        doc = link.document or link.video or link.audio
        mime, name = doc.mime_type or "", getattr(doc, 'file_name', '') or ""
        if "video" in mime:   file_type = "video"
        elif "audio" in mime: file_type = "audio"
        elif any(name.endswith(e) for e in [".srt", ".ass", ".vtt", ".sub"]): file_type = "subtitle"

    if file_type == "unknown": return await safe_reply(message, "❌ Jenis file tidak didukung.")

    try:
        if file_type == "video": opts = ["mp4", "mkv", "avi", "mov", "Kustom", "❌ Batal"]
        elif file_type == "audio": opts = ["mp3", "m4a", "flac", "wav", "Kustom", "❌ Batal"]
        else: opts = ["srt", "ass", "vtt", "Kustom", "❌ Batal"]
        
        kb_ext = _make_reply_kb(opts, 3)
        ask_ext = await message.reply(f"Anda mengirim berkas **{file_type}**. Pilih atau kirim ekstensi baru:", reply_markup=kb_ext)
        resp = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(ask_ext, resp)
        
        txt = (resp.text or "").strip()
        if "batal" in txt.lower(): return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        if "kustom" in txt.lower():
            ask_cust = await message.reply("Ketik ekstensi kustom tanpa titik (contoh `webm`):", reply_markup=ReplyKeyboardRemove())
            cust_res = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_cust, cust_res)
            txt = cust_res.text
            
        new_extension = txt.lstrip(".")
        
        kb_conf = _make_reply_kb(["✅ Ubah", "❌ Batal"], 2)
        conf_txt = (
            f"**📁 KONFIRMASI UBAH EKSTENSI**\n\n"
            f"🎬 File Asli: `{fname}`\n"
            f"🎯 Tipe Berkas: `{file_type.capitalize()}`\n"
            f"🔄 Perubahan: `Menjadi .{new_extension}`\n\n"
            "Lanjutkan?"
        )
        conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
        press2 = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(conf_msg, press2)
        
        if "batal" in (press2.text or "").lower():
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        # [NEW v4.2] MESIN KASIR: POTONG SALDO POIN
        payment = await process_payment(user_id=user_id, command="extension")
        if not payment["success"]:
            return await message.answer(payment["message"], reply_markup=ReplyKeyboardRemove())
            
        await message.answer(f"⏳ ✅ Mempersiapkan konversi ekstensi...\n{payment['message']}", reply_markup=ReplyKeyboardRemove())
        
    except asyncio.TimeoutError: return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        LOGGER.error(f"/extension error: {e}", exc_info=True)
        return await safe_reply(message, f"❌ Error: `{e}`")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.extension, custom_file_name)
    ps.new_extension = new_extension
    ps.custom_watermark = {"enabled": False} # Bypass Setting Global
    await get_thumbnail(ps, [f"/extension{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, video_event_for_task)
    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  /extract (TERINTEGRASI: AUDIO/SUBTITLE, THUMBNAIL, FRAMES ZIP)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"extract{CMD_SUFFIX}"))
async def _extract_streams(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    video_event_for_task   = None

    if link == "invalid": return await safe_reply(message, "❌ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("🗜️ Kirim Video atau URL yang ingin diekstrak (Audio, Subtitle, Thumbnail, atau Frame).")
            resp = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_msg)
            if resp.video or resp.document: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await message.answer("❌ Input tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        except asyncio.TimeoutError: return await safe_reply(message, "❌ Waktu habis. Dibatalkan.")

    # [NEW v4.2] ANALISIS SALDO AWAL (Minimal 50 poin untuk buka menu)
    if user_id not in Config.SUDO_USERS:
        if get_user_balance(user_id) < 50:
            return await message.reply("❌ **Saldo Poin Anda kurang dari 50.**\nSilakan top-up terlebih dahulu sebelum menggunakan fitur analisa ini.")

    video_event_for_task = link
    fname = _get_fname(link, custom_file_name)
    dling_msg = await message.reply("⏳ 🔽 Mengunduh berkas untuk dianalisis...")

    async def _download_temp():
        from bot_helper.Others.Names import Names as N_
        import time
        temp_ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, N_.pre_download)
        
        if not isinstance(link, str):
            target = link.video or link.document
            dest = f"{temp_ps.dir}/{target.file_name or 'video.mp4'}"
            
            last_update = [0.0]
            async def _progress(current: int, total: int):
                now = time.time()
                if now - last_update[0] >= 2.0 and total:
                    last_update[0] = now
                    pct = current / total
                    bar = "█" * int(pct * 10) + "░" * (10 - int(pct * 10))
                    try: await dling_msg.edit_text(f"⏳ 🔽 **Mengunduh untuk dianalisis...**\n\n[{bar}] {pct*100:.1f}%\n📥 `{get_human_size(current)} / {get_human_size(total)}`")
                    except Exception: pass

            pyro_client = Telegram.PYROGRAM_CLIENT
            downloaded = False
            if pyro_client:
                try:
                    pyro_msg = await pyro_client.get_messages(link.chat.id, link.message_id)
                    await pyro_client.download_media(message=pyro_msg, file_name=dest, progress=_progress)
                    downloaded = True
                except Exception as e:
                    LOGGER.error(f"Pyrogram temp dl error: {e}")
            
            if not downloaded:
                await Telegram.AIOGRAM_BOT.download(target, destination=dest)
            
            temp_ps.append_dw_files(dest)
            return dest, temp_ps

        from bot_helper.Aria2.Aria2_Engine import Aria2
        from bot_helper.Process.Running_Tasks import add_task, working_task, queued_task
        funcs = [["Aria", Aria2.add_aria2c_download, [link, temp_ps, False, False, False, False]]]
        await add_task({"process_status": temp_ps, "functions": funcs})
        
        waited = 0
        while any(t["process_status"].process_id == temp_ps.process_id for t in working_task + list(queued_task)):
            if waited > 3600: break
            await asyncio.sleep(2)
            waited += 2
            if waited % 4 == 0:
                try: await dling_msg.edit_text(temp_ps.status_message or "⏳ 🔽 Mengunduh berkas dengan Aria2...")
                except: pass
        return (temp_ps.send_files[-1] if temp_ps.send_files else None), temp_ps

    input_file, temp_ps = await _download_temp()

    if not input_file or not exists(input_file):
        await dling_msg.edit_text("❌ Gagal mengunduh berkas.")
        try: await asyncio.to_thread(shutil.rmtree, temp_ps.dir, ignore_errors=True)
        except Exception: pass
        return

    try:
        proc = await create_subprocess_exec("ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", input_file, stdout=asyncioPIPE)
        stdout, _ = await proc.communicate()
        all_streams = json_loads(stdout.decode("utf-8", "replace")).get("streams", [])
    except Exception as e: 
        return await safe_reply(message, f"❌ Gagal menganalisis video: `{e}`")

    # Menganalisa Stream Audio & Subtitle
    txt = f"🎞️ **Info Stream `{fname}`**\n\n"
    extractable_streams = []
    for s in all_streams:
        ct = s.get("codec_type")
        si = s.get("index")
        codec = s.get("codec_name", "N/A").upper()
        lang = s.get("tags", {}).get("language", "und").upper()
        title = s.get("tags", {}).get("title", "")
        
        if ct == "video":
            icon = "🎬 Video"
            info = f"{s.get('width')}x{s.get('height')}"
        elif ct == "audio":
            icon = "🎧 Audio"
            info = f"{lang}" + (f" - {title}" if title else "")
            extractable_streams.append(s)
        elif ct == "subtitle":
            icon = "📖 Subtitle"
            info = f"{lang}" + (f" - {title}" if title else "")
            extractable_streams.append(s)
        else:
            continue
            
        txt += f"**{si}.** {icon} | `{codec}` | {info}\n"

    # MENU UTAMA EKSTRAKSI
    await dling_msg.delete()
    kb_main = _make_reply_kb(["🗜 Extract Audio/Subtitle", "🖼 Extract Thumbnail", "🎞 Extract Frames (ZIP)", "❌ Batal"], 2)
    ask_main = await message.reply(
        f"{txt}\n"
        "🗜️ **Pilih Mode Ekstraksi:**\n\n"
        "Silakan pilih apa yang ingin Anda ekstrak dari video ini melalui tombol di bawah.",
        reply_markup=kb_main
    )
    
    res_main = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ask_main, res_main)
    
    txt_main = (res_main.text or "").lower() if res_main else ""
    
    if not res_main or "batal" in txt_main:
        try: await asyncio.to_thread(shutil.rmtree, temp_ps.dir, ignore_errors=True)
        except: pass
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    # [NEW v4.2] PENAGIHAN KASIR BERDASARKAN CABANG FITUR
    cmd_to_pay = "extract" # Default 300 Poin
    if "thumbnail" in txt_main: cmd_to_pay = "genss" # 50 Poin
    elif "frames" in txt_main: cmd_to_pay = "genss" # Sementara 50 Poin
    
    payment = await process_payment(user_id, cmd_to_pay)
    if not payment["success"]:
        try: await asyncio.to_thread(shutil.rmtree, temp_ps.dir, ignore_errors=True)
        except: pass
        return await message.answer(payment["message"], reply_markup=ReplyKeyboardRemove())

    # ==========================================
    # BRANCH 1: EXTRACT THUMBNAIL
    # ==========================================
    if "thumbnail" in txt_main:
        msg_run = await message.answer(f"⏳ 🖼️ Mengekstrak Thumbnail HD...\n{payment['message']}", reply_markup=ReplyKeyboardRemove())
        out_file = f"{temp_ps.dir}/thumb_ext.jpg"
        
        cmd = f'ffmpeg -hide_banner -y -i "{input_file}" -ss 00:00:05 -vframes 1 -q:v 2 "{out_file}"'
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.communicate()
        
        if os.path.exists(out_file):
            await message.reply_photo(FSInputFile(out_file), caption="✅ Thumbnail berhasil diekstrak!")
        else:
            await message.answer("❌ Gagal mengekstrak thumbnail.")
            
        await msg_run.delete()
        try: await asyncio.to_thread(shutil.rmtree, temp_ps.dir, ignore_errors=True)
        except: pass
        return

    # ==========================================
    # BRANCH 2: EXTRACT FRAMES (ZIP)
    # ==========================================
    elif "frames" in txt_main:
        ask_int = await message.reply("🎞 **Mau ambil frame setiap berapa detik?**\n_(Ketik angka saja, contoh: `5` artinya 1 gambar setiap 5 detik)_", reply_markup=ReplyKeyboardRemove())
        res_int = await wait_for_message(chat_id, user_id, 60)
        await _clean_msgs(ask_int, res_int)
        
        interval = (res_int.text or "").strip()
        if not interval.isdigit(): interval = "5" # Default jika input ngawur
        
        msg_run = await message.answer(f"⏳ 🎞️ Sedang mengekstrak frame (1 gambar per {interval} detik) dan membuat ZIP...\n_Mohon tunggu sebentar._\n{payment['message']}")
        
        out_dir = f"{temp_ps.dir}/frames"
        os.makedirs(out_dir, exist_ok=True)
        
        cmd = f'ffmpeg -hide_banner -y -i "{input_file}" -vf "fps=1/{interval}" -q:v 2 "{out_dir}/frame_%04d.jpg"'
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.communicate()
        
        zip_path = f"{temp_ps.dir}/Frames_Extracted.zip"
        try:
            shutil.make_archive(zip_path.replace('.zip', ''), 'zip', out_dir)
            if os.path.exists(zip_path):
                await message.reply_document(FSInputFile(zip_path), caption=f"✅ Ekstrak Frame selesai! (Interval: {interval} detik)")
            else:
                await msg_run.edit_text("❌ Gagal membuat file ZIP.")
        except Exception as e:
            await msg_run.edit_text(f"❌ Terjadi kesalahan: {e}")
            
        await msg_run.delete()
        try: await asyncio.to_thread(shutil.rmtree, temp_ps.dir, ignore_errors=True)
        except: pass
        return

    # ==========================================
    # BRANCH 3: EXTRACT AUDIO / SUBTITLE
    # ==========================================
    elif "audio" in txt_main or "subtitle" in txt_main or "extract" in txt_main:
        if not extractable_streams:
            try: await asyncio.to_thread(shutil.rmtree, temp_ps.dir, ignore_errors=True)
            except: pass
            return await message.answer("❌ Tidak ada stream audio atau subtitle yang dapat diekstrak pada video ini.", reply_markup=ReplyKeyboardRemove())

        async def build_extract_kb(selected_indices):
            opts_buttons = []
            for s in extractable_streams:
                si = s.get("index")
                ct = s.get("codec_type")
                icon = "🎧" if ct == "audio" else "📖"
                btn_text = f"✅ {icon} Stream {si}" if si in selected_indices else f"{icon} Stream {si}"
                opts_buttons.append(btn_text)
            opts_buttons.append("✅ Selesai")
            opts_buttons.append("❌ Batal")
            return _make_reply_kb(opts_buttons, 2)

        selected_indices = []
        ask_ex = await message.reply(
            f"{txt}\n"
            "🗜️ **Pilih Stream untuk Diekstrak:**\n\n"
            "Tekan tombol stream di bawah. Anda bisa memilih lebih dari satu.\n"
            "Jika sudah selesai, tekan **✅ Selesai**.", 
            reply_markup=await build_extract_kb(selected_indices)
        )

        try:
            while True:
                resp = await wait_for_message(chat_id, user_id, 120)
                await _clean_msgs(resp)
                
                if not resp:
                    await _clean_msgs(ask_ex)
                    return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
                    
                msg_txt = (resp.text or "")
                if "batal" in msg_txt.lower():
                    await _clean_msgs(ask_ex)
                    try: await asyncio.to_thread(shutil.rmtree, temp_ps.dir, ignore_errors=True)
                    except: pass
                    return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
                    
                if "selesai" in msg_txt.lower():
                    await _clean_msgs(ask_ex)
                    break
                    
                match = _re.search(r'Stream (\d+)', msg_txt, _re.IGNORECASE)
                if match:
                    idx = int(match.group(1))
                    if idx in selected_indices:
                        selected_indices.remove(idx)
                    else:
                        selected_indices.append(idx)
                    
                    sel_str = ", ".join(map(str, sorted(selected_indices))) if selected_indices else "(Belum ada)"
                    try:
                        await ask_ex.edit_text(
                            f"{txt}\n"
                            f"🗜️ **Pilih Stream untuk Diekstrak:**\n\n"
                            f"✅ **Terpilih:** `Stream {sel_str}`\n\n"
                            f"Tekan tombol stream lain untuk menambah/menghapus, atau **✅ Selesai** jika sudah.",
                            reply_markup=await build_extract_kb(selected_indices)
                        )
                    except Exception:
                        pass
                else:
                    err = await message.answer("❌ Input tidak valid.")
                    await asyncio.sleep(1.5)
                    await _clean_msgs(err)

            if not selected_indices:
                try: await asyncio.to_thread(shutil.rmtree, temp_ps.dir, ignore_errors=True)
                except: pass
                return await message.answer("❌ Anda tidak memilih stream apapun. Dibatalkan.", reply_markup=ReplyKeyboardRemove())

            selected = sorted(selected_indices)
            
            kb_conf = _make_reply_kb(["✅ Ekstrak", "❌ Batal"], 2)
            idx_str = ", ".join(map(str, selected))
            conf_txt = (
                f"**🗜️ KONFIRMASI EKSTRAKSI STREAM**\n\n"
                f"🎬 File: `{fname}`\n"
                f"🔢 Index Stream: `{idx_str}`\n\n"
                "Lanjutkan?"
            )
            conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
            press2 = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(conf_msg, press2)
            
            if "batal" in (press2.text or "").lower():
                try: await asyncio.to_thread(shutil.rmtree, temp_ps.dir, ignore_errors=True)
                except: pass
                return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
                
            await message.answer(f"⏳ ✅ Mempersiapkan ekstraksi stream...\n{payment['message']}", reply_markup=ReplyKeyboardRemove())
            
        except asyncio.TimeoutError: 
            try: await asyncio.to_thread(shutil.rmtree, temp_ps.dir, ignore_errors=True)
            except: pass
            return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        except Exception as e:
            LOGGER.error(f"/extract error: {e}", exc_info=True)
            try: await asyncio.to_thread(shutil.rmtree, temp_ps.dir, ignore_errors=True)
            except: pass
            return await safe_reply(message, f"❌ Error: `{e}`")

        # Masuk antrean task normal untuk Stream
        ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.extract, custom_file_name)
        ps.extract_maps = [f"0:{s}" for s in selected]
        ps.custom_watermark = {"enabled": False} 
        ps.move_send_files(temp_ps.send_files)
        try: await asyncio.to_thread(shutil.rmtree, temp_ps.dir, ignore_errors=True)
        except Exception: pass

        final_task = {"process_status": ps, "functions": []}
        from bot_helper.Process.Running_Tasks import submit_task
        await submit_task(final_task)
        await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  /mediainfo (GRATIS)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"mediainfo{CMD_SUFFIX}"))
async def _media_info(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, _ = await get_link(message)
    video_event_for_task = None

    if link == "invalid": return await safe_reply(message, "❌ Tautan tidak valid.")
    if not link:
        try:
            ask_msg = await message.reply("ℹ️ Kirim berkas media atau URL untuk analisis.")
            resp = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_msg) 
            if resp.video or resp.document or resp.audio: link = resp
            elif (resp.text or "").startswith("http"): link = resp.text
            else: return await message.answer("❌ Input tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        except asyncio.TimeoutError: return await safe_reply(message, "❌ Waktu habis. Dibatalkan.")

    video_event_for_task = link
    dling_msg = await message.reply("⏳ 🔽 Mengunduh berkas (Analisis Gratis)...")

    async def _download_temp():
        from bot_helper.Others.Names import Names as N_
        import time
        temp_ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, N_.pre_download)
        
        if not isinstance(link, str):
            target = link.video or link.document or link.audio
            dest = f"{temp_ps.dir}/{target.file_name or 'media.mp4'}"
            
            last_update = [0.0]
            async def _progress(current: int, total: int):
                now = time.time()
                if now - last_update[0] >= 2.0 and total:
                    last_update[0] = now
                    pct = current / total
                    bar = "█" * int(pct * 10) + "░" * (10 - int(pct * 10))
                    try: await dling_msg.edit_text(f"⏳ 🔽 **Mengunduh untuk dianalisis (Gratis)...**\n\n[{bar}] {pct*100:.1f}%\n📥 `{get_human_size(current)} / {get_human_size(total)}`")
                    except Exception: pass

            pyro_client = Telegram.PYROGRAM_CLIENT
            downloaded = False
            if pyro_client:
                try:
                    pyro_msg = await pyro_client.get_messages(link.chat.id, link.message_id)
                    await pyro_client.download_media(message=pyro_msg, file_name=dest, progress=_progress)
                    downloaded = True
                except Exception as e:
                    LOGGER.error(f"Pyrogram temp dl error: {e}")
            
            if not downloaded:
                await Telegram.AIOGRAM_BOT.download(target, destination=dest)
            
            temp_ps.append_dw_files(dest)
            return dest, temp_ps.dir

        from bot_helper.Process.Running_Tasks import working_task, queued_task, add_task
        from bot_helper.Aria2.Aria2_Engine import Aria2
        funcs = [["Aria", Aria2.add_aria2c_download, [link, temp_ps, False, False, False, False]]]
        await add_task({"process_status": temp_ps, "functions": funcs})
        
        waited = 0
        while any(t["process_status"].process_id == temp_ps.process_id for t in working_task + list(queued_task)):
            if waited > 3600: break
            await asyncio.sleep(2)
            waited += 2
            if waited % 4 == 0:
                try: await dling_msg.edit_text(temp_ps.status_message or "⏳ 🔽 Mengunduh berkas dengan Aria2...")
                except: pass
        return (temp_ps.send_files[-1] if temp_ps.send_files else None), temp_ps.dir

    input_file, temp_dir = await _download_temp()
    if not input_file or not exists(input_file):
        await dling_msg.edit_text("❌ Gagal mengunduh berkas.")
        if temp_dir:
            try:
                await asyncio.to_thread(shutil.rmtree, temp_dir, ignore_errors=True)
            except Exception:
                pass
        return

    await dling_msg.edit_text("⏳ 🔍 Menganalisis berkas...")

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
                await asyncio.to_thread(shutil.rmtree, temp_dir, ignore_errors=True)
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════
#  STATUS
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"status{CMD_SUFFIX}"))
async def _status(message: Message):
    if not await user_auth_checker(message): return
    user_id = message.from_user.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)
    await update_status_message(message)
