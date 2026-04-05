"""
FSM Video Production Flow untuk STUDIO KHOIRUL
Berkas ini menangani alur step-by-step Text-to-Video.
Dilengkapi dengan Dummy AI Engine yang siap diganti dengan API sungguhan nanti.
"""

import asyncio
from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, URLInputFile
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
# 3. DUMMY AI ENGINE (TEMPAT API NANTI)
# ==========================================
async def dummy_ai_video_engine(prompt: str, voice: str, style: str, callback: CallbackQuery):
    """
    FUNGSI PLACEHOLDER (MOCK-UP)
    Di sinilah nanti kita menaruh script koneksi ke API AI aslinya (misal OpenAI/Runway).
    Untuk sekarang, fungsi ini akan pura-pura memproses dan mengirimkan video MP4 sampel.
    """
    
    # Animasi Loading (Fake Progress Bar)
    frames = [
        ("10%", f"Menganalisis prompt: '{prompt[:15]}...'...", "██░░░░░░░░░░░░░░░░░░"),
        ("45%", f"Mensintesis suara ({voice})...", "█████████░░░░░░░░░░░"),
        ("80%", f"Menerapkan filter visual ({style})...", "████████████████░░░░"),
        ("100%", "Finalisasi metadata & rendering...", "████████████████████")
    ]
    
    for pct, action, bar in frames:
        text = f"""<blockquote>🚀 <b>RENDERING IN PROGRESS...</b>
━━━━━━━━━━━━━━━━━━━━━━
<code>[{bar}] {pct}</code>

🔄 <i>{action}</i>
━━━━━━━━━━━━━━━━━━━━━━</blockquote>"""
        await callback.message.edit_text(text, parse_mode="HTML")
        await asyncio.sleep(2) # Simulasi waktu tunggu server API (2 detik per frame)

    # NANTI: URL/File ini diganti dengan hasil download dari API AI kamu
    dummy_video_url = "https://www.w3schools.com/html/mov_bbb.mp4" 
    video_file = URLInputFile(dummy_video_url, filename="Studio_Khoirul_Draft.mp4")

    # Kirim Video Hasil
    await callback.message.answer_video(
        video=video_file,
        caption=f"🎬 <b>Render Selesai!</b>\nPrompt: <i>{prompt}</i>\nStyle: <code>{style}</code>",
        parse_mode="HTML"
    )

# ==========================================
# 4. STEP 1: INPUT PROMPT
# ==========================================
@flow_router.callback_query(F.data == "prod_t2v")
async def step1_ask_prompt(callback: CallbackQuery, state: FSMContext):
    text = """<blockquote>📝 <b>TEXT TO VIDEO</b> | <i>Step 1 of 3</i>
━━━━━━━━━━━━━━━━━━━━━━
Please <b>reply</b> to this message with your video script or prompt.

💡 <i>Tip: Be descriptive. E.g., "A neon-lit cyberpunk street scene, cinematic lighting, 4K."</i></blockquote>"""
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="action_cancel")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(VideoProductionState.waiting_for_prompt)
    await callback.answer()

# ==========================================
# 5. STEP 2: CUSTOMIZE
# ==========================================
@flow_router.message(VideoProductionState.waiting_for_prompt, F.text)
async def step2_customize(message: Message, state: FSMContext):
    prompt = message.text
    await state.update_data(prompt=prompt, voice="EN-Male 1", style="Cinematic", bgm="Synthwave")
    
    try:
        await message.delete()
    except TelegramBadRequest:
        pass 

    prompt_display = prompt[:60] + "..." if len(prompt) > 60 else prompt
    text = f"""<blockquote>🎛 <b>CUSTOMIZE ASSETS</b> | <i>Step 2 of 3</i>
━━━━━━━━━━━━━━━━━━━━━━
<b>Prompt:</b> <i>"{prompt_display}"</i>

Select your preferred AI Voice and Visual Style below:</blockquote>"""

    kb = get_customize_kb("EN-Male 1", "Cinematic", "Synthwave")
    await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(VideoProductionState.customizing)

# ==========================================
# 6. STEP 3: PRE-FLIGHT CHECK
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
# 7. STEP 4: PROCESSING & FINAL OUTPUT
# ==========================================
@flow_router.callback_query(VideoProductionState.confirming, F.data == "flow_start")
async def process_generation(callback: CallbackQuery, state: FSMContext):
    # Ambil data dari memori sebelum dihapus
    data = await state.get_data()
    prompt = data.get("prompt", "Empty Prompt")
    voice = data.get("voice", "Default Voice")
    style = data.get("style", "Default Style")
    
    # Hapus State agar user bisa melakukan task lain
    await state.clear()
    
    # 1. Panggil Dummy AI Engine
    await dummy_ai_video_engine(prompt, voice, style, callback)

    # 2. Tampilkan Menu Akhir Setelah Video Dikirim
    final_text = """<blockquote>✅ <b>𝐑𝐄𝐍𝐃𝐄𝐑 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄𝐃</b>
━━━━━━━━━━━━━━━━━━━━━━
Sistem telah berhasil menyelesaikan tugas Anda.
File video telah dikirim ke obrolan ini.
━━━━━━━━━━━━━━━━━━━━━━
<i>What would you like to do next?</i></blockquote>"""

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✂️ Open in Editor", callback_data="menu_vid_edit"),
         InlineKeyboardButton(text="📥 Save to Vault", callback_data="action_save")],
        [InlineKeyboardButton(text="🗑️ Delete", callback_data="action_cancel"),
         InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu_main")]
    ])
    
    await callback.message.edit_text(final_text, reply_markup=kb, parse_mode="HTML")

# ==========================================
# 8. GLOBAL CANCEL ENHANCEMENT
# ==========================================
@flow_router.callback_query(F.data == "action_cancel")
async def global_cancel(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None:
        await state.clear()
        
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await callback.answer("❌ Tugas dibatalkan.", show_alert=False)
