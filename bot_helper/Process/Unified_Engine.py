"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Process/Unified_Engine.py                      ║
║            Mesin Antrean & UI Terpusat (Studio Khoirul)              ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v5.0 (Synergy Update):                                    ║
║  [NEW] Mengekspor _ue_ui_objects agar progress bar Studio bisa       ║
║        dibaca secara real-time oleh perintah /status global.         ║
║  [UX]  Layout UI disamakan 100% dengan Process_Status.py.            ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import time
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest
from config.config import Config

LOGGER = Config.LOGGER
_task_semaphore = asyncio.Semaphore(Config.RUNNING_TASK_LIMIT)

# Memori Internal & UI Exporter (Untuk Sinergi dengan Running_Tasks)
_ue_queued = {}
_ue_working = {}
_ue_ui_objects = {}  # MENYIMPAN OBJEK UI AGAR BISA DIBACA GLOBAL

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
    def __init__(self, message: Message, module_name: str):
        self.message = message
        self.module_name = module_name
        self.last_text = ""
        self.start_time = time.time()
        self.user_id = message.from_user.id
        self.is_admin_user = is_admin(self.user_id)
        if message.from_user.username: self.added_by = f"[{message.from_user.first_name}](https://t.me/{message.from_user.username})"
        else: self.added_by = f"**{message.from_user.first_name}**"

        self._animating = False
        self._anim_task = None
        self._anim_status = "⚙️ Memproses Data..."
        self._anim_details = "Sistem sedang bekerja..."

    async def prep_phase(self, action_text: str = "Mempersiapkan proses...", remaining: int = 0):
        await self.stop_animation()
        admin_text = "👑 **Akses Admin:** Bypass sistem poin." if self.is_admin_user else "💎 **Sistem Poin:** Saldo Terpotong."
        rem_text = f"⏳ **Belum di proses:** `{remaining}`" if remaining > 0 else "⏳ **Proses sinkronisasi...**"
        text = (
            f"**{action_text}**\n"
            f"📁 `{self.module_name}`\n"
            f"{DIVIDER}\n"
            f"👤 **Aktor:** {self.added_by} | **ID:** `{self.user_id}`\n"
            f"🚀 **Engine:** `Unified Core`\n"
            f"{admin_text}\n"
            f"{rem_text}\n"
            f"{DIVIDER}\n"
            f"_Sedang menyiapkan potongan video..._"
        )
        if text != self.last_text:
            try:
                await self.message.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)
                self.last_text = text
            except TelegramBadRequest: pass

    async def _animation_loop(self):
        frames = ["[█░░░░░░░░░]", "[██░░░░░░░░]", "[███░░░░░░░]", "[████░░░░░░]", "[█████░░░░░]", "[██████░░░░]", "[███████░░░]", "[████████░░]", "[█████████░]", "[██████████]", "[░█████████]", "[░░████████]", "[░░░███████]", "[░░░░██████]", "[░░░░░░████]", "[░░░░░░░░██]"]
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
                except TelegramBadRequest: pass
            await asyncio.sleep(1)

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
                f"**{status}**\n"
                f"📁 `{self.module_name}`\n"
                f"{bar} **{round(min(max(percent, 0), 100), 1)}%**\n"
                f"{DIVIDER}\n"
                f"👤 **Aktor:** {self.added_by} | **ID:** `{self.user_id}`\n"
                f"🚀 **Engine:** `Unified Core`\n"
                f"📦 **Data:** `{humanbytes(current)} / {humanbytes(total)}`\n"
            )
            if speed > 0: text += f"⚡ **Speed:** `{humanbytes(speed)}/s` | ⏱ **ETA:** `{TimeFormatter(eta * 1000)}`\n"
            if details: text += f"{DIVIDER}\n_{details}_"
            if text != self.last_text:
                try:
                    await self.message.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)
                    self.last_text = text
                except TelegramBadRequest: pass 
        else:
            await self.start_animation(status, details)

    async def finish(self, final_text: str = "✅ **Proses Selesai!**"):
        await self.stop_animation()
        try:
            elapsed = TimeFormatter((time.time() - self.start_time) * 1000)
            text = f"{final_text}\n\n⏱️ **Waktu Total:** `{elapsed}`"
            await self.message.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)
            self.last_text = text # Simpan untuk history
        except: pass

    async def error(self, error_text: str):
        await self.stop_animation()
        try: 
            text = f"❌ **Error Terjadi:**\n`{error_text}`"
            await self.message.edit_text(text, parse_mode="Markdown")
            self.last_text = text
        except: pass

# ==========================================
# 3. FUNGSI PENGIKAT (THE WRAPPER)
# ==========================================
async def execute_unified_task(message: Message, module_name: str, task_function, *args, **kwargs):
    user_id = message.from_user.id
    task_id = f"UE_{user_id}_{int(time.time())}"
    status_msg = await message.answer(f"🔄 **Menambahkan {module_name} ke antrean...**", parse_mode="Markdown")
    ui = ProgressUI(status_msg, module_name)
    
    _ue_queued[task_id] = module_name
    _ue_ui_objects[task_id] = ui # DAFTARKAN KE GLOBAL EXPORTER
    
    await ui.update(f"⏳ Menunggu Giliran", details=f"Posisi antrean: {len(_ue_queued)}")
    
    async with _task_semaphore:
        _ue_queued.pop(task_id, None)
        _ue_working[task_id] = module_name
        await ui.update("⚙️ Mengeksekusi Modul...", details="Sistem sedang menganalisis data naskah...")
        try:
            await task_function(message, ui, *args, **kwargs)
        except Exception as e:
            LOGGER.error(f"Task Error [{module_name}]: {e}", exc_info=True)
            await ui.error(str(e))
        finally:
            _ue_working.pop(task_id, None)
            _ue_ui_objects.pop(task_id, None) # HAPUS DARI GLOBAL EXPORTER SETELAH SELESAI
