"""
╔══════════════════════════════════════════════════════════════════════╗
║    bot/Gameplay.py — v5.3 (ONE-CLICK STUDIO EDITION)                 ║
║    Studio Khoirul: Core Engine Video Production Bot (Pay-As-You-Go)  ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v5.3:                                                     ║
║  [UX PREMIUM] ROMBAK TOTAL ENTRY POINT! Tidak perlu reply TXT lagi.  ║
║  [UX PREMIUM] Bot otomatis mendeteksi file .txt yang dikirim dan     ║
║               memunculkan Dashboard Studio Interaktif (Satu Klik).   ║
║  [NEW] INTEGRASI SISTEM POIN! Memotong saldo sebelum render jalan.   ║
║  [INTEGRATION] Migrasi total ke bot_helper.Process.Unified_Engine    ║
║  [FIX CRITICAL] Memperbaiki AttributeError: ganti Telegram.          ║
║                 PYROGRAM_BOT menjadi Telegram.PYROGRAM_CLIENT untuk  ║
║                 upload final yang aman dari timeout.                 ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import gc
import os
import random
import re
import subprocess
import time
import shutil
import math
import psutil 
from datetime import datetime
from typing import Optional

# ── Aiogram ───────────────────────────────────────────────────────────
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandObject
from aiogram.exceptions import TelegramBadRequest

# ── Third Party ───────────────────────────────────────────────────────
import cv2
import edge_tts
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import (
    AudioFileClip, ColorClip, CompositeVideoClip,
    ImageClip, VideoFileClip, concatenate_videoclips,
    CompositeAudioClip, concatenate_audioclips
)
from moviepy.video.fx import FadeIn, FadeOut, Loop
from moviepy.audio.fx import AudioLoop, MultiplyVolume

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.User_Data import get_data, ensure_user_data_structure
from bot_helper.Others.Helper_Functions import get_human_size, get_readable_time
from bot_helper.Others.Names import Names
from bot_helper.Process.Unified_Engine import execute_unified_task
from bot_helper.Telegram.Telegram_Client import Telegram
from config.config import Config
from bot.shared import wait_for_message, CMD_SUFFIX

# [NEW] Import Mesin Kasir Poin
from bot_helper.Process.point_manager import process_payment

try:
    from bot.YTUpload import _core_ytupload_logic, YOUTUBE_ENABLED, _is_vip as _yt_is_vip
    _HAS_YTUPLOAD = True
except ImportError:
    YOUTUBE_ENABLED = False
    _HAS_YTUPLOAD   = False
    def _yt_is_vip(uid): return uid == Config.OWNER_ID or uid in Config.SUDO_USERS

try:
    import yt_dlp
    YTDLP_ENABLED = True
except ImportError:
    YTDLP_ENABLED = False

LOGGER     = Config.LOGGER
router     = Router()

# ═══════════════════════════════════════════════════════════════════════
#  KONFIGURASI GLOBAL
# ═══════════════════════════════════════════════════════════════════════
VOICE        = "en-US-SteffanNeural"  
GAMEPLAY_DIR = "./gameplay/"
TEMP_DIR     = "./temp/"
THUMB_DIR    = "./thumbs/"

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

TARGET_W, TARGET_H, TARGET_FPS = 1920, 1080, 30
SHORT_W, SHORT_H = 1080, 1920
BITRATE, AUDIO_BR, PRESET, PROG_H = "8000k", "192k", "fast", 8

FFMPEG_PARAMS = [
    "-preset", PRESET, 
    "-profile:v", "high", 
    "-level", "4.2", 
    "-pix_fmt", "yuv420p", 
    "-movflags", "+faststart", 
    "-g", "30", 
    "-keyint_min", "30", 
    "-sc_threshold", "0",
    "-threads", "4"  
]
FFMPEG_SHORT  = FFMPEG_PARAMS

THUMB_W, THUMB_H, THUMB_SHORT_W, THUMB_SHORT_H = 1920, 1080, 1080, 1920

VERDICT_MAP = {
    10: ("MASTERPIECE", (255, 215,   0)), 9: ("MUST PLAY",   (255, 200,   0)),
    8: ("GREAT",       ( 80, 220,  80)), 7: ("GOOD",        ( 80, 200,  80)),
    6: ("DECENT",      ( 80, 180, 255)), 5: ("AVERAGE",     (180, 180, 180)),
    4: ("BELOW AVG",   (255, 160,  50)), 3: ("WEAK",        (255, 110,  50)),
    2: ("BAD",         (220,  50,  50)), 1: ("AWFUL",       (190,  30,  30)),
}

ARCADE_GOLD, CINEMA_RED, CINEMA_CREAM, CINEMA_GOLD = (255, 200, 0), (200, 30, 30), (255, 240, 210), (220, 180, 80)
BURST_CYAN, BURST_MAGENTA, BURST_WHITE = (0, 230, 255), (255, 30, 120), (255, 255, 255)
ARCHIVE_AMBER, LORE_PURPLE, LORE_GREEN = (255, 191, 0), (148, 0, 211), (57, 255, 20)
RADAR_CYAN, RADAR_ORANGE, PATCH_RED, PATCH_YELLOW = (0, 255, 255), (255, 140, 0), (220, 20, 60), (255, 255, 0)

for _d in [GAMEPLAY_DIR, TEMP_DIR, THUMB_DIR, "./audio"]: os.makedirs(_d, exist_ok=True)

# State sementara per user untuk menyimpan file script .txt yang baru dikirim
_studio_session: dict = {}


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
        if "Batal" in opt or "❌" in opt: btn_style = "danger"
        elif "Ya" in opt or "✅" in opt: btn_style = "success"
        else: btn_style = "primary"
        row.append(KeyboardButton(text=opt, style=btn_style))
        if len(row) == row_width: kb.append(row); row = []
    if row: kb.append(row)
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)

def get_dynamic_semaphore():
    try:
        mem = psutil.virtual_memory()
        if mem.percent > 85: return 1  
        elif mem.percent > 70: return 2 
        else: return 3                
    except:
        return 2

def _dash(icon: str, title: str, rows: list) -> str: return f"{icon} **{title}**\n`{'─'*30}`\n" + "\n".join(f"  {lbl:<13}{val}" for lbl, val in rows) + f"\n`{'─'*30}`"
def _st(step: str, detail: str = "") -> str: return f"⏳ {step}" + (f"\n`{detail}`" if detail else "")
def _ok(step: str, detail: str = "") -> str: return f"✅ {step}" + (f"\n`{detail}`" if detail else "")
def _er(msg: str) -> str: return f"❌ {msg}"
def _is_video_msg(msg: Message) -> bool: return bool(msg and (msg.video or (msg.document and msg.document.mime_type and "video" in msg.document.mime_type)))

async def _safe_edit(msg: Message, text: str, buttons=None):
    try: 
        if buttons: await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else: await msg.edit_text(text)
    except TelegramBadRequest: pass
    except Exception: pass

def tmp(name: str) -> str: return os.path.join(TEMP_DIR, name)
def cleanup_temp(files: list):
    for f in files:
        if f and os.path.isfile(f):
            try: os.remove(f)
            except: pass

def safe_filename(name: str, ext: str = ".mp4") -> str:
    clean = re.sub(r'[^\w\-_. ]', '_', name).strip()
    return clean if clean.lower().endswith(ext) else clean + ext

async def download_with_progress(message: Message, reply_msg: Message, dest: str, label: str = "Video", status_msg: Message = None) -> bool:
    target_media = reply_msg.video or reply_msg.document or reply_msg.audio
    if not target_media: return False
    
    last_dl_edit = 0.0
    async def _dl_progress(current: int, total: int):
        nonlocal last_dl_edit
        now = time.time()
        if now - last_dl_edit >= 2.0 and status_msg:
            pct = current / total if total else 0
            bar = "█" * int(pct * 10) + "░" * (10 - int(pct * 10))
            try: await status_msg.edit_text(f"⏳ 🔽 **Mengunduh {label}...**\n\n[{bar}] {pct*100:.1f}%\n📥 `{get_human_size(current)} / {get_human_size(total)}`")
            except Exception: pass
            last_dl_edit = now

    pyro_client = Telegram.PYROGRAM_CLIENT
    downloaded = False
    if pyro_client:
        try:
            pyro_msg = await pyro_client.get_messages(reply_msg.chat.id, reply_msg.message_id)
            await pyro_client.download_media(message=pyro_msg, file_name=dest, progress=_dl_progress)
            downloaded = True
        except Exception as e:
            LOGGER.error(f"Pyrogram temp dl error: {e}")
    
    if not downloaded:
        await Telegram.AIOGRAM_BOT.download(target_media, destination=dest)
        
    return os.path.exists(dest)


# ═══════════════════════════════════════════════════════════════════════
#  VIDEO REFRAME & SMART SLICING (ALL SYNC FUNCTIONS)
# ═══════════════════════════════════════════════════════════════════════

def normalize_clip(clip, w=TARGET_W, h=TARGET_H, fps=TARGET_FPS):
    if clip.fps != fps: clip = clip.with_fps(fps)
    src_r = clip.w/clip.h; tgt_r = w/h
    nw, nh = (int(clip.w*(h/clip.h)), h) if src_r > tgt_r else (w, int(clip.h*(w/clip.w)))
    clip = clip.resized((nw, nh)); x1, y1 = (nw-w)//2, (nh-h)//2
    return clip.cropped(x1=x1, y1=y1, x2=x1+w, y2=y1+h)

def reframe_to_short(clip, w=SHORT_W, h=SHORT_H, fps=TARGET_FPS):
    if clip.fps != fps: clip = clip.with_fps(fps)
    src_r = clip.w/clip.h; tgt_r = w/h
    nw, nh = (w, int(clip.h*(w/clip.w))) if src_r <= tgt_r else (int(clip.w*(h/clip.h)), h)
    clip = clip.resized((nw, nh)); x1, y1 = (nw-w)//2, (nh-h)//2
    return clip.cropped(x1=x1, y1=y1, x2=x1+w, y2=y1+h)

def list_gameplay_videos() -> list: return [f for f in os.listdir(GAMEPLAY_DIR) if f.lower().endswith(('.mp4', '.mkv', '.avi', '.mov'))]

def find_gameplay_for_game(game_title: str) -> Optional[str]:
    vids = list_gameplay_videos(); tgt = game_title.lower().strip()
    if not vids: return None
    for v in vids:
        if v.lower().rsplit('.', 1)[0] == tgt: return os.path.join(GAMEPLAY_DIR, v)
    for v in vids:
        stem = v.lower().rsplit('.', 1)[0]
        if tgt in stem or stem in tgt: return os.path.join(GAMEPLAY_DIR, v)
    return max([os.path.join(GAMEPLAY_DIR, v) for v in vids], key=os.path.getmtime)

def split_gameplay(gameplay_path: str, scenes: list) -> list:
    tot = VideoFileClip(gameplay_path).duration
    weights = [0 if sc["type"]=="RATING" else max(5.0, min(60.0, len(sc["narration"].split())/2.5)) for sc in scenes]
    tw = sum(weights); cur = 0.0; segs = []
    for sc, w in zip(scenes, weights):
        if sc["type"] == "RATING": segs.append(None); continue
        end = min(cur+max(5.0, (w/tw)*tot if tw > 0 else tot/max(len(scenes), 1)), tot)
        segs.append((cur, end)); cur = end
    return segs

def get_gameplay_clip(path: str, start: float, end: float, target: float):
    raw = normalize_clip(VideoFileClip(path)); max_start = max(start, end - target)
    t0 = random.uniform(start, max_start) if max_start > start else start
    seg = raw.with_subclip(t0, min(t0+target, raw.duration))
    return seg.with_effects([Loop(duration=target)]).with_subclip(0, target) if seg.duration < target else seg

def get_gameplay_montage(path: str, target: float):
    raw = normalize_clip(VideoFileClip(path)); n = max(3, int(target/3.0)); sd = target/n; segs = []
    for i in range(n):
        max_start = max(0, raw.duration - sd); t0 = random.uniform(0, max_start); seg = raw.with_subclip(t0, t0+sd)
        fx = []; fx += [FadeIn(0.3)] if i > 0 else []; fx += [FadeOut(0.3)] if i < n-1 else []
        segs.append(seg.with_effects(fx) if fx else seg)
    m = concatenate_videoclips(segs, method="compose")
    return m.with_subclip(0, target) if m.duration > target else m

def get_short_clip(path: str, start: float, end: float, target: float):
    raw = reframe_to_short(VideoFileClip(path)); max_start = max(start, end - target)
    t0 = random.uniform(start, max_start) if max_start > start else start
    seg = raw.with_subclip(t0, min(t0+target, raw.duration))
    return seg.with_effects([Loop(duration=target)]).with_subclip(0, target) if seg.duration < target else seg

def get_short_montage(path: str, target: float):
    raw = reframe_to_short(VideoFileClip(path)); n = max(3, int(target/3.0)); sd = target/n; segs = []
    for i in range(n):
        max_start = max(0, raw.duration - sd); t0 = random.uniform(0, max_start); seg = raw.with_subclip(t0, t0+sd)
        fx = []; fx += [FadeIn(0.3)] if i > 0 else []; fx += [FadeOut(0.3)] if i < n-1 else []
        segs.append(seg.with_effects(fx) if fx else seg)
    m = concatenate_videoclips(segs, method="compose")
    return m.with_subclip(0, target) if m.duration > target else m

def get_hook_clip(path: str, is_portrait: bool, est_dur: float):
    raw = reframe_to_short(VideoFileClip(path)) if is_portrait else normalize_clip(VideoFileClip(path))
    max_start = max(0, raw.duration - est_dur)
    t0_hook = random.uniform(0, max_start)
    return raw.with_subclip(t0_hook, t0_hook + est_dur)


# ═══════════════════════════════════════════════════════════════════════
#  ULTRA-FAST MERGE (FFMPEG CONCAT DEMUXER)
# ═══════════════════════════════════════════════════════════════════════

def _merge_with_ffmpeg_ultrafast(video_paths: list, output_path: str, ffmpeg_params: list, apply_bgm: bool = True) -> float:
    if not video_paths: return 0.0
    
    list_file = tmp(f"concat_list_{int(time.time())}.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in video_paths: 
            f.write(f"file '{os.path.abspath(p)}'\n")

    temp_concat = tmp(f"merged_concat_{int(time.time())}.mp4")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", 
            "-i", list_file, 
            "-c", "copy", 
            temp_concat
        ], check=True, capture_output=True, timeout=300)
    except subprocess.CalledProcessError as e:
        LOGGER.error(f"FFmpeg Concat Error: {e.stderr.decode()}")
        clips = [VideoFileClip(v) for v in video_paths]
        merged = concatenate_videoclips(clips, method="compose")
        merged.write_videofile(temp_concat, fps=TARGET_FPS, codec="libx264", 
                               bitrate=BITRATE, audio_bitrate=AUDIO_BR, 
                               logger=None, threads=4)
        for c in clips: c.close()
        merged.close()

    bgm_path = os.path.abspath("./audio/bgm.mp3")
    
    if apply_bgm and os.path.exists(bgm_path):
        probe_cmd = [
            "ffprobe", "-v", "error", "-show_entries", 
            "format=duration", "-of", 
            "default=noprint_wrappers=1:nokey=1", temp_concat
        ]
        try:
            result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
            video_duration = float(result.stdout.strip())
        except:
            video_duration = 60.0  
        
        temp_final = tmp(f"merged_with_bgm_{int(time.time())}.mp4")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", temp_concat,
            "-stream_loop", "-1", "-i", bgm_path,  
            "-filter_complex", 
            f"[1:a]volume=0.3,aloop=loop=-1:size=2e+09[bg]; [0:a][bg]amix=inputs=2:duration=first[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-t", str(video_duration),  
            "-c:v", "copy",  
            "-c:a", "aac",
            "-b:a", AUDIO_BR,
            "-shortest",
            temp_final
        ], check=True, capture_output=True, timeout=600)
        
        cleanup_temp([temp_concat])
        shutil.move(temp_final, output_path)
    else:
        shutil.move(temp_concat, output_path)
    
    cleanup_temp([list_file])
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", output_path], capture_output=True, text=True, timeout=10)
        return float(result.stdout.strip())
    except: return 0.0

def merge_clips(video_paths: list, output_path: str, apply_bgm: bool = True) -> float: 
    return _merge_with_ffmpeg_ultrafast(video_paths, output_path, FFMPEG_PARAMS, apply_bgm)

def merge_short_clips(video_paths: list, output_path: str, apply_bgm: bool = True) -> float: 
    return _merge_with_ffmpeg_ultrafast(video_paths, output_path, FFMPEG_SHORT, apply_bgm)


# ═══════════════════════════════════════════════════════════════════════
#  PILLOW TEXT SYSTEM & EFEK VISUAL
# ═══════════════════════════════════════════════════════════════════════

def _font(size: int, bold: bool = True):
    try: return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    except: return ImageFont.load_default()
def _measure(text: str, font): return ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=font)[2:4]
def _wrap(text: str, font, max_w: int) -> list:
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if _measure(test, font)[0] <= max_w: cur = test
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines or [text]
def _stroke(draw, x, y, text, font, fill, sfill, sw): draw.text((x, y), text, font=font, fill=(*fill, 255), stroke_width=sw, stroke_fill=(*sfill, 255))
def _glow(draw, x, y, text, font, fill, glow_color, radius=3):
    for r in range(radius, 0, -1): draw.text((x, y), text, font=font, fill=(*glow_color, int(180*(1-r/(radius+1)))), stroke_width=r, stroke_fill=(*glow_color, int(180*(1-r/(radius+1)))))
    draw.text((x, y), text, font=font, fill=(*fill, 255))
def make_gradient_bar(w, h, duration, a_top=0, a_bot=235, color=(0,0,0)):
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    for y in range(h): arr[y, :, :3] = color; arr[y, :, 3] = int(a_top + (a_bot-a_top)*(y/h)**1.4)
    return ImageClip(arr, is_mask=False).with_duration(duration).with_position(('center', 'bottom'))
def make_vignette(w, h, duration, strength=155):
    arr = np.zeros((h, w, 4), dtype=np.uint8); cx, cy = w/2, h/2; md = np.sqrt(cx**2+cy**2); ys, xs = np.ogrid[:h, :w]
    arr[:, :, 3] = (strength*(np.sqrt((xs-cx)**2+(ys-cy)**2)/md)**2.2).clip(0, 255).astype(np.uint8)
    return ImageClip(arr, is_mask=False).with_duration(duration).with_position('center')
def make_progress_bar(w, h, duration, color=ARCADE_GOLD, bg=(20,20,20)):
    return ColorClip(size=(w, PROG_H), color=bg).with_duration(duration).with_position(('center', h-PROG_H)), ColorClip(size=(1, PROG_H), color=color).with_duration(duration).with_position((0, h-PROG_H)).resized(lambda t: (max(1, int(w*t/max(duration, 0.1))), PROG_H))
def make_noise_overlay(w, h, duration, opacity=18):
    arr = np.zeros((h, w, 4), dtype=np.uint8); np.random.seed(42)
    arr[:, :, 3] = (np.random.randint(0, 255, (h, w), dtype=np.uint8) * opacity // 255).astype(np.uint8)
    return ImageClip(arr, is_mask=False).with_duration(duration).with_position('center')
def _calc_stars(card_w: int, sc: int = 10):
    max_star_w = int(card_w * 0.86); star_gap = max(2, int(max_star_w * 0.015))
    star_size = max(12, (max_star_w - star_gap*(sc-1)) // sc); fs_stl = _font(star_size); stw, sth = _measure("★", fs_stl)
    return fs_stl, stw, sth, star_gap, stw * sc + star_gap * (sc-1)
def make_cinema_game_badge(title, duration, w, h):
    is_portrait = h > w; fs = _font(int(w * 0.05) if is_portrait else max(24, int(h*0.036))); tw, th = _measure(title.upper(), fs); PAD_X, PAD_Y = 18, 12
    bw = min(tw+PAD_X*2, int(w*0.8) if is_portrait else int(w*0.45)); bh = th+PAD_Y*2; x, y = int(w*0.04), int(h*0.04)
    canvas = Image.new("RGBA", (w, h), (0,0,0,0)); draw = ImageDraw.Draw(canvas)
    draw.rectangle([x, y, x+bw, y+bh], fill=(*CINEMA_RED, 240)); draw.rectangle([x, y+bh, x+bw, y+bh+3], fill=(*CINEMA_GOLD, 200)); yc = y+PAD_Y
    for line in _wrap(title.upper(), fs, bw-PAD_X*2): _stroke(draw, x+PAD_X, yc, line, fs, CINEMA_CREAM, (0,0,0), 1); yc += _measure(line, fs)[1]+3
    return ImageClip(np.array(canvas), is_mask=False).with_duration(duration).with_effects([FadeIn(0.3)])
def make_cinema_subtitle(narration, duration, w, h, safe_bottom):
    is_portrait = h > w; fs = _font(int(w * 0.065) if is_portrait else max(26, int(h*0.048))); max_tw = int(w*0.9) if is_portrait else int(w*0.82)
    words = narration.split(); chunks = [" ".join(words[i:i+8]) for i in range(0, len(words), 8)]; tot_w = len(words); subs = []; tc = 0.0
    for chunk in chunks:
        cd = min(max(1.5, duration*len(chunk.split())/max(tot_w, 1)), duration-tc)
        if cd <= 0.1: break
        lines = _wrap(chunk, fs, max_tw); lsizes = [_measure(l, fs) for l in lines]; gap = int(h*0.010); PAD_X, PAD_Y = 24, 14
        bw = min(max(lw for lw,_ in lsizes)+PAD_X*2, int(w*0.92)); bh = sum(lh for _,lh in lsizes)+gap*max(0, len(lines)-1)+PAD_Y*2
        bx = (w-bw)//2; by = h-safe_bottom-bh
        canvas = Image.new("RGBA", (w, h), (0,0,0,0)); draw = ImageDraw.Draw(canvas)
        draw.rectangle([bx-2, by-2, bx+bw+2, by+bh+2], fill=(*CINEMA_RED, 40)); draw.rectangle([bx, by, bx+bw, by+bh], fill=(0,0,0,175)); draw.rectangle([bx, by, bx+4, by+bh], fill=(*CINEMA_RED, 220)); yc = by+PAD_Y
        for line, (lw2, lh2) in zip(lines, lsizes): _stroke(draw, (w-lw2)//2, yc, line, fs, CINEMA_CREAM, (0,0,0), 2); yc += lh2+gap
        subs.append(ImageClip(np.array(canvas), is_mask=False).with_duration(cd).with_start(tc).with_effects([FadeIn(0.2), FadeOut(0.2)])); tc += cd
    return subs
def make_cinema_watermark(duration, w, h, segment_name="THE VERDICT"):
    is_portrait = h > w; fs = _font(int(w * 0.035) if is_portrait else max(18, int(h*0.022)), bold=False); theme = get_segment_theme(segment_name)
    accent = theme.get("title_glow", theme["title_color"]); text = f"⚡ STUDIO KHOIRUL | {segment_name}"; tw, th = _measure(text, fs); MARGIN = 14; x, y = w-tw-MARGIN, h-th-PROG_H-MARGIN
    canvas = Image.new("RGBA", (w, h), (0,0,0,0)); draw = ImageDraw.Draw(canvas)
    draw.rectangle([x-6, y-3, x+tw+6, y+th+3], fill=(0,0,0,150)); draw.rectangle([x-6, y+th+3, x+tw+6, y+th+6], fill=(*accent[:3], 200)); _stroke(draw, x, y, text, fs, theme["subtitle_color"][:3], (0,0,0), 1)
    return ImageClip(np.array(canvas), is_mask=False).with_duration(duration)
def make_cinema_title_overlay(title, duration, w, h, segment_name="THE VERDICT"):
    theme = get_segment_theme(segment_name); is_portrait = h > w
    fs_big = _font(int(w * 0.11) if is_portrait else max(55, int(h * 0.110)), bold=theme["font_bold"]); max_title_w = int(w * 0.90) if is_portrait else int(w * 0.78)
    lines = _wrap(title.upper(), fs_big, max_title_w); lsizes = [_measure(l, fs_big) for l in lines]; gap = int(h*0.018); tot_h = sum(lh for _,lh in lsizes)+gap*max(0, len(lines)-1)
    fs_sub = _font(int(w * 0.04) if is_portrait else max(20, int(h * 0.032)), bold=False); sub_lines = _wrap(f"STUDIO KHOIRUL • {segment_name}", fs_sub, max_title_w) if is_portrait else [f"STUDIO KHOIRUL • {segment_name}"]
    sub_lsizes = [_measure(l, fs_sub) for l in sub_lines]
    y0 = int(h * 0.28) - (tot_h // 2) if is_portrait else (h-(sum(lh for _,lh in sub_lsizes)+20+tot_h))//2
    canvas = Image.new("RGBA", (w, h), (0,0,0,0)); draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, w, h], fill=(0,0,0,160)); lw2 = int(w*0.8) if is_portrait else int(w*0.6); lx = (w-lw2)//2; accent = theme.get("title_glow", theme["title_color"])
    draw.rectangle([lx, y0-8, lx+lw2, y0-4], fill=(*accent[:3], 220)); yc = y0
    for line, (tw2, th2) in zip(lines, lsizes):
        if "title_glow" in theme: _glow(draw, (w-tw2)//2, yc, line, fs_big, theme["title_color"], theme["title_glow"], 4)
        else: _stroke(draw, (w-tw2)//2, yc, line, fs_big, theme["title_color"], (0,0,0), 3)
        yc += th2+gap
    draw.rectangle([lx, yc+4, lx+lw2, yc+8], fill=(*accent[:3], 220)); yc += 18
    for sub_line, (stw, sth) in zip(sub_lines, sub_lsizes): _stroke(draw, (w-stw)//2, yc, sub_line, fs_sub, theme["subtitle_color"], (0,0,0), 1); yc += sth + 5
    return ImageClip(np.array(canvas), is_mask=False).with_duration(duration).with_effects([FadeIn(0.8), FadeOut(0.6)])
def make_cinema_rating_card(score, game_title, duration, w, h):
    is_portrait = h > w; score = max(1, min(10, score)); label, col = VERDICT_MAP.get(score, ("OK",(180,180,180)))
    fs_num = _font(int(w*0.25) if is_portrait else int(h*0.17)); fs_lbl = _font(int(w*0.07) if is_portrait else int(h*0.055))
    fs_g = _font(int(w*0.06) if is_portrait else max(26, int(h*0.040))); fs_sub = _font(int(w*0.035) if is_portrait else max(18, int(h*0.028)), bold=False)
    sw, sh = _measure(str(score), fs_num); lw, lh = _measure(label, fs_lbl); out_stw, out_sth = _measure("FINAL VERDICT", fs_sub)
    g_lines = _wrap(game_title.upper(), fs_g, int(w*0.85) if is_portrait else int(w*0.72)); g_sizes = [_measure(l, fs_g) for l in g_lines]
    g_gap = int(h*0.008); GAP = int(h*0.016); CPX, CPY = int(w*0.05) if is_portrait else int(w*0.13), int(h*0.04) if is_portrait else int(h*0.065); cw_card = w-CPX*2
    fs_stl, stw, sth, star_gap, star_row_w = _calc_stars(cw_card)
    tot_h = out_sth+GAP+sh+GAP+sth+GAP+lh+GAP+sum(gh for _,gh in g_sizes)+g_gap*max(0, len(g_lines)-1)+4; y0 = (h-tot_h)//2; cx, cy = CPX, y0-CPY; ch = tot_h+CPY*2
    canvas = Image.new("RGBA", (w, h), (0,0,0,0)); draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle([cx, cy, cx+cw_card, cy+ch], radius=8, fill=(8,6,6,220)); draw.rounded_rectangle([cx, cy, cx+cw_card, cy+ch], radius=8, outline=(*CINEMA_GOLD, 200), width=2); draw.rectangle([cx+8, cy+ch-8, cx+cw_card-8, cy+ch-4], fill=(*CINEMA_RED, 200)); ry = y0
    _stroke(draw, (w-out_stw)//2, ry, "FINAL VERDICT", fs_sub, CINEMA_GOLD, (0,0,0), 1); ry += out_sth+GAP
    _stroke(draw, (w-sw)//2, ry, str(score), fs_num, col, (0,0,0), 4); ry += sh+GAP; sx_s = cx+(cw_card-star_row_w)//2
    for i in range(10): _stroke(draw, sx_s+i*(stw+star_gap), ry, "★" if i<score else "☆", fs_stl, col if i<score else (50,40,40), (0,0,0), 1)
    ry += sth+GAP; _stroke(draw, (w-lw)//2, ry, label, fs_lbl, col, (0,0,0), 2); ry += lh+GAP
    for line, (glw, glh) in zip(g_lines, g_sizes): _stroke(draw, (w-glw)//2, ry, line, fs_g, CINEMA_CREAM, (0,0,0), 2); ry += glh+g_gap
    return ImageClip(np.array(canvas), is_mask=False).with_duration(duration).with_effects([FadeIn(0.7), FadeOut(0.5)])
def make_burst_section_badge(text, duration, w, h):
    is_portrait = h > w; fs = _font(int(w * 0.05) if is_portrait else max(34, int(h*0.032))); tw, th = _measure(text.upper(), fs)
    PAD_X, PAD_Y = 22, 12; bw = tw+PAD_X*2; bh = th+PAD_Y*2; M = int(h*0.045)
    canvas = Image.new("RGBA", (w, h), (0,0,0,0)); draw = ImageDraw.Draw(canvas)
    draw.rectangle([M, M, M+bw, M+bh], fill=(0,0,0,210)); draw.rectangle([M, M, M+4, M+bh], fill=(*BURST_CYAN, 255)); draw.rectangle([M, M+bh-4, M+bw, M+bh], fill=(*BURST_CYAN, 255)); draw.rectangle([M+bw-12, M, M+bw, M+12], fill=(*BURST_MAGENTA, 255))
    _stroke(draw, M+PAD_X, M+PAD_Y, text.upper(), fs, BURST_WHITE, (0,0,0), 2)
    return ImageClip(np.array(canvas), is_mask=False).with_duration(duration).with_effects([FadeIn(0.2), FadeOut(0.3)])
def make_burst_subtitle(text, chunk_dur, w, h):
    is_portrait = h > w; fs = _font(int(w * 0.075) if is_portrait else max(50, int(h*0.042))); lines = _wrap(text.upper(), fs, int(w * 0.92) if is_portrait else int(w*0.86))
    lsizes = [_measure(l, fs) for l in lines]; gap = int(h*0.012); PAD_X, PAD_Y = 24, 16; bw = min(max(lw for lw,_ in lsizes)+PAD_X*2, int(w*0.96))
    bh = sum(lh for _,lh in lsizes)+gap*max(0, len(lines)-1)+PAD_Y*2; bx = (w-bw)//2; by = h-bh-int(h*0.30)
    canvas = Image.new("RGBA", (w, h), (0,0,0,0)); draw = ImageDraw.Draw(canvas)
    draw.rectangle([bx, by, bx+bw, by+bh], fill=(0,0,0,190)); draw.rectangle([bx, by+bh-4, bx+bw, by+bh], fill=(*BURST_CYAN, 200)); yc = by+PAD_Y
    for line, (lw2, lh2) in zip(lines, lsizes): _stroke(draw, (w-lw2)//2, yc, line, fs, BURST_WHITE, (0,0,0), 3); yc += lh2+gap
    return ImageClip(np.array(canvas), is_mask=False).with_duration(chunk_dur).with_effects([FadeIn(0.15), FadeOut(0.15)])
def make_burst_rating_card(score, game_title, duration, w=SHORT_W, h=SHORT_H):
    is_portrait = h > w; score = max(1, min(10, score)); label, col = VERDICT_MAP.get(score, ("OK",(180,180,180)))
    fs_num = _font(int(w*0.25) if is_portrait else int(h*0.155)); fs_lbl = _font(int(w*0.07) if is_portrait else int(h*0.048)); fs_g = _font(int(w*0.06) if is_portrait else max(32, int(h*0.036)))
    sw, sh = _measure(str(score), fs_num); lw, lh = _measure(label, fs_lbl); g_lines = _wrap(game_title.upper(), fs_g, int(w*0.9) if is_portrait else int(w*0.80))
    g_sizes = [_measure(l, fs_g) for l in g_lines]; g_gap = int(h*0.008); GAP = int(h*0.016); CPX, CPY = int(w*0.05) if is_portrait else int(w*0.08), int(h*0.04) if is_portrait else int(h*0.045)
    cw_card = w-CPX*2; fs_stl, stw, sth, star_gap, star_row_w = _calc_stars(cw_card); tot_h = sh+GAP+sth+GAP+lh+GAP+sum(gh for _,gh in g_sizes)+g_gap*max(0, len(g_lines)-1)+4; y0 = (h-tot_h)//2; cx, cy = CPX, y0-CPY; ch = tot_h+CPY*2
    canvas = Image.new("RGBA", (w, h), (0,0,0,0)); draw = ImageDraw.Draw(canvas)
    draw.rectangle([cx, cy, cx+cw_card, cy+ch], fill=(0,0,0,220)); draw.rectangle([cx, cy, cx+cw_card, cy+4], fill=(*BURST_CYAN, 255)); draw.rectangle([cx, cy, cx+cw_card, cy+ch], fill=(*BURST_CYAN, 255)); draw.rectangle([cx, cy, cx+4, cy+ch], fill=(*BURST_CYAN, 255)); draw.rectangle([cx+cw_card-4, cy, cx+cw_card, cy+ch], fill=(*BURST_CYAN, 255)); ry = y0
    _glow(draw, (w-sw)//2, ry, str(score), fs_num, col, BURST_CYAN, 5); ry += sh+GAP; sx_s = cx+(cw_card-star_row_w)//2
    for i in range(10): _glow(draw, sx_s+i*(stw+star_gap), ry, "★" if i<score else "☆", fs_stl, col if i<score else (30,30,50), col if i<score else (30,30,50), 2)
    ry += sth+GAP; _glow(draw, (w-lw)//2, ry, label, fs_lbl, col, BURST_CYAN, 3); ry += lh+GAP
    for line, (glw, glh) in zip(g_lines, g_sizes): _stroke(draw, (w-glw)//2, ry, line, fs_g, BURST_WHITE, (0,0,0), 2); ry += glh+g_gap
    return ImageClip(np.array(canvas), is_mask=False).with_duration(duration).with_effects([FadeIn(0.6), FadeOut(0.5)])

def get_random_thumb_frame(video_path: str) -> np.ndarray:
    cap = cv2.VideoCapture(video_path); total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    random_idx = random.randint(int(total_frames * 0.1), int(total_frames * 0.9)); cap.set(cv2.CAP_PROP_POS_FRAMES, random_idx)
    ok, frame = cap.read(); cap.release()
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if ok and frame is not None else np.zeros((THUMB_H, THUMB_W, 3), dtype=np.uint8)

def make_thumbnail(frame_rgb, game_title, score=None, w=THUMB_W, h=THUMB_H, mode="review"):
    is_portrait = h > w; img = Image.fromarray(frame_rgb); src_r = img.width/img.height; tgt_r = w/h
    nw, nh = (h, int(img.width*h/img.height)) if src_r > tgt_r else (w, int(img.height*w/img.width))
    img = img.resize((nw, nh), Image.LANCZOS); x1, y1 = (nw-w)//2, (nh-h)//2; bg = img.crop((x1, y1, x1+w, y1+h)).convert("RGBA"); canvas = bg.copy(); draw = ImageDraw.Draw(canvas)
    grad_h = int(h*(0.52 if is_portrait else 0.65)); grad = Image.new("RGBA", (w, grad_h), (0,0,0,0)); gd = ImageDraw.Draw(grad)
    for y in range(grad_h): gd.line([(0,y),(w,y)], fill=(0,0,0,int(220*(y/grad_h)**1.5)))
    canvas.paste(grad, (0, h-grad_h), grad); MARGIN_L = int(w*0.055); MARGIN_B = int(h*(0.055 if is_portrait else 0.075)); tlen = len(game_title)
    fs = int(w*(0.125 if tlen<=10 else 0.096 if tlen<=18 else 0.078 if tlen<=28 else 0.062)) if is_portrait else int(h*(0.112 if tlen<=10 else 0.086 if tlen<=18 else 0.068 if tlen<=28 else 0.055))
    ft = _font(fs, bold=True); lines = _wrap(game_title.upper(), ft, int(w*(0.86 if is_portrait else 0.62))); lsizes = [_measure(l, ft) for l in lines]; gap = int(fs*0.18)
    tot_th = sum(lh for _,lh in lsizes)+gap*max(0, len(lines)-1); accent_col = {"arcade":ARCADE_GOLD,"review":CINEMA_RED,"short":BURST_CYAN}.get(mode, CINEMA_RED)
    title_col = {"arcade":(255,255,255),"review":CINEMA_CREAM,"short":BURST_WHITE}.get(mode, CINEMA_CREAM); line_y = h-MARGIN_B-tot_th-5-int(h*0.016)
    draw.rectangle([MARGIN_L, line_y, MARGIN_L+min(int(w*0.48), max(lw for lw,_ in lsizes)+24), line_y+5], fill=(*accent_col, 255)); ty = h-MARGIN_B-tot_th
    for line, (lw2, lh2) in zip(lines, lsizes): _stroke(draw, MARGIN_L, ty, line, ft, title_col, (0,0,0), 3); ty += lh2+gap
    if score is not None:
        score = max(1, min(10, score)); label, col = VERDICT_MAP.get(score, ("OK",(180,180,180)))
        fs_num = int(w*0.195) if is_portrait else int(h*0.170); fs_sub = int(w*0.052) if is_portrait else int(h*0.045); fs_lbl = int(w*0.056) if is_portrait else int(h*0.048)
        fn_num=_font(fs_num); fn_sub=_font(fs_sub, bold=False); fn_lbl=_font(fs_lbl); s_txt=str(score); slash_txt="/10"; sw2,sh2=_measure(s_txt,fn_num); slw,slh=_measure(slash_txt,fn_sub); lbw,lbh=_measure(label,fn_lbl)
        PAD_X=int(w*0.028); PAD_Y=int(h*0.020); badge_w=max(sw2+slw+10,lbw)+PAD_X*2; badge_h=sh2+lbh+PAD_Y*2+int(h*0.010)
        bx = (w-int(w*0.055))-badge_w if is_portrait else (w-MARGIN_L)-badge_w; by = int(h*0.058) if is_portrait else (h-MARGIN_B)-badge_h
        draw.rounded_rectangle([bx-6,by-6,bx+badge_w+6,by+badge_h+6], radius=14, fill=(0,0,0,210)); draw.rounded_rectangle([bx-6,by-6,bx+badge_w+6,by+badge_h+6], radius=14, outline=(*col,215), width=3)
        num_x=bx+(badge_w-sw2-slw-8)//2; num_y=by+PAD_Y; _stroke(draw,num_x,num_y,s_txt,fn_num,col,(0,0,0),4); _stroke(draw,num_x+sw2+5,num_y+sh2-slh-int(h*0.004),slash_txt,fn_sub,(185,185,185),(0,0,0),2); _stroke(draw,bx+(badge_w-lbw)//2,num_y+sh2+int(h*0.008),label,fn_lbl,col,(0,0,0),2)
    fs_logo = max(15,int(w*0.026) if is_portrait else int(h*0.028)); fl=_font(fs_logo, bold=False); logo="STUDIO KHOIRUL"; ltw,lth=_measure(logo,fl); lx=int(w*0.028) if is_portrait else w-ltw-int(w*0.028); ly=int(h*0.028); P=7
    draw.rounded_rectangle([lx-P,ly-P//2,lx+ltw+P,ly+lth+P//2], radius=5, fill=(0,0,0,170)); draw.rectangle([lx-P,ly+lth+P//2-3,lx+ltw+P,ly+lth+P//2], fill=(*accent_col,200)); draw.text((lx,ly), logo, font=fl, fill=(*accent_col, 240))
    return canvas.convert("RGB")

def generate_thumbnail(game_title, score=None, gameplay_path=None, save_path=None, portrait=False, mode="review") -> str:
    src = gameplay_path if (gameplay_path and os.path.exists(gameplay_path)) else find_gameplay_for_game(game_title)
    if not src and list_gameplay_videos(): src = os.path.join(GAMEPLAY_DIR, random.choice(list_gameplay_videos()))
    if not src: raise ValueError("Tidak ada video sumber untuk thumbnail.")
    img = make_thumbnail(get_random_thumb_frame(src), game_title, score=score, w=THUMB_SHORT_W if portrait else THUMB_W, h=THUMB_SHORT_H if portrait else THUMB_H, mode=mode)
    
    if not save_path: 
        safe_title = re.sub(r'[^\w]', '_', game_title)
        suffix = '_portrait' if portrait else ''
        save_path = os.path.join(THUMB_DIR, f"thumb_{safe_title}{suffix}.png")
        
    img.save(save_path, "PNG", optimize=True); return save_path


# ═══════════════════════════════════════════════════════════════════════
#  UNIVERSAL TEXT PARSER & THEME
# ═══════════════════════════════════════════════════════════════════════

def parse_studio_txt(path: str) -> dict:
    scenes, errors, main_title, yt_description, rating_score = [], [], None, "", None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, raw in enumerate(f, 1):
            line = raw.strip()
            if not line or line.startswith("#"): continue
            parts = [x.strip() for x in line.split("|")]; stype = parts[0].upper() if parts else ""
            if stype == "DESC": yt_description = parts[1] if len(parts) > 1 else ""; continue
            if stype == "RATING":
                try:
                    sc = int(parts[1] if len(parts) > 1 else "")
                    if not 1 <= sc <= 10: raise ValueError
                    rating_score = sc; scenes.append({"type": "RATING", "segment": "Verdict", "narration": str(sc)})
                except: errors.append(f"Baris {i}: Skor RATING harus angka 1-10")
                continue
            if len(parts) < 3:
                if len(parts) == 2 and stype in ["TITLE", "HOOK"]: parts.append(" ")
                else: errors.append(f"Baris {i}: Format salah"); continue
            seg, narr = parts[1], parts[2]
            if stype not in {"TITLE", "HOOK", "INTRO", "OUTRO", "CONCLUSION", "SECTION", "CHAPTER", "DROP", "FACT", "THEORY", "UPDATE"} and not stype.isdigit():
                errors.append(f"Baris {i}: Tag '{stype}' tidak dikenali"); continue
            if not seg: errors.append(f"Baris {i}: Judul segmen kosong"); continue
            if narr == "-" or not narr: narr = "-"
            if stype in ["TITLE", "HOOK"] and main_title is None: main_title = seg
            scenes.append({"type": stype, "segment": seg, "narration": narr})
    if errors: raise ValueError("Format .txt salah:\n" + "\n".join(errors))
    if not scenes: raise ValueError("File .txt kosong.")
    if main_title is None: main_title = scenes[0]["segment"]
    return {"title": main_title, "description": yt_description, "score": rating_score, "scenes": scenes}

def get_segment_theme(segment_name):
    nu = segment_name.upper()
    if nu == "THE ARCHIVES": return {"title_color": ARCHIVE_AMBER, "subtitle_color": ARCHIVE_AMBER, "sub_bar_color": (0, 0, 0, 200), "font_bold": False}
    if nu == "LORE & CONSPIRACIES": 
        return {"title_color": (229, 9, 20), "title_glow": (150, 0, 0), "subtitle_color": (255, 255, 255), "sub_bar_color": (15, 15, 15, 240), "font_bold": True} 
    if nu == "TOP TIER": return {"title_color": ARCADE_GOLD, "subtitle_color": ARCADE_GOLD, "sub_bar_color": (0,0,0,180), "font_bold": True}
    if nu == "ON THE RADAR": return {"title_color": (255,255,255), "title_glow": RADAR_CYAN, "subtitle_color": (255,255,255), "sub_bar_color": (*RADAR_ORANGE, 200), "font_bold": False}
    if nu == "THE LATEST PATCH": return {"title_color": (255,255,255), "subtitle_color": PATCH_YELLOW, "sub_bar_color": (*PATCH_RED, 230), "font_bold": True}
    return {"title_color": CINEMA_CREAM, "subtitle_color": CINEMA_GOLD, "sub_bar_color": (*CINEMA_RED, 200), "font_bold": True}


# ═══════════════════════════════════════════════════════════════════════
#  UNIVERSAL RENDERER (STRICT CLEANUP)
# ═══════════════════════════════════════════════════════════════════════

async def render_studio_clip(scene_dict, segment_name, output_name, game_title, bg_clip=None, res_mode="16:9", subtitles_on=True, show_badge=True) -> str:
    temp = []; is_portrait = (res_mode == "9:16"); W, H = (SHORT_W, SHORT_H) if is_portrait else (TARGET_W, TARGET_H)
    ffmpeg_cfg = FFMPEG_SHORT if is_portrait else FFMPEG_PARAMS; theme = get_segment_theme(segment_name)
    stype, seg, narr = scene_dict["type"], scene_dict["segment"], scene_dict["narration"]
    
    final_clip = None
    vo = None
    sfx_audio = None
    bg = None

    try:
        dur = 3.0
        tts_text = narr 
        pitch_setting = "+0Hz"
        rate_setting = "+0%"
        volume_setting = "+0%"
        current_voice = VOICE
        
        if "[DEEP]" in tts_text:
            tts_text = tts_text.replace("[DEEP]", "").strip()
            pitch_setting = "-10Hz"; rate_setting = "-15%"
        elif "[SLOW]" in tts_text:
            tts_text = tts_text.replace("[SLOW]", "").strip()
            rate_setting = "-20%"
        elif "[FAST]" in tts_text:
            tts_text = tts_text.replace("[FAST]", "").strip()
            rate_setting = "+15%"
        elif "[WHISPER]" in tts_text: 
            tts_text = tts_text.replace("[WHISPER]", "").strip()
            pitch_setting = "-5Hz"; rate_setting = "-10%"; volume_setting = "-40%"
        elif "[PANIC]" in tts_text: 
            tts_text = tts_text.replace("[PANIC]", "").strip()
            pitch_setting = "+15Hz"; rate_setting = "+25%"; volume_setting = "+20%"
        elif "[DRAMATIC]" in tts_text: 
            tts_text = tts_text.replace("[DRAMATIC]", "").strip()
            pitch_setting = "-15Hz"; rate_setting = "-5%"; volume_setting = "+40%"
        elif "[ARCHIVE]" in tts_text: 
            tts_text = tts_text.replace("[ARCHIVE]", "").strip()
            current_voice = "en-GB-SoniaNeural"
            pitch_setting = "+0Hz"; rate_setting = "-10%"; volume_setting = "-20%"

        visual_text = re.sub(r'\[.*?\]', '', narr)
        visual_text = re.sub(r'[\.\-\~]+', '', visual_text).strip()
        if not visual_text: visual_text = narr 

        if narr.strip() and narr != "-":
            ap = output_name.replace(".mp4", ".mp3"); temp.append(ap)
            await edge_tts.Communicate(tts_text, current_voice, rate=rate_setting, pitch=pitch_setting, volume=volume_setting).save(ap) 
            if os.path.exists(ap) and os.path.getsize(ap) > 512:
                vo = AudioFileClip(ap); dur = max(vo.duration, 1.0)
        else: dur = 3.0; subtitles_on = False 
        
        sfx_map = {
            "HOOK": "sfx_impact.mp3", "DROP": "sfx_impact.mp3", "FACT": "sfx_impact.mp3", "TITLE": "sfx_impact.mp3", "CLIMAX": "sfx_impact.mp3",
            "CHAPTER": "sfx_whoosh.mp3", "SECTION": "sfx_whoosh.mp3", "INTRO": "sfx_whoosh.mp3", "CONCLUSION": "sfx_whoosh.mp3", "OUTRO": "sfx_whoosh.mp3",
            "THEORY": "sfx_glitch.mp3", "UPDATE": "sfx_glitch.mp3", "MIDPOINT": "sfx_glitch.mp3",
            "RATING": "sfx_rating.mp3"
        }
        sfx_file = sfx_map.get(stype)
        if sfx_file:
            sfx_path = os.path.abspath(f"./audio/{sfx_file}")
            if os.path.exists(sfx_path): 
                try: sfx_audio = AudioFileClip(sfx_path).with_duration(min(1.5, dur))
                except: pass

        if bg_clip is None: raise ValueError("Tidak ada sumber video gameplay.")
        if bg_clip.duration < dur: bg_clip = bg_clip.with_effects([Loop(duration=dur)])
        bg = bg_clip.with_subclip(0, dur)

        audio_layers = []
        if bg.audio is not None: audio_layers.append(bg.audio.with_effects([MultiplyVolume(0.1)]))
        if vo: audio_layers.append(vo)
        if sfx_audio: audio_layers.append(sfx_audio.with_effects([MultiplyVolume(0.8)]))
        
        if audio_layers:
            final_audio = CompositeAudioClip(audio_layers)
            bg = bg.with_audio(final_audio)
        
        clips = [bg, make_vignette(W, H, dur, 200), make_noise_overlay(W, H, dur, 20)]
        prog_bg, prog_bar = make_progress_bar(W, H, dur, theme["title_color"], (20,20,20))
        
        if stype in ("TITLE", "HOOK"):
            clips += [ColorClip(size=(W,H), color=(0,0,0)).with_opacity(0.7).with_duration(dur).with_effects([FadeIn(0.5)]), make_cinema_title_overlay(game_title, dur, W, H, segment_name)]
        elif stype == "RATING":
            clips += [ColorClip(size=(W,H), color=(0,0,0)).with_opacity(0.85).with_duration(dur).with_effects([FadeIn(0.5)]), make_burst_rating_card(int(narr) if narr.isdigit() else 8, game_title, dur, W, H) if is_portrait else make_cinema_rating_card(int(narr) if narr.isdigit() else 8, game_title, dur, W, H)]
        else:
            text_dur = min(3.5, dur); SAFE_M = PROG_H + int(H * 0.08)
            if show_badge: clips += [make_burst_section_badge(seg, text_dur, W, H)] if is_portrait else [make_gradient_bar(W, int(H*0.44), text_dur, 0, 240, (5,5,10)).with_effects([FadeIn(0.4),FadeOut(0.4)]), make_cinema_game_badge(seg, text_dur, W, H)]
            if subtitles_on and visual_text.strip() and visual_text != "-":
                words = visual_text.split(); chunks = [" ".join(words[i:i+15]) for i in range(0, len(words), 15)]; tot_w = len(words); tc = 0.0
                for chunk in chunks:
                    cd = min(max(1.5, dur * len(chunk.split()) / max(tot_w, 1)), dur - tc)
                    if cd <= 0.1: break
                    clips.append(make_burst_subtitle(chunk, cd, W, H).with_start(tc) if is_portrait else make_cinema_subtitle(chunk, cd, W, H, SAFE_M)[0].with_start(tc)); tc += cd
                    
        clips += [make_cinema_watermark(dur, W, H, segment_name), prog_bg, prog_bar]
        final_clip = CompositeVideoClip(clips, size=(W,H))
        
        kw = {
            "fps": TARGET_FPS, 
            "codec": "libx264", 
            "bitrate": BITRATE, 
            "audio_codec": "aac", 
            "audio_bitrate": AUDIO_BR, 
            "ffmpeg_params": ffmpeg_cfg, 
            "logger": None, 
            "threads": 4, 
            "write_logfile": False  
        }
        
        await asyncio.to_thread(final_clip.write_videofile, output_name, **kw)
        
    finally: 
        if final_clip:
            try: final_clip.close()
            except: pass
        if bg_clip:
            try: bg_clip.close()
            except: pass
        if bg:
            try: bg.close()
            except: pass
        if vo:
            try: vo.close()
            except: pass
        if sfx_audio:
            try: sfx_audio.close()
            except: pass
        cleanup_temp(temp)
        gc.collect() 
        
    return output_name


# ═══════════════════════════════════════════════════════════════════════
#  WORKER STUDIO (INTEGRATED WITH UNIFIED_ENGINE)
# ═══════════════════════════════════════════════════════════════════════

async def _core_studio_logic(message: Message, ui, st: dict, gameplay_path: str) -> None:
    scenes, total, t0 = st["scenes"], len(st["scenes"]), time.time()
    
    for res_mode in [r for r in ["16:9", "9:16"] if st["resolution"] in [r, "both"]]:
        is_portrait = (res_mode == "9:16")
        res_label = f"{SHORT_W}×{SHORT_H} (Shorts)" if is_portrait else f"{TARGET_W}×{TARGET_H} (Landscape)"
        windows = await asyncio.to_thread(split_gameplay, gameplay_path, scenes)
        safe_title = re.sub(r'[^\w]', '_', st["title"])
        
        CHUNK_SIZE = 15 
        part_files = []
        completed_count = 0

        for chunk_idx in range(0, total, CHUNK_SIZE):
            chunk_scenes = scenes[chunk_idx:chunk_idx + CHUNK_SIZE]
            chunk_windows = windows[chunk_idx:chunk_idx + CHUNK_SIZE]
            concurrency = get_dynamic_semaphore()
            semaphore = asyncio.Semaphore(concurrency)
            chunk_generated = [None] * len(chunk_scenes)
            tasks = []
            prev_seg = None if chunk_idx == 0 else scenes[chunk_idx - 1]["segment"]
            
            async def process_single_scene(local_idx, global_idx, scene, window, prev_seg_local):
                nonlocal completed_count
                async with semaphore:
                    # Update fungsi prep_phase ke UI di Unified_Engine
                    sisa = total - completed_count
                    await ui.prep_phase("Mempersiapkan proses pemotongan...", remaining=sisa)

                    current_segment = scene["segment"]
                    out_name = tmp(f"cache_{message.from_user.id}_{safe_title}_{res_mode.replace(':','')}_{global_idx:02d}.mp4")
                    
                    if os.path.exists(out_name) and os.path.getsize(out_name) > 10000:
                        LOGGER.info(f"[CACHE HIT] Scene {global_idx} already rendered.")
                    else:
                        bg_clip = None
                        if scene["type"] == "RATING": 
                            bg_clip = await asyncio.to_thread(get_short_montage if is_portrait else get_gameplay_montage, gameplay_path, 10.0)
                        elif scene["type"] == "HOOK":
                            est_dur = max(5.0, len(scene["narration"].split()) / 2.0) if scene["narration"] != "-" else 4.0
                            bg_clip = await asyncio.to_thread(get_hook_clip, gameplay_path, is_portrait, est_dur)
                        else:
                            st_time, en_time = window; est_dur = max(5.0, len(scene["narration"].split()) / 2.5) if scene["narration"] != "-" else 4.0
                            bg_clip = await asyncio.to_thread(get_short_clip if is_portrait else get_gameplay_clip, gameplay_path, st_time, en_time, est_dur)
                        
                        for attempt in range(3):
                            try: 
                                await render_studio_clip(scene, st["segment_name"], out_name, st["title"], bg_clip, res_mode, st["subtitles"], show_badge=(current_segment != prev_seg_local))
                                break
                            except Exception as e:
                                LOGGER.error(f"Scene {global_idx} attempt {attempt+1} failed: {e}")
                                if attempt == 2: raise e
                                await asyncio.sleep(2)
                    
                    chunk_generated[local_idx] = out_name
                    completed_count += 1
                    
                    if completed_count % 2 == 0 or completed_count == total:
                        # REPORT PROGRESS TO UNIFIED_ENGINE UI
                        asyncio.create_task(ui.update(
                            status=f"🎬 Merender [{res_mode}] (Paralel {concurrency}x)",
                            current=completed_count,
                            total=total,
                            details=f"Scene {global_idx}: {current_segment[:20]}"
                        ))
                    gc.collect()

            for i, (sc, win) in enumerate(zip(chunk_scenes, chunk_windows)):
                tasks.append(process_single_scene(i, chunk_idx + i + 1, sc, win, prev_seg))
                prev_seg = sc["segment"]
                
            await asyncio.gather(*tasks)
            valid_chunk_files = [f for f in chunk_generated if f is not None]
            
            if valid_chunk_files:
                part_name = tmp(f"PART_{chunk_idx//CHUNK_SIZE}_{safe_title}_{res_mode.replace(':','')}.mp4")
                await asyncio.to_thread(merge_short_clips if is_portrait else merge_clips, valid_chunk_files, part_name, False)
                part_files.append(part_name)
                cleanup_temp(valid_chunk_files)
                gc.collect()

        # ─── THE FINAL MERGE ───
        if len(part_files) > 0:
            await ui.update(f"⚡ Final Merging [{res_mode}]", details="Menggabungkan semua part video (Ultrafast Mode)...")
            merged_path = tmp(f"FINAL_{st['segment_name'].replace(' ','')}_{res_mode.replace(':','')}_{safe_title}.mp4")
            
            await asyncio.to_thread(merge_short_clips if is_portrait else merge_clips, part_files, merged_path, True)
            
            # Buat Thumbnail & Upload Telegram
            await ui.update(f"📤 Mengunggah ke Telegram [{res_mode}]", details="Menyiapkan thumbnail HD...")
            score = next((int(s["narration"]) for s in scenes if s["type"] == "RATING" and str(s["narration"]).isdigit()), None)
            thumb_path = await asyncio.to_thread(generate_thumbnail, st["title"], score, gameplay_path, None, is_portrait, "short" if is_portrait else "review")
            
            # [FIX CRITICAL v5.3] Menggunakan Telegram.PYROGRAM_CLIENT
            try:
                await Telegram.PYROGRAM_CLIENT.send_video(
                    chat_id=message.chat.id,
                    video=merged_path,
                    thumb=thumb_path, 
                    caption=f"🎬 **{st['segment_name']} - {st['title']}**\n📐 {res_label}\n✅ Berhasil Dirender!",
                    supports_streaming=True,
                    width=SHORT_W if is_portrait else TARGET_W,
                    height=SHORT_H if is_portrait else TARGET_H
                )
            except Exception as e:
                LOGGER.error(f"Gagal upload Pyrogram: {e}")
                # Fallback ke Aiogram jika Pyrogram gagal
                try:
                    await Telegram.AIOGRAM_BOT.send_video(
                        chat_id=message.chat.id,
                        video=FSInputFile(merged_path),
                        thumbnail=FSInputFile(thumb_path),
                        caption=f"🎬 **{st['segment_name']} - {st['title']}**\n📐 {res_label}\n✅ Berhasil Dirender!",
                        supports_streaming=True,
                        width=SHORT_W if is_portrait else TARGET_W,
                        height=SHORT_H if is_portrait else TARGET_H,
                        request_timeout=3600 
                    )
                except Exception as fallback_e:
                    await message.answer(f"❌ Gagal mengirim video hasil akhir: {fallback_e}")
            
            # YouTube Upload (Jika aktif)
            if st["yt_enabled"] and YOUTUBE_ENABLED and _HAS_YTUPLOAD and os.path.exists(merged_path):
                await ui.update(f"🌐 Mengunggah [{res_mode}] ke YouTube...", details=f"Privasi: {st['yt_privacy'].capitalize()}")
                try:
                    from googleapiclient.http import MediaFileUpload
                    from bot.YTUpload import _get_youtube_client, YT_CHUNK_SIZE, YT_CATEGORY_ID, YT_TAGS
                    youtube = _get_youtube_client()
                    media = MediaFileUpload(merged_path, chunksize=YT_CHUNK_SIZE, resumable=True)
                    request = youtube.videos().insert(
                        part="snippet,status",
                        body={
                            "snippet": {
                                "categoryId": YT_CATEGORY_ID, "description": st["description"], 
                                "title": st["title"] + (" #Shorts" if is_portrait else ""), "tags": YT_TAGS,
                            },
                            "status": {"privacyStatus": st["yt_privacy"]},
                        },
                        media_body=media,
                    )
                    response = None
                    last_up_edit = 0.0
                    fsize = os.path.getsize(merged_path)
                    while response is None:
                        chunk_status, response = await asyncio.to_thread(request.next_chunk)
                        if chunk_status:
                            current = chunk_status.resumable_progress
                            now = time.time()
                            if now - last_up_edit >= 2.0:
                                await ui.update(f"🚀 Upload YouTube [{res_mode}]", current=current, total=fsize, details=f"Judul: {st['title']}")
                                last_up_edit = now

                    yt_link = f"https://youtu.be/{response.get('id', '')}"
                    btn = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📺 Buka YouTube", url=yt_link, style="success")]])
                    await message.answer(f"📺 **Berhasil Upload YouTube!** [{res_mode}]\n[Tonton Video ↗]({yt_link})", reply_markup=btn)
                except Exception as e: 
                    await message.answer(f"❌ YouTube upload gagal [{res_mode}]: `{e}`")
            
            cleanup_temp(part_files)
            cleanup_temp([merged_path])
            
    try: subprocess.run(["pkill", "-f", "ffmpeg"], check=False)
    except: pass
    
    elapsed = time.time() - t0
    txt_path = st.get("txt_path", "")
    cleanup_temp([txt_path] if txt_path else [])
    
    await ui.finish(f"✅ **Produksi Selesai!**\n{st['segment_name']} - {st['title']}")


# ═══════════════════════════════════════════════════════════════════════
#  MASTER COMMAND HANDLER (WIZARD UI)
# ═══════════════════════════════════════════════════════════════════════

STUDIO_COMMANDS = {
    "verdict": "THE VERDICT", "toptier": "TOP TIER", "archives": "THE ARCHIVES", 
    "lore": "LORE & CONSPIRACIES", "radar": "ON THE RADAR", "patch": "THE LATEST PATCH"
}

@router.message(F.document & F.document.file_name.endswith('.txt'))
async def auto_detect_txt_handler(message: Message) -> None:
    """Auto-detect file .txt dan memunculkan Dashboard Studio"""
    user_id = message.from_user.id
    
    # Save session data temporary
    _studio_session[user_id] = {
        "txt_msg": message,
        "document": message.document
    }
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 The Verdict (Merah)", callback_data="studio_verdict", style="primary"),
         InlineKeyboardButton(text="🏆 Top Tier (Emas)", callback_data="studio_toptier", style="primary")],
        [InlineKeyboardButton(text="📜 The Archives (Retro)", callback_data="studio_archives", style="primary"),
         InlineKeyboardButton(text="🧠 Lore (Netflix)", callback_data="studio_lore", style="primary")],
        [InlineKeyboardButton(text="📡 Radar (Cyan)", callback_data="studio_radar", style="primary"),
         InlineKeyboardButton(text="🗞️ Patch (Berita)", callback_data="studio_patch", style="primary")],
        [InlineKeyboardButton(text="❌ Batal", callback_data="studio_cancel", style="danger")]
    ])
    
    await message.reply(
        "📄 **Naskah Studio (.txt) Terdeteksi!**\n\n"
        "Silakan pilih Mode Produksi yang Anda inginkan untuk naskah ini:",
        reply_markup=kb
    )

@router.callback_query(F.data.startswith("studio_"))
async def studio_dashboard_cb(call: CallbackQuery) -> None:
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    action = call.data.replace("studio_", "")
    
    if action == "cancel":
        _studio_session.pop(user_id, None)
        return await call.message.edit_text("❌ Proses dibatalkan.")
        
    if user_id not in _studio_session:
        return await call.answer("❌ Sesi telah berakhir. Silakan kirim ulang file .txt Anda.", show_alert=True)
        
    session_data = _studio_session.pop(user_id)
    txt_msg = session_data["txt_msg"]
    
    segment_name = STUDIO_COMMANDS.get(action, "STUDIO KHOIRUL")
    command_used = action
    
    await call.message.delete() # Hapus dashboard inline
    
    txt_path = tmp(f"studio_{int(time.time())}.txt")
    await Telegram.AIOGRAM_BOT.download(session_data["document"], destination=txt_path)
    
    try: data = parse_studio_txt(txt_path)
    except ValueError as e: 
        cleanup_temp([txt_path])
        return await call.message.answer(f"❌ **Error Format TXT:**\n{str(e)}")
    
    await ensure_user_data_structure(user_id)
    
    # --- WIZARD START ---
    # Step 1: Resolusi
    kb_res = _make_reply_kb(["🖥 16:9", "📱 9:16", "🖥📱 Keduanya", "❌ Batal"], 3)
    msg_res = await call.message.answer("📐 **Pilih Resolusi Video:**", reply_markup=kb_res)
    resp_res = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_res, resp_res)
    
    if not resp_res:
        cleanup_temp([txt_path])
        return await call.message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    if "batal" in (resp_res.text or "").lower():
        cleanup_temp([txt_path])
        return await call.message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    
    res_txt = (resp_res.text or "").lower()
    res_mode = "both" if "keduanya" in res_txt else "9:16" if "9:16" in res_txt else "16:9"
    
    # Step 2: Subtitle
    kb_sub = _make_reply_kb(["✅ ON", "❌ OFF", "❌ Batal"], 3)
    msg_sub = await call.message.answer("💬 **Gunakan Subtitle Bergerak?**", reply_markup=kb_sub)
    resp_sub = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_sub, resp_sub)
    
    if not resp_sub:
        cleanup_temp([txt_path])
        return await call.message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    if "batal" in (resp_sub.text or "").lower():
        cleanup_temp([txt_path])
        return await call.message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    subs_on = True if "on" in (resp_sub.text or "").lower() else False
    
    # Step 3: YouTube
    yt_enabled, yt_privacy = False, "private"
    if YOUTUBE_ENABLED and _HAS_YTUPLOAD:
        kb_yt = _make_reply_kb(["⏭️ Skip", "🌍 Public", "🔗 Unlisted", "🔒 Private", "❌ Batal"], 3)
        msg_yt = await call.message.answer("📺 **Upload ke YouTube Otomatis?**", reply_markup=kb_yt)
        resp_yt = await wait_for_message(chat_id, user_id, 60)
        await _clean_msgs(msg_yt, resp_yt)
        
        if not resp_yt:
            cleanup_temp([txt_path])
            return await call.message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        if "batal" in (resp_yt.text or "").lower():
            cleanup_temp([txt_path])
            return await call.message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
            
        yt_txt = (resp_yt.text or "").lower()
        yt_enabled = "skip" not in yt_txt
        yt_privacy = "public" if "public" in yt_txt else "unlisted" if "unlisted" in yt_txt else "private"
    
    # Step 4: Konfirmasi Akhir (Summary Box)
    st = {
        "segment_name": segment_name, "title": data["title"], "description": data["description"], 
        "score": data["score"], "scenes": data["scenes"], "txt_path": txt_path, 
        "gameplay_reply": None, "resolution": res_mode, "subtitles": subs_on, 
        "yt_enabled": yt_enabled, "yt_privacy": yt_privacy
    }
    
    res_label = '🖥 16:9' if res_mode == '16:9' else '📱 9:16' if res_mode == '9:16' else '🖥📱 Keduanya'
    yt_label = f'✅ Upload ({yt_privacy.capitalize()})' if yt_enabled else '⏭️ Skip'
    
    conf_txt = (
        f"🎬 **KONFIRMASI PRODUKSI**\n\n"
        f"🏷️ **Segmen:** `{segment_name}`\n"
        f"📝 **Judul:** `{st['title'][:35]}...`\n"
        f"🎬 **Total Scene:** `{len(st['scenes'])} klip`\n"
        f"📐 **Resolusi:** `{res_label}`\n"
        f"💬 **Subtitle:** `{'✅ ON' if subs_on else '❌ OFF'}`\n"
        f"📺 **YouTube:** `{yt_label}`\n\n"
        "Lanjutkan?"
    )
    kb_conf = _make_reply_kb(["✅ Render", "❌ Batal"], 2)
    msg_conf = await call.message.answer(conf_txt, reply_markup=kb_conf)
    resp_conf = await wait_for_message(chat_id, user_id, 60)
    await _clean_msgs(msg_conf, resp_conf)
    
    if not resp_conf:
        cleanup_temp([txt_path])
        return await call.message.answer("❌ Waktu habis. Dibatalkan.", reply_markup=ReplyKeyboardRemove())
    if "batal" in (resp_conf.text or "").lower():
        cleanup_temp([txt_path])
        return await call.message.answer("❌ Dibatalkan.", reply_markup=ReplyKeyboardRemove())
        
    # [NEW v5.2] MESIN KASIR: POTONG SALDO POIN
    await call.message.answer("🔄 Mengecek Saldo Poin...", reply_markup=ReplyKeyboardRemove())
    
    payment = await process_payment(user_id=user_id, command=command_used)
    
    if not payment["success"]:
        cleanup_temp([txt_path])
        return await call.message.answer(payment["message"])

    await call.message.answer(f"⏳ ✅ Menyiapkan Mesin Produksi...\n{payment['message']}", reply_markup=ReplyKeyboardRemove())
    
    gp_path = await asyncio.to_thread(find_gameplay_for_game, st["title"])
    if not gp_path: 
        cleanup_temp([txt_path])
        return await call.message.answer(f"❌ Gameplay untuk `{st['title']}` tidak ditemukan di server!\nGunakan `/addgameplay{CMD_SUFFIX}`.")

    # 🚀 JALANKAN VIA UNIFIED ENGINE
    await execute_unified_task(txt_msg, f"PRODUKSI STUDIO ({segment_name})", _core_studio_logic, st, gp_path)


# ═══════════════════════════════════════════════════════════════════════
#  HANDLERS LAINNYA & ADDSFX
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"addsfx{CMD_SUFFIX}"))
async def addsfx_handler(message: Message, command: CommandObject) -> None:
    # Hanya untuk admin, tidak dipotong poin
    if message.from_user.id not in Config.SUDO_USERS and message.from_user.id != Config.OWNER_ID: 
        return
    raw_text = (command.args or "").strip()
    if not raw_text: return await message.reply(f"❌ **Format:** Balas file MP3/Audio -> `/addsfx{CMD_SUFFIX} sfx_impact`")
    
    reply_msg = message.reply_to_message
    if not reply_msg or not (reply_msg.audio or reply_msg.voice or reply_msg.document):
        return await message.reply("❌ Balas sebuah file audio/mp3!")

    valid_names = ["sfx_impact", "sfx_whoosh", "sfx_glitch", "sfx_rating", "bgm"]
    if raw_text not in valid_names:
        return await message.reply(f"❌ **Nama SFX harus salah satu dari:**\n`{', '.join(valid_names)}`\n\n_Contoh: /addsfx{CMD_SUFFIX} sfx_glitch_")

    final_path = os.path.join("./audio", f"{raw_text}.mp3")
    status_msg = await message.reply(f"⏳ Mengunduh `{raw_text}.mp3`...")
    
    res = await download_with_progress(message, reply_msg, final_path, label="sfx", status_msg=status_msg)
    if res: await _safe_edit(status_msg, f"✅ **Berhasil menyimpan SFX: `{raw_text}.mp3`**\n_Audio ini akan otomatis terpasang saat merender video!_")
    else: await _safe_edit(status_msg, "❌ Gagal mengunduh audio.")


def _check_gameplay_clip(path):
    t = VideoFileClip(path)
    w, h, d = t.w, t.h, t.duration
    t.close()
    return w, h, d

@router.message(Command(f"addgameplay{CMD_SUFFIX}"))
async def add_gameplay_handler(message: Message, command: CommandObject) -> None:
    if not message.reply_to_message: return await message.reply(_dash("🎮","Cara Pakai /addgameplay",[("Format",f"Balas video → /addgameplay{CMD_SUFFIX} Nama"),("Contoh",f"/addgameplay{CMD_SUFFIX} Hollow Knight"),("Lokasi","./gameplay/")]))
    
    custom_name = (command.args or "").strip()
    reply_msg = message.reply_to_message
    if not (reply_msg.video or reply_msg.document): return await message.reply(_er("Pesan yang di-reply bukan video!"))
    
    if custom_name: file_name = safe_filename(custom_name)
    else:
        doc = reply_msg.document or reply_msg.video
        file_name = re.sub(r'[^\w\-_. ]','_', doc.file_name) if getattr(doc, 'file_name', None) else f"gameplay_{message.message_id}.mp4"
        
    final_path = os.path.join(GAMEPLAY_DIR, file_name); status_msg = await message.reply(_st(f"Mengunduh `{file_name}`..."))
    if not await download_with_progress(message, reply_msg, final_path, label=f"`{file_name}`", status_msg=status_msg): 
        return await _safe_edit(status_msg, _er("Download gagal."))
        
    try: 
        w, h, d = await asyncio.to_thread(_check_gameplay_clip, final_path)
        await _safe_edit(status_msg, _dash("✅","Gameplay Tersimpan",[("File", file_name),("Resolusi",f"{w}×{h}"),("Durasi",f"{d:.1f}s"),("Lokasi","./gameplay/")]))
    except Exception as e: 
        cleanup_temp([final_path]); await _safe_edit(status_msg, _er(f"File tidak valid: {e}"))


def _get_gameplay_list_text(videos):
    lines = []
    tot = 0.0
    for i, v in enumerate(videos, 1):
        try:
            c = VideoFileClip(os.path.join(GAMEPLAY_DIR, v))
            d = c.duration
            lines.append((f"{i}. {v}", f"{c.w}×{c.h} · {d:.1f}s"))
            c.close()
            tot += d
        except:
            lines.append((f"{i}. {v}", "❌ error"))
    return lines, tot

@router.message(Command(f"listgameplay{CMD_SUFFIX}"))
async def list_gameplay_handler(message: Message) -> None:
    videos = sorted(list_gameplay_videos())
    if not videos: return await message.answer(f"❌ Belum ada gameplay.\n\nUpload: Balas video → `/addgameplay{CMD_SUFFIX} Nama Game`")
    
    status_msg = await message.answer("⏳ Membaca data durasi video...")
    lines, tot = await asyncio.to_thread(_get_gameplay_list_text, videos)
    
    await _safe_edit(status_msg, _dash("🎮", f"Gameplay — {len(videos)} video · {tot:.0f}s total", lines), buttons=[[InlineKeyboardButton(text="🗑️ Hapus gameplay", callback_data="gp_delete_prompt", style="danger")]])

@router.callback_query(F.data == "gp_delete_prompt")
async def gp_delete_prompt_cb(call: CallbackQuery) -> None: 
    await call.answer()
    await call.message.answer(f"Kirim: `/deletegameplay{CMD_SUFFIX} nama_file.mp4`")

@router.message(Command(f"deletegameplay{CMD_SUFFIX}"))
async def delete_gameplay_handler(message: Message, command: CommandObject) -> None:
    name = (command.args or "").strip(); path = os.path.join(GAMEPLAY_DIR, name)
    if os.path.exists(path): os.remove(path); await message.reply(_ok(f"Dihapus: {name}"))
    else: await message.reply(_er(f"File `{name}` tidak ditemukan.\nCek: `/listgameplay{CMD_SUFFIX}`"))


@router.message(Command(f"help{CMD_SUFFIX}"))
async def help_handler(message: Message) -> None:
    btns = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Gameplay", callback_data="help_gameplay", style="primary"), InlineKeyboardButton(text="🎬 Produksi", callback_data="help_produksi", style="primary")], 
        [InlineKeyboardButton(text="🛠 Tools", callback_data="help_tools", style="primary"), InlineKeyboardButton(text="⚙️ Settings", callback_data="help_settings", style="primary")]
    ])
    await message.answer(_dash("📖","STUDIO KHOIRUL — Panduan",[("","─── 🎮 MEDIA ───"),(f"/addgameplay{CMD_SUFFIX}", "Balas video → simpan gameplay"),(f"/addsfx{CMD_SUFFIX}", "Balas MP3 → simpan SFX"),(f"/listgameplay{CMD_SUFFIX}","Lihat semua gameplay"),("","─── 🎬 PRODUKSI UNIVERSAL ───"),("Kirim file .txt", "Otomatis memunculkan Menu Studio Khoirul"),("","─── ⚙️ LAINNYA ───"),(f"/settings{CMD_SUFFIX}","Konfigurasi bot"),(f"/help{CMD_SUFFIX}",   "Panduan ini")]), reply_markup=btns)

@router.callback_query(F.data == "help_gameplay")
async def help_gameplay_cb(call: CallbackQuery) -> None: 
    await call.answer()
    await call.message.answer(_dash("🎮","GAMEPLAY — Cara Pakai",[("Simpan",  f"Balas video → /addgameplay{CMD_SUFFIX} Nama"),("List", f"/listgameplay{CMD_SUFFIX}"),("Hapus", f"/deletegameplay{CMD_SUFFIX} nama.mp4"),("Format", "Nama file = nama game di .txt"),("Lokasi", "./gameplay/")]))

@router.callback_query(F.data == "help_produksi")
async def help_produksi_cb(call: CallbackQuery) -> None: 
    await call.answer()
    await call.message.answer(_dash("🎬","PRODUKSI — Format .txt",[("DESC", "DESC | Deskripsi video YouTube"),("TITLE", "TITLE | Judul Video | Teks Pembuka"),("HOOK", "HOOK | Kalimat Penarik Perhatian | Teks"),("SECTION", "SECTION | Nama Segmen | Teks"),("RATING",  "RATING | 9")]))

@router.callback_query(F.data == "help_tools")
async def help_tools_cb(call: CallbackQuery) -> None: 
    await call.answer()
    await call.message.answer(_dash("🛠","TOOLS — Cara Pakai",[("Auto SFX",  f"Balas mp3 -> /addsfx{CMD_SUFFIX} sfx_impact")]))

@router.callback_query(F.data == "help_settings")
async def help_settings_cb(call: CallbackQuery) -> None: 
    await call.answer()
    await _send_settings(call.message)

@router.message(Command(f"settings{CMD_SUFFIX}"))
async def settings_handler(message: Message) -> None: 
    await _send_settings(message)

async def _send_settings(message: Message) -> None: 
    btns = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Gameplay", callback_data="set_gameplay", style="primary"), InlineKeyboardButton(text="📺 YouTube", callback_data="set_yt", style="primary")], 
        [InlineKeyboardButton(text="📖 Help", callback_data="help_tools", style="primary")]
    ])
    await message.answer(_dash("⚙️","Studio Khoirul — Konfigurasi",[("","─── Resolusi ───"),("Landscape", f"{TARGET_W}×{TARGET_H} · {TARGET_FPS}fps"),("Portrait",  f"{SHORT_W}×{SHORT_H} · {TARGET_FPS}fps"),("","─── Encode ───"),("Bitrate",  f"{BITRATE} video · {AUDIO_BR} audio"),("Preset",  PRESET),("TTS Voice",VOICE),("","─── Status ───"),("Gameplay",  f"{len(list_gameplay_videos())} video"),("YouTube", "✅ Aktif" if YOUTUBE_ENABLED else "❌ Nonaktif"),("yt-dlp", "✅ Aktif" if YTDLP_ENABLED else "❌ Nonaktif")]), reply_markup=btns)

@router.callback_query(F.data == "set_gameplay")
async def set_gameplay_cb(call: CallbackQuery) -> None:
    await call.answer()
    videos = sorted(list_gameplay_videos())
    if not videos: return await call.message.answer(f"❌ Belum ada gameplay.\n\n`/addgameplay{CMD_SUFFIX} Nama`")
    
    status_msg = await call.message.answer("⏳ Membaca data durasi video...")
    lines, tot = await asyncio.to_thread(_get_gameplay_list_text, videos)
    
    await _safe_edit(status_msg, _dash("🎮",f"Gameplay ({len(videos)} video · {tot:.0f}s total)", lines))

@router.callback_query(F.data == "set_yt")
async def set_yt_cb(call: CallbackQuery) -> None: 
    await call.answer()
    await call.message.answer(_dash("📺","YouTube Status",[("API Upload", "✅ Siap" if YOUTUBE_ENABLED else "❌ Belum diinstall"),("yt-dlp", "✅ Siap" if YOUTUBE_ENABLED else "❌ Belum diinstall"),("Token", "✅ Ada" if os.path.exists("token.json") else "❌ Belum login"),("Secret", "✅ Ada" if os.path.exists("client_secret.json") else "❌ Tidak ada")]))
