"""
FSM Video Production Flow untuk STUDIO KHOIRUL v2.0
Text-to-Video Production dengan Enhanced UI & Visual Feedback
Selaras dengan UI Dashboard Modern Aesthetic
"""

import asyncio
from aiogram import Router, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, URLInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

# Router untuk production flow
flow_router = Router(name="flow_video")

# ==========================================
# 1. STATE DEFINITIONS (FSM)
# ==========================================
class VideoProductionState(StatesGroup):
    waiting_for_prompt = State()
    customizing = State()
    confirming = State()

# ==========================================
# 2. VISUAL CONSTANTS
# ==========================================

# Borders & Separators (Selaras dengan dashboard)
BORDER_PRIMARY = "━━━━━━━━━━━━━━━━━━━"
BORDER_SUBTLE = "─────────────────────"
TOP_LEFT, TOP_RIGHT = "╭", "╮"
BOTTOM_LEFT, BOTTOM_RIGHT = "╰", "╯"

# Progress Bar Variations
def get_progress_bar(percentage: int, width: int = 15) -> str:
    """Generate animated progress bar"""
    filled = int((percentage / 100) * width)
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}] {percentage}%"

def get_smooth_progress(percentage: int, width: int = 12) -> str:
    """Smooth progress bar variation"""
    filled = int((percentage / 100) * width)
    empty = width - filled
    return f"[{'▓' * filled}{'░' * empty}]"

# Step Indicator
def get_step_indicator(current: int, total: int) -> str:
    """Visual step indicator"""
    dots = "●" * current + "○" * (total - current)
    return f"Step {current}/{total}  {dots}"

# ==========================================
# 3. HELPER KEYBOARDS
# ==========================================

def get_voice_kb(current_voice: str) -> InlineKeyboardMarkup:
    """Voice selection keyboard"""
    voices = [
        ("🇺🇸 EN-Male 1", "voice_en_m1", current_voice == "EN-Male 1"),
        ("🇺🇸 EN-Female 1", "voice_en_f1", current_voice == "EN-Female 1"),
        ("🇮🇩 ID-Male 1", "voice_id_m1", current_voice == "ID-Male 1"),
        ("🇮🇩 ID-Female 1", "voice_id_f1", current_voice == "ID-Female 1"),
    ]
    
    kb = []
    for label, callback, is_selected in voices:
        text = f"✓ {label}" if is_selected else label
        kb.append([InlineKeyboardButton(text=text, callback_data=callback)])
    
    kb.append([InlineKeyboardButton(text="⏭️ Next", callback_data="flow_voice_done")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_style_kb(current_style: str) -> InlineKeyboardMarkup:
    """Style selection keyboard"""
    styles = [
        ("🎬 Cinematic", "style_cinematic", current_style == "Cinematic"),
        ("🌅 Documentary", "style_doc", current_style == "Documentary"),
        ("⚡ Dynamic", "style_dynamic", current_style == "Dynamic"),
        ("🎨 Artistic", "style_artistic", current_style == "Artistic"),
    ]
    
    kb = []
    for label, callback, is_selected in styles:
        text = f"✓ {label}" if is_selected else label
        kb.append([InlineKeyboardButton(text=text, callback_data=callback)])
    
    kb.append([InlineKeyboardButton(text="⏭️ Next", callback_data="flow_style_done")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_bgm_kb(current_bgm: str) -> InlineKeyboardMarkup:
    """Background music selection keyboard"""
    bgms = [
        ("🎵 Synthwave", "bgm_synthwave", current_bgm == "Synthwave"),
        ("🎶 Ambient", "bgm_ambient", current_bgm == "Ambient"),
        ("🎼 Cinematic", "bgm_cinematic", current_bgm == "Cinematic"),
        ("🔇 None", "bgm_none", current_bgm == "None"),
    ]
    
    kb = []
    for label, callback, is_selected in bgms:
        text = f"✓ {label}" if is_selected else label
        kb.append([InlineKeyboardButton(text=text, callback_data=callback)])
    
    kb.append([InlineKeyboardButton(text="✓ Continue", callback_data="flow_continue")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_confirm_kb() -> InlineKeyboardMarkup:
    """Final confirmation keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Start Generation", callback_data="flow_start"),
         InlineKeyboardButton(text="✏️ Edit", callback_data="flow_edit_settings")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="action_cancel")]
    ])

def get_completion_kb() -> InlineKeyboardMarkup:
    """Post-render options"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✂️ Edit in Suite", callback_data="menu_vid_edit"),
         InlineKeyboardButton(text="💾 Save", callback_data="action_save")],
        [InlineKeyboardButton(text="🔄 Generate New", callback_data="prod_t2v"),
         InlineKeyboardButton(text="🏠 Menu", callback_data="menu_main")]
    ])

# ==========================================
# 4. ENHANCED AI ENGINE (DENGAN VISUAL FEEDBACK)
# ==========================================

async def enhanced_ai_video_engine(
    prompt: str, 
    voice: str, 
    style: str, 
    bgm: str,
    message: Message
):
    """
    Enhanced AI Video Generation dengan visual progress feedback
    PLACEHOLDER - ganti dengan API real nanti (OpenAI, Runway, etc)
    """
    
    # Rendering stages dengan visual feedback
    stages = [
        {
            "percent": 15,
            "action": "📖 Analyzing prompt structure",
            "emoji": "🔍"
        },
        {
            "percent": 35,
            "action": "🤖 Generating AI visuals",
            "emoji": "✨"
        },
        {
            "percent": 60,
            "action": f"🗣️ Synthesizing voice ({voice})",
            "emoji": "🎤"
        },
        {
            "percent": 80,
            "action": f"🎵 Composing audio track ({bgm})",
            "emoji": "🎶"
        },
        {
            "percent": 95,
            "action": "🎬 Finalizing render",
            "emoji": "⚙️"
        },
        {
            "percent": 100,
            "action": "✅ Complete!",
            "emoji": "🎉"
        }
    ]
    
    for stage in stages:
        percent = stage["percent"]
        action = stage["action"]
        emoji = stage["emoji"]
        
        progress_bar = get_progress_bar(percent, 16)
        
        text = f"""
<b>{TOP_LEFT}─ RENDERING IN PROGRESS ─{TOP_RIGHT}</b>

{progress_bar}

{emoji} <i>{action}</i>

<code>Style: {style} | Voice: {voice}</code>

{BORDER_SUBTLE}
"""
        
        try:
            await message.edit_text(text, parse_mode="HTML")
        except TelegramBadRequest:
            pass
        
        # Sleep proportional ke progress untuk simulasi real rendering
        await asyncio.sleep(1.5)
    
    # DUMMY: Ganti dengan URL hasil API AI sungguhan nanti
    dummy_video_url = "https://www.w3schools.com/html/mov_bbb.mp4"
    video_file = URLInputFile(dummy_video_url, filename="studio_khoirul_render.mp4")
    
    # Send rendered video
    caption = f"""<b>🎬 Render Complete!</b>

<b>Prompt:</b> <i>{prompt[:80]}</i>
<b>Style:</b> <code>{style}</code>
<b>Voice:</b> <code>{voice}</code>
<b>BGM:</b> <code>{bgm}</code>

Duration: ~30 seconds
Quality: 1080p
"""
    
    try:
        await message.delete()
    except:
        pass
    
    await message.answer_video(
        video=video_file,
        caption=caption,
        parse_mode="HTML"
    )

# ==========================================
# 5. STEP 1: INPUT PROMPT
# ==========================================

@flow_router.callback_query(F.data == "prod_t2v")
async def step1_input_prompt(callback: CallbackQuery, state: FSMContext):
    """Step 1 of 4: Get video prompt from user"""
    
    text = f"""
<b>{TOP_LEFT}─ TEXT TO VIDEO ─{TOP_RIGHT}</b>

{get_step_indicator(1, 4)}

<b>Deskripsikan video yang ingin Anda buat</b>

💡 <i>Tips:</i>
  • Be specific & descriptive
  • Include mood, lighting, action
  • Example: "Cyberpunk city streets, neon lights, rain"

{BORDER_SUBTLE}
<i>👇 Balas pesan ini dengan prompt Anda</i>

<b>{BOTTOM_LEFT}─────────────────────{BOTTOM_RIGHT}</b>
"""
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="action_cancel")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(VideoProductionState.waiting_for_prompt)
    await callback.answer()

# ==========================================
# 6. STEP 2: VOICE SELECTION
# ==========================================

@flow_router.message(VideoProductionState.waiting_for_prompt, F.text)
async def step2_select_voice(message: Message, state: FSMContext):
    """Step 2 of 4: Voice selection"""
    
    prompt = message.text
    await state.update_data(
        prompt=prompt,
        voice="EN-Male 1",
        style="Cinematic",
        bgm="Synthwave"
    )
    
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
    
    prompt_preview = prompt[:50] + "..." if len(prompt) > 50 else prompt
    
    text = f"""
<b>{TOP_LEFT}─ VOICE SELECTION ─{TOP_RIGHT}</b>

{get_step_indicator(2, 4)}

<b>📝 Prompt:</b> <i>"{prompt_preview}"</i>

<b>🗣️ Select voiceover preference:</b>

{BORDER_SUBTLE}

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
    
    await message.answer(
        text,
        reply_markup=get_voice_kb("EN-Male 1"),
        parse_mode="HTML"
    )

# Voice selection handlers
@flow_router.callback_query(F.data.startswith("voice_"))
async def handle_voice_selection(callback: CallbackQuery, state: FSMContext):
    """Handle voice toggle"""
    voice_map = {
        "voice_en_m1": "EN-Male 1",
        "voice_en_f1": "EN-Female 1",
        "voice_id_m1": "ID-Male 1",
        "voice_id_f1": "ID-Female 1",
    }
    
    selected_voice = voice_map.get(callback.data, "EN-Male 1")
    await state.update_data(voice=selected_voice)
    
    data = await state.get_data()
    prompt_preview = data.get("prompt", "")[:50]
    
    text = f"""
<b>{TOP_LEFT}─ VOICE SELECTION ─{TOP_RIGHT}</b>

{get_step_indicator(2, 4)}

<b>📝 Prompt:</b> <i>"{prompt_preview}..."</i>

<b>🗣️ Select voiceover preference:</b>
<code>Current: {selected_voice} ✓</code>

{BORDER_SUBTLE}

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_voice_kb(selected_voice),
        parse_mode="HTML"
    )
    await callback.answer()

@flow_router.callback_query(F.data == "flow_voice_done")
async def step3_select_style(callback: CallbackQuery, state: FSMContext):
    """Move to style selection"""
    data = await state.get_data()
    voice = data.get("voice", "EN-Male 1")
    prompt_preview = data.get("prompt", "")[:50]
    
    text = f"""
<b>{TOP_LEFT}─ STYLE SELECTION ─{TOP_RIGHT}</b>

{get_step_indicator(3, 4)}

<b>📝 Prompt:</b> <i>"{prompt_preview}..."</i>
<b>🗣️ Voice:</b> <code>{voice} ✓</code>

<b>🎨 Choose visual style:</b>

{BORDER_SUBTLE}

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_style_kb(data.get("style", "Cinematic")),
        parse_mode="HTML"
    )
    await callback.answer()

# Style selection handlers
@flow_router.callback_query(F.data.startswith("style_"))
async def handle_style_selection(callback: CallbackQuery, state: FSMContext):
    """Handle style toggle"""
    style_map = {
        "style_cinematic": "Cinematic",
        "style_doc": "Documentary",
        "style_dynamic": "Dynamic",
        "style_artistic": "Artistic",
    }
    
    selected_style = style_map.get(callback.data, "Cinematic")
    await state.update_data(style=selected_style)
    
    data = await state.get_data()
    prompt_preview = data.get("prompt", "")[:50]
    voice = data.get("voice", "EN-Male 1")
    
    text = f"""
<b>{TOP_LEFT}─ STYLE SELECTION ─{TOP_RIGHT}</b>

{get_step_indicator(3, 4)}

<b>📝 Prompt:</b> <i>"{prompt_preview}..."</i>
<b>🗣️ Voice:</b> <code>{voice} ✓</code>

<b>🎨 Choose visual style:</b>
<code>Current: {selected_style} ✓</code>

{BORDER_SUBTLE}

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_style_kb(selected_style),
        parse_mode="HTML"
    )
    await callback.answer()

@flow_router.callback_query(F.data == "flow_style_done")
async def step4_select_bgm(callback: CallbackQuery, state: FSMContext):
    """Move to BGM selection"""
    data = await state.get_data()
    voice = data.get("voice", "EN-Male 1")
    style = data.get("style", "Cinematic")
    prompt_preview = data.get("prompt", "")[:50]
    
    text = f"""
<b>{TOP_LEFT}─ BGM SELECTION ─{TOP_RIGHT}</b>

{get_step_indicator(4, 4)}

<b>📝 Prompt:</b> <i>"{prompt_preview}..."</i>
<b>🗣️ Voice:</b> <code>{voice} ✓</code>
<b>🎨 Style:</b> <code>{style} ✓</code>

<b>🎵 Choose background music:</b>

{BORDER_SUBTLE}

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_bgm_kb(data.get("bgm", "Synthwave")),
        parse_mode="HTML"
    )
    await callback.answer()

# BGM selection handlers
@flow_router.callback_query(F.data.startswith("bgm_"))
async def handle_bgm_selection(callback: CallbackQuery, state: FSMContext):
    """Handle BGM toggle"""
    bgm_map = {
        "bgm_synthwave": "Synthwave",
        "bgm_ambient": "Ambient",
        "bgm_cinematic": "Cinematic",
        "bgm_none": "None",
    }
    
    selected_bgm = bgm_map.get(callback.data, "Synthwave")
    await state.update_data(bgm=selected_bgm)
    
    data = await state.get_data()
    prompt_preview = data.get("prompt", "")[:50]
    voice = data.get("voice", "EN-Male 1")
    style = data.get("style", "Cinematic")
    
    text = f"""
<b>{TOP_LEFT}─ BGM SELECTION ─{TOP_RIGHT}</b>

{get_step_indicator(4, 4)}

<b>📝 Prompt:</b> <i>"{prompt_preview}..."</i>
<b>🗣️ Voice:</b> <code>{voice} ✓</code>
<b>🎨 Style:</b> <code>{style} ✓</code>

<b>🎵 Choose background music:</b>
<code>Current: {selected_bgm} ✓</code>

{BORDER_SUBTLE}

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_bgm_kb(selected_bgm),
        parse_mode="HTML"
    )
    await callback.answer()

# ==========================================
# 7. STEP 5: PRE-FLIGHT CHECK & CONFIRMATION
# ==========================================

@flow_router.callback_query(F.data == "flow_continue")
async def step5_preflight_check(callback: CallbackQuery, state: FSMContext):
    """Review all settings before rendering"""
    data = await state.get_data()
    prompt = data.get("prompt", "")
    voice = data.get("voice", "EN-Male 1")
    style = data.get("style", "Cinematic")
    bgm = data.get("bgm", "Synthwave")
    
    text = f"""
<b>{TOP_LEFT}─ PRE-FLIGHT CHECK ─{TOP_RIGHT}</b>

⚙️ <b>Verifying all parameters...</b>

<b>✓ Content Settings:</b>
  📝 Prompt: <i>{prompt[:70]}</i>
  🗣️ Voice: <code>{voice}</code>
  🎨 Style: <code>{style}</code>
  🎵 BGM: <code>{bgm}</code>

<b>✓ Render Info:</b>
  ⏱️ Est. Duration: 30-45 seconds
  📊 Quality: 1080p
  💎 Cost: 1 VIP Credit

{BORDER_SUBTLE}
<i>👇 Ready to generate?</i>

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=get_confirm_kb(),
        parse_mode="HTML"
    )
    await state.set_state(VideoProductionState.confirming)
    await callback.answer()

# ==========================================
# 8. RENDERING & OUTPUT
# ==========================================

@flow_router.callback_query(VideoProductionState.confirming, F.data == "flow_start")
async def start_rendering(callback: CallbackQuery, state: FSMContext):
    """Begin video generation"""
    data = await state.get_data()
    prompt = data.get("prompt", "")
    voice = data.get("voice", "EN-Male 1")
    style = data.get("style", "Cinematic")
    bgm = data.get("bgm", "Synthwave")
    
    await state.clear()
    
    # Start rendering with enhanced visual feedback
    await enhanced_ai_video_engine(prompt, voice, style, bgm, callback.message)
    
    # Show completion options
    completion_text = f"""
<b>{TOP_LEFT}─ RENDER COMPLETE ─{TOP_RIGHT}</b>

✅ <b>Video successfully generated!</b>

📊 <b>Render Summary:</b>
  📝 Prompt: <i>{prompt[:60]}</i>
  🗣️ Voice: <code>{voice}</code>
  🎨 Style: <code>{style}</code>
  🎵 BGM: <code>{bgm}</code>
  ⏱️ Duration: 30s
  📈 Quality: 1080p

{BORDER_SUBTLE}
<i>What would you like to do next?</i>

<b>{BOTTOM_LEFT}──────────────────{BOTTOM_RIGHT}</b>
"""
    
    await callback.message.answer(
        completion_text,
        reply_markup=get_completion_kb(),
        parse_mode="HTML"
    )

@flow_router.callback_query(F.data == "flow_edit_settings")
async def edit_settings(callback: CallbackQuery, state: FSMContext):
    """Go back to customize"""
    data = await state.get_data()
    if not data:
        await callback.answer("❌ Session expired", show_alert=True)
        return
    
    text = f"""
<b>{TOP_LEFT}─ EDIT SETTINGS ─{TOP_RIGHT}</b>

<b>Current Configuration:</b>
  🗣️ Voice: {data.get('voice', 'EN-Male 1')}
  🎨 Style: {data.get('style', 'Cinematic')}
  🎵 BGM: {data.get('bgm', 'Synthwave')}

{BORDER_SUBTLE}
"""
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗣️ Change Voice", callback_data="flow_voice_done")],
        [InlineKeyboardButton(text="🎨 Change Style", callback_data="flow_style_done")],
        [InlineKeyboardButton(text="🎵 Change BGM", callback_data="flow_continue")],
        [InlineKeyboardButton(text="✓ Confirm", callback_data="flow_continue")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="action_cancel")]
    ])
    
    await callback.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(VideoProductionState.customizing)
    await callback.answer()

# ==========================================
# 9. GLOBAL CANCEL & CLEANUP
# ==========================================

@flow_router.callback_query(F.data == "action_cancel")
async def global_cancel(callback: CallbackQuery, state: FSMContext):
    """Cancel operation and cleanup"""
    current_state = await state.get_state()
    
    if current_state is not None:
        await state.clear()
        cancel_text = "❌ Operation cancelled."
    else:
        cancel_text = "✕ Closed."
    
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    
    await callback.answer(cancel_text, show_alert=False)

@flow_router.callback_query(F.data == "action_save")
async def save_video(callback: CallbackQuery):
    """Save video to vault (placeholder)"""
    await callback.answer("💾 Video saved to vault!", show_alert=False)

# ==========================================
# 10. EXPORT
# ==========================================
__all__ = ["flow_router"]
