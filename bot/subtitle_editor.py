"""
╔══════════════════════════════════════════════════════════════════════╗
║                 bot/subtitle_editor.py — v2.0 (WORKSPACE)            ║
║       Subtitle Editor: Save, Load, Edit, & Trans (Studio Khoirul)    ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v2.0:                                                     ║
║  [NEW] Sistem Manajemen Proyek (Save, Load, Delete Session).         ║
║  [NEW] Menu Workspace terbuka jika /subedit dipanggil tanpa file.    ║
║  [UX]  Kombinasi cerdas InlineKeyboard (Menu) & ReplyKeyboard (Input)║
║  [FIX] Database fully integrated dengan MongoDB subtitle_projects.   ║
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

# ═══════════════════════════════════════════════════════════════════════
#  UI GENERATORS (INLINE KEYBOARDS)
# ═══════════════════════════════════════════════════════════════════════

async def get_workspace_kb(user_id: int):
    """Menu Utama Workspace (Tanpa File)"""
    db = get_db()
    kb = []
    
    # Cek apakah ada proyek yang sedang aktif di memory (temp)
    active_count = await db.db["subtitle_temp"].count_documents({"user_id": user_id})
    if active_count > 0:
        kb.append([InlineKeyboardButton(text=f"▶️ Lanjutkan Proyek Aktif ({active_count} Baris)", callback_data=f"sub_pg_{user_id}_1")])
    
    # Cek apakah ada proyek tersimpan
    saved_count = await db.db["subtitle_projects"].count_documents({"user_id": user_id})
    if saved_count > 0:
        kb.append([InlineKeyboardButton(text=f"📂 Buka Proyek Tersimpan ({saved_count})", callback_data=f"sub_proj_{user_id}")])
    
    kb.append([InlineKeyboardButton(text="❌ Tutup Workspace", callback_data=f"sub_cancel_{user_id}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def get_saved_projects_kb(user_id: int):
    """Daftar Proyek yang Tersimpan"""
    db = get_db()
    projects = await db.db["subtitle_projects"].find({"user_id": user_id}).sort("_id", -1).to_list(length=10) # Max 10 proyek
    
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
    """Menu Editor Utama"""
    kb = []
    for line in lines:
        raw_text = str(line.get('text', ''))
        preview = raw_text[:35] + "..." if len(raw_text) > 35 else raw_text
        idx = line.get('index', 0)
        kb.append([
            InlineKeyboardButton(
                text=f"#{idx} | {preview}", 
                callback_data=f"sub_focus_{user_id}_{idx}"
            )
        ])
    
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton(text="⏪ Prev", callback_data=f"sub_pg_{user_id}_{current_page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {current_page}/{total_pages}", callback_data="none"))
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Next ⏩", callback_data=f"sub_pg_{user_id}_{current_page+1}"))
    kb.append(nav_row)
    
    kb.append([
        InlineKeyboardButton(text=f"🌐 Set Bahasa Target: {target_lang.upper()}", callback_data=f"sub_setlang_{user_id}")
    ])
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

def get_focus_kb(user_id, line_index):
    """Menu Fokus Per Baris"""
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
            InlineKeyboardButton(text="↩️ Kembali", callback_data=f"sub_pg_{user_id}_back", style="danger")
        ]
    ])

# ═══════════════════════════════════════════════════════════════════════
#  COMMAND HANDLER
# ═══════════════════════════════════════════════════════════════════════

@router.message(Command(f"subedit{CMD_SUFFIX}"))
async def subedit_start(message: Message):
    user_id = message.from_user.id
    
    # JIKA TIDAK ADA FILE -> BUKA WORKSPACE
    if not message.reply_to_message or not message.reply_to_message.document:
        kb = await get_workspace_kb(user_id)
        text = (
            "<b>🗂️ SUBTITLE WORKSPACE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Selamat datang di Manajer Proyek Subtitle.\n"
            "<i>Balas sebuah file <code>.srt</code> dengan /subedit untuk memulai proyek baru, atau pilih opsi di bawah ini:</i>"
        )
        return await message.answer(text, reply_markup=kb, parse_mode="HTML")

    # JIKA ADA FILE -> PARSE & BUKA EDITOR BARU
    file_name = message.reply_to_message.document.file_name
    if not file_name.lower().endswith('.srt'):
        return await message.reply("❌ **Gagal:** Hanya mendukung format `.srt` untuk saat ini.")

    status_msg = await message.reply("⏳ 📝 **Menganalisis Subtitle untuk Proyek Baru...**")
    
    try:
        os.makedirs("./temp", exist_ok=True)
        srt_path = f"./temp/sub_{user_id}.srt"
        
        await message.bot.download(message.reply_to_message.document, destination=srt_path)
        
        # Parse data baru ke DB
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
        await status_msg.edit_text(f"❌ **Error:** {e}")

# ═══════════════════════════════════════════════════════════════════════
#  WORKSPACE HANDLERS (SAVE, LOAD, DELETE, LIST)
# ═══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("sub_main_"))
async def handle_workspace_main(call: CallbackQuery):
    try:
        user_id = int(call.data.split("_")[2])
        if call.from_user.id != user_id: return await call.answer("Bukan milikmu!", show_alert=True)
        
        kb = await get_workspace_kb(user_id)
        text = (
            "<b>🗂️ SUBTITLE WORKSPACE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Selamat datang di Manajer Proyek Subtitle.\n"
            "<i>Balas sebuah file <code>.srt</code> dengan /subedit untuk memulai proyek baru, atau pilih opsi di bawah:</i>"
        )
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
        prompt = await call.message.answer(
            "💾 <b>SIMPAN PROYEK</b>\n\nKetik nama untuk proyek ini (Contoh: `Eps 1 Final`):", 
            reply_markup=get_cancel_kb(), parse_mode="HTML"
        )
        
        try: response = await wait_for_message(call.message.chat.id, user_id, 60)
        except asyncio.TimeoutError: response = None
            
        if not response or response.text.lower() == "batal":
            if prompt: await prompt.delete()
            return await call.message.answer("Penyimpanan dibatalkan.", reply_markup=ReplyKeyboardRemove())

        project_name = response.text.strip()
        db = get_db()
        
        # Ambil semua baris dari proyek aktif (temp)
        active_lines = await db.db["subtitle_temp"].find({"user_id": user_id}).to_list(length=None)
        if not active_lines:
            await prompt.delete()
            return await call.message.answer("❌ Proyek kosong, tidak ada yang disimpan.", reply_markup=ReplyKeyboardRemove())

        # Simpan ke koleksi subtitle_projects
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
        LOGGER.error(f"Save Error: {e}", exc_info=True)
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
        
        # Bersihkan workspace saat ini dan masukkan data proyek
        await db.db["subtitle_temp"].delete_many({"user_id": user_id})
        await db.db["subtitle_temp"].insert_many(project["lines"])
        
        # Lempar ke UI Editor Halaman 1
        lines = await get_subtitle_page(user_id, page=1, limit=5)
        total_lines = await get_total_sub_lines(user_id)
        total_pages = (total_lines // 5) + (1 if total_lines % 5 > 0 else 0)
        target_lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        
        text = f"<b>📝 SUBTITLE EDITOR (Proyek: {project.get('project_name')})</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total_lines} Baris</code>\n\n<i>Pilih baris:</i>"
        await call.message.edit_text(text, reply_markup=get_editor_kb(lines, 1, total_pages, user_id, target_lang), parse_mode="HTML")
        
    except Exception as e:
        LOGGER.error(f"Load Error: {e}", exc_info=True)
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
        
        # Refresh daftar proyek
        kb = await get_saved_projects_kb(user_id)
        text = "<b>💾 PROYEK TERSIMPAN</b>\n━━━━━━━━━━━━━━━━━━━━\n<i>Pilih proyek untuk dimuat (Load) atau dihapus:</i>"
        try: await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except TelegramBadRequest: pass
        
    except Exception as e:
        await call.answer(f"⚠️ Error: {str(e)[:40]}", show_alert=True)

# ═══════════════════════════════════════════════════════════════════════
#  EDITOR LOGIC (PAGINATION, EDIT, RESYNC, DLL)
# ═══════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("sub_pg_"))
async def handle_pagination(call: CallbackQuery):
    try:
        parts = call.data.split("_")
        user_id = int(parts[2])
        page = 1 if parts[3] == "back" else int(parts[3])
        
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
        await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx), parse_mode="HTML")
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
        
        line_data = await get_single_sub_line(user_id, line_idx)
        safe_text = html.escape(str(line_data.get('text', '')))
        text = (
            f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n"
            f"⏰ <b>Waktu:</b> <code>{line_data.get('start')} --> {line_data.get('end')}</code>\n"
            f"💬 <b>Teks:</b> <code>{safe_text}</code>\n────────────────────"
        )
        try: await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx), parse_mode="HTML")
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
        
        line_data = await get_single_sub_line(user_id, line_idx)
        safe_text = html.escape(str(line_data.get('text', '')))
        text = (
            f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n"
            f"⏰ <b>Waktu:</b> <code>{line_data.get('start')} --> {line_data.get('end')}</code>\n"
            f"💬 <b>Teks:</b> <code>{safe_text}</code>\n────────────────────"
        )
        await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx), parse_mode="HTML")
        
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
        
        try:
            response = await wait_for_message(call.message.chat.id, user_id, 120)
        except asyncio.TimeoutError:
            response = None
            
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
        
        line_data = await get_single_sub_line(user_id, line_idx)
        safe_text = html.escape(str(line_data.get('text', '')))
        text = (
            f"<b>🛠 EDITING BARIS #{line_idx}</b>\n────────────────────\n"
            f"⏰ <b>Waktu:</b> <code>{line_data.get('start')} --> {line_data.get('end')}</code>\n"
            f"💬 <b>Teks:</b> <code>{safe_text}</code>\n────────────────────"
        )
        try: await call.message.edit_text(text, reply_markup=get_focus_kb(user_id, line_idx), parse_mode="HTML")
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
        await db.db["subtitle_temp"].delete_one({"user_id": user_id, "index": line_idx})
        await call.answer("🗑️ Baris dihapus!")
        
        lines = await get_subtitle_page(user_id, page=1, limit=5)
        total_lines = await get_total_sub_lines(user_id)
        total_pages = (total_lines // 5) + (1 if total_lines % 5 > 0 else 0)
        target_lang = get_active_settings(user_id).get("ai_subtitle", {}).get("target_lang", "id")
        
        text = f"<b>📝 SUBTITLE EDITOR</b>\n━━━━━━━━━━━━━━━━━━━━\n📊 Total: <code>{total_lines} Baris</code>\n\n<i>Pilih baris:</i>"
        try: await call.message.edit_text(text, reply_markup=get_editor_kb(lines, 1, total_pages, user_id, target_lang), parse_mode="HTML")
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
