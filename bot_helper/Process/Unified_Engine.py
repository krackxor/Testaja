"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Process/Unified_Engine.py                      ║
║            Mesin Antrean & UI Terpusat (Studio Khoirul)              ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v4.5:                                                     ║
║  [NEW] Menanamkan fitur "Indeterminate Animation Loop". Jika tugas   ║
║        memakan waktu lama tanpa ukuran file yang jelas (cth: Render  ║
║        AI Studio), bar [██░░░░] akan terus bergerak secara otomatis  ║
║        agar user tahu bot tidak macet/stuck.                         ║
║  [UX REFINED] Mengubah seluruh pelaporan UI menggunakan format       ║
║               Markdown murni (**tebal**, `kode`) (No HTML leaking).  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import time
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest
from config.config import Config

LOGGER = Config.LOGGER
_task_semaphore = asyncio.Semaphore(Config.RUNNING_TASK_LIMIT)

# Memori dictionary internal agar tidak bertabrakan dengan Running_Tasks
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
    """Style Progress Bar statis untuk ukuran pasti [████░░░░]"""
    if max_val <= 0: 
        return f"[{'░' * width}]"
    
    percent = min(max(current / max_val, 0.0), 1.0)
    filled = int(percent * width)
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}]"

# ==========================================
# 2. SISTEM UI (PROGRESS MANAGER & ANIMATOR)
# ==========================================
class ProgressUI:
    def __init__(self, message: Message, module_name: str):
        self.message = message
        self.module_name = module_name
        self.last_text = ""
        self.start_time = time.time()
        self.user_id = message.from_user.id
        
        # Konversi HTML link ke Markdown Telegram
        if message.from_user.username:
            self.added_by = f"[{message.from_user.first_name}](https://t.me/{message.from_user.username})"
        else:
            self.added_by = f"**{message.from_user.first_name}**"

        # Variabel untuk Animasi Loading Otomatis
        self._animating = False
        self._anim_task = None
        self._anim_status = "⚙️ Memproses Data..."
        self._anim_details = "Sistem sedang bekerja..."

    async def _animation_loop(self):
        """Looping animasi bar (Sweep effect) saat ukuran file belum diketahui"""
        frames = [
            "[█░░░░░░░░░]", "[██░░░░░░░░]", "[███░░░░░░░]", "[████░░░░░░]",
            "[█████░░░░░]", "[██████░░░░]", "[███████░░░]", "[████████░░]",
            "[█████████░]", "[██████████]", "[░█████████]", "[░░████████]",
            "[░░░███████]", "[░░░░██████]", "[░░░░░░████]", "[░░░░░░░░██]"
        ]
        idx = 0
        while self._animating:
            frame = frames[idx % len(frames)]
            idx += 1
            
            text = (
                f"**{self._anim_status}**\n"
                f"📁 `{self.module_name}`\n"
                f"{frame} **Sedang Berjalan...**\n"
                f"{DIVIDER}\n"
                f"👤 **Aktor:** {self.added_by} | **ID:** `{self.user_id}`\n"
                f"🚀 **Engine:** `Unified Core`\n"
                f"{DIVIDER}\n"
                f"_{self._anim_details}_"
            )
            
            if text != self.last_text:
                try:
                    await self.message.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)
                    self.last_text = text
                except TelegramBadRequest:
                    pass
            await asyncio.sleep(1) # Bergerak 1 frame setiap 1 detik

    async def start_animation(self, status: str, details: str = ""):
        """Memulai task animasi background"""
        self._anim_status = status
        if details:
            self._anim_details = details
            
        if self._animating:
            return # Sudah jalan, cukup perbarui teksnya saja
            
        self._animating = True
        self._anim_task = asyncio.create_task(self._animation_loop())

    async def stop_animation(self):
        """Menghentikan animasi saat proses selesai atau mendapat ukuran file pasti"""
        self._animating = False
        if self._anim_task:
            self._anim_task.cancel()
            self._anim_task = None

    async def update(self, status: str, current: float = 0, total: float = 0, speed: float = 0, eta: float = 0, details: str = ""):
        """Update UI. Jika total=0 (Indeterminate), jalankan animasi. Jika total>0, jalankan bar biasa."""
        
        # 1. JIKA ADA TOTAL UKURAN FILE (Misal: Download/Upload)
        if total > 0:
            await self.stop_animation() # Matikan animasi looping
            
            percent = (current / total * 100)
            percent_clean = round(min(max(percent, 0), 100), 1)
            bar = get_progress_bar(current, total, width=10)
            
            cur_str = humanbytes(current)
            tot_str = humanbytes(total)
            speed_str = f"{humanbytes(speed)}/s" if speed > 0 else "0 B/s"
            eta_str = TimeFormatter(eta * 1000) if eta > 0 else "N/A"

            text = (
                f"**{status}**\n"
                f"📁 `{self.module_name}`\n"
                f"{bar} **{percent_clean}%**\n"
                f"{DIVIDER}\n"
                f"👤 **Aktor:** {self.added_by} | **ID:** `{self.user_id}`\n"
                f"🚀 **Engine:** `Unified Core`\n"
                f"📦 **Data:** `{cur_str} / {tot_str}`\n"
            )
            if speed > 0:
                text += f"⚡ **Speed:** `{speed_str}` | ⏱ **ETA:** `{eta_str}`\n"
                
            if details:
                text += f"{DIVIDER}\n_{details}_"

            if text != self.last_text:
                try:
                    await self.message.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)
                    self.last_text = text
                except TelegramBadRequest:
                    pass 
                    
        # 2. JIKA TOTAL = 0 (Proses Rendering / AI TTS yang memakan waktu)
        else:
            await self.start_animation(status, details)


    async def finish(self, final_text: str = "✅ **Proses Selesai!**"):
        await self.stop_animation()
        try:
            elapsed = TimeFormatter((time.time() - self.start_time) * 1000)
            text = f"{final_text}\n\n⏱️ **Waktu Total:** `{elapsed}`"
            await self.message.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)
        except: 
            pass

    async def error(self, error_text: str):
        await self.stop_animation()
        try:
            await self.message.edit_text(f"❌ **Error Terjadi:**\n`{error_text}`", parse_mode="Markdown")
        except: 
            pass

# ==========================================
# 3. FUNGSI PENGIKAT (THE WRAPPER)
# ==========================================
async def execute_unified_task(message: Message, module_name: str, task_function, *args, **kwargs):
    user_id = message.from_user.id
    task_id = f"{user_id}_{int(time.time())}"
    
    status_msg = await message.answer(f"🔄 **Menambahkan {module_name} ke antrean...**", parse_mode="Markdown")
    ui = ProgressUI(status_msg, module_name)

    _ue_queued[task_id] = module_name
    queue_position = len(_ue_queued)
    
    await ui.update(f"⏳ Menunggu Giliran", details=f"Posisi antrean saat ini: {queue_position}")

    # MASUK KE MESIN KERJA
    async with _task_semaphore:
        if task_id in _ue_queued:
            del _ue_queued[task_id]
        _ue_working[task_id] = module_name
        
        # Mulai animasi bar otomatis agar user tahu proses sedang berjalan
        await ui.update("⚙️ Mengeksekusi Modul...", details="Sistem AI dan FFmpeg sedang memproses data. Harap tunggu, ini mungkin memakan waktu beberapa menit...")
        
        try:
            # Eksekusi fungsi bisnis utamanya
            await task_function(message, ui, *args, **kwargs)
        except Exception as e:
            LOGGER.error(f"Task Error [{module_name}]: {e}", exc_info=True)
            await ui.error(str(e))
        finally:
            if task_id in _ue_working:
                del _ue_working[task_id]
