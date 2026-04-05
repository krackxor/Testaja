"""
FSM Video Editing Suite untuk STUDIO KHOIRUL
Menangkap video yang dikirim user dan memunculkan panel alat (Tools).
100% TERINTEGRASI DENGAN MESIN FFMPEG & MENDUKUNG 20 ALAT EDITING
"""

import asyncio
from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

# Import UI dan Modul Internal Mesin FFmpeg
from bot.ui_dashboard import VIDEO_EDIT_TEXT, get_back_cancel_kb, safe_edit_message
from bot_helper.Process.Process_Status import ProcessStatus
from bot_helper.Process.Running_Tasks import add_task
from bot_helper.Others.Names import Names

# Router khusus untuk alur Video Editing
edit_router = Router(name="flow_edit")

# ==========================================
# 1. DEFINISI STATE (FSM)
# ==========================================
class VideoEditState(StatesGroup):
    waiting_for_video = State()
    choosing_tool = State()

# ==========================================
# 2. HELPER KEYBOARDS (FULL 20 FITUR)
# ==========================================
def get_editor_tools_kb() -> InlineKeyboardMarkup:
    """Panel alat editing lengkap (20 Fitur) yang muncul setelah video dikirim"""
    return InlineKeyboardMarkup(inline_keyboard=[
        # Baris 1: Dasar
        [InlineKeyboardButton(text="🗜 Compress", callback_data="tool_compress"), 
         InlineKeyboardButton(text="🔄 Convert", callback_data="tool_convert"), 
         InlineKeyboardButton(text="🔗 Merge", callback_data="tool_merge")],
        
        # Baris 2: Pemotongan
        [InlineKeyboardButton(text="🎞 Trim", callback_data="tool_trim"), 
         InlineKeyboardButton(text="✂️ Split", callback_data="tool_split"), 
         InlineKeyboardButton(text="🔪 Cut", callback_data="tool_cut")],
        
        # Baris 3: Rasio & Orientasi
        [InlineKeyboardButton(text="📐 Crop", callback_data="tool_crop"), 
         InlineKeyboardButton(text="🎬 Autocrop", callback_data="tool_autocrop"), 
         InlineKeyboardButton(text="🔃 Rotate", callback_data="tool_rotate")],
        
        # Baris 4: Subtitle & Muxing
        [InlineKeyboardButton(text="📌 Hardmux", callback_data="tool_hardmux"), 
         InlineKeyboardButton(text="📝 Softmux", callback_data="tool_softmux"), 
         InlineKeyboardButton(text="♻️ Remux", callback_data="tool_softremux")],
        
        # Baris 5: Ekstraksi & Index
        [InlineKeyboardButton(text="🎵 Extract", callback_data="tool_extract"), 
         InlineKeyboardButton(text="🗂 Extension", callback_data="tool_extension"), 
         InlineKeyboardButton(text="🔢 Index", callback_data="tool_changeindex")],
        
        # Baris 6: Info & Metadata
        [InlineKeyboardButton(text="🏷 Metadata", callback_data="tool_changemetadata"), 
         InlineKeyboardButton(text="ℹ️ MediaInfo", callback_data="tool_mediainfo")],
        
        # Baris 7: Watermark & Gambar
        [InlineKeyboardButton(text="©️ Watermark", callback_data="tool_watermark"), 
         InlineKeyboardButton(text="📸 Screenshot", callback_data="tool_genss"), 
         InlineKeyboardButton(text="🎞 Sample", callback_data="tool_gensample")],
        
        # Baris 8: Batal
        [InlineKeyboardButton(text="❌ Cancel & Delete", callback_data="action_cancel")]
    ])

# ==========================================
# 3. AKTIFKAN MODE EDIT (Dari Dashboard)
# ==========================================
@edit_router.callback_query(F.data == "menu_vid_edit")
async def trigger_edit_mode(callback: CallbackQuery, state: FSMContext):
    """Menangani tombol ✂️ Video Editing di Dashboard Utama"""
    await state.set_state(VideoEditState.waiting_for_video)
    await safe_edit_message(callback.message, VIDEO_EDIT_TEXT, get_back_cancel_kb())
    await callback.answer("Mode Editor Aktif! Silakan kirim video.", show_alert=False)

# ==========================================
# 4. TANGKAP VIDEO & MUNCULKAN PANEL TOOLS
# ==========================================
@edit_router.message(VideoEditState.waiting_for_video, F.video | F.document)
async def catch_video_for_edit(message: Message, state: FSMContext):
    """Menangkap video yang dikirim user khusus saat Mode Edit Aktif"""
    # [PENTING] Menyimpan objek pesan utuh ke memori FSM untuk ditarik nanti
    await state.update_data(original_message=message)
    
    file_name = "Video File"
    file_size = 0
    if message.video:
        file_name = message.video.file_name or "Unknown_Video.mp4"
        file_size = message.video.file_size
    elif message.document:
        file_name = message.document.file_name or "Unknown_Document.mp4"
        file_size = message.document.file_size
        
    size_mb = round(file_size / (1024 * 1024), 2) if file_size else 0

    text = f"""<blockquote>✂️ <b>𝐕𝐈𝐃𝐄𝐎 𝐄𝐃𝐈𝐓𝐈𝐍𝐆 𝐒𝐔𝐈𝐓𝐄</b>
━━━━━━━━━━━━━━━━━━━━━━
📥 <b>File Diterima:</b> <code>{file_name[:40]}{'...' if len(file_name) > 40 else ''}</code>
💽 <b>Ukuran:</b> <code>{size_mb} MB</code>
━━━━━━━━━━━━━━━━━━━━━━
<i>Silakan pilih operasi FFmpeg yang ingin Anda terapkan pada video ini:</i></blockquote>"""

    await state.set_state(VideoEditState.choosing_tool)
    await message.reply(text, reply_markup=get_editor_tools_kb(), parse_mode="HTML")

# ==========================================
# 5. INTEGRASI PENUH KE RUNNING TASKS
# ==========================================
@edit_router.callback_query(VideoEditState.choosing_tool, F.data.startswith("tool_"))
async def process_selected_tool(callback: CallbackQuery, state: FSMContext):
    """Menangkap pilihan alat editing & Memicu fungsi FFmpeg Asli"""
    data = await state.get_data()
    original_message = data.get("original_message")
    
    # Dapatkan nama alat, contoh: 'rotate', 'split', 'compress'
    tool_selected = callback.data.split("_")[1] 
    
    # Bersihkan state agar user tidak tersangkut di Mode Edit
    await state.clear()
    
    if not original_message:
        await callback.message.edit_text("❌ Pesan video asli hilang dari memori. Silakan kirim ulang videonya.", parse_mode="HTML")
        return
        
    await callback.message.edit_text(f"⏳ Menghubungkan tugas <b>{tool_selected.upper()}</b> ke server FFmpeg...", parse_mode="HTML")
    
    # Mengambil variabel Proses secara dinamis dari file Names.py
    # Jika fitur tidak ada di Names.py, ia akan memakai string aslinya.
    process_type = getattr(Names, tool_selected, tool_selected)
    
    try:
        # 1. Inisialisasi Objek ProcessStatus
        process_status = ProcessStatus(original_message, process_type)
        
        # 2. Format struktur Task (Sesuai dengan logika asli bot kamu)
        task = {
            "process_status": process_status,
            "functions": [("telegram", original_message)] 
        }
        
        # 3. Masukkan ke Antrean (Background Tasker)
        await add_task(task)
        
        # 4. Hapus Panel (Karena proses status message akan mengambil alih chat)
        await callback.message.delete()
        
    except Exception as e:
        await callback.message.edit_text(
            f"❌ <b>Terjadi Kesalahan Integrasi Task:</b>\n<code>{e}</code>\n\n"
            f"<i>Cek log terminal untuk detail argumen ProcessStatus.</i>",
            parse_mode="HTML"
        )
