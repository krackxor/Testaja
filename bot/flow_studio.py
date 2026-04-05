"""
FSM Studio Produksi untuk STUDIO KHOIRUL
Menangani alur interaktif untuk pembuatan video AI (Recap, Clip, Lore, dll).
"""

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Integrasi ke mesin utama botmu
from bot.ui_dashboard import get_back_cancel_kb
from bot_helper.Process.Process_Status import ProcessStatus
from bot_helper.Process.Running_Tasks import add_task
from bot_helper.Others.Names import Names

studio_router = Router(name="flow_studio")

# ==========================================
# 1. DEFINISI STATE (FSM)
# ==========================================
class StudioState(StatesGroup):
    waiting_for_script = State()

def get_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Batalkan", callback_data="action_cancel")]])

# ==========================================
# 2. TANGKAP TOMBOL STUDIO DARI DASHBOARD
# ==========================================
# Daftar semua fitur AI Production dari commands kamu
STUDIO_FEATURES = [
    "cmd_recap", "cmd_clip", "cmd_verdict", "cmd_toptier", 
    "cmd_lore", "cmd_radar", "cmd_patch", "cmd_archives"
]

@studio_router.callback_query(F.data.in_(STUDIO_FEATURES))
async def trigger_studio_mode(callback: CallbackQuery, state: FSMContext):
    # Dapatkan nama fitur, misal 'recap' atau 'clip'
    feature_name = callback.data.split("_")[1]
    
    # Simpan nama fitur ke memori FSM
    await state.update_data(studio_mode=feature_name)
    await state.set_state(StudioState.waiting_for_script)
    
    # Kustomisasi teks panduan berdasarkan fitur yang dipilih
    if feature_name == "clip":
        guide = "Potong video jadi Shorts/Reels. Kirimkan teks naskah atau file .txt!"
    elif feature_name == "recap":
        guide = "Rangkum film otomatis dengan AI. Kirimkan naskah plot (script) filmnya!"
    else:
        guide = f"Pembuatan video {feature_name.upper()}. Silakan kirim naskah atau file .txt referensinya."

    text = f"""<blockquote>🎬 <b>𝐒𝐓𝐔𝐃𝐈𝐎: {feature_name.upper()}</b>
━━━━━━━━━━━━━━━━━━━━━━
{guide}

💡 <i>Tip: Anda bisa mengetik langsung teksnya di sini, atau mengirim dokumen berformat .txt.</i>
━━━━━━━━━━━━━━━━━━━━━━</blockquote>"""
    
    await callback.message.edit_text(text, reply_markup=get_cancel_kb(), parse_mode="HTML")
    await callback.answer(f"Studio {feature_name.upper()} siap!", show_alert=False)

# ==========================================
# 3. TANGKAP NASKAH & EKSEKUSI KE FFMPEG/AI
# ==========================================
@studio_router.message(StudioState.waiting_for_script, F.text | F.document)
async def process_studio_script(message: Message, state: FSMContext):
    data = await state.get_data()
    feature_name = data.get("studio_mode", "recap")
    
    # Bersihkan state agar user bisa melakukan hal lain
    await state.clear()
    
    # Tangkap naskah (Bisa berupa teks panjang atau dokumen .txt)
    script_content = "Teks Naskah"
    if message.text:
        script_content = f"{message.text[:50]}..."
    elif message.document:
        script_content = f"File Document ({message.document.file_name})"

    bot_msg = await message.reply(f"⏳ Menganalisis <b>{script_content}</b> dan menyiapkan mesin <b>{feature_name.upper()}</b>...", parse_mode="HTML")
    
    try:
        # Trik "Fake Command" seperti sebelumnya agar mesin lama bisa membacanya!
        # Seolah-olah user mengetik "/recap [isi pesan/dokumen asli]"
        fake_command = f"/{feature_name}"
        fake_message = message.model_copy(update={"text": fake_command, "caption": fake_command})
        
        # Ambil variabel dari Names.py jika ada, kalau tidak ada pakai string aslinya
        process_type = getattr(Names, feature_name, feature_name)
        process_status = ProcessStatus(fake_message, process_type)
        
        task = {
            "process_status": process_status,
            "functions": [("telegram", fake_message)]
        }
        
        # Lempar ke Antrean Task
        await add_task(task)
        await bot_msg.delete() 
        
    except Exception as e:
        await bot_msg.edit_text(f"❌ <b>Sistem Studio Gagal Memulai:</b>\n<code>{e}</code>", parse_mode="HTML")
