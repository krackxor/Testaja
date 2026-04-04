"""
╔══════════════════════════════════════════════════════════════════════╗
║                    bot/AutoClip.py — v3.2                            ║
║        Auto Clip: Potong video panjang → Shorts/Reels terpisah       ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG:                                                          ║
║  [UX PREMIUM] Migrasi Total Dashboard Inline menjadi Interactive     ║
║               Wizard (Step-by-step) dengan Reply Keyboard Singkat!   ║
║  [UX PREMIUM] Auto-Delete disematkan di semua langkah setup produksi ║
║               agar obrolan tidak dipenuhi pesan sampah.              ║
║  [UX PREMIUM] Kotak Konfirmasi (Summary Box) diseragamkan dengan     ║
║               desain modul lain.                                     ║
║  [FIX HIGH] Implementasi CMD_SUFFIX pada command filter /clip        ║
║  [FIX] Syntax error pada pesan help /clip diperbaiki                 ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from moviepy import VideoFileClip, CompositeVideoClip, ColorClip, ImageClip
from moviepy.video.fx import FadeIn, FadeOut

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramBadRequest

from bot_helper.Database.User_Data import get_data, ensure_user_data_structure, get_task_limit
from bot_helper.Others.Helper_Functions import get_human_size, get_readable_time
from bot_helper.Others.Names import Names
from bot_helper.Process.Process_Status import ProcessStatus, get_progress_bar_string
from bot_helper.Process.Running_Process import append_running_process, check_running_process, remove_running_process
from bot_helper.Process.Running_Tasks import working_task, working_task_lock, queued_task, queued_task_lock
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config
from bot.shared import wait_for_message

try:
    from bot.YTUpload import upload_to_youtube, YOUTUBE_ENABLED
    _HAS_YTUPLOAD = True
except ImportError:
    YOUTUBE_ENABLED = False
    _HAS_YTUPLOAD   = False

LOGGER     = Config.LOGGER
CMD_SUFFIX = Config.CMD_SUFFIX
router     = Router()

TEMP_DIR           = "./temp/autoclip/"
SHORT_W, SHORT_H   = 1080, 1920
LAND_W,  LAND_H    = 1920, 1080
TARGET_FPS         = 30
QUEUE_TIMEOUT      = 7200

QUALITY_PRESETS = {
    "fast":     {"bitrate": "4000k", "preset": "ultrafast", "label": "⚡ Cepat"},
    "balanced": {"bitrate": "6000k", "preset": "fast",      "label": "⚖️ Seimbang"},
    "hq":       {"bitrate": "8000k", "preset": "slow",      "label": "💎 HQ"},
}

_clip_state: dict = {}
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

def _find_source_video(topic: str) -> Optional[str]:
    search_dirs = ["./gameplay/", "./userdata/gameplay/", "./videos/"]
    exts = [".mp4", ".mkv", ".avi", ".mov", ".webm"]
    for folder in search_dirs:
        if not os.path.isdir(folder): continue
        for f in os.listdir(folder):
            if topic.lower().replace(" ", "_") in f.lower() or f.lower().startswith(topic.lower().replace(" ", "_")):
                if any(f.lower().endswith(ext) for ext in exts): return os.path.join(folder, f)
    try:
        from bot.Gameplay import find_gameplay_for_game
        return find_gameplay_for_game(topic)
    except ImportError: pass
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
        if len(parts) < 2: errors.append(f"Baris {i}: Kurang kolom. Format: `Waktu | Judul`"); continue
        time_str, segment, desc = parts[0], parts[1], parts[2] if len(parts) >= 3 else ""
        t_split = [x.strip() for x in time_str.split("-")]
        if len(t_split) != 2: errors.append(f"Baris {i}: Format waktu salah. Contoh: `00:15 - 01:30`"); continue
        try:
            start_t, end_t = _time_to_sec(t_split[0]), _time_to_sec(t_split[1])
            if end_t <= start_t: errors.append(f"Baris {i}: Waktu akhir harus lebih besar dari waktu awal"); continue
            scenes.append({"segment": segment, "desc": desc, "start": start_t, "end": end_t, "duration": end_t - start_t})
        except ValueError: errors.append(f"Baris {i}: Angka waktu tidak valid")
    if errors: raise ValueError("❌ Format .txt salah:\n" + "\n".join(f"  • {e}" for e in errors))
    if not scenes: raise ValueError("❌ File .txt kosong atau tidak ada scene yang valid.")
    return scenes

# ═══════════════════════════════════════════════════════════════════════
#  VIDEO RENDERER
# ═══════════════════════════════════════════════════════════════════════

def _reframe_to_portrait(clip, w: int, h: int) -> "VideoFileClip":
    cw, ch = clip.size
    target_ratio, source_ratio = w / h, cw / ch
    if abs(source_ratio - target_ratio) < 0.05: return clip.resized((w, h))
    if source_ratio > target_ratio:
        new_w = int(ch * target_ratio); x1 = (cw - new_w) // 2
        return clip.cropped(x1=x1, x2=x1 + new_w).resized((w, h))
    else:
        new_h = int(cw / target_ratio); y1 = (ch - new_h) // 2
        return clip.cropped(y1=y1, y2=y1 + new_h).resized((w, h))

def _make_title_overlay(title: str, duration: float, w: int, h: int) -> ImageClip:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0)); draw = ImageDraw.Draw(img)
    bar_h = int(h * 0.10); draw.rectangle([0, 0, w, bar_h], fill=(0, 0, 0, 180))
    try: font_size = max(24, int(h * 0.038)); font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except Exception: font = ImageFont.load_default()
    max_chars = int(w / (font_size * 0.55))
    if len(title) > max_chars: title = title[:max_chars - 3] + "..."
    bbox = draw.textbbox((0, 0), title, font=font); tw, tx, ty = bbox[2] - bbox[0], (w - (bbox[2] - bbox[0])) // 2, (bar_h - (bbox[3] - bbox[1])) // 2
    draw.text((tx + 2, ty + 2), title, font=font, fill=(0, 0, 0, 180)); draw.text((tx, ty), title, font=font, fill=(255, 255, 255, 240))
    return ImageClip(__import__("numpy").array(img), is_mask=False).with_duration(duration).with_effects([FadeIn(0.3), FadeOut(0.3)])

def _make_progress_bar_overlay(duration: float, w: int, h: int) -> CompositeVideoClip:
    BAR_H = max(6, int(h * 0.007)); y_pos = h - BAR_H
    bg = ColorClip(size=(w, BAR_H), color=(50, 50, 50)).with_duration(duration).with_position((0, y_pos)).with_opacity(0.7)
    def _make_frame(t: float):
        fill_w = max(1, int(w * t / max(duration, 0.001)))
        arr = __import__("numpy").zeros((BAR_H, w, 3), dtype=__import__("numpy").uint8)
        arr[:, :fill_w] = [0, 200, 255]
        return arr
    bar = ImageClip(_make_frame, duration=duration, is_mask=False).with_position((0, y_pos))
    return bg, bar

def _make_watermark(duration: float, w: int, h: int) -> ImageClip:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0)); draw = ImageDraw.Draw(img)
    text = f"@{Config.BOT_USERNAME}" if Config.BOT_USERNAME else "Studio Khoirul"
    try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(18, int(h * 0.022)))
    except Exception: font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font); tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx, ty = w - tw - 12, h - th - 12 - 20
    draw.text((tx + 1, ty + 1), text, font=font, fill=(0, 0, 0, 160)); draw.text((tx, ty), text, font=font, fill=(200, 200, 200, 200))
    return ImageClip(__import__("numpy").array(img), is_mask=False).with_duration(duration).with_effects([FadeIn(0.5)])

async def render_clip(scene: dict, source_path: str, output_path: str, mode: str, quality: str, process_status: ProcessStatus) -> str:
    if not check_running_process(process_status.process_id): raise asyncio.CancelledError("Dibatalkan")
    start_t, end_t, title, dur, q = scene["start"], scene["end"], scene["segment"], scene["duration"], QUALITY_PRESETS.get(quality, QUALITY_PRESETS["balanced"])
    raw = None
    try:
        raw = VideoFileClip(source_path); end_t = min(end_t, raw.duration); dur = end_t - start_t
        if dur <= 0.5: raise ValueError(f"Durasi terlalu pendek ({dur:.1f}s) untuk scene '{title}'")
        clip = raw.subclip(start_t, end_t)
        if mode == "short": W, H = SHORT_W, SHORT_H; clip = _reframe_to_portrait(clip, W, H)
        elif mode == "landscape": W, H = LAND_W, LAND_H; clip = clip.resized((W, H))
        else: W, H = clip.size; W, H = W if W % 2 == 0 else W - 1, H if H % 2 == 0 else H - 1; clip = clip.resized((W, H))
        clip = clip.with_fps(TARGET_FPS)
        final = CompositeVideoClip([clip, _make_title_overlay(title, dur, W, H), _make_watermark(dur, W, H), *_make_progress_bar_overlay(dur, W, H)], size=(W, H))
        ffmpeg_params = ["-preset", q["preset"], "-profile:v", "high", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        def _write(): final.write_videofile(output_path, fps=TARGET_FPS, codec="libx264", bitrate=q["bitrate"], audio_codec="aac", audio_bitrate="192k", ffmpeg_params=ffmpeg_params, logger=None)
        await asyncio.to_thread(_write); return output_path
    finally:
        for obj in [raw]:
            if obj:
                try: obj.close()
                except Exception: pass

def _generate_clip_thumbnail(source_path: str, scene: dict, output_path: str, mode: str) -> Optional[str]:
    try:
        from PIL import Image, ImageDraw, ImageFont
        mid_time = scene["start"] + scene["duration"] / 2
        raw = VideoFileClip(source_path); frame = raw.get_frame(min(mid_time, raw.duration - 0.1)); raw.close()
        img = Image.fromarray(frame.astype("uint8"))
        if mode == "short": w, h = SHORT_W // 2, SHORT_H // 2
        elif mode == "landscape": w, h = LAND_W // 2, LAND_H // 2
        else: w, h = img.width, img.height
        img = img.resize((w, h), Image.LANCZOS); draw = ImageDraw.Draw(img)
        try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(16, h // 20))
        except Exception: font = ImageFont.load_default()
        title, bbox, margin = scene["segment"], draw.textbbox((0, 0), scene["segment"], font=font), 10
        draw.rectangle([0, 0, w, bbox[3] - bbox[1] + margin * 2], fill=(0, 0, 0, 180)); draw.text((margin, margin), title, font=font, fill=(255, 255, 255))
        img.save(output_path, "JPEG", quality=85); return output_path
    except Exception as e:
        LOGGER.debug(f"Thumbnail gagal untuk '{scene['segment']}': {e}"); return None

# ═══════════════════════════════════════════════════════════════════════
#  MAIN WORKER
# ═══════════════════════════════════════════════════════════════════════

async def _autoclip_worker(process_status: ProcessStatus, original_event: Message, reply_msg: Message, topic: str, mode: str, quality: str, yt_enabled: bool, yt_privacy: str, status_msg: Message) -> None:
    txt_path, render_start = _tmp(f"clip_{process_status.process_id}.txt"), time.time()
    try:
        process_status.update_process_message(f"📥 **Mengunduh naskah waktu cut...**\n\n**Sumber:** `{topic}`\n**Mode:** `{mode.upper()}`\n**Quality:** `{QUALITY_PRESETS[quality]['label']}`\n**ID:** `{process_status.process_id}`\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
        await _safe_edit(status_msg, process_status.status_message)
        await Telegram.AIOGRAM_BOT.download(reply_msg.document, destination=txt_path)
        if not os.path.exists(txt_path): raise RuntimeError("Gagal download file .txt")

        scenes, total = parse_clip_txt(txt_path), len(parse_clip_txt(txt_path))
        LOGGER.info(f"AutoClip: {total} scene ditemukan untuk '{topic}'")
        source_path = _find_source_video(topic)
        if not source_path:
            available = _list_available_sources(); av_text = "\n".join(f"  • `{s}`" for s in available[:10]) if available else "  _Belum ada video_"
            raise RuntimeError(f"Video sumber `{topic}` tidak ditemukan!\n\n**Video tersedia:**\n{av_text}\n\nUpload dulu via `/addgameplay{CMD_SUFFIX}`")
        
        source_size, success_count = os.path.getsize(source_path), 0
        LOGGER.info(f"AutoClip sumber: {source_path} ({get_human_size(source_size)})")

        for idx, scene in enumerate(scenes, 1):
            if not check_running_process(process_status.process_id): raise asyncio.CancelledError("Dibatalkan")
            seg_title, seg_dur, out_file, thumb_file = scene["segment"], scene["duration"], _tmp(f"clip_{process_status.process_id}_{idx:02d}.mp4"), _tmp(f"thumb_{process_status.process_id}_{idx:02d}.jpg")
            elapsed, eta_secs = time.time() - render_start, ((time.time() - render_start) / idx * (total - idx + 1)) if idx > 1 else 0
            
            process_status.update_process_message(f"✂️ **Merender Clip [{idx}/{total}]**\n\n`{seg_title}`\n{get_progress_bar_string(idx - 1, total)} {((idx-1)*100//total)}%\n**Waktu:** `{scene['start']:.1f}s` → `{scene['end']:.1f}s` ({seg_dur:.0f}s)\n**Sumber:** `{topic}`\n**Mode:** `{mode.upper()}` | **Quality:** `{QUALITY_PRESETS[quality]['label']}`\n**W.Proses:** `{get_readable_time(elapsed)}` | **ETA:** `{get_readable_time(eta_secs)}`\n**Ditambahkan Oleh:** {process_status.added_by}\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
            await _safe_edit(status_msg, process_status.status_message)
            process_status.ping = time.time()

            try: await render_clip(scene, source_path, out_file, mode, quality, process_status)
            except asyncio.CancelledError: raise
            except Exception as e:
                LOGGER.error(f"❌ Render scene {idx} gagal: {e}", exc_info=True)
                await _safe_edit(status_msg, f"⚠️ **Clip [{idx}/{total}] gagal render:**\n`{e}`\n\nLanjut ke clip berikutnya...")
                _cleanup(out_file); continue

            thumb = _generate_clip_thumbnail(source_path, scene, thumb_file, mode)
            clip_size = os.path.getsize(out_file)
            caption = f"✂️ **CLIP {idx}/{total}**\n\n📌 **Judul:** {seg_title}\n🎬 **Sumber:** `{topic}`\n⏱️ **Durasi:** `{seg_dur:.0f}` detik\n📐 **Mode:** `{mode.upper()}` | `{QUALITY_PRESETS[quality]['label']}`\n💽 **Ukuran:** `{get_human_size(clip_size)}`"
            if scene.get("desc"): caption += f"\n📝 **Catatan:** {scene['desc']}"

            try: _vc = VideoFileClip(out_file); vdur, vw, vh = int(_vc.duration), _vc.size[0], _vc.size[1]; _vc.close()
            except Exception: vdur, vw, vh = int(seg_dur), 1080, 1920

            try:
                await Telegram.AIOGRAM_BOT.send_video(chat_id=original_event.chat.id, video=FSInputFile(out_file), caption=caption, thumbnail=FSInputFile(thumb) if thumb else None, supports_streaming=True, width=vw, height=vh, duration=vdur, reply_to_message_id=original_event.message_id)
                success_count += 1
            except Exception as e:
                LOGGER.error(f"❌ Upload Telegram clip {idx} gagal: {e}", exc_info=True)
                await _safe_edit(status_msg, f"⚠️ Upload clip {idx} gagal: `{e}`")

            if yt_enabled and YOUTUBE_ENABLED and _HAS_YTUPLOAD:
                yt_title_clip, yt_desc_clip = f"{topic} — {seg_title}", f"Clip dari: {topic}\nSegmen: {seg_title}\nDurasi: {seg_dur:.0f} detik\n" + (scene["desc"] if scene.get("desc") else "")
                process_status.update_process_message(f"⬆️ **Upload YouTube Clip [{idx}/{total}]**\n\n`{yt_title_clip}`\n**Ditambahkan Oleh:** {process_status.added_by}\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
                await _safe_edit(status_msg, process_status.status_message)
                try:
                    yt_link = await upload_to_youtube(out_file, yt_title_clip, yt_desc_clip, yt_privacy, process_status, status_msg)
                    await original_event.answer(f"📺 **YouTube Clip {idx}:** [Buka ↗]({yt_link})", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📺 Tonton di YouTube", url=yt_link)]]))
                except asyncio.CancelledError: raise
                except Exception as e:
                    LOGGER.warning(f"⚠️  YouTube upload clip {idx} gagal: {e}")
                    await original_event.answer(f"⚠️ YouTube clip {idx} gagal: `{e}`")

            _cleanup(out_file, thumb_file); process_status.ping = time.time()

        total_time = get_readable_time(time.time() - render_start)
        final_text = f"✅ **Auto Clip Selesai!**\n\n📊 **Berhasil:** `{success_count}/{total}` clip\n🎬 **Sumber:** `{topic}`\n📐 **Mode:** `{mode.upper()}` | `{QUALITY_PRESETS[quality]['label']}`\n⏱️ **Total Waktu:** `{total_time}`\n**Oleh:** {process_status.added_by}"
        if success_count < total: final_text += f"\n\n⚠️ {total - success_count} clip gagal (lihat log di atas)"
        await _safe_edit(status_msg, final_text)

    except asyncio.CancelledError: await _safe_edit(status_msg, "🚫 **Auto Clip Dibatalkan.**")
    except Exception as e:
        LOGGER.error(f"❌ AutoClip worker error: {e}", exc_info=True)
        await _safe_edit(status_msg, f"❌ **Error AutoClip:**\n\n`{str(e)[:400]}`")
    finally:
        _cleanup(txt_path); _clip_state.pop(process_status.user_id, None)
        await remove_running_process(process_status.process_id)
        async with working_task_lock:
            for task in list(working_task):
                ps = task.get("process_status")
                if ps and ps.process_id == process_status.process_id:
                    working_task.remove(task); break

async def _start_autoclip_task(process_status: ProcessStatus, original_event: Message, reply_msg: Message, topic: str, mode: str, quality: str, yt_enabled: bool, yt_privacy: str, status_msg: Message) -> None:
    task_wrapper = {"process_status": process_status, "functions": [], "_autoclip": True}; queued = False
    async with working_task_lock:
        if len(working_task) < get_task_limit():
            working_task.append(task_wrapper); await append_running_process(process_status.process_id)
        else: queued = True

    if queued:
        async with queued_task_lock: pos = len(queued_task) + 1; queued_task.append(task_wrapper)
        await _safe_edit(status_msg, f"⏳ **Masuk Antrian Auto Clip**\n\n📋 **Posisi:** `{pos}`\n🎬 **Sumber:** `{topic}`\n📐 **Mode:** `{mode.upper()}` | `{QUALITY_PRESETS[quality]['label']}`\n**ID:** `{process_status.process_id}`\n`/cancel{CMD_SUFFIX} process {process_status.process_id}`")
        waited = 0
        while waited < QUEUE_TIMEOUT:
            await asyncio.sleep(5); waited += 5
            async with queued_task_lock:
                if task_wrapper not in queued_task: break
        else:
            async with queued_task_lock:
                if task_wrapper in queued_task: queued_task.remove(task_wrapper)
            await _safe_edit(status_msg, "❌ **Timeout antrian (2 jam).** Coba lagi.")
            _clip_state.pop(process_status.user_id, None); return
        if not check_running_process(process_status.process_id):
            _clip_state.pop(process_status.user_id, None); return

    await _autoclip_worker(process_status, original_event, reply_msg, topic, mode, quality, yt_enabled, yt_privacy, status_msg)

# ═══════════════════════════════════════════════════════════════════════
#  DASHBOARD & COMMAND HANDLERS (WIZARD UI)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"clip{CMD_SUFFIX}"))
async def autoclip_handler(message: Message, command: CommandObject) -> None:
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if not _is_vip(user_id):
        return await message.reply("👑 **Fitur Eksklusif VIP**\n\nAuto Clip membutuhkan resource render yang besar.\nFitur ini hanya untuk member **VIP/Premium**.\n\nHubungi admin untuk info berlangganan.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Hubungi Admin", url=f"https://t.me/{Config.BOT_USERNAME}")]]))

    if not message.reply_to_message:
        return await message.reply(
            f"❌ **Cara Pakai:**\nBalas file `.txt` dengan perintah:\n`/clip{CMD_SUFFIX} NamaVideo`\n\n"
            "**Contoh isi .txt:**\n"
            "00:00 - 00:30 | Momen Epik Pertama\n"
            "01:15 - 01:45 | Pertarungan Bos Akhir"
        )

    topic = (command.args or "").strip()
    if not topic:
        return await message.reply(
            "❌ **Nama Video Kosong**\n"
            f"Silakan sertakan nama game/video yang ingin dipotong.\nContoh: `/clip{CMD_SUFFIX} Resident Evil 4`"
        )

    # WIZARD STEP 1: MODE
    kb_mode = _make_reply_kb(["📱 Shorts", "🖥️ Landscape", "🔄 Auto", "❌ Batal"], 3)
    msg_mode = await message.reply("📐 **Pilih Format Pemotongan:**", reply_markup=kb_mode)
    resp_mode = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_mode, resp_mode)
    
    txt_mode = (resp_mode.text or "").lower()
    if not resp_mode or "batal" in txt_mode:
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    mode = "landscape" if "landscape" in txt_mode else "auto" if "auto" in txt_mode else "short"

    # WIZARD STEP 2: QUALITY
    kb_qual = _make_reply_kb(["⚡ Cepat", "⚖️ Seimbang", "💎 HQ", "❌ Batal"], 3)
    msg_qual = await message.reply("⚙️ **Pilih Kualitas Render:**", reply_markup=kb_qual)
    resp_qual = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_qual, resp_qual)
    
    txt_qual = (resp_qual.text or "").lower()
    if not resp_qual or "batal" in txt_qual:
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    quality = "fast" if "cepat" in txt_qual else "hq" if "hq" in txt_qual else "balanced"

    # WIZARD STEP 3: YOUTUBE
    yt_enabled, yt_privacy = False, "private"
    if YOUTUBE_ENABLED and _HAS_YTUPLOAD:
        kb_yt = _make_reply_kb(["❌ Skip", "🌍 Public", "🔗 Unlisted", "🔒 Private", "❌ Batal"], 3)
        msg_yt = await message.reply("📺 **Upload ke YouTube Otomatis?**", reply_markup=kb_yt)
        resp_yt = await wait_for_message(chat_id, user_id, 60)
        await _clean_msgs(msg_yt, resp_yt)
        
        txt_yt = (resp_yt.text or "").lower()
        if not resp_yt or "batal" in txt_yt:
            return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        yt_enabled = "skip" not in txt_yt
        if yt_enabled:
            yt_privacy = "public" if "public" in txt_yt else "unlisted" if "unlisted" in txt_yt else "private"

    # WIZARD STEP 4: CONFIRMATION
    kb_conf = _make_reply_kb(["✅ Potong", "❌ Batal"], 2)
    conf_txt = (
        f"**✂️ KONFIRMASI AUTO CLIP**\n\n"
        f"🎬 **Sumber:** `{topic}`\n"
        f"📐 **Mode:** `{mode.upper()}`\n"
        f"⚙️ **Quality:** `{QUALITY_PRESETS[quality]['label']}`\n"
        f"📺 **YouTube:** `{'✅ Upload ('+yt_privacy.capitalize()+')' if yt_enabled else '❌ Skip'}`\n\n"
        "Lanjutkan?"
    )
    msg_conf = await message.reply(conf_txt, reply_markup=kb_conf)
    resp_conf = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_conf, resp_conf)
    
    if not resp_conf or "batal" in (resp_conf.text or "").lower():
        return await message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())

    await message.answer("✅ Menyiapkan Proses Auto Clip...", reply_markup=ReplyKeyboardRemove())

    # INITIALIZE PROCESS
    sender_name = message.from_user.first_name or str(user_id)
    ps = ProcessStatus(user_id, chat_id, message.from_user.username or "", sender_name, message, getattr(Names, "autoclip", "AutoClip"), "Telegram")
    
    init_text = f"✂️ **Memulai Auto Clip...**\n**Sumber:** `{topic}`\n**ID:** `{ps.process_id}`\n`/cancel{CMD_SUFFIX} process {ps.process_id}`"
    kb_action = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Batalkan", callback_data=f"ac_cancel_{user_id}_{ps.process_id}")]])
    
    status_msg = await message.answer(init_text, reply_markup=kb_action)
    
    asyncio.create_task(_start_autoclip_task(
        ps, message, message.reply_to_message, topic, mode, quality, yt_enabled, yt_privacy, status_msg
    ))


@router.callback_query(F.data.startswith("ac_cancel_"))
async def cb_ac_cancel(call: CallbackQuery):
    await call.answer("🚫 Membatalkan...")
    parts = call.data.split("_")
    uid = int(parts[2])
    
    if call.from_user.id != uid: 
        return await call.answer("❌ Bukan milikmu!", show_alert=True)
        
    if len(parts) >= 4:
        process_id = parts[3]
        await remove_running_process(process_id)
        
    await _safe_edit(call.message, "❌ **Auto Clip dibatalkan.**")
