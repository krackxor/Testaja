"""
╔══════════════════════════════════════════════════════════════════════╗
║       bot_helper/Handlers/media_handlers.py — v3.9                   ║
║       Media Processing Command Handlers (Aiogram 3.x)                ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v3.9:                                                     ║
║  [FIX] Memisahkan /compress agar lebih instan (tanpa dub/sub).       ║
║  [FIX] /watermark kini menggunakan tombol Skip yang aman dari error. ║
║  [NEW] /softmux & /softremux kini mendukung penambahan file Audio!   ║
║  [NEW PREMIUM] /convert kini 100% FULL TOMBOL! Mendukung Multi-Select║
║  [HOTFIX] /changeindex menggunakan FULL TOMBOL (Interactive Builder) ║
║  [HOTFIX] /genss dan /gensample kini FULL TOMBOL dan lepas dari      ║
║           pengaturan global!                                         ║
║  [NEW FEATURES] Mengintegrasikan /mute, /speed, /dubbing, /ext_thumb,║
║           dan /ext_frames!                                           ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import re
import os
import shutil
from json import loads as json_loads
from asyncio import create_subprocess_exec
from asyncio.subprocess import PIPE as asyncioPIPE
from os.path import exists

# ── Aiogram ───────────────────────────────────────────────────────────
from aiogram import Router, F
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile
)
from aiogram.filters import Command

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.User_Data import get_data, new_user, saveoptions, saveconfig
from bot_helper.Others.Helper_Functions import get_human_size
from bot_helper.Others.Names import Names
from bot_helper.Process.Process_Status import ProcessStatus
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config

from .shared import (
    CMD_SUFFIX, LOGGER, SAVE_TO_DATABASE,
    ask_media_OR_url, ask_text_event, ask_url, build_task,
    check_file, create_direc, finalize_multi_tasks,
    get_custom_name, get_link, get_thumbnail, get_url_from_message,
    get_username, safe_reply, submit_task, update_status_message,
    user_auth_checker, vip_check, wait_for_message
)

owner_id = Config.OWNER_ID
router = Router()

# ═══════════════════════════════════════════════════════════════════════
#  UI & CLEANUP HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def _clean_msgs(*msgs):
    for m in msgs:
        if m:
            try: await m.delete()
            except Exception: pass

def _make_reply_kb(options: list, row_width: int = 2) -> ReplyKeyboardMarkup:
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

def _get_fname(link, custom_file_name: str) -> str:
    if custom_file_name: return custom_file_name
    if isinstance(link, str): return "Tautan / URL"
    doc = getattr(link, "document", None) or getattr(link, "video", None) or getattr(link, "audio", None)
    return getattr(doc, "file_name", "Berkas Media")

def _sanitize_link_for_db(link):
    if not isinstance(link, str) and hasattr(link, 'reply_markup'):
        try: link.reply_markup = None
        except Exception: pass
    return link


# ═══════════════════════════════════════════════════════════════════════
#  MULTI-TASK SYSTEM & GENERIC FACTORY
# ═══════════════════════════════════════════════════════════════════════

async def hardmux_multi_task(multi_ps, message: Message, chat_id, user_id, process_command) -> bool:
    new_msg = await ask_media_OR_url(message, chat_id, user_id, [process_command, "stop"], "Kirim Berkas Subtitle SRT", 120, False, False, allow_magnet=False, allow_url=False)
    if not new_msg or new_msg in ["cancelled", "stopped", "batal"]: return False
    if not new_msg.document:
        await safe_reply(message, "❗ Hanya Berkas Dokumen Telegram yang Didukung")
        return False
    mime = str(new_msg.document.mime_type)
    if mime.startswith("video/") or mime.startswith("image/"):
        await safe_reply(message, "❌ Saya Membutuhkan Berkas Subtitle (SRT/ASS).")
        return False
    if new_msg.document.file_size >= 512_000:
        await safe_reply(message, "❌ Ukuran Subtitle Lebih dari 500KB")
        return False
    sub_name = new_msg.document.file_name
    create_direc(f"{multi_ps.dir}/subtitles")
    sub_dw_loc = check_file(f"{multi_ps.dir}/subtitles", sub_name)
    await Telegram.AIOGRAM_BOT.download(new_msg.document, destination=sub_dw_loc)
    multi_ps.append_subtitles(sub_dw_loc)
    return True

async def append_multi_task(process_status, process_name, cmd, message: Message) -> bool:
    multi_ps = ProcessStatus(process_status.user_id, process_status.chat_id, process_status.user_name, process_status.user_first_name, message, process_name, process_status.file_name)
    ok = True
    if process_name == Names.hardmux: ok = await hardmux_multi_task(multi_ps, message, process_status.chat_id, process_status.user_id, cmd)
    if not ok: del multi_ps; return False
    process_status.append_multi_tasks(multi_ps)
    return True

async def multi_tasks(process_status, cmd) -> bool:
    ffmpeg_funcs = [Names.compress, Names.watermark, Names.convert, Names.hardmux]
    p_text = "\n".join(f"`{p}`" for p in ffmpeg_funcs)
    q = 1; p_cmd = cmd; valid_list = ffmpeg_funcs + ["stop", "cancel", "batal"]; m_result = True; chat_message = process_status.event
    while True:
        text = f"Apa yang Harus Dilakukan dengan Hasil **{p_cmd.replace('/', '').upper()}**\n🔶 Tugas Multi Ke-{q}\n\n{p_text}\n\n🔷 Kirim `stop` untuk Proses | `batal` untuk Batalkan"
        from .shared import ask_text_list
        result = await ask_text_list(process_status.chat_id, process_status.user_id, chat_message, 120, text, valid_list)
        if not result: m_result = False; break
        msg_text = result.text.lower()
        if msg_text == "stop": break
        if msg_text in ["cancel", "batal"]: await safe_reply(result, "❌ Dibatalkan."); m_result = False; break
        if await append_multi_task(process_status, msg_text, cmd, result):
            p_cmd = msg_text; chat_message = result; q += 1
    return m_result

async def _generic_video_handler(message: Message, process_name: str, cmd_name: str):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid")
        
    if not link:
        ne = await ask_media_OR_url(message, chat_id, user_id, [f"/{cmd_name}{CMD_SUFFIX}", "stop"], "Kirim Video atau URL", 120, "video/", False)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, process_name, custom_file_name)
    await get_thumbnail(ps, [f"/{cmd_name}{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  /encode - DUBBING & HARDMUX SUPPORT (MEMAKAI GLOBAL SETTINGS)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"encode{CMD_SUFFIX}"))
async def _encode_video(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid")
        
    if not link:
        ne = await ask_media_OR_url(message, chat_id, user_id, [f"/encode{CMD_SUFFIX}", "stop"], "🎬 Kirim Video atau URL untuk di-Encode", 120, "video/", False)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    link = _sanitize_link_for_db(link)
    fname = _get_fname(link, custom_file_name)

    kb_skip = _make_reply_kb(["⏭ Skip", "❌ Batal"], 2)
    ask_sub = await message.reply("💬 Kirim file Subtitle (SRT/ASS) untuk di-Hardmux.\n\nAtau tekan tombol `⏭ Skip` jika tidak perlu.", reply_markup=kb_skip)
    sub_msg = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ask_sub)
    
    txt_sub = (sub_msg.text or "").lower() if sub_msg else ""
    if "batal" in txt_sub: return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    
    sub_path = None
    sub_name_str = "Tidak Ada"
    if "skip" not in txt_sub and hasattr(sub_msg, "document") and sub_msg.document:
        create_direc(f"./temp/subs_{user_id}")
        sub_path = check_file(f"./temp/subs_{user_id}", sub_msg.document.file_name)
        sub_name_str = sub_msg.document.file_name
        await Telegram.AIOGRAM_BOT.download(sub_msg.document, destination=sub_path)

    ask_aud = await message.reply("🎵 Kirim file Audio (MP3/M4A) untuk Dubbing.\n\nAtau tekan tombol `⏭ Skip` jika tidak perlu.", reply_markup=kb_skip)
    aud_msg = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ask_aud)
    
    txt_aud = (aud_msg.text or "").lower() if aud_msg else ""
    if "batal" in txt_aud: return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    
    aud_path = None
    aud_name_str = "Suara Asli"
    if "skip" not in txt_aud:
        aud_doc = getattr(aud_msg, "audio", None) or getattr(aud_msg, "document", None)
        if aud_doc:
            create_direc(f"./temp/auds_{user_id}")
            aud_path = check_file(f"./temp/auds_{user_id}", aud_doc.file_name or "dub.mp3")
            aud_name_str = aud_doc.file_name or "Audio Dubbing"
            await Telegram.AIOGRAM_BOT.download(aud_doc, destination=aud_path)

    kb_conf = _make_reply_kb(["✅ Encode", "❌ Batal"], 2)
    conf_txt = (
        f"**⚙️ KONFIRMASI ENCODE VIDEO**\n\n"
        f"🎬 File: `{fname}`\n"
        f"💬 Subtitle: `{sub_name_str}`\n"
        f"🎵 Audio: `{aud_name_str}`\n\n"
        "Lanjutkan?"
    )
    conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
    press = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(conf_msg, press)
    
    if not press or "batal" in (press.text or "").lower():
         return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
         
    await message.answer("✅ Mempersiapkan proses encode...", reply_markup=ReplyKeyboardRemove())

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, "encode", custom_file_name)
    if sub_path: ps.append_subtitles(sub_path)
    if aud_path: ps.custom_dub_audio = aud_path 

    await get_thumbnail(ps, [f"/encode{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)

    if get_data().get(user_id, {}).get("multi_tasks"):
        if not await multi_tasks(ps, f"/encode{CMD_SUFFIX}"): del ps; return
        finalize_multi_tasks(ps)

    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  /compress - INSTAN (TANPA SUB / AUDIO)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"compress{CMD_SUFFIX}"))
async def _compress_video(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid")
        
    if not link:
        ne = await ask_media_OR_url(message, chat_id, user_id, [f"/compress{CMD_SUFFIX}", "stop"], "🎬 Kirim Video atau URL untuk di-Compress", 120, "video/", False)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    link = _sanitize_link_for_db(link)
    fname = _get_fname(link, custom_file_name)

    kb_conf = _make_reply_kb(["✅ Compress", "❌ Batal"], 2)
    conf_txt = (
        f"**⚙️ KONFIRMASI COMPRESS VIDEO**\n\n"
        f"🎬 File: `{fname}`\n\n"
        "Lanjutkan?"
    )
    conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
    press = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(conf_msg, press)
    
    if not press or "batal" in (press.text or "").lower():
         return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
         
    await message.answer("✅ Mempersiapkan proses compress...", reply_markup=ReplyKeyboardRemove())

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.compress, custom_file_name)

    await get_thumbnail(ps, [f"/compress{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)

    if get_data().get(user_id, {}).get("multi_tasks"):
        if not await multi_tasks(ps, f"/compress{CMD_SUFFIX}"): del ps; return
        finalize_multi_tasks(ps)

    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  /convert - MANDIRI & BERANTAI FULL TOMBOL (MULTI SELECT)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"convert{CMD_SUFFIX}"))
async def _convert_video(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid")
        
    if not link:
        ne = await ask_media_OR_url(message, chat_id, user_id, [f"/convert{CMD_SUFFIX}", "stop"], "📺 Kirim Video atau URL untuk di-Convert", 120, "video/", False)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    link = _sanitize_link_for_db(link)
    fname = _get_fname(link, custom_file_name)

    resolutions = []
    opts_buttons = ["240", "360", "480", "540", "720", "1080", "1440", "2160", "2880", "3240", "4320", "✅ Selesai", "❌ Batal"]
    
    ask_res = await message.reply(
        "📺 **Pilih Resolusi Konversi**\n\n"
        "Silakan tekan tombol angka di bawah (240 hingga 4320).\nAnda bisa menekan beberapa tombol sekaligus.\n"
        "Jika sudah selesai memilih, tekan tombol **✅ Selesai**.", 
        reply_markup=_make_reply_kb(opts_buttons, 4)
    )
    
    while True:
        res_msg = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(res_msg) 
        
        if res_msg is None: 
            await _clean_msgs(ask_res)
            return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        txt = (res_msg.text or "").lower()
        if "batal" in txt:
            await _clean_msgs(ask_res)
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        if "selesai" in txt:
            await _clean_msgs(ask_res)
            break
            
        nums = re.findall(r'\d+', txt)
        if nums:
            for n in nums:
                res = int(n)
                if res in resolutions:
                    resolutions.remove(res)
                else:
                    resolutions.append(res)
            
            sorted_res = sorted(resolutions, reverse=True)
            res_str = ", ".join([f"{r}p" for r in sorted_res]) if sorted_res else "(Belum ada)"
            try:
                await ask_res.edit_text(
                    f"📺 **Pilih Resolusi Konversi**\n\n"
                    f"✅ **Terpilih:** `{res_str}`\n\n"
                    f"Tekan tombol angka lain untuk menambah/menghapus, atau tekan **✅ Selesai** jika sudah."
                )
            except Exception:
                pass 
        else:
            err = await message.answer("❌ Input tidak valid.")
            await asyncio.sleep(1.5)
            await _clean_msgs(err)

    if not resolutions:
        return await message.answer("❌ Anda tidak memilih resolusi apapun. Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    sorted_res = sorted(resolutions, reverse=True)
    res_str = ", ".join([f"{r}p" for r in sorted_res])
    
    kb_conf = _make_reply_kb(["✅ Convert", "❌ Batal"], 2)
    conf_txt = (
        f"**📺 KONFIRMASI KONVERSI RESOLUSI**\n\n"
        f"🎬 File: `{fname}`\n"
        f"🎯 Output File: `{len(sorted_res)} Resolusi ({res_str})`\n\n"
        "Lanjutkan?"
    )
    conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
    press = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(conf_msg, press)
    
    if not press or "batal" in (press.text or "").lower():
         return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    await saveconfig(user_id, "convert", "convert_list", sorted_res, SAVE_TO_DATABASE)
         
    await message.answer(f"✅ Mengantrekan proses konversi massa ({res_str})...", reply_markup=ReplyKeyboardRemove())

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.convert, custom_file_name)
    ps.convert_quality = str(sorted_res[0])
    ps.convert_list = sorted_res 
    ps.video_resolution = str(sorted_res[0])
    ps.custom_watermark = {"enabled": False}

    await get_thumbnail(ps, [f"/convert{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)

    if get_data().get(user_id, {}).get("multi_tasks"):
        if not await multi_tasks(ps, f"/convert{CMD_SUFFIX}"): del ps; return
        finalize_multi_tasks(ps)

    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  /watermark - MANDIRI & FULL INTERAKTIF
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"watermark{CMD_SUFFIX}"))
async def _add_watermark_interactive(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid")
        
    if not link:
        ne = await ask_media_OR_url(message, chat_id, user_id, [f"/watermark{CMD_SUFFIX}", "stop"], "🛺 Kirim Video atau URL untuk diberi Watermark", 120, "video/", False)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    link = _sanitize_link_for_db(link)
    fname = _get_fname(link, custom_file_name)
    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.watermark, custom_file_name)

    kb_mode = _make_reply_kb(["🖼️ Gambar / Logo", "✍️ Teks", "❌ Batal"], 2)
    mode_msg = await message.reply("🛺 **Pilih Mode Watermark:**", reply_markup=kb_mode)
    res_mode = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(mode_msg, res_mode)
    
    if not res_mode or "batal" in (res_mode.text or "").lower(): return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    
    mode = "image" if "gambar" in (res_mode.text or "").lower() else "text"
    custom_wm = {"type": mode, "enabled": True}
    wm_info_str = ""
    
    if mode == "image":
        img_msg = await ask_media_OR_url(message, chat_id, user_id, ["stop", "batal"], "🖼️ Kirim file Gambar (PNG/JPG) untuk Watermark.", 120, "photo/", False)
        if not img_msg or img_msg in ["stopped", "cancelled", "batal"]: return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
        doc = img_msg.photo[-1] if img_msg.photo else img_msg.document
        create_direc(f"./temp/wm_{user_id}")
        wm_path = f"./temp/wm_{user_id}/logo.png"
        await Telegram.AIOGRAM_BOT.download(doc, destination=wm_path)
        custom_wm["image"] = {"path": wm_path}
        wm_info_str = "Logo Kustom (Gambar)"
    else:
        txt_msg = await ask_text_event(chat_id, user_id, message, 60, "✍️ Kirim teks untuk Watermark:", message_hint=None)
        if not txt_msg: return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
        kb_skip = _make_reply_kb(["⏭ Skip", "❌ Batal"], 2)
        
        ask_font = await message.reply("🔤 Kirim file Font (.ttf/.otf)\n\nAtau tekan tombol `⏭ Skip` untuk memakai font standar.", reply_markup=kb_skip)
        font_msg = await wait_for_message(chat_id, user_id, 60)
        await _clean_msgs(ask_font)
        
        txt_fmsg = (font_msg.text or "").lower() if font_msg else ""
        if not font_msg or "batal" in txt_fmsg: 
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
        font_path = None
        if "skip" not in txt_fmsg and hasattr(font_msg, "document") and font_msg.document:
            create_direc(f"./temp/wm_{user_id}")
            font_path = f"./temp/wm_{user_id}/custom_font.ttf"
            await Telegram.AIOGRAM_BOT.download(font_msg.document, destination=font_path)
            
        ask_color = await message.reply("🎨 Kirim warna teks (contoh: `white`, `red`, `yellow`, `#FF0000`)\n\nAtau tekan tombol `⏭ Skip` untuk warna default:", reply_markup=kb_skip)
        color_msg = await wait_for_message(chat_id, user_id, 60)
        await _clean_msgs(ask_color)
        
        txt_cmsg = (color_msg.text or "").lower() if color_msg else ""
        if not color_msg or "batal" in txt_cmsg: 
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
        color = "white"
        if "skip" not in txt_cmsg:
            color = color_msg.text.strip()
        
        custom_wm["text"] = {"content": txt_msg.text, "font_path": font_path, "color": color, "size": 32}
        wm_info_str = f"Teks: '{txt_msg.text}' ({color})"

    kb_pos = _make_reply_kb(["↖️", "⬆️", "↗️", "⬅️", "⏺️", "➡️", "↙️", "⬇️", "↘️"], 3)
    pos_msg = await message.reply("📍 Pilih Posisi Watermark (Gunakan Tombol Ikon):", reply_markup=kb_pos)
    pos_resp = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(pos_msg, pos_resp)
    
    pos_map = {
        "↖️": "top_left", "⬆️": "top_center", "↗️": "top_right",
        "⬅️": "middle_left", "⏺️": "middle_center", "➡️": "middle_right",
        "↙️": "bottom_left", "⬇️": "bottom_center", "↘️": "bottom_right"
    }
    pos = pos_map.get((pos_resp.text or "").strip(), "bottom_right") if pos_resp else "bottom_right"
    
    if mode == "image": custom_wm["image"]["position"] = pos
    else: custom_wm["text"]["position"] = pos
    
    kb_conf = _make_reply_kb(["✅ Watermark", "❌ Batal"], 2)
    conf_txt = (
        f"**🛺 KONFIRMASI WATERMARK**\n\n"
        f"🎬 File: `{fname}`\n"
        f"🎨 Mode: `{mode.capitalize()}`\n"
        f"📍 Posisi: `{pos}`\n"
        f"📌 Info: `{wm_info_str}`\n\n"
        "Lanjutkan?"
    )
    conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
    press = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(conf_msg, press)
    
    if not press or "batal" in (press.text or "").lower():
         return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
         
    await message.answer("✅ Mempersiapkan proses watermark...", reply_markup=ReplyKeyboardRemove())
    
    ps.custom_watermark = custom_wm

    await get_thumbnail(ps, [f"/watermark{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)

    if get_data().get(user_id, {}).get("multi_tasks"):
        if not await multi_tasks(ps, f"/watermark{CMD_SUFFIX}"): del ps; return
        finalize_multi_tasks(ps)

    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  MERGE
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"merge{CMD_SUFFIX}"))
async def _merge_videos(message: Message):
    if not await vip_check(message): return
    user_id = message.from_user.id
    chat_id = message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    custom_file_name = await get_custom_name(message)
    ps   = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.merge, custom_file_name)
    task = {"process_status": ps, "functions": []}
    idx  = 1

    kb_action = _make_reply_kb(["✅ Selesai", "❌ Batal"], 2)

    while True:
        ask_msg = await message.reply(f"🎬 Kirim Video/URL No {idx}\n\nTekan tombol jika sudah selesai:", reply_markup=kb_action)
        ne = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(ask_msg)
        
        txt = (ne.text or "").lower() if ne.text else ""
        if "batal" in txt or txt == "/cancel":
            del ps
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        if "selesai" in txt or txt == "/stop":
            break
            
        link = await get_url_from_message(ne)
        from bot_helper.Aria2.Aria2_Engine import Aria2
        if isinstance(link, str) and (link.startswith("http") or link.startswith("magnet")):
            task["functions"].append(["Aria", Aria2.add_aria2c_download, [link, ps, False, False, False, False]])
            idx += 1
        elif ne.video or ne.document:
            task["functions"].append(["TG", [ne]])
            idx += 1
        else:
            err = await message.reply("❗ Format tidak valid atau bukan video.")
            await asyncio.sleep(2)
            await _clean_msgs(err)

    if len(task["functions"]) < 2:
        del ps
        return await message.answer("❗ Minimal 2 Berkas Diperlukan untuk Menggabungkan.", reply_markup=ReplyKeyboardRemove())

    await message.answer("✅ Mempersiapkan proses penggabungan...", reply_markup=ReplyKeyboardRemove())

    await get_thumbnail(ps, [f"/merge{CMD_SUFFIX}", "pass"], 120)
    ps.custom_watermark = {"enabled": False}

    if get_data().get(user_id, {}).get("multi_tasks"):
        ok = await multi_tasks(ps, f"/merge{CMD_SUFFIX}")
        if not ok: del ps; return
        finalize_multi_tasks(ps)

    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  SOFTMUX / SOFTREMUX / HARDMUX
# ═══════════════════════════════════════════════════════════════════════

async def _subtitle_mux_handler(message: Message, process_name: str, cmd_name: str):
    if not await vip_check(message): return
    user_id = message.from_user.id
    chat_id = message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid")
    if not link:
        ne = await ask_media_OR_url(message, chat_id, user_id, [f"/{cmd_name}{CMD_SUFFIX}", "stop"], "Kirim Video atau URL", 120, "video/", False)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    link = _sanitize_link_for_db(link)
    fname = _get_fname(link, custom_file_name)
    ps     = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, process_name, custom_file_name)
    idx    = 1
    cancel = False

    is_hardmux = (process_name == Names.hardmux)
    kb_action = _make_reply_kb(["❌ Batal"], 2) if is_hardmux else _make_reply_kb(["✅ Selesai", "❌ Batal"], 2)

    while True:
        if is_hardmux:
            ask_text = "💬 Kirim 1 File Subtitle (SRT/ASS) untuk di-Hardmux:"
        else:
            ask_text = f"💬 Kirim Subtitle (SRT/ASS) atau Audio (MP3/M4A) No {idx}\n\nTekan tombol jika sudah selesai:"

        ask_msg = await message.reply(ask_text, reply_markup=kb_action)
        ne = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(ask_msg)
        
        txt = (ne.text or "").lower() if ne.text else ""
        if "batal" in txt or txt == "/cancel":
            cancel = True
            break
            
        if not is_hardmux and ("selesai" in txt or txt == "/stop"):
            break
            
        media_obj = getattr(ne, "document", None) or getattr(ne, "audio", None)
        if media_obj:
            mime = str(media_obj.mime_type).lower()
            is_audio = mime.startswith("audio/")
            
            if mime.startswith("video/") or mime.startswith("image/"):
                err = await message.reply("❌ Saya Membutuhkan Berkas Subtitle atau Audio.")
                await asyncio.sleep(2)
                await _clean_msgs(err)
                continue
                
            if is_hardmux and is_audio:
                err = await message.reply("❌ Hardmux hanya mendukung berkas Subtitle.")
                await asyncio.sleep(2)
                await _clean_msgs(err)
                continue
                
            if not is_audio and media_obj.file_size >= 2_000_000:
                err = await message.reply("❌ Ukuran Subtitle terlalu besar (Lebih dari 2MB).")
                await asyncio.sleep(2)
                await _clean_msgs(err)
                continue
                
            sub_name   = media_obj.file_name or f"audio_track_{idx}.m4a"
            create_direc(f"{ps.dir}/subtitles")
            sub_dw_loc = check_file(f"{ps.dir}/subtitles", sub_name)
            
            await Telegram.AIOGRAM_BOT.download(media_obj, destination=sub_dw_loc)
            ps.append_subtitles(sub_dw_loc)
            
            if is_hardmux:
                break
            idx += 1
        else: 
            err = await message.reply("❗ Hanya Berkas Media/Dokumen Telegram yang Didukung.")
            await asyncio.sleep(2)
            await _clean_msgs(err)

    if cancel: 
        del ps
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    if not ps.subtitles: 
        del ps
        return await message.answer(f"❗ Minimal 1 Berkas (Subtitle/Audio) Diperlukan untuk {process_name}.", reply_markup=ReplyKeyboardRemove())

    kb_conf = _make_reply_kb(["✅ Mux", "❌ Batal"], 2)
    conf_txt = (
        f"**💬 KONFIRMASI {process_name.upper()}**\n\n"
        f"🎬 File: `{fname}`\n"
        f"📖 Total Berkas Tambahan: `{len(ps.subtitles)} Berkas`\n\n"
        "Lanjutkan?"
    )
    conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
    press = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(conf_msg, press)
    
    if not press or "batal" in (press.text or "").lower():
         return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
         
    await message.answer("✅ Mempersiapkan proses...", reply_markup=ReplyKeyboardRemove())

    await get_thumbnail(ps, [f"/{cmd_name}{CMD_SUFFIX}", "pass"], 120)
    ps.custom_watermark = {"enabled": False} 
    task = build_task(ps, link)

    if get_data().get(user_id, {}).get("multi_tasks"):
        ok = await multi_tasks(ps, f"/{cmd_name}{CMD_SUFFIX}")
        if not ok: del ps; return
        finalize_multi_tasks(ps)

    await submit_task(task)
    await update_status_message(message)

@router.message(Command(f"softmux{CMD_SUFFIX}"))
async def _softmux(message: Message): await _subtitle_mux_handler(message, Names.softmux, "softmux")

@router.message(Command(f"softremux{CMD_SUFFIX}"))
async def _softremux(message: Message): await _subtitle_mux_handler(message, Names.softremux, "softremux")

@router.message(Command(f"hardmux{CMD_SUFFIX}"))
async def _hardmux(message: Message): await _subtitle_mux_handler(message, Names.hardmux, "hardmux")


# ═══════════════════════════════════════════════════════════════════════
#  GENSAMPLE / GENSS (INTERACTIVE WIZARD)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"gensample{CMD_SUFFIX}"))
async def _gen_video_sample(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid")
    if not link:
        ne = await ask_media_OR_url(message, chat_id, user_id, [f"/gensample{CMD_SUFFIX}", "stop"], "🎬 Kirim Video atau URL untuk dibuatkan Sampel", 120, "video/", False)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    link = _sanitize_link_for_db(link)
    fname = _get_fname(link, custom_file_name)

    opts_buttons = ["30 Detik", "60 Detik", "90 Detik", "120 Detik", "❌ Batal"]
    ask_dur = await message.reply(
        "⏱️ **Pilih Durasi Sampel Video:**\n\n"
        "Silakan tekan tombol di bawah untuk menentukan durasi sampel yang ingin dipotong dari pertengahan video.", 
        reply_markup=_make_reply_kb(opts_buttons, 2)
    )
    
    resp = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ask_dur, resp)
    
    if not resp or "batal" in (resp.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    dur_txt = (resp.text or "").lower().replace(" detik", "").strip()
    if not dur_txt.isdigit():
        return await message.answer("❌ Input tidak valid. Harus berupa angka.", reply_markup=ReplyKeyboardRemove())
        
    sample_duration = int(dur_txt)

    kb_conf = _make_reply_kb(["✅ Buat Sampel", "❌ Batal"], 2)
    conf_txt = (
        f"**🎞️ KONFIRMASI PEMBUATAN SAMPEL**\n\n"
        f"🎬 File: `{fname}`\n"
        f"⏱️ Durasi Target: `{sample_duration} Detik`\n\n"
        "Lanjutkan?"
    )
    conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
    press = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(conf_msg, press)
    
    if not press or "batal" in (press.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    await message.answer("✅ Mempersiapkan proses pembuatan sampel...", reply_markup=ReplyKeyboardRemove())

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.gensample, custom_file_name)
    ps.custom_sample_duration = sample_duration # Inject durasi custom
    ps.custom_watermark = {"enabled": False} 
    await get_thumbnail(ps, [f"/gensample{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(message)


@router.message(Command(f"genss{CMD_SUFFIX}"))
async def _gen_screenshots(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid")
    if not link:
        ne = await ask_media_OR_url(message, chat_id, user_id, [f"/genss{CMD_SUFFIX}", "stop"], "📷 Kirim Video atau URL untuk di-Screenshot", 120, "video/", False)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    link = _sanitize_link_for_db(link)
    fname = _get_fname(link, custom_file_name)

    opts_buttons = ["3", "5", "7", "10", "15", "20", "❌ Batal"]
    ask_num = await message.reply(
        "📷 **Pilih Jumlah Screenshot:**\n\n"
        "Silakan tekan tombol angka di bawah untuk menentukan berapa banyak screenshot yang ingin diambil secara merata.", 
        reply_markup=_make_reply_kb(opts_buttons, 3)
    )
    
    resp = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ask_num, resp)
    
    if not resp or "batal" in (resp.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    ss_num_text = (resp.text or "").strip()
    if not ss_num_text.isdigit():
        return await message.answer("❌ Input tidak valid. Harus berupa angka.", reply_markup=ReplyKeyboardRemove())
        
    ss_num = int(ss_num_text)
    
    kb_conf = _make_reply_kb(["✅ Ambil Screenshot", "❌ Batal"], 2)
    conf_txt = (
        f"**📷 KONFIRMASI SCREENSHOT**\n\n"
        f"🎬 File: `{fname}`\n"
        f"🔢 Jumlah Target: `{ss_num} Gambar`\n\n"
        "Lanjutkan?"
    )
    conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
    press2 = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(conf_msg, press2)
    
    if not press2 or "batal" in (press2.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    await message.answer("✅ Mempersiapkan proses...", reply_markup=ReplyKeyboardRemove())

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.genss, custom_file_name)
    ps.custom_ss_no = ss_num # Inject jumlah screenshot custom
    ps.custom_watermark = {"enabled": False} 
    await get_thumbnail(ps, [f"/genss{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  CHANGE METADATA
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"changemetadata{CMD_SUFFIX}"))
async def _change_metadata(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    cmd     = f"/changemetadata{CMD_SUFFIX}"
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid")
    if not link:
        ne = await ask_media_OR_url(message, chat_id, user_id, [cmd, "stop"], "Kirim Video atau URL", 120, "video/", False)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    link = _sanitize_link_for_db(link)
    fname = _get_fname(link, custom_file_name)

    meta_data = {"title": "", "author": "", "year": "", "comment": "", "encoder": "", "custom_cmd": ""}
    opts_buttons = ["✏️ Title", "👤 Author", "📅 Year", "💬 Comment", "🛠 Encoder", "🎛 Custom FFMPEG", "✅ Selesai", "❌ Batal"]
    
    kb = _make_reply_kb(opts_buttons, 3)
    menu_msg = await message.reply("Memuat menu...", reply_markup=kb)

    while True:
        text_menu = (
            f"**🏷️ MENU UBAH METADATA**\n\n"
            f"🎬 File: `{fname}`\n\n"
            f"**Metadata Saat Ini:**\n"
            f"✏️ **Title:** `{meta_data['title'] or '(Kosong)'}`\n"
            f"👤 **Author:** `{meta_data['author'] or '(Kosong)'}`\n"
            f"📅 **Year:** `{meta_data['year'] or '(Kosong)'}`\n"
            f"💬 **Comment:** `{meta_data['comment'] or '(Kosong)'}`\n"
            f"🛠 **Encoder:** `{meta_data['encoder'] or '(Kosong)'}`\n"
            f"🎛 **Custom FFMPEG:** `{meta_data['custom_cmd'] or '(Kosong)'}`\n\n"
            f"Pilih tombol di bawah untuk mengisi/mengubah nilai, lalu tekan **✅ Selesai** jika sudah."
        )
        
        try:
            await menu_msg.edit_text(text_menu)
        except Exception:
            pass 

        resp = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(resp)

        if not resp:
            await _clean_msgs(menu_msg)
            return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        txt = (resp.text or "").strip().lower()
        
        if "batal" in txt:
            await _clean_msgs(menu_msg)
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        if "selesai" in txt:
            await _clean_msgs(menu_msg)
            break
            
        field = None
        if "title" in txt: field = "title"
        elif "author" in txt: field = "author"
        elif "year" in txt: field = "year"
        elif "comment" in txt: field = "comment"
        elif "encoder" in txt or "encode" in txt: field = "encoder"
        elif "custom" in txt or "ffmpeg" in txt: field = "custom_cmd"
        
        if field:
            ask_val = await message.answer(f"Ketik teks baru untuk **{field.replace('_', ' ').title()}**:\n_(Ketik 'hapus' untuk mengosongkan)_", reply_markup=ReplyKeyboardRemove())
            val_resp = await wait_for_message(chat_id, user_id, 120)
            await _clean_msgs(ask_val, val_resp)
            
            if val_resp and val_resp.text:
                if val_resp.text.lower() == "hapus":
                    meta_data[field] = ""
                else:
                    meta_data[field] = val_resp.text
            
            await _clean_msgs(menu_msg)
            menu_msg = await message.answer(text_menu, reply_markup=kb)
        else:
            err = await message.answer("❌ Input tidak valid.")
            await asyncio.sleep(1.5)
            await _clean_msgs(err)

    import shlex
    custom_metadata = []
    for key, val in meta_data.items():
        if val:
            if key == "custom_cmd":
                custom_metadata.extend(shlex.split(val))
            else:
                custom_metadata.extend(["-metadata", f"{key}={val}"])

    if not custom_metadata:
        return await message.answer("❌ Tidak ada metadata yang ditambahkan. Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    kb_conf = _make_reply_kb(["✅ Ubah Metadata", "❌ Batal"], 2)
    conf_txt = (
        f"**🏷️ KONFIRMASI UBAH METADATA**\n\n"
        f"🎬 File: `{fname}`\n"
        f"⚙️ Target: `{len(custom_metadata) // 2} Atribut`\n\n"
        "Lanjutkan?"
    )
    conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
    press2 = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(conf_msg, press2)
    
    if not press2 or "batal" in (press2.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    await message.answer("✅ Mempersiapkan proses...", reply_markup=ReplyKeyboardRemove())

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.changeMetadata, custom_file_name, custom_metadata=custom_metadata)
    ps.custom_watermark = {"enabled": False} 
    await get_thumbnail(ps, [cmd, "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  CHANGE INDEX (INTERACTIVE BUILDER - NO DUPLICATION)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"changeindex{CMD_SUFFIX}"))
async def _change_index(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    cmd     = f"/changeindex{CMD_SUFFIX}"
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid")
    if not link:
        ne = await ask_media_OR_url(message, chat_id, user_id, [cmd, "stop"], "Kirim Video atau URL", 120, "video/", False)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    link = _sanitize_link_for_db(link)
    fname = _get_fname(link, custom_file_name)

    dling_msg = await message.reply("🔽 Mengunduh berkas untuk dianalisis...")

    async def _download_temp():
        from bot_helper.Others.Names import Names as N_
        import time
        temp_ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, N_.pre_download)
        
        if not isinstance(link, str):
            target = link.video or link.document or link.audio
            dest = f"{temp_ps.dir}/{target.file_name or 'video.mp4'}"
            
            last_update = [0.0]
            async def _progress(current: int, total: int):
                now = time.time()
                if now - last_update[0] >= 2.0 and total:
                    last_update[0] = now
                    pct = current / total
                    bar = "█" * int(pct * 10) + "░" * (10 - int(pct * 10))
                    try: await dling_msg.edit_text(f"🔽 **Mengunduh untuk dianalisis...**\n\n[{bar}] {pct*100:.1f}%\n📥 `{get_human_size(current)} / {get_human_size(total)}`")
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
                try: await dling_msg.edit_text(temp_ps.status_message or "🔽 Mengunduh berkas dengan Aria2...")
                except: pass
        return (temp_ps.send_files[-1] if temp_ps.send_files else None), temp_ps

    input_file, temp_ps = await _download_temp()

    if not input_file or not exists(input_file):
        await dling_msg.edit_text("❌ Gagal mengunduh berkas.")
        try: await asyncio.to_thread(shutil.rmtree, temp_ps.dir, ignore_errors=True)
        except Exception: pass
        return

    try:
        from asyncio import create_subprocess_exec
        from asyncio.subprocess import PIPE as asyncioPIPE
        from json import loads as json_loads
        proc = await create_subprocess_exec("ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", input_file, stdout=asyncioPIPE)
        stdout, _ = await proc.communicate()
        all_streams = json_loads(stdout.decode("utf-8", "replace")).get("streams", [])
    except Exception as e: return await safe_reply(message, f"❌ Gagal menganalisis video: `{e}`")

    audio_streams = []
    sub_streams = []
    
    for s in all_streams:
        ct = s.get("codec_type")
        if ct == "audio":
            audio_streams.append({"id": s.get("index"), "lang": s.get("tags", {}).get("language", "und").upper(), "title": s.get("tags", {}).get("title", "No Title")})
        elif ct == "subtitle":
            sub_streams.append({"id": s.get("index"), "lang": s.get("tags", {}).get("language", "und").upper(), "title": s.get("tags", {}).get("title", "No Title")})

    if not audio_streams and not sub_streams:
        return await dling_msg.edit_text("❌ Tidak ada stream audio atau subtitle untuk diubah pada video ini.")

    await dling_msg.delete()

    # 1. TAMPILKAN DAFTAR AUDIO
    aud_text = "🎧 **DAFTAR AUDIO TERSEDIA:**\n"
    for a in audio_streams:
        aud_text += f"ID: {a['id']} - {a['lang']} ({a['title']})\n"
        
    ask_aud = await message.reply(
        f"{aud_text}\n"
        "👉 **Ketik urutan ID Audio** yang ingin digunakan (pisahkan dengan koma).\n"
        "_(Contoh: `1, 0` -> ID 1 jadi Track Utama, ID 0 jadi Track Kedua)_\n"
        "👉 Ketik `tanpa` jika video ingin di-mute.",
        reply_markup=ReplyKeyboardRemove()
    )
    res_aud = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ask_aud, res_aud)
    
    audio_sel = []
    if "tanpa" not in (res_aud.text or "").lower():
        audio_sel = [int(x.strip()) for x in (res_aud.text or "").split(',') if x.strip().isdigit()]

    # 2. TAMPILKAN DAFTAR SUBTITLE
    sub_text = "📖 **DAFTAR SUBTITLE TERSEDIA:**\n"
    for s in sub_streams:
        sub_text += f"ID: {s['id']} - {s['lang']} ({s['title']})\n"
        
    ask_sub = await message.reply(
        f"{sub_text}\n"
        "👉 **Ketik urutan ID Subtitle** yang ingin digunakan (pisahkan dengan koma).\n"
        "_(Contoh: `2, 0` -> ID 2 jadi Sub Utama, ID 0 jadi Sub Kedua)_\n"
        "👉 Ketik `tanpa` jika tidak ingin ada subtitle."
    )
    res_sub = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ask_sub, res_sub)
    
    sub_sel = []
    if "tanpa" not in (res_sub.text or "").lower():
        sub_sel = [int(x.strip()) for x in (res_sub.text or "").split(',') if x.strip().isdigit()]

    # 3. MEMBANGUN FFMPEG COMMAND SESUAI URUTAN
    custom_index = ["-map", "0:v:0?"] # Ambil video utama
    
    for i, aud_id in enumerate(audio_sel):
        custom_index.extend(["-map", f"0:{aud_id}?"]) # Map based on absolute ID
        if i == 0:
            custom_index.extend([f"-disposition:a:{i}", "default"])
        else:
            custom_index.extend([f"-disposition:a:{i}", "0"]) 
            
    for i, sub_id in enumerate(sub_sel):
        custom_index.extend(["-map", f"0:{sub_id}?"])
        if i == 0:
            custom_index.extend([f"-disposition:s:{i}", "default"])
        else:
            custom_index.extend([f"-disposition:s:{i}", "0"])

    custom_index.extend(["-c", "copy"])

    await message.answer("✅ Menyusun ulang urutan track...", reply_markup=ReplyKeyboardRemove())
    
    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.changeindex, custom_file_name, custom_index=custom_index)
    ps.custom_watermark = {"enabled": False}
    
    # Recycle the already downloaded file!
    if hasattr(temp_ps, 'dir') and os.path.exists(temp_ps.dir):
        for f in temp_ps.send_files:
            if os.path.exists(f):
                import shutil, os
                new_f = f"{ps.dir}/{os.path.basename(f)}"
                shutil.move(f, new_f)
                ps.send_files = [new_f]

    try: await asyncio.to_thread(shutil.rmtree, temp_ps.dir, ignore_errors=True)
    except Exception: pass

    final_task = {"process_status": ps, "functions": []}
    from bot_helper.Process.Running_Tasks import submit_task
    await submit_task(final_task)
    await update_status_message(message)


# ═══════════════════════════════════════════════════════════════════════
#  MUTE, SPEED, DUBBING
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"mute{CMD_SUFFIX}"))
async def _mute_video(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    link, custom_file_name = await get_link(message)
    if not link: return await safe_reply(message, f"Kirim video/URL lalu balas dengan perintah /mute{CMD_SUFFIX}")

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, "mute", custom_file_name)
    ps.custom_watermark = {"enabled": False}
    ps.audio_settings = {"enabled": False} 
    await get_thumbnail(ps, [f"/mute{CMD_SUFFIX}", "pass"], 120)
    
    await message.answer("🔇 Memproses Mute Video (Menghapus Audio)...")
    task = build_task(ps, link)
    await submit_task(task)

@router.message(Command(f"dubbing{CMD_SUFFIX}"))
async def _dubbing_video(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    
    link, custom_file_name = await get_link(message)
    if not link: return await safe_reply(message, f"Kirim video/URL lalu balas dengan perintah /dubbing{CMD_SUFFIX}")

    ask_aud = await message.reply("🎵 Kirim file Audio (MP3/M4A/WAV) yang akan menggantikan suara asli video:")
    aud_msg = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ask_aud)
    
    if not aud_msg or not (aud_msg.audio or aud_msg.document):
        return await message.answer("❌ Audio tidak valid. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    aud_doc = aud_msg.audio or aud_msg.document
    create_direc(f"./temp/dubs_{user_id}")
    aud_path = f"./temp/dubs_{user_id}/{aud_doc.file_name or 'dub.mp3'}"
    await Telegram.AIOGRAM_BOT.download(aud_doc, destination=aud_path)

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, "dubbing", custom_file_name)
    ps.custom_dub_audio = aud_path 
    ps.custom_watermark = {"enabled": False}
    
    await message.answer("🎙 Memproses Dubbing (Suara Asli Dihapus, Suara Baru Dimasukkan)...")
    await get_thumbnail(ps, [f"/dubbing{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)

@router.message(Command(f"speed{CMD_SUFFIX}"))
async def _speed_video(message: Message):
    if not await vip_check(message): return
    user_id, chat_id = message.from_user.id, message.chat.id
    
    link, custom_file_name = await get_link(message)
    if not link: return await safe_reply(message, f"Kirim video/URL lalu balas dengan perintah /speed{CMD_SUFFIX}")

    kb_speed = _make_reply_kb(["Lambat (0.5x)", "Cepat (1.5x)", "Sangat Cepat (2.0x)", "❌ Batal"], 2)
    ask_spd = await message.reply("⚡ Pilih Kecepatan Video Baru:", reply_markup=kb_speed)
    resp = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ask_spd, resp)
    
    txt = (resp.text or "").lower()
    if not txt or "batal" in txt: return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    
    speed_factor = 2.0 if "2.0" in txt else 1.5 if "1.5" in txt else 0.5
    v_pts = 1 / speed_factor
    
    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, "speed", custom_file_name)
    ps.video_filters = [f"setpts={v_pts}*PTS"]
    ps.audio_filters = [f"atempo={speed_factor}"]
    ps.custom_watermark = {"enabled": False}

    await message.answer(f"⚡ Memproses perubahan kecepatan menjadi {speed_factor}x...")
    await get_thumbnail(ps, [f"/speed{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)


# ═══════════════════════════════════════════════════════════════════════
#  EXTRACT THUMBNAIL & FRAMES (ZIP)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"ext_thumb{CMD_SUFFIX}"))
async def _extract_thumbnail(message: Message):
    if not await vip_check(message): return
    link, _ = await get_link(message)
    if not link: return await safe_reply(message, "Kirim/Balas video lalu gunakan command ini.")

    msg = await message.answer("🖼 Mengambil Thumbnail HD...")
    user_id = message.from_user.id
    
    # Check if link is a Telegram object
    if not isinstance(link, str):
        target = getattr(link, "video", None) or getattr(link, "document", None)
        if not target: return await msg.edit_text("❌ Tautan tidak valid.")
        
        # Temp download
        create_direc(f"./temp/thumb_{user_id}")
        input_file = f"./temp/thumb_{user_id}/vid.mp4"
        await Telegram.AIOGRAM_BOT.download(target, destination=input_file)
    else:
        input_file = link
        
    out_file = f"./temp/thumb_{user_id}_out.jpg"
    
    cmd = f'ffmpeg -hide_banner -y -i "{input_file}" -ss 00:00:05 -vframes 1 -q:v 2 "{out_file}"'
    proc = await asyncio.create_subprocess_shell(cmd)
    await proc.communicate()
    
    if os.path.exists(out_file):
        await message.reply_photo(FSInputFile(out_file), caption="✅ Thumbnail berhasil diekstrak!")
        os.remove(out_file)
    else:
        await msg.edit_text("❌ Gagal mengekstrak thumbnail.")
        
    if not isinstance(link, str):
        try: shutil.rmtree(f"./temp/thumb_{user_id}")
        except: pass
    await msg.delete()

@router.message(Command(f"ext_frames{CMD_SUFFIX}"))
async def _extract_frames_zip(message: Message):
    if not await vip_check(message): return
    link, _ = await get_link(message)
    if not link: return await safe_reply(message, "Kirim/Balas video lalu gunakan command ini.")

    ask = await message.reply("🎞 **Mau ambil frame setiap berapa detik?**\n_(Ketik angka saja, contoh: `5` artinya 1 gambar setiap 5 detik)_")
    res = await wait_for_message(message.chat.id, message.from_user.id, 60)
    await _clean_msgs(ask, res)
    
    interval = (res.text or "").strip()
    if not interval.isdigit(): interval = "5" 
    
    msg = await message.answer(f"🎞 Sedang mengekstrak frame (1 gambar per {interval} detik) dan membuat ZIP...\n_Mohon tunggu sebentar._")
    user_id = message.from_user.id
    
    if not isinstance(link, str):
        target = getattr(link, "video", None) or getattr(link, "document", None)
        if not target: return await msg.edit_text("❌ Tautan tidak valid.")
        create_direc(f"./temp/frames_{user_id}")
        input_file = f"./temp/frames_{user_id}/vid.mp4"
        await Telegram.AIOGRAM_BOT.download(target, destination=input_file)
    else:
        input_file = link
        
    out_dir = f"./temp/frames_folder_{user_id}"
    os.makedirs(out_dir, exist_ok=True)
    
    cmd = f'ffmpeg -hide_banner -y -i "{input_file}" -vf "fps=1/{interval}" -q:v 2 "{out_dir}/frame_%04d.jpg"'
    proc = await asyncio.create_subprocess_shell(cmd)
    await proc.communicate()
    
    zip_path = f"./temp/Frames_Extracted_{user_id}.zip"
    try:
        shutil.make_archive(zip_path.replace('.zip', ''), 'zip', out_dir)
        if os.path.exists(zip_path):
            await message.reply_document(FSInputFile(zip_path), caption=f"✅ Ekstrak Frame selesai! (Interval: {interval} detik)")
            os.remove(zip_path)
        else:
            await msg.edit_text("❌ Gagal membuat file ZIP.")
    except Exception as e:
        await msg.edit_text(f"❌ Terjadi kesalahan: {e}")
        
    shutil.rmtree(out_dir, ignore_errors=True)
    if not isinstance(link, str):
        try: shutil.rmtree(f"./temp/frames_{user_id}")
        except: pass
    await msg.delete()


# ═══════════════════════════════════════════════════════════════════════
#  LEECH / MIRROR
# ═══════════════════════════════════════════════════════════════════════

async def _leech_mirror_handler(message: Message, process_name: str, cmd_name: str):
    if not await vip_check(message): return
    user_id = message.from_user.id
    chat_id = message.chat.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid")
    if not link:
        ne = await ask_url(message, chat_id, user_id, [f"/{cmd_name}{CMD_SUFFIX}", "stop"], "Kirim Tautan", 120, False)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, process_name, custom_file_name)
    await get_thumbnail(ps, [f"/{cmd_name}{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(message)

@router.message(Command(f"leech{CMD_SUFFIX}"))
async def _leech_file(message: Message): await _leech_mirror_handler(message, Names.leech, "leech")

@router.message(Command(f"mirror{CMD_SUFFIX}"))
async def _mirror_file(message: Message): await _leech_mirror_handler(message, Names.mirror, "mirror")

# ═══════════════════════════════════════════════════════════════════════
#  STATUS
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"status{CMD_SUFFIX}"))
async def _status(message: Message):
    if not await user_auth_checker(message): return
    user_id = message.from_user.id
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)
    await update_status_message(message)
