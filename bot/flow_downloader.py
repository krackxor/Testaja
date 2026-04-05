"""
FSM Downloader Flow untuk STUDIO KHOIRUL
Menangani penangkapan URL secara interaktif untuk mode Leech & Mirror.
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Integrasi ke mesin downloader bawaan botmu
from bot_helper.Process.Process_Status import ProcessStatus
from bot_helper.Process.Running_Tasks import add_task
from bot_helper.Others.Names import Names

down_router = Router(name="flow_downloader")

# ==========================================
# 1. DEFINISI STATE
# ==========================================
class DownloaderState(StatesGroup):
    waiting_for_link = State()

def get_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Batalkan", callback_data="action_cancel")]])

# ==========================================
# 2. TRIGGER DARI DASHBOARD
# ==========================================
# Menangkap klik tombol Leech dan Mirror
@down_router.callback_query(F.data.in_(["cmd_leech", "cmd_mirror"]))
async def trigger_downloader(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split("_")[1] # mendapatkan kata 'leech' atau 'mirror'
    
    # Simpan mode yang dipilih ke memori FSM
    await state.update_data(dl_mode=mode)
    await state.set_state(DownloaderState.waiting_for_link)
    
    text = f"""<blockquote>📥 <b>MODE {mode.upper()} AKTIF</b>
━━━━━━━━━━━━━━━━━━━━━━
Silakan kirimkan <b>Link/URL</b> yang ingin diunduh.
(<i>Mendukung Direct Link, YouTube, Torrent, atau Magnet</i>).
━━━━━━━━━━━━━━━━━━━━━━</blockquote>"""
    
    await callback.message.edit_text(text, reply_markup=get_cancel_kb(), parse_mode="HTML")
    await callback.answer(f"Mode {mode.capitalize()} siap!", show_alert=False)

# ==========================================
# 3. TANGKAP URL & EKSEKUSI
# ==========================================
@down_router.message(DownloaderState.waiting_for_link, F.text)
async def process_download_link(message: Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get("dl_mode", "leech") # Default ke leech jika kosong
    url = message.text
    
    # Bersihkan state agar user tidak terus-terusan di mode download
    await state.clear()
    
    # [Premium Feel] Hapus URL yang diketik user biar chat bersih
    try:
        await message.delete()
    except Exception:
        pass
        
    bot_msg = await message.answer(f"⏳ Menghubungkan URL ke mesin downloader <b>{mode.upper()}</b>...", parse_mode="HTML")
    
    try:
        # Suntikkan trik "Fake Command" seperti di Editor
        # Seolah-olah user mengetik "/leech https://..."
        fake_command = f"/{mode} {url}"
        fake_message = message.model_copy(update={"text": fake_command})
        
        # Panggil variabel dari Names.py (Names.leech atau Names.mirror)
        process_type = getattr(Names, mode, mode)
        process_status = ProcessStatus(fake_message, process_type)
        
        # Format task
        task = {
            "process_status": process_status,
            "functions": [("telegram", fake_message)]
        }
        
        # Masukkan ke Antrean Mesin (Aria2 akan langsung merespons ini!)
        await add_task(task)
        await bot_msg.delete() # Hapus pesan loading, diganti pesan progress asli
        
    except Exception as e:
        await bot_msg.edit_text(f"❌ <b>Gagal menambahkan tugas:</b>\n<code>{e}</code>", parse_mode="HTML")
