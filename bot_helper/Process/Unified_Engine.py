"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Process/Unified_Engine.py                      ║
║            Mesin Antrean & UI Terpusat (Studio Khoirul)              ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v4.2:                                                     ║
║  [UX REFINED] Tampilan UI dirombak menggunakan garis pemisah (Divider)║
║               agar identik dengan gaya visual Process_Status.py.     ║
║  [FIX CRITICAL] Memisahkan memori antrean _ue_queued & _ue_working   ║
║                 agar tidak bertabrakan dengan tipe data `deque`.     ║
║  [FIX]   Memperbaiki bug formatting angka/waktu pada Progress Bar.   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import time
import math
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest
from config.config import Config

LOGGER = Config.LOGGER
_task_semaphore = asyncio.Semaphore(Config.RUNNING_TASK_LIMIT)

# [FIX CRITICAL] Menggunakan memori dictionary internal agar tidak bertabrakan 
# dengan struktur list/deque milik modul FFmpeg (Running_Tasks)
_ue_queued = {}
_ue_working = {}

# Konstanta UI
DIVIDER = "━━━━━━━━━━━━━━━━━━━━"

# ==========================================
# 1. HELPER FORMATTER
# ==========================================
def humanbytes(size):
    """Format bytes ke ukuran yang mudah dibaca (MB, GB)"""
    if not size or size <= 0: 
        return "0 B"
    power = 2**10
    n = 0
    Dic_powerN = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size >= power and n < 4:
        size /= power
        n += 1
    return f"{round(size, 2)} {Dic_powerN[n]}"

def TimeFormatter(milliseconds: float) -> str:
    """Format waktu (ETA) ke bentuk jam, menit, detik"""
    if not milliseconds or milliseconds <= 0:
        return "0s"
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((str(days) + "d, ") if days else "") + \
          ((str(hours) + "h, ") if hours else "") + \
          ((str(minutes) + "m, ") if minutes else "") + \
          ((str(seconds) + "s") if seconds else "")
    
    tmp = tmp.strip()
    if tmp.endswith(","): 
        tmp = tmp[:-1]
    return tmp if tmp else "0s"

def get_progress_bar(current: float, max_val: float, width: int = 10) -> str:
    """Style Progress Bar bawaan Process_Status.py [████░░░░]"""
    if max_val <= 0: 
        return f"[{'░' * width}]"
    
    percent = min(max(current / max_val, 0.0), 1.0)
    filled = int(percent * width)
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}]"

def escape_html(text: str) -> str:
    """Mencegah Telegram memunculkan error unparsed HTML entity."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ==========================================
# 2. SISTEM UI (PROGRESS MANAGER)
# ==========================================
class ProgressUI:
    def __init__(self, message: Message, module_name: str):
        self.message = message
        self.module_name = escape_html(module_name)
        self.last_text = ""
        self.start_time = time.time()
        self.user_id = message.from_user.id
        self.added_by = f"<a href='https://t.me/{message.from_user.username}'>{message.from_user.first_name}</a>" if message.from_user.username else f"<b>{message.from_user.first_name}</b>"

    async def update(self, status: str, current: float = 0, total: float = 0, speed: float = 0, eta: float = 0, details: str = ""):
        """
        Update UI dengan parameter lengkap dan visual yang konsisten dengan Process_Status.
        """
        safe_status = escape_html(status)
        safe_details = escape_html(details)
        
        text = f"<b>{safe_status}</b>\n"
        text += f"📁 <code>{self.module_name}</code>\n"
        
        # Hanya tampilkan bar & persentase jika total > 0
        if total > 0:
            percent = (current / total * 100)
            percent_clean = round(min(max(percent, 0), 100), 1)
            bar = get_progress_bar(current, total, width=10)
            
            cur_str = humanbytes(current)
            tot_str = humanbytes(total)
            speed_str = f"{humanbytes(speed)}/s" if speed > 0 else "0 B/s"
            eta_str = TimeFormatter(eta * 1000) if eta > 0 else "N/A"

            text += f"{bar} <b>{percent_clean}%</b>\n"
            text += f"{DIVIDER}\n"
            text += f"👤 <b>Aktor:</b> {self.added_by} | <b>ID:</b> <code>{self.user_id}</code>\n"
            text += f"🚀 <b>Engine:</b> <code>Unified Core</code>\n"
            text += f"📦 <b>Data:</b> <code>{cur_str} / {tot_str}</code>\n"
            if speed > 0:
                text += f"⚡ <b>Speed:</b> <code>{speed_str}</code> | ⏱ <b>ETA:</b> <code>{eta_str}</code>\n"
        else:
            # Mode Indeterminate (misal: saat render video di Studio)
            text += f"⏳ <b>Memproses Data...</b>\n"
            text += f"{DIVIDER}\n"
            text += f"👤 <b>Aktor:</b> {self.added_by} | <b>ID:</b> <code>{self.user_id}</code>\n"
            text += f"🚀 <b>Engine:</b> <code>Unified Core</code>\n"

        if details:
            text += f"{DIVIDER}\n"
            text += f"<i>{safe_details}</i>"

        if text != self.last_text:
            try:
                await self.message.edit_text(text, parse_mode="HTML", disable_web_page_preview=True)
                self.last_text = text
            except TelegramBadRequest:
                pass 

    async def finish(self, final_text: str = "✅ <b>Proses Selesai!</b>"):
        try:
            elapsed = TimeFormatter((time.time() - self.start_time) * 1000)
            text = f"{final_text}\n\n⏱️ <b>Waktu Total:</b> <code>{elapsed}</code>"
            await self.message.edit_text(text, parse_mode="HTML", disable_web_page_preview=True)
        except: 
            pass

    async def error(self, error_text: str):
        try:
            safe_error = escape_html(str(error_text))
            await self.message.edit_text(f"❌ <b>Error Terjadi:</b>\n<code>{safe_error}</code>", parse_mode="HTML")
        except: 
            pass

# ==========================================
# 3. FUNGSI PENGIKAT (THE WRAPPER)
# ==========================================
async def execute_unified_task(message: Message, module_name: str, task_function, *args, **kwargs):
    user_id = message.from_user.id
    task_id = f"{user_id}_{int(time.time())}"
    
    status_msg = await message.answer(f"🔄 <b>Menambahkan {escape_html(module_name)} ke antrean...</b>", parse_mode="HTML")
    ui = ProgressUI(status_msg, module_name)

    # [FIX] Masukkan ke antrean internal Unified Engine
    _ue_queued[task_id] = module_name
    queue_position = len(_ue_queued)
    
    await ui.update(f"⏳ Menunggu Giliran", details=f"Posisi antrean saat ini: {queue_position}")

    async with _task_semaphore:
        # Pindahkan dari antrean ke proses berjalan
        if task_id in _ue_queued:
            del _ue_queued[task_id]
        _ue_working[task_id] = module_name
        
        try:
            # Eksekusi fungsi bisnis utamanya (misal: render studio, upload cloud, dsb)
            await task_function(message, ui, *args, **kwargs)
        except Exception as e:
            LOGGER.error(f"Task Error [{module_name}]: {e}", exc_info=True)
            await ui.error(str(e))
        finally:
            # Hapus dari memori kerja setelah selesai/error
            if task_id in _ue_working:
                del _ue_working[task_id]
