"""
╔══════════════════════════════════════════════════════════════════════╗
║                    bot/AutoClip.py — v5.0                            ║
║        Auto Clip: Potong video panjang → Shorts/Reels terpisah        ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v5.0:                                                     ║
║  [INTEGRATION] Migrasi total ke bot_helper.Process.Unified_Engine    ║
║  [CLEANUP] Menghapus sistem antrean manual (Task/Semaphore manual)   ║
║  [UX PREMIUM] Progress Bar tersentralisasi untuk Render & Upload.    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import os
import time
from datetime import datetime
from typing import Optional
import re

from moviepy import VideoFileClip, CompositeVideoClip, ColorClip, ImageClip
from moviepy.video.fx import FadeIn, FadeOut

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramBadRequest

from bot_helper.Database.User_Data import get_data, ensure_user_data_structure
from bot_helper.Others.Helper_Functions import get_human_size, get_readable_time
from bot_helper.Others.Names import Names
from bot_helper.Process.Unified_Engine import execute_unified_task
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config
from bot.shared import wait_for_message

try:
    from bot.YTUpload import _core_ytupload_logic, YOUTUBE_ENABLED
    _HAS_YTUPLOAD = True
except ImportError:
    YOUTUBE_ENABLED = False
    _HAS_YTUPLOAD   = False

LOGGER      = Config.LOGGER
CMD_SUFFIX  = Config.CMD_SUFFIX
router      = Router()

TEMP_DIR           = "./temp/autoclip/"
SHORT_W, SHORT_H   = 1080, 1920
LAND_W,  LAND_H    = 1920, 1080
TARGET_FPS         = 30

QUALITY_PRESETS = {
    "fast":     {"bitrate": "4000k", "preset": "ultrafast", "label": "⚡ Cepat"},
    "balanced": {"bitrate": "6000k", "preset": "fast",      "label": "⚖️ Seimbang"},
    "hq":       {"bitrate": "8000k", "preset": "slow",      "label": "💎 HQ"},
}

os.makedirs(TEMP_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS & UI
# ═══════════════════════════════════════════════════════════════════════

async def _clean_msgs(*msgs):
    """Menghapus pesan untuk menjaga chat tetap rapi."""
    for m in msgs:
        if m:
            try: await m.delete()
            except Exception: pass

def _make_reply_kb(options: list, row_width: int = 2) -> ReplyKeyboardMarkup:
    """Membuat Reply Keyboard dengan warna otomatis (Native Telegram)."""
    kb, row = [], []
    for opt in options:
        if "Batal" in opt or "❌" in opt: btn_style = "danger"
        elif "Ya" in opt or "✅" in opt: btn_style = "success"
        else: btn_style = "primary"
        row.append(KeyboardButton(text=opt, style=btn_style))
        if len(row) == row_width: kb.append(row); row = []
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

def _find_source_video(topic: str) -> Optional[str]:
    search_dirs = ["./gameplay/", "./userdata/gameplay/", "./videos/"]
    exts = [".mp4", ".mkv", ".avi", ".mov", ".webm"]
    for folder in search_dirs:
        if not os.path.isdir(folder): continue
        for f in os.listdir(folder):
            if topic.lower().replace(" ", "_") in f.lower() or f.lower().startswith(topic.lower().replace(" ", "_")):
                if any(f.lower().endswith(ext) for ext in exts): return os.path.join(folder, f)
    return None

def _list_available_sources() -> list[str]:
    sources = []
    search_dirs = ["./gameplay/", "./userdata/gameplay/", "./videos/"]
    exts = [".mp4", ".mkv", ".avi", ".mov", ".webm"]
    for folder in search_dirs:
        if not os.path.isdir(folder): continue
        for f in os.listdir(folder):
            if any(f.lower().endswith(ext) for ext in exts): sources.append(os.path.splitext(f)[0])
    return sorted(set(sources))

def _time_to_sec(t_str: str) -> float:
    parts = [p.strip() for p in t_str.strip().split(":")]
    if len(parts) == 3: return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2: return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])

def parse_clip_txt(path: str) -> list[dict]:
    scenes, errors = [], []
    with open(path, "r", encoding="utf-8", errors="replace") as f: lines = f.readlines()
    for i, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"): continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) < 2: errors.append(f"Baris {i}: Format salah"); continue
        time_str, segment, desc = parts[0], parts[1], parts[2] if len(parts) >= 3 else ""
        t_split = [x.strip() for x in time_str.split("-")]
        if len(t_split) != 2: errors.append(f"Baris {i}: Waktu salah"); continue
        try:
            start_t, end_t = _time_to_sec(t_split[0]), _time_to_sec(t_split[1])
            if end_t <= start_t: continue
            scenes.append({"segment": segment, "desc": desc, "start": start_t, "end": end_t, "duration": end_t - start_t})
        except ValueError: continue
    if errors: raise ValueError("Format .txt salah.")
    return scenes

# ═══════════════════════════════════════════════════════════════════════
#  VIDEO PROCESSING
# ═══════════════════════════════════════════════════════════════════════

def _reframe_to_portrait(clip, w: int, h: int) -> "VideoFileClip":
    cw, ch = clip.size
    target_ratio = w / h
    source_ratio = cw / ch
    if source_ratio > target_ratio:
        new_w = int(ch * target_ratio); x1 = (cw - new_w) // 2
        return clip.cropped(x1=x1, x2=x1 + new_w).resized((w, h))
    else:
        new_h = int(cw / target_ratio); y1 = (ch - new_h) // 2
        return clip.cropped(y1=y1, y2=y1 + new_h).resized((w, h))

async def render_clip(scene: dict, source_path: str, output_path: str, mode: str, quality: str) -> str:
    start_t, end_t, title, dur = scene["start"], scene["end"], scene["segment"], scene["duration"]
    q = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["balanced"])
    raw = None
    try:
        raw = VideoFileClip(source_path); end_t = min(end_t, raw.duration); dur = end_t - start_t
        clip = raw.subclip(start_t, end_t)
        if mode == "short": W, H = SHORT_W, SHORT_H; clip = _reframe_to_portrait(clip, W, H)
        elif mode == "landscape": W, H = LAND_W, LAND_H; clip = clip.resized((W, H))
        else: W, H = clip.size; W, H = (W//2)*2, (H//2)*2; clip = clip.resized((W, H))
        
        def _write():
            clip.write_videofile(output_path, fps=TARGET_FPS, codec="libx264", bitrate=q["bitrate"], audio_codec="aac", logger=None, ffmpeg_params=["-preset", q["preset"]])
        await asyncio.to_thread(_write); return output_path
    finally:
        if raw: raw.close()

def _generate_clip_thumbnail(source_path: str, scene: dict, output_path: str, mode: str) -> Optional[str]:
    try:
        from PIL import Image, ImageDraw, ImageFont
        raw = VideoFileClip(source_path); frame = raw.get_frame(scene["start"] + scene["duration"]/2); raw.close()
        img = Image.fromarray(frame.astype("uint8"))
        w, h = (SHORT_W//2, SHORT_H//2) if mode == "short" else (LAND_W//2, LAND_H//2)
        img = img.resize((w, h), Image.LANCZOS); img.save(output_path, "JPEG", quality=80)
        return output_path
    except: return None


# ═══════════════════════════════════════════════════════════════════════
#  CORE LOGIC (UNIFIED ENGINE COMPATIBLE)
# ═══════════════════════════════════════════════════════════════════════

async def _core_autoclip_logic(message: Message, ui, reply_msg: Message, topic: str, mode: str, quality: str, yt_enabled: bool, yt_privacy: str) -> None:
    txt_path, render_start = _tmp(f"clip_script_{message.message_id}.txt"), time.time()
    try:
        await ui.update("📥 Mengunduh Naskah...", details=f"Sumber: {topic}")
        await Telegram.AIOGRAM_BOT.download(reply_msg.document, destination=txt_path)
        
        scenes = parse_clip_txt(txt_path); total = len(scenes)
        source_path = _find_source_video(topic)
        if not source_path: raise RuntimeError(f"Video sumber `{topic}` tidak ditemukan!")

        success_count = 0
        for idx, scene in enumerate(scenes, 1):
            out_file = _tmp(f"clip_{message.message_id}_{idx:02d}.mp4")
            thumb_file = _tmp(f"thumb_{message.message_id}_{idx:02d}.jpg")
            
            await ui.update(
                status=f"✂️ Memotong Clip {idx}/{total}",
                current=idx-1, total=total,
                details=f"🎬 Scene: {scene['segment'][:25]}\n⏱ Durasi: {scene['duration']:.1f}s"
            )

            try:
                await render_clip(scene, source_path, out_file, mode, quality)
                thumb = _generate_clip_thumbnail(source_path, scene, thumb_file, mode)
                
                # Upload ke Telegram
                caption = f"✂️ **CLIP {idx}/{total}**\n\n📌 **Judul:** {scene['segment']}\n🎬 **Sumber:** `{topic}`\n⏱️ **Durasi:** `{scene['duration']:.1f}s`"
                await Telegram.AIOGRAM_BOT.send_video(
                    chat_id=message.chat.id, video=FSInputFile(out_file), 
                    caption=caption, thumbnail=FSInputFile(thumb) if thumb else None,
                    supports_streaming=True, reply_to_message_id=message.message_id
                )
                
                # Upload ke YouTube jika diminta
                if yt_enabled and _HAS_YTUPLOAD:
                    await ui.update(f"🚀 Uploading Clip {idx} to YouTube...", details=f"Judul: {scene['segment']}")
                    # Reuse YT Logic
                    from bot.YTUpload import _get_youtube_client, YT_CHUNK_SIZE, YT_CATEGORY_ID, YT_TAGS
                    from googleapiclient.http import MediaFileUpload
                    youtube = _get_youtube_client()
                    media = MediaFileUpload(out_file, chunksize=YT_CHUNK_SIZE, resumable=True)
                    request = youtube.videos().insert(
                        part="snippet,status",
                        body={
                            "snippet": {"categoryId": YT_CATEGORY_ID, "title": f"{topic} - {scene['segment']}", "description": f"Clip from {topic}", "tags": YT_TAGS},
                            "status": {"privacyStatus": yt_privacy},
                        },
                        media_body=media
                    )
                    response = None
                    while response is None:
                        _, response = await asyncio.to_thread(request.next_chunk)
                
                success_count += 1
            except Exception as e:
                LOGGER.error(f"Clip {idx} failed: {e}")
            finally:
                _cleanup(out_file, thumb_file)

        await ui.finish(f"✅ <b>Auto Clip Selesai!</b>\nBerhasil: <code>{success_count}/{total}</code> klip.")

    finally:
        _cleanup(txt_path)


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND HANDLER
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"clip{CMD_SUFFIX}"))
async def autoclip_handler(message: Message, command: CommandObject) -> None:
    user_id = message.from_user.id
    if not _is_vip(user_id): return await message.reply("👑 **Fitur VIP**")

    if not message.reply_to_message or not message.reply_to_message.document:
        return await message.reply("❌ Balas file `.txt` dengan perintah `/clip NamaVideo`!")

    topic = (command.args or "").strip()
    if not topic: return await message.reply("❌ Sertakan nama video! Contoh: `/clip RE4`")

    await ensure_user_data_structure(user_id)
    chat_id = message.chat.id

    # Wizard
    kb_mode = _make_reply_kb(["📱 Shorts", "🖥️ Landscape", "❌ Batal"], 2)
    msg_mode = await message.reply("📐 **Pilih Format:**", reply_markup=kb_mode)
    resp_mode = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_mode, resp_mode)
    if not resp_mode or "batal" in (resp_mode.text or "").lower(): return

    mode = "landscape" if "landscape" in resp_mode.text.lower() else "short"
    
    kb_qual = _make_reply_kb(["⚡ Cepat", "⚖️ Seimbang", "💎 HQ", "❌ Batal"], 3)
    msg_qual = await message.reply("⚙️ **Kualitas:**", reply_markup=kb_qual)
    resp_qual = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_qual, resp_qual)
    if not resp_qual or "batal" in (resp_qual.text or "").lower(): return

    quality = "fast" if "cepat" in resp_qual.text.lower() else "hq" if "hq" in resp_qual.text.lower() else "balanced"

    yt_enabled, yt_privacy = False, "private"
    if _HAS_YTUPLOAD:
        kb_yt = _make_reply_kb(["⏭️ Skip", "🌍 Public", "🔒 Private"], 3)
        msg_yt = await message.reply("📺 **YouTube?**", reply_markup=kb_yt)
        resp_yt = await wait_for_message(chat_id, user_id, 60)
        await _clean_msgs(msg_yt, resp_yt)
        if resp_yt and "skip" not in resp_yt.text.lower():
            yt_enabled = True
            yt_privacy = "public" if "public" in resp_yt.text.lower() else "private"

    await message.answer("⏳ Menyiapkan...", reply_markup=ReplyKeyboardRemove())
    
    # 🚀 EXECUTE
    await execute_unified_task(message, "AUTO CLIP", _core_autoclip_logic, message.reply_to_message, topic, mode, quality, yt_enabled, yt_privacy)
