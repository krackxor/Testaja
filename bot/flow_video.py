"""
FSM Video Production Flow untuk STUDIO KHOIRUL
Berkas ini murni menangani alur step-by-step Text-to-Video tanpa mengganggu fitur lama.
"""

import asyncio
from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

# Router khusus untuk alur produksi video
flow_router = Router(name="flow_video")

# ==========================================
# 1. DEFINISI STATE (FSM)
# ==========================================
class VideoProductionState(StatesGroup):
    waiting_for_prompt = State()
    customizing = State()
    confirming = State()

# ==========================================
# 2. HELPER KEYBOARDS
# ==========================================
def get_customize_kb(voice: str, style: str, bgm: str) -> InlineKeyboardMarkup:
    """Keyboard dinamis untuk menyesuaikan preferensi"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🗣️ Voice: {voice}", callback_data="toggle_voice")],
        [InlineKeyboardButton(text=f"🎨 Style: {style}", callback_data="toggle_style")],
        [InlineKeyboardButton(text=f"🎵 BGM: {bgm}", callback_data="toggle_bgm")],
        [InlineKeyboardButton(text="⏭️ Continue to Review", callback_data="flow_continue")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="action_cancel")]
    ])

def get_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Start Generation", callback_data="flow_start")],
        [InlineKeyboardButton(text="✏️ Edit Settings", callback_data="flow_edit"),
         InlineKeyboardButton(text="❌ Cancel", callback_data="action_cancel")]
    ])

# ==========================================
# 3. STEP 1: INPUT PROMPT
# ==========================================
@flow_router.callback_query(F.data == "prod_t2v")
async def step1_ask_prompt(callback: CallbackQuery, state: FSMContext):
    """Merespons saat tombol 'Text to Video' di Dashboard ditekan"""
    text = """<blockquote>📝 <b>TEXT TO VIDEO</b> | <i>Step 1 of 3</i>
━━━━━━━━━━━━━━━━━━━━━━
Please <b>reply</b> to this message with your video script or prompt.

💡 <i>Tip: Be descriptive. E.g., "A neon-lit cyberpunk street scene, cinematic lighting, 4K."</i></blockquote>"""
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="action_cancel")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    
    # Aktifkan FSM State
    await state.set_state(VideoProductionState.waiting_for_prompt)
    await callback.answer()

# ==========================================
# 4. STEP 2: CUSTOMIZE
# ==========================================
@flow_router.message(VideoProductionState.waiting_for_prompt, F.text)
async def step2_customize(message: Message, state: FSMContext):
    """Menangkap balasan teks dari pengguna"""
    prompt = message.text
    
    # Simpan data ke memori sementara (FSM)
    await state.update_data(prompt=prompt, voice="EN-Male 1", style="Cinematic", bgm="Synthwave")
    
    # [Premium Feel] Hapus pesan ketikan user agar chat tetap bersih
    try:
        await message.delete()
    except TelegramBadRequest:
        pass # Abaikan jika tidak punya izin hapus

    prompt_display = prompt[:60] + "..." if len(prompt) > 60 else prompt
    text = f"""<blockquote>🎛 <b>CUSTOMIZE ASSETS</b> | <i>Step 2 of 3</i>
━━━━━━━━━━━━━━━━━━━━━━
<b>Prompt:</b> <i>"{prompt_display}"</i>

Select your preferred AI Voice and Visual Style below:</blockquote>"""

    kb = get_customize_kb("EN-Male 1", "Cinematic", "Synthwave")
    bot_msg = await message.answer(text, reply_markup=kb, parse_mode="HTML")
    
    # Simpan ID pesan bot untuk di-edit nanti
    await state.update_data(last_bot_msg_id=bot_msg.message_id)
    await state.set_state(VideoProductionState.customizing)

# ==========================================
# 5. STEP 3: PRE-FLIGHT CHECK
# ==========================================
@flow_router.callback_query(VideoProductionState.customizing, F.data == "flow_continue")
async def step3_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    text = f"""<blockquote>⚙️ <b>PRE-FLIGHT CHECK</b> | <i>Step 3 of 3</i>
━━━━━━━━━━━━━━━━━━━━━━
Everything is set. Review your parameters:

🗣️ <b>Voiceover:</b> <code>Activated ({data.get('voice')})</code>
🎨 <b>Visuals:</b> <code>{data.get('style')} Dark Mode</code>
🎵 <b>BGM:</b> <code>{data.get('bgm')}</code>
⏱️ <b>Est. Time:</b> <code>~45 Seconds</code>
💎 <b>Cost:</b> <code>1 VIP Credit</code>
━━━━━━━━━━━━━━━━━━━━━━
<i>Ready to deploy?</i></blockquote>"""

    await callback.message.edit_text(text, reply_markup=get_confirm_kb(), parse_mode="HTML")
    await state.set_state(VideoProductionState.confirming)
    await callback.answer()

# ==========================================
# 6. STEP 4: PROCESSING & FINAL OUTPUT
# ==========================================
@flow_router.callback_query(VideoProductionState.confirming, F.data == "flow_start")
async def process_generation(callback: CallbackQuery, state: FSMContext):
    # Hapus State karena proses sudah dikonfirmasi
    await state.clear()
    
    # Animasi Loading (Fake Progress Bar)
    frames = [
        ("10%", "Synthesizing AI voiceover...", "██░░░░░░░░░░░░░░░░░░"),
        ("45%", "Applying cinematic color grading...", "█████████░░░░░░░░░░░"),
        ("80%", "Rendering 4K output...", "████████████████░░░░"),
        ("100%", "Finalizing metadata...", "████████████████████")
    ]
    
    for pct, action, bar in frames:
        text = f"""<blockquote>🚀 <b>RENDERING IN PROGRESS...</b>
━━━━━━━━━━━━━━━━━━━━━━
<code>[{bar}] {pct}</code>

🔄 <i>{action}</i>
━━━━━━━━━━━━━━━━━━━━━━</blockquote>"""
        await callback.message.edit_text(text, parse_mode="HTML")
        await asyncio.sleep(1.5) # Jeda simulasi (Nanti bisa diganti dengan FFmpeg aslimu)

    # Hasil Akhir
    final_text = """<blockquote>✅ <b>𝐑𝐄𝐍𝐃𝐄𝐑 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃</b>
━━━━━━━━━━━━━━━━━━━━━━
🎬 <b>File:</b> <code>Cyberpunk_Scene_001.mp4</code>
⏱️ <b>Duration:</b> <code>00:00:30</code>
💽 <b>Size:</b> <code>14.2 MB</code>
━━━━━━━━━━━━━━━━━━━━━━
<i>What would you like to do next?</i></blockquote>"""

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✂️ Open in Editor", callback_data="menu_vid_edit"),
         InlineKeyboardButton(text="📥 Save to Vault", callback_data="action_save")],
        [InlineKeyboardButton(text="🗑️ Delete", callback_data="action_cancel"),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu_main")]
    ])
    
    await callback.message.edit_text(final_text, reply_markup=kb, parse_mode="HTML")
    # INFO: Di sini kamu nanti bisa memanggil `await callback.message.answer_video(...)` 
    # untuk mengirim video aslinya.

# ==========================================
# 7. GLOBAL CANCEL ENHANCEMENT
# ==========================================
@flow_router.callback_query(F.data == "action_cancel")
async def global_cancel(callback: CallbackQuery, state: FSMContext):
    """Membatalkan seluruh proses dan menghapus State aktif"""
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear() # Bersihkan memori FSM
        
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await callback.answer("❌ Tugas dibatalkan.", show_alert=False)
