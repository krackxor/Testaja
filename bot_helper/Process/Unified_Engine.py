"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Process/Unified_Engine.py                      ║
║            Mesin Antrean & UI Terpusat (Studio Khoirul)              ║
╠══════════════════════════════════════════════════════════════════════╣
║  UPDATE: Integrasi Antrean + UI disamakan dengan Process_Status.py   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import time
import math
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest
from config.config import Config

# [INTEGRASI ANTREAN]
try:
    from bot_helper.Process.Running_Tasks import queued_task, working_task
except ImportError:
    queued_task = {}
    working_task = {}

LOGGER = Config.LOGGER
_task_semaphore = asyncio.Semaphore(Config.RUNNING_TASK_LIMIT)

# ==========================================
# 1. HELPER FORMATTER (Sama dengan Process_Status)
# ==========================================
def humanbytes(size):
    """Format bytes ke ukuran yang mudah dibaca (MB, GB)"""
    if not size: return "0 B"
    power = 2**10
    n = 0
    Dic_powerN = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size > power:
        size /= power
        n += 1
    return f"{round(size, 2)} {Dic_powerN[n]}"

def TimeFormatter(milliseconds: int) -> str:
    """Format waktu (ETA) ke bentuk jam, menit, detik"""
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((str(days) + "d, ") if days else "") + \
          ((str(hours) + "h, ") if hours else "") + \
          ((str(minutes) + "m, ") if minutes else "") + \
          ((str(seconds) + "s, ") if seconds else "")
    return tmp[:-2] if tmp else "0s"

def get_progress_bar(current: float, max_val: float, width: int = 10) -> str:
    """Style Progress Bar bawaan Process_Status.py [████░░░░]"""
    if max_val <= 0: return f"[{'░' * width}]"
    filled = int((current / max_val) * width)
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}]"

# ==========================================
# 2. SISTEM UI (PROGRESS MANAGER)
# ==========================================
class ProgressUI:
    def __init__(self, message: Message, module_name: str):
        self.message = message
        self.module_name = module_name
        self.last_text = ""
        self.start_time = time.time()

    async def update(self, status: str, current: int = 0, total: int = 0, speed: int = 0, eta: int = 0, details: str = ""):
        """
        Update UI dengan parameter lengkap persis seperti Process_Status.
        """
        percent = (current / total * 100) if total > 0 else 0
        percent_clean = round(min(max(percent, 0), 100), 1)
        bar = get_progress_bar(current, total, width=10)
        
        # Format angka menjadi Human Readable
        cur_str = humanbytes(current) if current > 0 else current
        tot_str = humanbytes(total) if total > 0 else total
        speed_str = f"{humanbytes(speed)}/s" if speed > 0 else "0 B/s"
        eta_str = TimeFormatter(eta * 1000) if eta > 0 else "Menghitung..."

        # FORMAT UI IDENTIK DENGAN PROCESS_STATUS.PY
        text = f"<b>{status}</b>\n\n"
        text += f"<b>Modul:</b> <code>{self.module_name}</code>\n"
        text += f"<b>Progress:</b> {bar} <code>{percent_clean}%</code>\n"
        
        if total > 0:
            text += f"<b>Loaded:</b> <code>{cur_str} / {tot_str}</code>\n"
        if speed > 0:
            text += f"<b>Speed:</b> <code>{speed_str}</code>\n"
        if eta > 0:
            text += f"<b>ETA:</b> <code>{eta_str}</code>\n"
        
        if details:
            text += f"\n<i>{details}</i>"

        if text != self.last_text:
            try:
                await self.message.edit_text(text, parse_mode="HTML")
                self.last_text = text
            except TelegramBadRequest:
                pass 

    async def finish(self, final_text: str = "✅ <b>Proses Selesai!</b>"):
        try:
            elapsed = TimeFormatter((time.time() - self.start_time) * 1000)
            text = f"{final_text}\n\n⏱️ <b>Waktu Total:</b> <code>{elapsed}</code>"
            await self.message.edit_text(text, parse_mode="HTML")
        except: pass

    async def error(self, error_text: str):
        try:
            await self.message.edit_text(f"❌ <b>Error Terjadi:</b>\n<code>{error_text}</code>", parse_mode="HTML")
        except: pass

# ==========================================
# 3. FUNGSI PENGIKAT (THE WRAPPER)
# ==========================================
async def execute_unified_task(message: Message, module_name: str, task_function, *args, **kwargs):
    user_id = message.from_user.id
    task_id = f"{user_id}_{int(time.time())}"
    
    status_msg = await message.answer(f"🔄 <b>Menambahkan {module_name} ke antrean...</b>", parse_mode="HTML")
    ui = ProgressUI(status_msg, module_name)

    queued_task[task_id] = module_name
    queue_position = len(queued_task)
    
    await ui.update(f"⏳ <b>Menunggu Giliran (Antrean: {queue_position})</b>", details="Server sedang memproses tugas lain.")

    async with _task_semaphore:
        if task_id in queued_task:
            del queued_task[task_id]
        working_task[task_id] = module_name
        
        try:
            await task_function(message, ui, *args, **kwargs)
        except Exception as e:
            LOGGER.error(f"Task Error [{module_name}]: {e}", exc_info=True)
            await ui.error(str(e))
        finally:
            if task_id in working_task:
                del working_task[task_id]
