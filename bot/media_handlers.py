"""
╔══════════════════════════════════════════════════════════════════════╗
║       bot_helper/Handlers/media_handlers.py — v3.9                   ║
║       Media Processing Command Handlers (Aiogram 3.x)                ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [FIX] Memisahkan /compress agar lebih instan (tanpa dub/sub).       ║
║  [FIX] /watermark kini menggunakan tombol Skip yang aman dari error. ║
║  [FIX] /hardmux kini hanya meminta 1 subtitle lalu otomatis lanjut.  ║
║  [NEW] /softmux & /softremux kini mendukung penambahan file Audio!   ║
║  [NEW PREMIUM] /convert kini 100% FULL TOMBOL! Mendukung Multi-Select║
║                dengan tombol "✅ Selesai" tanpa perlu mengetik koma. ║
║  [UPDATE] Konsistensi tombol dan teks pembatalan di seluruh fitur.   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import re
from os.path import exists

# ── Aiogram ───────────────────────────────────────────────────────────
from aiogram import Router, F
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.User_Data import get_data, new_user, saveoptions
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
    new_msg = await ask_media_OR_url(message, chat_id, user_id, [process_command, "stop"], "Kirim Berkas Subtitle SRT", 120, False, True, allow_magnet=False, allow_url=False)
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
        ne = await ask_media_OR_url(message, chat_id, user_id, [f"/{cmd_name}{CMD_SUFFIX}", "stop"], "Kirim Video atau URL", 120, "video/", True)
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
        ne = await ask_media_OR_url(message, chat_id, user_id, [f"/encode{CMD_SUFFIX}", "stop"], "🎬 Kirim Video atau URL untuk di-Encode", 120, "video/", True)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    link = _sanitize_link_for_db(link)
    fname = _get_fname(link, custom_file_name)

    # Prompt Subtitle
    kb_skip = _make_reply_kb(["⏭ Skip", "❌ Batal"], 2)
    ask_sub = await message.reply("💬 Kirim file Subtitle (SRT/ASS) untuk di-Hardmux.\n\nAtau tekan tombol `⏭ Skip` jika tidak perlu.", reply_markup=kb_skip)
    sub_msg = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ask_sub)
    
    txt_sub = (sub_msg.text or "").lower()
    if "batal" in txt_sub: return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    
    sub_path = None
    sub_name_str = "Tidak Ada"
    if "skip" not in txt_sub and hasattr(sub_msg, "document") and sub_msg.document:
        create_direc(f"./temp/subs_{user_id}")
        sub_path = check_file(f"./temp/subs_{user_id}", sub_msg.document.file_name)
        sub_name_str = sub_msg.document.file_name
        await Telegram.AIOGRAM_BOT.download(sub_msg.document, destination=sub_path)

    # Prompt Audio Dubbing
    ask_aud = await message.reply("🎵 Kirim file Audio (MP3/M4A) untuk Dubbing.\n\nAtau tekan tombol `⏭ Skip` jika tidak perlu.", reply_markup=kb_skip)
    aud_msg = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ask_aud)
    
    txt_aud = (aud_msg.text or "").lower()
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

    # Namanya diganti jadi "encode" agar Backend tahu file ini harus membaca settingan Global
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
        ne = await ask_media_OR_url(message, chat_id, user_id, [f"/compress{CMD_SUFFIX}", "stop"], "🎬 Kirim Video atau URL untuk di-Compress", 120, "video/", True)
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
        ne = await ask_media_OR_url(message, chat_id, user_id, [f"/convert{CMD_SUFFIX}", "stop"], "📺 Kirim Video atau URL untuk di-Convert", 120, "video/", True)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    link = _sanitize_link_for_db(link)
    fname = _get_fname(link, custom_file_name)

    # 🚨 FITUR BARU: FULL TOMBOL LOOP MULTI-SELECT 🚨
    resolutions = []
    opts_buttons = ["240", "360", "480", "720", "1080", "✅ Selesai", "❌ Batal"]
    
    ask_res = await message.reply(
        "📺 **Pilih Resolusi Konversi**\n\n"
        "Silakan tekan tombol angka di bawah. Anda bisa menekan beberapa tombol sekaligus.\n"
        "Jika sudah selesai memilih, tekan tombol **✅ Selesai**.", 
        reply_markup=_make_reply_kb(opts_buttons, 3)
    )
    
    # Loop tanya-jawab hingga pengguna menekan Selesai atau Batal
    while True:
        res_msg = await wait_for_message(chat_id, user_id, 120)
        await _clean_msgs(res_msg) # Bersihkan chat user yang mencet tombol agar rapi
        
        if res_msg is None: 
            return await message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        txt = (res_msg.text or "").lower()
        if "batal" in txt:
            await _clean_msgs(ask_res)
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        if "selesai" in txt:
            await _clean_msgs(ask_res)
            break
            
        # Ekstrak angka resolusi dari tombol yang ditekan
        nums = re.findall(r'\d+', txt)
        if nums:
            for n in nums:
                res = int(n)
                if res not in resolutions:
                    resolutions.append(res)
            
            # Tampilkan resolusi yang sudah terpilih ke pengguna secara LIVE
            sorted_res = sorted(resolutions, reverse=True)
            res_str = ", ".join([f"{r}p" for r in sorted_res])
            try:
                await ask_res.edit_text(
                    f"📺 **Pilih Resolusi Konversi**\n\n"
                    f"✅ **Telah Memilih:** `{res_str}`\n\n"
                    f"Tekan tombol angka lain untuk menambah, atau tekan **✅ Selesai** jika sudah cukup."
                )
            except Exception:
                pass # Abaikan error jika isi pesan sama (Telegram tidak mengizinkan edit pesan dengan isi yang 100% sama)
        else:
            err = await message.answer("❌ Input tidak valid.")
            await asyncio.sleep(1.5)
            await _clean_msgs(err)

    # Validasi Akhir
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
         
    await message.answer(f"✅ Mengantrekan {len(sorted_res)} proses konversi secara berurutan...", reply_markup=ReplyKeyboardRemove())

    # Membuat Tugas Berantai
    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.convert, custom_file_name)
    ps.convert_quality = sorted_res[0]

    # Tambahkan resolusi selanjutnya sebagai Sub-Tasks (Tugas Turunan) agar diproses sekaligus
    if len(sorted_res) > 1:
        for res in sorted_res[1:]:
            mt_ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.convert, custom_file_name)
            mt_ps.convert_quality = res
            ps.append_multi_tasks(mt_ps)

    await get_thumbnail(ps, [f"/convert{CMD_SUFFIX}", "pass"], 120)
    task = build_task(ps, link)

    # Cek opsi multi-task interaktif tambahan (opsional)
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
        ne = await ask_media_OR_url(message, chat_id, user_id, [f"/watermark{CMD_SUFFIX}", "stop"], "🛺 Kirim Video atau URL untuk diberi Watermark", 120, "video/", True)
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
        img_msg = await ask_media_OR_url(message, chat_id, user_id, ["stop", "batal"], "🖼️ Kirim file Gambar (PNG/JPG) untuk Watermark.", 120, "photo/", True)
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

    kb_pos = _make_reply_kb(["Kiri Atas", "Kanan Atas", "Tengah", "Kiri Bawah", "Kanan Bawah"], 2)
    pos_msg = await message.reply("📍 Pilih Posisi Watermark:", reply_markup=kb_pos)
    pos_resp = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(pos_msg, pos_resp)
    
    pos_map = {"kiri atas": "top_left", "kanan atas": "top_right", "tengah": "middle_center", "kiri bawah": "bottom_left", "kanan bawah": "bottom_right"}
    pos = pos_map.get((pos_resp.text or "").strip().lower(), "bottom_right") if pos_resp else "bottom_right"
    
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
        
        txt = (ne.text or "").lower()
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
        ne = await ask_media_OR_url(message, chat_id, user_id, [f"/{cmd_name}{CMD_SUFFIX}", "stop"], "Kirim Video atau URL", 120, "video/", True)
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
        
        txt = (ne.text or "").lower()
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
#  GENSAMPLE / GENSS
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"gensample{CMD_SUFFIX}"))
async def _gen_video_sample(message: Message): await _generic_video_handler(message, Names.gensample, "gensample")

@router.message(Command(f"genss{CMD_SUFFIX}"))
async def _gen_screenshots(message: Message): await _generic_video_handler(message, Names.genss, "genss")

# ═══════════════════════════════════════════════════════════════════════
#  CHANGE METADATA
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"changemetadata{CMD_SUFFIX}"))
async def _change_metadata(message: Message):
    if not await vip_check(message): return
    user_id = message.from_user.id
    chat_id = message.chat.id
    cmd     = f"/changemetadata{CMD_SUFFIX}"
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid")
    if not link:
        ne = await ask_media_OR_url(message, chat_id, user_id, [cmd, "stop"], "Kirim Video atau URL", 120, "video/", True)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    link = _sanitize_link_for_db(link)
    fname = _get_fname(link, custom_file_name)

    me = await ask_text_event(chat_id, user_id, message, 120, "Kirim MetaData", message_hint=("Format:\n`a:0-BahasaAudio-JudulAudio`\n`s:0-BahasaSub-JudulSub`\n\nContoh: `a:1-eng-EncoderBot`"))
    if not me: return

    custom_metadata = []
    for m in str(me.text).split("\n"):
        mdata = str(m).strip().split("-")
        try:
            sindex = str(mdata[0]).strip().lower()
            mlang  = str(mdata[1]).lower()
            mtitle = str(mdata[2])
            custom_metadata.append([f"-metadata:s:{sindex}", f"language={mlang}", f"-metadata:s:{sindex}", f"title={mtitle}"])
        except (IndexError, Exception) as e:
            return await safe_reply(me, f"❗ Metadata Tidak Valid: `{e}`")

    kb_conf = _make_reply_kb(["✅ Ubah Metadata", "❌ Batal"], 2)
    conf_txt = (
        f"**🏷️ KONFIRMASI UBAH METADATA**\n\n"
        f"🎬 File: `{fname}`\n"
        f"⚙️ Target Index: `{len(custom_metadata) // 4} Stream`\n\n"
        "Lanjutkan?"
    )
    conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
    press2 = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(me, conf_msg, press2)
    
    if not press2 or "batal" in (press2.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    await message.answer("✅ Mempersiapkan proses...", reply_markup=ReplyKeyboardRemove())

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.changeMetadata, custom_file_name, custom_metadata=custom_metadata)
    await get_thumbnail(ps, [cmd, "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(message)

# ═══════════════════════════════════════════════════════════════════════
#  CHANGE INDEX
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"changeindex{CMD_SUFFIX}"))
async def _change_index(message: Message):
    if not await vip_check(message): return
    user_id = message.from_user.id
    chat_id = message.chat.id
    cmd     = f"/changeindex{CMD_SUFFIX}"
    if user_id not in get_data(): await new_user(user_id, SAVE_TO_DATABASE)

    link, custom_file_name = await get_link(message)
    if link == "invalid": return await safe_reply(message, "❗ Tautan tidak valid")
    if not link:
        ne = await ask_media_OR_url(message, chat_id, user_id, [cmd, "stop"], "Kirim Video atau URL", 120, "video/", True)
        if ne and ne not in ["cancelled", "stopped"]: link = await get_url_from_message(ne)
        else: return

    link = _sanitize_link_for_db(link)
    fname = _get_fname(link, custom_file_name)

    ie = await ask_text_event(chat_id, user_id, message, 120, "Kirim Indeks", message_hint=("`a` Audio | `s` Subtitle\nFormat: `a-3-1-2` (urutan 3,1,2)\nContoh: `s-2-1`"))
    if not ie: return

    custom_index = []
    for m in str(ie.text).split("\n"):
        mdata = str(m).strip().split("-")
        try:
            stream = str(mdata[0]).strip().lower()
            mdata.pop(0)
            for s in mdata:
                si = int(s.strip()) - 1
                custom_index += ["-map", f"0:{stream}:{si}"]
            custom_index += [f"-disposition:{stream}:0", "default"]
        except (ValueError, IndexError, Exception) as e:
            return await safe_reply(ie, f"❗ Indeks Tidak Valid: `{e}`")

    kb_conf = _make_reply_kb(["✅ Ubah Index", "❌ Batal"], 2)
    conf_txt = (
        f"**🔄 KONFIRMASI UBAH INDEX**\n\n"
        f"🎬 File: `{fname}`\n"
        f"🔢 Susunan Index: `{ie.text}`\n\n"
        "Lanjutkan?"
    )
    conf_msg = await message.reply(conf_txt, reply_markup=kb_conf)
    press2 = await wait_for_message(chat_id, user_id, 120)
    await _clean_msgs(ie, conf_msg, press2)
    
    if not press2 or "batal" in (press2.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    await message.answer("✅ Mempersiapkan proses...", reply_markup=ReplyKeyboardRemove())

    ps = ProcessStatus(user_id, chat_id, get_username(message), message.from_user.first_name, message, Names.changeindex, custom_file_name, custom_index=custom_index)
    await get_thumbnail(ps, [cmd, "pass"], 120)
    task = build_task(ps, link)
    await submit_task(task)
    await update_status_message(message)

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
        ne = await ask_url(message, chat_id, user_id, [f"/{cmd_name}{CMD_SUFFIX}", "stop"], "Kirim Tautan", 120, True)
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
