"""
╔══════════════════════════════════════════════════════════════════════╗
║                 bot/subtitle_editor.py — v2.3 (SMART NAV)            ║
║       Subtitle Editor: Workspace & Jump Feature (Studio Khoirul)     ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v2.3:                                                     ║
║  [FIX CRITICAL] Memori Halaman Dinamis: Saat mengklik 'Kembali' atau ║
║                 menghapus baris, user akan dikembalikan ke halaman   ║
║                 terakhir mereka, BUKAN lagi reset ke Halaman 1.      ║
║  [IMPROVE] Fitur 'Lompat' kini lebih akurat dengan get_current_page. ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import os
import pysrt
import html
from bson.objectid import ObjectId
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from deep_translator import GoogleTranslator

from config.config import Config
from bot_helper.Database.DB_Handler import get_db
from bot_helper.Database.User_Data import (
    get_data, DATA, get_subtitle_page, get_total_sub_lines, 
    get_single_sub_line, clear_subtitle_temp, get_active_settings,
    _DATA_LOCK, _save_to_db
)
from bot_helper.Others.SrtParser import parse_srt_to_db
from bot_helper.Others.SrtCompiler import compile_db_to_srt
from bot.shared import wait_for_message, CMD_SUFFIX, LOGGER

router = Router()

def get_cancel_kb():
    """Membuat ReplyKeyboard untuk membatalkan input."""
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Batal")]], resize_keyboard=True, one_time_keyboard=True)

async def get_current_page(user_id: int, line_idx: int) -> int:
    """[NEW] Menghitung posisi halaman secara dinamis agar tidak reset ke Hal 1."""
    db = get_db()
    count = await db.db["subtitle_temp"].count_documents({"user_id": user_id, "index": {"$lte": line_idx}})
    return max(1, ((count - 1) // 5) + 1)

# ═══════════════════════════════════════════════════════════════════════
#  UI GENERATORS (INLINE KEYBOARDS)
# ═══════════════════════════════════════════════════════════════════════

async def get_workspace_kb(user_id: int):
    """Menu Utama Workspace"""
    db = get_db()
    kb = []
    
    kb.append([InlineKeyboardButton(text="🆕 Buat Proyek Baru", callback_data=f"sub_new_{user_id}")])
    
    active_count = await db.db["subtitle_temp"].count_documents({"user_id": user_id})
    if active_count > 0:
        kb.append([InlineKeyboardButton(text=f"▶️ Lanjutkan Proyek Aktif ({active_count} Baris)", callback_data=f"sub_pg_{user_id}_1")])
    
    saved_count = await db.db["subtitle_projects"].count_documents({"user_id": user_id})
    if saved_count > 0:
        kb.append([InlineKeyboardButton(text=f"📂 Buka Proyek Tersimpan ({saved_count})", callback_data=f"sub_proj_{user_id}")])
    
    kb.append([InlineKeyboardButton(text="❌ Tutup Workspace", callback_data=f"sub_cancel_{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def get_saved_projects_kb(user_id: int):
    """Daftar Proyek yang Tersimpan"""
    db = get_db()
    projects = await db.db["subtitle_projects"].find({"user_id": user_id}).sort("_id", -1).to_list(length=10)
    
    kb = []
    for p in projects:
        name = p.get("project_name", "Untitled")
        pid = str(p["_id"])
        kb.append([
            InlineKeyboardButton(text=f"📁 {name}", callback_data=f"sub_load_{user_id}_{pid}"),
            InlineKeyboardButton(text="🗑️ Hapus", callback_data=f"sub_delp_{user_id}_{pid}")
        ])
    
    kb.append([InlineKeyboardButton(text="↩️ Kembali ke Workspace", callback_data=f"sub_main_{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_editor_kb(lines, current_page, total_pages, user_id, target_lang):
    """Menu Editor Utama dengan Fitur Jump"""
    kb = []
    for line in lines:
        raw_text = str(line.get('text', ''))
        preview = raw_text[:35] + "..." if len(raw_text) > 35 else raw_text
        idx = line.get('index', 0)
        kb.append([InlineKeyboardButton(text=f"#{idx} | {preview}", callback_data=f"sub_focus_{user_id}_{idx}")])
    
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton(text="⏪ Prev", callback_data=f"sub_pg_{user_id}_{current_page-1}"))
    
    nav_row.append(InlineKeyboardButton(text=f"🔍 {current_page}/{total_pages}", callback_data=f"sub_jump_{user_id}"))
    
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Next ⏩", callback_data=f"sub_pg_{user_id}_{current_page+1}"))
    kb.append(nav_row)
    
    kb.append([InlineKeyboardButton(text=f"🌐 Set Bahasa Target: {target_lang.upper()}", callback_data=f"sub_setlang_{user_id}")])
    kb.append([
        InlineKeyboardButton(text="⏳ Resync All", callback_data=f"sub_rsall_{user_id}", style="primary"),
        InlineKeyboardButton(text="🌐 Trans All", callback_data=f"sub_trall_{user_id}", style="primary")
    ])
    kb.append([
        InlineKeyboardButton(text="💾 Simpan Proyek", callback_data=f"sub_save_{user_id}", style="success"),
        InlineKeyboardButton(text="✅ Kompilasi SRT", callback_data=f"sub_compile_{user_id}", style="success")
    ])
    kb.append([InlineKeyboardButton(text="❌ Keluar Editor", callback_data=f"sub_main_{user_id}", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_focus_kb(user_id, line_index, current_page):
    """Menu Fokus Per Baris (Menyimpan Memori Halaman)"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📝 Edit Teks", callback_data=f"sub_edit_txt_{user_id}_{line_index}", style="primary"),
            InlineKeyboardButton(text="🌐 Terjemahkan", callback_data=f"sub_edit_tr_{user_id}_{line_index}", style="primary")
        ],
        [
            InlineKeyboardButton(text="⏪ -0.5s", callback_data=f"sub_adj_{user_id}_{line_index}_-500"),
            InlineKeyboardButton(text="+0.5s ⏩", callback_data=f"sub_adj_{user_id}_{line_index}_500")
        ],
        [
            InlineKeyboardButton(text="🗑️ Hapus Baris", callback_data=f"sub_del_{user_id}_{line_index}", style="danger"),
            # [FIX] Tombol kembali kini melempar user ke current_page, BUKAN halaman 1!
            InlineKeyboardButton(text="↩️ Kembali", callback_data=f"sub_pg_{user_id}_{current_page}", style="danger")
        ]
    ])

# ═══════════════════════════════════════════════════════════════════════
#  CORE PARSER LOGIC
# ═══════════════════════════════════════════════════════════════════════

async def start_new_project_from_file(message: Message, document, user_id: int):
    """Fungsi inti untuk memproses file SRT yang dikirim user."""
    file_name = document.file_name
    status_msg = await message.answer("⏳ 📝 **Menganalisis Subtitle untuk Proyek Baru...**", reply_markup=ReplyKeyboardRemove())
    
    try:
        os.makedirs("./temp", exist_ok=True)
        srt_path = f"./temp/sub_{user_id}.srt"
        
        await Telegram.AIOGRAM_BOT.download(document, destination=srt_path)
        
        total_lines = await parse_srt_to_db(user_id, srt_path)
        lines = await get_subtitle_page(user_id, page=1, limit=5)
        total_pages = (total_lines // 5) + (1 if total_lines % 5 > 0 else 0)
        target_lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        
        text = (
            f"<b>📝 SUBTITLE EDITOR (Proyek Aktif)</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>File:</b> <code>{file_name}</code>\n"
            f"📊 <b>Total:</b> <code>{total_lines} Baris</code>\n\n"
            f"<i>Silakan pilih baris yang ingin Anda edit di bawah ini 👇</i>"
        )
        await status_msg.edit_text(text, reply_markup=get_editor_kb(lines, 1, total_pages, user_id, target_lang), parse_mode="HTML")
        if os.path.exists(srt_path): os.remove(srt_path)
    except Exception as e:
        LOGGER.error(f"SubEdit Error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ **Error saat memproses file:** {e}")

# ═══════════════════════════════════════════════════════════════════════
#  ENTRY POINTS (COMMAND & EXTERNAL BUTTON)
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"subedit{CMD_SUFFIX}"))
async def subedit_start(message: Message):
    user_id = message.from_user.id
    
    if message.reply_to_message and message.reply_to_message.document:
        if not message.reply_to_message.document.file_name.lower().endswith('.srt'):
            return await message.reply("❌ **Gagal:** Hanya mendukung format `.srt`.")
        return await start_new_project_from_file(message, message.reply_to_message.document, user_id)

    kb = await get_workspace_kb(user_id)
    text = (
        "<b>🗂️ SUBTITLE WORKSPACE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Selamat datang di Manajer Proyek Subtitle.\n\n"
        "<i>Pilih opsi di bawah ini untuk memulai:</i>"
    )
    return await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "open_sub_workspace")
async def handle_open_workspace_external(call: CallbackQuery):
    user_id = call.from_user.id
    kb = await get_workspace_kb(user_id)
    text = (
        "<b>🗂️ SUBTITLE WORKSPACE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Selamat datang di Manajer Proyek Subtitle.\n\n"
        "<i>Pilih opsi di bawah ini untuk memulai:</i>"
    )
    try: await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest: pass
    await call.answer()

# ═══════════════════════════════════════════════════════════════════════
#  WORKSPACE HANDLERS (NEW, SAVE, LOAD, DELETE, LIST)
# ═══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("sub_new_"))
async def handle_new_project_btn(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        await call.answer()
        prompt = await call.message.answer(
            "🆕 <b>BUAT PROYEK BARU</b>\n\n"
            "Silakan kirimkan atau teruskan (forward) file <code>.srt</code> Anda ke sini.\n"
            "<i>Ketik 'batal' untuk kembali ke menu.</i>", 
            reply_markup=get_cancel_kb(), parse_mode="HTML"
        )
        
        try: response = await wait_for_message(call.message.chat.id, user_id, 120)
        except asyncio.TimeoutError: response = None
            
        if not response or (response.text and response.text.lower() == "batal"):
            if prompt: await prompt.delete()
            return await call.message.answer("Dibatalkan.", reply_markup=ReplyKeyboardRemove())

        if not response.document or not response.document.file_name.lower().endswith('.srt'):
            if prompt: await prompt.delete()
            return await call.message.answer("❌ Dibatalkan. Anda harus mengirimkan file dokumen berformat .srt!", reply_markup=ReplyKeyboardRemove())
            
        await prompt.delete()
        await start_new_project_from_file(response, response.document, user_id)
        
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_main_"))
async def handle_workspace_main(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        kb = await get_workspace_kb(user_id)
        text = "<b>🗂️ SUBTITLE WORKSPACE</b>\n━━━━━━━━━━━━━━━━━━━━\nSelamat datang di Manajer Proyek Subtitle.\n\n<i>Pilih opsi di bawah ini untuk memulai:</i>"
        try: await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest: pass
        await call.answer()
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_proj_"))
async def handle_list_projects(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        kb = await get_saved_projects_kb(user_id)
        text = "<b>💾 PROYEK TERSIMPAN</b>\n━━━━━━━━━━━━━━━━━━━━\n<i>Pilih proyek untuk dimuat (Load) atau dihapus:</i>"
        try: await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest: pass
        await call.answer()
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_save_"))
async def handle_save_project(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        await call.answer()
        prompt = await call.message.answer("💾 <b>SIMPAN PROYEK</b>\n\nKetik nama untuk proyek ini (Contoh: `Eps 1 Final`):", reply_markup=get_cancel_kb(), parse_mode="HTML")
        
        try: response = await wait_for_message(call.message.chat.id, user_id, 60)
        except asyncio.TimeoutError: response = None
            
        if not response or response.text.lower() == "batal":
            if prompt: await prompt.delete()
            return await call.message.answer("Penyimpanan dibatalkan.", reply_markup=ReplyKeyboardRemove())

        project_name = response.text.strip()
        db = get_db()
        active_lines = await db.db["subtitle_temp"].find({"user_id": user_id}).to_list(length=None)
        if not active_lines:
            await prompt.delete()
            return await call.message.answer("❌ Proyek kosong, tidak ada yang disimpan.", reply_markup=ReplyKeyboardRemove())

        await db.db["subtitle_projects"].update_one(
            {"user_id": user_id, "project_name": project_name},
            {"$set": {"lines": active_lines}},
            upsert=True
        )
        
        try:
            await prompt.delete()
            await response.delete()
        except: pass
        
        temp_msg = await call.message.answer(f"✅ Proyek <b>{project_name}</b> berhasil disimpan!", reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")
        await asyncio.sleep(2)
        await temp_msg.delete()
        
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_load_"))
async def handle_load_project(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id, proj_id = int(parts[2]), parts[3]
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        db = get_db()
        project = await db.db["subtitle_projects"].find_one({"_id": ObjectId(proj_id), "user_id": user_id})
        
        if not project or "lines" not in project:
            return await call.answer("❌ Proyek tidak ditemukan/rusak.", show_alert=True)
            
        await call.answer("⏳ Memuat proyek...", show_alert=False)
        
        await db.db["subtitle_temp"].delete_many({"user_id": user_id})
        await db.db["subtitle_temp"].insert_many(project["lines"])
        
        lines = await get_subtitle_page(user_id, page=1, limit=5)
        total_lines = await get_total_sub_lines(user_id)
        total_pages = (total_lines // 5) + (1 if total_lines % 5 > 0 else 0)
        target_lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        
        text = f"<b>📝 SUBTITLE EDITOR (Proyek: {project.get('project_name')})</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total_lines} Baris</code>\n\n<i>Pilih baris:</i>"
        await call.message.edit_text(text, reply_markup=get_editor_kb(lines, 1, total_pages, user_id, target_lang), parse_mode="HTML")
        
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_delp_"))
async def handle_delete_project(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id, proj_id = int(parts[2]), parts[3]
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        db = get_db()
        await db.db["subtitle_projects"].delete_one({"_id": ObjectId(proj_id), "user_id": user_id})
        await call.answer("🗑️ Proyek dihapus!", show_alert=False)
        
        kb = await get_saved_projects_kb(user_id)
        text = "<b>💾 PROYEK TERSIMPAN</b>\n━━━━━━━━━━━━━━━━━━━━\n<i>Pilih proyek untuk dimuat (Load) atau dihapus:</i>"
        try: await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest: pass
        
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

# ═══════════════════════════════════════════════════════════════════════
#  EDITOR LOGIC (JUMP, PAGINATION, EDIT, RESYNC, DLL)
# ═══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("sub_jump_"))
async def handle_jump_prompt(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        await call.answer()
        total_lines = await get_total_sub_lines(user_id)
        prompt = await call.message.answer(
            f"🔍 <b>LOMPAT KE BARIS</b>\n\nTotal baris: <code>{total_lines}</code>\n"
            f"Ketik nomor baris yang ingin Anda tuju (contoh: <code>500</code>):", 
            reply_markup=get_cancel_kb(), parse_mode="HTML"
        )
        
        try: res = await wait_for_message(call.message.chat.id, user_id, 60)
        except asyncio.TimeoutError: res = None
            
        if not res or res.text.lower() == "batal":
            if prompt: await prompt.delete()
            return await call.message.answer("Pencarian dibatalkan.", reply_markup=ReplyKeyboardRemove())

        try:
            line_idx = int(res.text.strip())
        except ValueError:
            await prompt.delete()
            return await call.message.answer(f"❌ Masukkan angka bulat yang valid.", reply_markup=ReplyKeyboardRemove())

        # [FIX] Hitung halaman target secara akurat
        target_page = await get_current_page(user_id, line_idx)
        
        await prompt.delete()
        await res.delete()
        
        temp = await call.message.answer(f"🚀 Melompat ke baris terdekat (Halaman {target_page})...", reply_markup=ReplyKeyboardRemove())
        await asyncio.sleep(0.5)
        await temp.delete()

        lines = await get_subtitle_page(user_id, page=target_page, limit=5)
        total_pages = (total_lines // 5) + (1 if total_lines % 5 > 0 else 0)
        target_lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        
        text = f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total_lines} Baris</code>\n📍 Lokasi: Sekitar baris #{line_idx}\n\n<i>Silakan pilih baris:</i>"
        try: await call.message.edit_text(text, reply_markup=get_editor_kb(lines, target_page, total_pages, user_id, target_lang), parse_mode="HTML")
        except TelegramBadRequest: pass
        
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_pg_"))
async def handle_pagination(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id = int(parts[2])
        page = int(parts[3]) # [FIX] Tidak ada lagi hardcoded "back", selalu menerima nomor halaman akurat
        
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        lines = await get_subtitle_page(user_id, page=page, limit=5)
        total_lines = await get_total_sub_lines(user_id)
        total_pages = (total_lines // 5) + (1 if total_lines % 5 > 0 else 0)
        target_lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        
        text = f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total_lines} Baris</code>\n\n<i>Pilih baris:</i>"
        try: await call.message.edit_text(text, reply_markup=get_editor_kb(lines, page, total_pages, user_id, target_lang), parse_mode="HTML")
        except TelegramBadRequest: pass 
        await call.answer()
        
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_focus_"))
async def handle_focus(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id, line_idx = int(parts[2]), int(parts[3])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        line_data = await get_single_sub_line(user_id, line_idx)
        if not line_data: return await call.answer("Baris tidak ditemukan di DB.", show_alert=True)
        
        cur_page = await get_current_page(user_id, line_idx) # Ambil memori halaman saat ini
        
        safe_text = html.escape(str(line_data.get('text', ''))) 
        start_time = str(line_data.get('start', '00:00:00,000'))
        end_time = str(line_data.get('end', '00:00:00,000'))
        
        text = (
            f"<b>🛠 EDITING BARIS #{line_idx}</b>\n"
            f"────────────────────\n"
            f"⏰ <b>Waktu:</b> <code>{start_time} --> {end_time}</code>\n"
            f"💬 <b>Teks:</b> <code>{safe_text}</code>\n"
            f"────────────────────"
        )
        await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx, cur_page), parse_mode="HTML")
        await call.answer()
        
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_adj_"))
async def handle_adjust_time(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id, line_idx, ms = int(parts[2]), int(parts[3]), int(parts[4])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        line = await get_single_sub_line(user_id, line_idx)
        start_str = str(line.get("start", "00:00:00,000")).replace('.', ',')
        end_str = str(line.get("end", "00:00:00,000")).replace('.', ',')
        
        st = pysrt.SubRipTime.from_string(start_str)
        et = pysrt.SubRipTime.from_string(end_str)
        st.shift(milliseconds=ms)
        et.shift(milliseconds=ms)
        
        db = get_db()
        await db.db["subtitle_temp"].update_one(
            {"user_id": user_id, "index": line_idx},
            {"$set": {"start": str(st).replace(',', '.'), "end": str(et).replace(',', '.')}}
        )
        await call.answer(f"✅ Waktu digeser {ms}ms")
        
        cur_page = await get_current_page(user_id, line_idx)
        line_data = await get_single_sub_line(user_id, line_idx)
        safe_text = html.escape(str(line_data.get('text', '')))
        text = (
            f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n"
            f"⏰ <b>Waktu:</b> <code>{line_data.get('start')} --> {line_data.get('end')}</code>\n"
            f"💬 <b>Teks:</b> <code>{safe_text}</code>\n────────────────────"
        )
        try: await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx, cur_page), parse_mode="HTML")
        except TelegramBadRequest: pass
        
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_edit_tr_"))
async def handle_translate_line(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id, line_idx = int(parts[3]), int(parts[4])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        line = await get_single_sub_line(user_id, line_idx)
        raw_text = str(line.get("text", ""))
        target_lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        
        await call.answer(f"⏳ Menerjemahkan ke {target_lang.upper()}...", show_alert=False)
        
        translator = GoogleTranslator(source='auto', target=target_lang)
        translated = await asyncio.to_thread(translator.translate, raw_text)
        
        db = get_db()
        await db.db["subtitle_temp"].update_one({"user_id": user_id, "index": line_idx}, {"$set": {"text": translated}})
        
        cur_page = await get_current_page(user_id, line_idx)
        line_data = await get_single_sub_line(user_id, line_idx)
        safe_text = html.escape(str(line_data.get('text', '')))
        text = (
            f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n"
            f"⏰ <b>Waktu:</b> <code>{line_data.get('start')} --> {line_data.get('end')}</code>\n"
            f"💬 <b>Teks:</b> <code>{safe_text}</code>\n────────────────────"
        )
        await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx, cur_page), parse_mode="HTML")
        
    except Exception as e:
        await call.answer(f"⚠️ Gagal: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_edit_txt_"))
async def handle_edit_text_prompt(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id, line_idx = int(parts[3]), int(parts[4])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        await call.answer()
        prompt = await call.message.answer(
            f"📝 **Kirimkan teks baru untuk baris #{line_idx}:**", 
            reply_markup=get_cancel_kb()
        )
        
        try: response = await wait_for_message(call.message.chat.id, user_id, 120)
        except asyncio.TimeoutError: response = None
            
        if not response or response.text.lower() == "batal":
            if prompt: await prompt.delete()
            return await call.message.answer("Batal mengedit.", reply_markup=ReplyKeyboardRemove())

        db = get_db()
        await db.db["subtitle_temp"].update_one({"user_id": user_id, "index": line_idx}, {"$set": {"text": response.text}})
        
        try:
            await response.delete()
            await prompt.delete()
        except: pass
        
        temp_msg = await call.message.answer("✅ Teks diperbarui!", reply_markup=ReplyKeyboardRemove())
        await asyncio.sleep(1)
        await temp_msg.delete()
        
        cur_page = await get_current_page(user_id, line_idx)
        line_data = await get_single_sub_line(user_id, line_idx)
        safe_text = html.escape(str(line_data.get('text', '')))
        text = (
            f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n"
            f"⏰ <b>Waktu:</b> <code>{line_data.get('start')} --> {line_data.get('end')}</code>\n"
            f"💬 <b>Teks:</b> <code>{safe_text}</code>\n────────────────────"
        )
        try: await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx, cur_page), parse_mode="HTML")
        except TelegramBadRequest: pass
        
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_setlang_"))
async def handle_set_lang(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        await call.answer()
        prompt = await call.message.answer(
            "🌐 **Masukkan kode bahasa target:**\n"
            "(Contoh: `id` untuk Indonesia, `en` untuk Inggris, `ja` untuk Jepang, `ko` untuk Korea)\n\n", 
            reply_markup=get_cancel_kb()
        )
        
        try: res = await wait_for_message(call.message.chat.id, user_id, 60)
        except asyncio.TimeoutError: res = None
            
        if not res or res.text.lower() == "batal":
            await prompt.delete()
            return await call.message.answer("Dibatalkan.", reply_markup=ReplyKeyboardRemove())

        new_lang = res.text.strip().lower()
        
        async with _DATA_LOCK:
            active = DATA.get(user_id, {}).get("active_profile", "Default")
            if "profiles" not in DATA[user_id]: DATA[user_id]["profiles"] = {}
            if active not in DATA[user_id]["profiles"]: DATA[user_id]["profiles"][active] = {}
            if "ai_subtitle" not in DATA[user_id]["profiles"][active]: DATA[user_id]["profiles"][active]["ai_subtitle"] = {}
            DATA[user_id]["profiles"][active]["ai_subtitle"]["target_lang"] = new_lang
        await _save_to_db({user_id: DATA[user_id]})

        await prompt.delete()
        await res.delete()
        temp_msg = await call.message.answer(f"✅ Bahasa target diubah ke: `{new_lang}`", reply_markup=ReplyKeyboardRemove())
        await asyncio.sleep(1.5)
        await temp_msg.delete()
        
        # Reload current state
        parts = call.message.reply_markup.inline_keyboard[-4][1].callback_data.split("_")
        # Find current page from navigation row
        # It's better to just load page 1 if we can't reliably parse it, but we can do a fallback
        lines = await get_subtitle_page(user_id, page=1, limit=5)
        total_lines = await get_total_sub_lines(user_id)
        total_pages = (total_lines // 5) + (1 if total_lines % 5 > 0 else 0)
        text = f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total_lines} Baris</code>\n\n<i>Pilih baris:</i>"
        try: await call.message.edit_text(text, reply_markup=get_editor_kb(lines, 1, total_pages, user_id, new_lang), parse_mode="HTML")
        except TelegramBadRequest: pass
        
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_trall_"))
async def handle_translate_all(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        target_lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        await call.answer(f"⏳ Memulai Auto Translate ke {target_lang.upper()}...", show_alert=True)
        status_msg = await call.message.edit_text(f"⏳ <b>Menerjemahkan ke {target_lang.upper()} di latar belakang...</b>\nAnda bisa menggunakan fitur bot lainnya.", parse_mode="HTML")
        
        db = get_db()
        cursor = db.db["subtitle_temp"].find({"user_id": user_id})
        all_lines = await cursor.to_list(length=None)
        translator = GoogleTranslator(source='auto', target=target_lang)
        
        count = 0
        for line in all_lines:
            raw_text = str(line.get("text", ""))
            translated = await asyncio.to_thread(translator.translate, raw_text)
            await db.db["subtitle_temp"].update_one({"_id": line["_id"]}, {"$set": {"text": translated}})
            count += 1
            if count % 10 == 0: await asyncio.sleep(0.5) 
                    
        await status_msg.edit_text(f"✅ <b>Berhasil menerjemahkan {count} baris ke {target_lang.upper()}!</b>\nSilakan klik 'Selesai & Kompilasi'.", parse_mode="HTML")
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_rsall_"))
async def handle_resync_all(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        await call.answer()
        prompt = await call.message.answer(
            "⏳ <b>RESYNC SEMUA BARIS</b>\n\n"
            "Ketik jumlah milidetik (ms) untuk digeser.\n"
            "Contoh: <code>500</code> (maju 0.5 detik), <code>-1000</code> (mundur 1 detik).", 
            reply_markup=get_cancel_kb(),
            parse_mode="HTML"
        )
        
        try: response = await wait_for_message(call.message.chat.id, user_id, 60)
        except asyncio.TimeoutError: response = None
            
        if not response or response.text.lower() == "batal":
            if prompt: await prompt.delete()
            return await call.message.answer("Batal resync.", reply_markup=ReplyKeyboardRemove())

        try: ms_shift = int(response.text.strip())
        except ValueError:
            await prompt.delete()
            return await call.message.answer("❌ Harus berupa angka bulat (contoh: 500).", reply_markup=ReplyKeyboardRemove())

        status_msg = await call.message.edit_text(f"⏳ <b>Memproses Resync {ms_shift}ms...</b>", parse_mode="HTML")
        await call.message.answer("Memulai resync...", reply_markup=ReplyKeyboardRemove())
        
        db = get_db()
        cursor = db.db["subtitle_temp"].find({"user_id": user_id})
        all_lines = await cursor.to_list(length=None)
        
        count = 0
        for line in all_lines:
            st = pysrt.SubRipTime.from_string(str(line.get("start", "00:00:00,000")).replace('.', ','))
            et = pysrt.SubRipTime.from_string(str(line.get("end", "00:00:00,000")).replace('.', ','))
            st.shift(milliseconds=ms_shift)
            et.shift(milliseconds=ms_shift)
            
            await db.db["subtitle_temp"].update_one(
                {"_id": line["_id"]},
                {"$set": {"start": str(st).replace(',', '.'), "end": str(et).replace(',', '.')}}
            )
            count += 1
            if count % 50 == 0: await asyncio.sleep(0.05)
                    
        await status_msg.edit_text(f"✅ <b>Berhasil Resync {count} baris sebanyak {ms_shift}ms!</b>\nSilakan klik 'Selesai & Kompilasi'.", parse_mode="HTML")
        
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_compile_"))
async def handle_compile(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        await call.answer()
        msg = await call.message.edit_text("⏳ 🏗 **Menyusun file SRT baru...**")
        output_path = await compile_db_to_srt(user_id)
        
        if output_path and os.path.exists(output_path):
            await call.message.answer_document(
                document=FSInputFile(output_path),
                caption="✅ **Subtitle Berhasil Dikompilasi!**"
            )
            await msg.delete()
        else:
            await call.message.edit_text("❌ Gagal mengompilasi file.")
            
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_del_"))
async def handle_delete_line(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id, line_idx = int(parts[2]), int(parts[3])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        db = get_db()
        # [FIX] Hitung halaman SEBELUM baris dihapus untuk menentukan fallback
        cur_page = await get_current_page(user_id, line_idx)
        
        await db.db["subtitle_temp"].delete_one({"user_id": user_id, "index": line_idx})
        await call.answer("🗑️ Baris dihapus!")
        
        total_lines = await get_total_sub_lines(user_id)
        total_pages = (total_lines // 5) + (1 if total_lines % 5 > 0 else 0)
        
        # [FIX] Jika halaman terakhir kosong karena baris dihapus, mundur 1 halaman
        if cur_page > total_pages and total_pages > 0:
            cur_page = total_pages
        elif total_pages == 0:
            cur_page = 1
            
        lines = await get_subtitle_page(user_id, page=cur_page, limit=5)
        target_lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        
        text = f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total_lines} Baris</code>\n\n<i>Pilih baris:</i>"
        try: await call.message.edit_text(text, reply_markup=get_editor_kb(lines, cur_page, total_pages, user_id, target_lang), parse_mode="HTML")
        except TelegramBadRequest: pass
        
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

@router.callback_query(F.data.startswith("sub_cancel_"))
async def handle_cancel(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        await clear_subtitle_temp(user_id)
        await call.message.edit_text("❌ <b>Workspace Ditutup.</b> Semua data proyek aktif di memori dibersihkan.", parse_mode="HTML")
        await call.answer("Berhasil ditutup.")
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)
