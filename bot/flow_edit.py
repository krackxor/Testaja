"""
FSM Video Editing Suite untuk STUDIO KHOIRUL
Menangkap video yang dikirim user dan memunculkan panel alat (Tools).
"""

import asyncio
from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

# Import dari ui_dashboard agar teks dan fungsi edit amannya seragam
from bot.ui_dashboard import VIDEO_EDIT_TEXT, get_back_cancel_kb, safe_edit_message

# Router khusus untuk alur Video Editing
edit_router = Router(name="flow_edit")

# ==========================================
# 1. DEFINISI STATE (FSM)
# ==========================================
class VideoEditState(StatesGroup):
    waiting_for_video = State()
    choosing_tool = State()

# ==========================================
# 2. HELPER KEYBOARDS
# ==========================================
def get_editor_tools_kb() -> InlineKeyboardMarkup:
    """Panel alat editing yang muncul setelah video dikirim"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎛 Encode / Compress", callback_data="tool_encode"),
         InlineKeyboardButton(text="✂️ Split Video", callback_data="tool_split")],
        [InlineKeyboardButton(text="🎵 Extract Audio", callback_data="tool_extract"),
         InlineKeyboardButton(text="🎞 Trim / Cut", callback_data="tool_trim")],
        [InlineKeyboardButton(text="🎬 Autocrop (Remove Bars)", callback_data="tool_autocrop"),
         InlineKeyboardButton(text="📸 Gen Screenshot", callback_data="tool_genss")],
        [InlineKeyboardButton(text="❌ Cancel & Delete", callback_data="action_cancel")]
    ])

# ==========================================
# 3. AKTIFKAN MODE EDIT (Dari Dashboard)
# ==========================================
@edit_router.callback_query(F.data == "menu_vid_edit")
async def trigger_edit_mode(callback: CallbackQuery, state: FSMContext):
    """Menangani tombol ✂️ Video Editing di Dashboard Utama"""
    # 1. Nyalakan Radar FSM untuk menunggu video
    await state.set_state(VideoEditState.waiting_for_video)
    
    # 2. Ubah layar Dashboard menjadi panel Video Editing
    await safe_edit_message(callback.message, VIDEO_EDIT_TEXT, get_back_cancel_kb())
    
    # 3. Beri notifikasi pop-up
    await callback.answer("Mode Editor Aktif! Silakan kirim video.", show_alert=False)

# ==========================================
# 4. TANGKAP VIDEO & MUNCULKAN PANEL TOOLS
# ==========================================
@edit_router.message(VideoEditState.waiting_for_video, F.video | F.document)
async def catch_video_for_edit(message: Message, state: FSMContext):
    """Menangkap video yang dikirim user khusus saat Mode Edit Aktif"""
    # Simpan ID pesan video ke FSM agar nanti bisa diproses oleh Telethon/Pyrogram
    await state.update_data(video_message_id=message.message_id)
    
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

    # Hapus pesan video/dokumen dari user agar chat tetap rapi (Opsional)
    # try:
    #     await message.delete()
    # except TelegramBadRequest:
    #     pass

    # Pindahkan state ke pemilihan tool
    await state.set_state(VideoEditState.choosing_tool)
    
    # Munculkan Panel Alat
    await message.reply(text, reply_markup=get_editor_tools_kb(), parse_mode="HTML")

# ==========================================
# 5. ROUTING KE FUNGSI FFmpeg ASLI
# ==========================================
@edit_router.callback_query(VideoEditState.choosing_tool, F.data.startswith("tool_"))
async def process_selected_tool(callback: CallbackQuery, state: FSMContext):
    """Menangkap pilihan alat editing yang diklik user"""
    data = await state.get_data()
    video_msg_id = data.get("video_message_id")
    tool_selected = callback.data.split("_")[1] # mendapatkan kata 'encode', 'split', dll
    
    # Bersihkan state agar user tidak tersangkut di Mode Edit
    await state.clear()
    
    await callback.message.edit_text(f"⏳ Mempersiapkan tugas <b>{tool_selected.upper()}</b>...", parse_mode="HTML")
    
    # ==========================================
    # DI SINI KITA NANTI MENYAMBUNGKAN KE Running_Tasks.py
    # Contoh:
    # if tool_selected == "encode":
    #     await trigger_convert_task(user_id, video_msg_id)
    # elif tool_selected == "split":
    #     await trigger_split_task(user_id, video_msg_id)
    # ==========================================
    
    # Untuk sementara, tampilkan pesan sukses simulasi
    await asyncio.sleep(1)
    await callback.message.edit_text(
        f"✅ <b>Modul {tool_selected.upper()} siap dijalankan!</b>\n\n"
        f"(Video Message ID: {video_msg_id})\n\n"
        f"<i>Nantinya ini akan langsung memicu proses FFmpeg dari bot_helper kamu.</i>",
        parse_mode="HTML"
    )
