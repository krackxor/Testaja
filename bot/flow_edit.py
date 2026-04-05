"""
FSM Video Editing Suite untuk STUDIO KHOIRUL
Fix: Sinkronisasi Argumen ProcessStatus dengan Mesin v3.1
"""

import asyncio
from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

# Ambil fungsi dan teks dari ui_dashboard
from bot.ui_dashboard import VIDEO_EDIT_TEXT, get_back_cancel_kb, safe_edit_message
from bot_helper.Process.Process_Status import ProcessStatus
from bot_helper.Process.Running_Tasks import add_task
from bot_helper.Others.Names import Names

edit_router = Router(name="flow_edit")

# ==========================================
# 1. DEFINISI STATE (FSM)
# ==========================================
class VideoEditState(StatesGroup):
    waiting_for_video = State()
    choosing_tool = State()
    waiting_for_param = State()

# ==========================================
# 2. HELPER KEYBOARDS
# ==========================================
def get_editor_tools_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗜 Compress", callback_data="tool_compress"), 
         InlineKeyboardButton(text="🔄 Convert", callback_data="tool_convert"), 
         InlineKeyboardButton(text="🔗 Merge", callback_data="tool_merge")],
        [InlineKeyboardButton(text="🎞 Trim", callback_data="tool_trim"), 
         InlineKeyboardButton(text="✂️ Split", callback_data="tool_split"), 
         InlineKeyboardButton(text="🔪 Cut", callback_data="tool_cut")],
        [InlineKeyboardButton(text="📐 Crop", callback_data="tool_crop"), 
         InlineKeyboardButton(text="🎬 Autocrop", callback_data="tool_autocrop"), 
         InlineKeyboardButton(text="🔃 Rotate", callback_data="tool_rotate")],
        [InlineKeyboardButton(text="📌 Hardmux", callback_data="tool_hardmux"), 
         InlineKeyboardButton(text="📝 Softmux", callback_data="tool_softmux"), 
         InlineKeyboardButton(text="♻️ Remux", callback_data="tool_softremux")],
        [InlineKeyboardButton(text="🎵 Extract", callback_data="tool_extract"), 
         InlineKeyboardButton(text="🗂 Extension", callback_data="tool_extension"), 
         InlineKeyboardButton(text="🔢 Index", callback_data="tool_changeindex")],
        [InlineKeyboardButton(text="❌ Cancel & Delete", callback_data="action_cancel")]
    ])

def get_cancel_only_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Batalkan", callback_data="action_cancel")]])

# ==========================================
# 3. AKTIFKAN MODE EDIT
# ==========================================
@edit_router.callback_query(F.data == "menu_vid_edit")
async def trigger_edit_mode(callback: CallbackQuery, state: FSMContext):
    await state.set_state(VideoEditState.waiting_for_video)
    await safe_edit_message(callback.message, VIDEO_EDIT_TEXT, get_back_cancel_kb())
    await callback.answer("Mode Editor Aktif! Silakan kirim video.", show_alert=False)

# ==========================================
# 4. TANGKAP VIDEO
# ==========================================
@edit_router.message(VideoEditState.waiting_for_video, F.video | F.document)
async def catch_video_for_edit(message: Message, state: FSMContext):
    await state.update_data(original_message=message)
    file_name = message.video.file_name if message.video else (message.document.file_name if message.document else "Video File")
    size_mb = round((message.video.file_size if message.video else message.document.file_size) / (1024 * 1024), 2)
    
    text = f"<blockquote>✂️ <b>𝐕𝐈𝐃𝐄𝐎 𝐄𝐃𝐈𝐓𝐈𝐍𝐆 𝐒𝐔𝐈𝐓𝐄</b>\n━━━━━━━━━━━━━━━━━━━━━━\n📥 <b>File:</b> <code>{file_name[:30]}...</code>\n💽 <b>Ukuran:</b> <code>{size_mb} MB</code>\n━━━━━━━━━━━━━━━━━━━━━━\n<i>Pilih operasi yang ingin diterapkan:</i></blockquote>"
    
    await state.set_state(VideoEditState.choosing_tool)
    await message.reply(text, reply_markup=get_editor_tools_kb(), parse_mode="HTML")

# ==========================================
# 5. FILTER FITUR
# ==========================================
@edit_router.callback_query(VideoEditState.choosing_tool, F.data.startswith("tool_"))
async def process_selected_tool(callback: CallbackQuery, state: FSMContext):
    tool_selected = callback.data.split("_")[1]
    
    tools_needing_params = {
        "trim": "Kirimkan waktu mulai dan durasi (Format: <code>HH:MM:SS HH:MM:SS</code>).\n<i>Contoh: 00:01:00 00:00:30</i>",
        "split": "Berapa menit/detik durasi per potongan?\n<i>Contoh: 00:05:00</i>",
        "crop": "Kirimkan resolusi potongan (Format: <code>Lebar:Tinggi</code>).\n<i>Contoh: 1080:1920</i>",
        "watermark": "Silakan kirimkan gambar/foto yang akan dijadikan Watermark!"
    }
    
    if tool_selected in tools_needing_params:
        await state.update_data(selected_tool=tool_selected)
        await state.set_state(VideoEditState.waiting_for_param)
        await callback.message.edit_text(
            f"<blockquote>⚙️ <b>PARAMETER: {tool_selected.upper()}</b>\n━━━━━━━━━━━━━━━━━━━━━━\n{tools_needing_params[tool_selected]}\n━━━━━━━━━━━━━━━━━━━━━━</blockquote>",
            reply_markup=get_cancel_only_kb(), parse_mode="HTML"
        )
    else:
        data = await state.get_data()
        original_message = data.get("original_message")
        await state.clear()
        await run_ffmpeg_engine(callback.message, original_message, tool_selected, param=None)

# ==========================================
# 6. TANGKAP PARAMETER
# ==========================================
@edit_router.message(VideoEditState.waiting_for_param)
async def catch_parameter_and_execute(message: Message, state: FSMContext):
    data = await state.get_data()
    original_message = data.get("original_message")
    tool_selected = data.get("selected_tool")
    
    param_value = message.text or getattr(message.document, "file_id", "Unknown")
    await state.clear()
    
    msg = await message.reply(f"✅ Parameter diterima. Meneruskan ke server...", parse_mode="HTML")
    await run_ffmpeg_engine(msg, original_message, tool_selected, param=param_value)

# ==========================================
# 7. FUNGSI EKSEKUSI UTAMA (FIXED ARGUMENTS)
# ==========================================
async def run_ffmpeg_engine(bot_message: Message, original_message: Message, tool_selected: str, param: str = None):
    try:
        user_id = original_message.from_user.id
        chat_id = original_message.chat.id
        username = original_message.from_user.username or ""
        first_name = original_message.from_user.first_name or str(user_id)
        
        # Injeksi parameter ke pesan asli
        if param:
            fake_command = f"/{tool_selected} {param}"
            original_message = original_message.model_copy(update={"text": fake_command, "caption": fake_command})

        await bot_message.edit_text(f"⏳ Menyiapkan tugas <b>{tool_selected.upper()}</b>...", parse_mode="HTML")
        
        process_name = getattr(Names, tool_selected, tool_selected)
        
        # [FIXED] Sesuai konstruktor ProcessStatus di Process_Status.py v3.1
        ps = ProcessStatus(
            user_id=user_id,
            chat_id=chat_id,
            username=username,
            first_name=first_name,
            message=original_message,
            process_name=process_name,
            source_type="Telegram"
        )
        
        task = {"process_status": ps, "functions": [("telegram", original_message)]}
        await add_task(task)
        await bot_message.delete()
        
    except Exception as e:
        await bot_message.edit_text(f"❌ <b>Gagal Menambahkan Task:</b>\n<code>{e}</code>", parse_mode="HTML")
