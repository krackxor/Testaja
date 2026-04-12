"""
╔══════════════════════════════════════════════════════════════════════╗
║    bot_helper/Process/Unified_Engine.py — v2.8                       ║
║    Core Task Manager & UI Progress Handler untuk Studio Khoirul      ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v2.8:                                                     ║
║  [UI] Membuat nama "Engine" menjadi dinamis! Kini bot bisa           ║
║       menampilkan "Whisper AI", "FFmpeg", dll sesuai modul yang      ║
║       sedang digunakan alih-alih hanya "Unified Core".               ║
║  [FIX] Perbaikan bug TimeFormatter (UnboundLocalError hours).        ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import time
import traceback
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from config.config import Config

LOGGER = Config.LOGGER
_task_semaphore = asyncio.Semaphore(Config.RUNNING_TASK_LIMIT)

# Memori Internal & UI Exporter
_ue_queued = {}
_ue_working = {}
_ue_ui_objects = {}  

DIVIDER = "━━━━━━━━━━━━━━━━━━━━"

def humanbytes(size):
    if not size or size <= 0: return "0 B"
    power = 2**10
    n = 0
    Dic_powerN = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size >= power and n < 4:
        size /= power; n += 1
    return f"{round(size, 2)} {Dic_powerN[n]}"

def TimeFormatter(milliseconds: float) -> str:
    if not milliseconds or milliseconds <= 0: return "0s"
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    # [PERBAIKAN BUG DISINI]
    # Menggunakan 'minutes' sebagai argumen divmod, bukan 'hours'
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((str(days) + "d, ") if days else "") + ((str(hours) + "h, ") if hours else "") + ((str(minutes) + "m, ") if minutes else "") + ((str(seconds) + "s") if seconds else "")
    tmp = tmp.strip()
    return tmp[:-1] if tmp.endswith(",") else tmp if tmp else "0s"

def get_progress_bar(current: float, max_val: float, width: int = 10) -> str:
    if max_val <= 0: return f"[{'░' * width}]"
    percent = min(max(current / max_val, 0.0), 1.0)
    filled = int(percent * width)
    return f"[{'█' * filled}{'░' * (width - filled)}]"

def is_admin(user_id: int) -> bool:
    return user_id in Config.SUDO_USERS

class ProgressUI:
    # [NEW] Menambahkan parameter engine_name (Default: Unified Core)
    def __init__(self, message: Message, module_name: str, engine_name: str = "Unified Core"):
        self.message = message
        self.module_name = module_name
        self.engine_name = engine_name
        self.last_text = ""
        self.start_time = time.time()
        
        self.last_update_time = 0.0
        self.update_interval = 2.0 
        
        self.user_id = message.from_user.id if message.from_user else 0
        self.is_admin_user = is_admin(self.user_id)
        
        self.aktor_name = "Encoder 1"

        self._animating = False
        self._anim_task = None
        self._anim_status = "⚙️ Memproses Data..."
        self._anim_details = "Sistem sedang bekerja..."

    async def _safe_edit(self, text: str, force: bool = False):
        if text == self.last_text: return
        now = time.time()
        if not force and (now - self.last_update_time < self.update_interval): return

        try:
            await self.message.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)
            self.last_text = text
            self.last_update_time = time.time()
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except TelegramBadRequest: pass
        except Exception as e:
            LOGGER.error(f"UI Edit Error pada {self.module_name}: {e}")

    async def prep_phase(self, action_text: str = "Mempersiapkan proses...", remaining: int = 0):
        await self.stop_animation()
        admin_text = "👑 **Akses Admin:** Bypass sistem poin." if self.is_admin_user else "💎 **Sistem Poin:** Saldo Terpotong."
        rem_text = f"⏳ **Antrean Pemotongan:** `{remaining}` klip tersisa" if remaining > 0 else "⏳ **Menyusun kerangka video...**"
        
        text = (
            f"📁 **{self.module_name}**\n"
            f"{DIVIDER}\n"
            f"👤 Aktor: {self.aktor_name} | ID: `{self.user_id}`\n"
            f"🚀 Engine: `{self.engine_name}`\n" # <--- Teks Dinamis
            f"{admin_text}\n"
            f"{DIVIDER}\n"
            f"⚙️ **{action_text}**\n"
            f"_{rem_text}_"
        )
        await self._safe_edit(text, force=True)

    async def _animation_loop(self):
        frames = ["[█░░░░░░░░░]", "[██░░░░░░░░]", "[███░░░░░░░]", "[████░░░░░░]", "[█████░░░░░]", "[██████░░░░]", "[███████░░░]", "[████████░░]", "[█████████░]", "[██████████]", "[░█████████]", "[░░████████]", "[░░░███████]", "[░░░░██████]", "[░░░░░░████]", "[░░░░░░░░██]"]
        idx = 0
        while self._animating:
            frame = frames[idx % len(frames)]
            idx += 1
            text = (
                f"📁 **{self.module_name}**\n"
                f"{frame} **Sedang Berjalan...**\n"
                f"{DIVIDER}\n"
                f"👤 Aktor: {self.aktor_name} | ID: `{self.user_id}`\n"
                f"🚀 Engine: `{self.engine_name}`\n" # <--- Teks Dinamis
                f"{DIVIDER}\n"
                f"**{self._anim_status}**\n"
                f"_{self._anim_details}_"
            )
            await self._safe_edit(text)
            await asyncio.sleep(self.update_interval)

    async def start_animation(self, status: str, details: str = ""):
        self._anim_status = status
        if details: self._anim_details = details
        if self._animating: return 
        self._animating = True
        self._anim_task = asyncio.create_task(self._animation_loop())

    async def stop_animation(self):
        self._animating = False
        if self._anim_task:
            self._anim_task.cancel()
            self._anim_task = None

    async def update(self, status: str, current: float = 0, total: float = 0, speed: float = 0, eta: float = 0, details: str = ""):
        if total > 0:
            await self.stop_animation()
            percent = (current / total * 100)
            bar = get_progress_bar(current, total, width=10)
            
            text = (
                f"📁 **{self.module_name}**\n"
                f"{bar} **{round(min(max(percent, 0), 100), 1)}%**\n"
                f"{DIVIDER}\n"
                f"👤 Aktor: {self.aktor_name} | ID: `{self.user_id}`\n"
                f"🚀 Engine: `{self.engine_name}`\n" # <--- Teks Dinamis
                f"{DIVIDER}\n"
                f"**{status}**\n"
            )
            
            if current > 1000 and total > 1000:
                text += f"📦 **Data:** `{humanbytes(current)} / {humanbytes(total)}`\n"
            else:
                text += f"📦 **Progres:** `{int(current)} / {int(total)}`\n"
                
            if speed > 0: text += f"⚡ **Speed:** `{humanbytes(speed)}/s` | ⏱ **ETA:** `{TimeFormatter(eta * 1000)}`\n"
            if details: text += f"_{details}_"
            
            await self._safe_edit(text)
        else:
            await self.start_animation(status, details)

    async def finish(self, final_text: str = "✅ **Proses Selesai!**"):
        await self.stop_animation()
        elapsed = TimeFormatter((time.time() - self.start_time) * 1000)
        text = f"{final_text}\n\n⏱️ **Waktu Total:** `{elapsed}`"
        await self._safe_edit(text, force=True)

    async def error(self, error_text: str):
        await self.stop_animation()
        text = f"❌ **Error Terjadi:**\n`{error_text}`"
        await self._safe_edit(text, force=True)


# ==========================================
# 3. FUNGSI PENGIKAT (THE WRAPPER)
# ==========================================
# [NEW] Menambahkan parameter engine_name secara Spesifik (Keyword Only)
async def execute_unified_task(message: Message, module_name: str, task_function, *args, engine_name: str = "Unified Core", **kwargs):
    user_id = message.from_user.id if message.from_user else 0
    task_id = f"UE_{user_id}_{int(time.time())}"
    
    status_msg = await message.answer(f"🔄 **Menambahkan `{module_name}` ke antrean...**", parse_mode="Markdown")
    ui = ProgressUI(status_msg, module_name, engine_name=engine_name) # Melempar nama engine
    
    _ue_queued[task_id] = module_name
    _ue_ui_objects[task_id] = ui 
    
    if _task_semaphore.locked():
        await ui.update(f"⏳ Menunggu Giliran Server", details=f"Server sedang memproses tugas lain (Posisi antrean: {len(_ue_queued)})")
    
    async with _task_semaphore:
        _ue_queued.pop(task_id, None)
        _ue_working[task_id] = module_name
        
        await ui.update("⚙️ Mengeksekusi Modul...", details="Sistem sedang menganalisis data...")
        
        try:
            await task_function(message, ui, *args, **kwargs)
        except Exception as e:
            err_trace = traceback.format_exc()
            LOGGER.error(f"Task Error [{module_name}]: {e}\n{err_trace}")
            await ui.error(str(e))
        finally:
            await ui.stop_animation()
            _ue_working.pop(task_id, None)
            _ue_ui_objects.pop(task_id, None)
