"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Database/User_Data.py — v4.3                   ║
║            Encoder1 Bot — PAY-AS-YOU-GO EDITION                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v4.3:                                                     ║
║  [NEW]  Migrasi dari sistem 'VIP Expiry Date' menjadi 'Sistem Poin'. ║
║  [NEW]  Menambahkan 'balance_points' (Saldo Poin) ke default user.   ║
║  [NEW]  Fungsi get_user_balance, add_user_balance, deduct_user_balance ║
║  [FIX]  Menghapus key usang (premium_expiry_date, total_vip_duration)║
║         agar database lebih bersih.                                  ║
║  [FIX]  Import List, Dict, Optional untuk Python 3.11 Typing.        ║
║  [FIX]  Thread-safe write operations dengan _DATA_LOCK               ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
import copy
import json
from typing import Any, List, Dict, Optional

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Database.DB_Handler import get_db, _deserialize, _serialize
from config.config import Config

LOGGER     = Config.LOGGER
TASK_LIMIT = Config.RUNNING_TASK_LIMIT

# ── Global DATA (in-memory cache) ─────────────────────────────────────
DATA: dict = Config.DATA

# Lock untuk semua write operations ke DATA
# Cegah race condition saat dua task modify DATA[user_id] bersamaan
_DATA_LOCK = asyncio.Lock()

# Flag untuk block request saat reset berlangsung
_RESETTING = False


# ═══════════════════════════════════════════════════════════════════════
#  TASK LIMIT
# ═══════════════════════════════════════════════════════════════════════

def get_task_limit() -> int:
    return TASK_LIMIT

def change_task_limit(new_limit: int) -> None:
    global TASK_LIMIT
    TASK_LIMIT = new_limit


# ═══════════════════════════════════════════════════════════════════════
#  DB SAVE HELPER
# ═══════════════════════════════════════════════════════════════════════

async def _save_to_db(data_to_save: dict) -> bool:
    if not Config.SAVE_TO_DATABASE:
        return True
    db = get_db()
    if db is None:
        LOGGER.warning("⚠️ DB tidak tersedia untuk save")
        return False
    try:
        return await db.save_data(json.dumps(data_to_save, ensure_ascii=False, default=str))
    except Exception as e:
        LOGGER.error(f"❌ _save_to_db error: {e}", exc_info=True)
        return False


# ═══════════════════════════════════════════════════════════════════════
#  DEFAULT USER DATA STRUCTURE
# ═══════════════════════════════════════════════════════════════════════

def _get_default_user_data() -> dict:
    """Return struktur data default untuk user baru."""
    default_settings = {
        "video": {
            "enabled": True, "encoder": "libx264", "preset": "fast", "crf": 23,
            "sync": False, "map": True, "copy_sub": True, "use_queue_size": False,
            "queue_size": 9999, "extension": "mp4", "tune": "None", "cabac": "On",
            "fast_start": "Yes", "bit_depth": "8-bit", "pixel_format": "yuv420p",
            "resolution": "Auto",
        },
        "audio": {
            "enabled": False, "codec": "aac", "codec_profile": "lc", "bitrate": "128k",
            "channels": "stereo", "samplerate": "48000", "normalization": "none",
            "filter": "none", "downmix": "none",
        },
        "watermark": {
            "enabled": False, "type": "image",
            "image": {
                "position": "top_left", "size": "15",
                "duration": {"mode": "full", "from": "00:00:10", "to": "00:00:20", "interval": 60},
            },
            "text": {
                "content": "Watermark Text", "font_size": "24", "font_color": "white",
                "position": "bottom_right",
                "duration": {"mode": "full", "from": "00:00:10", "to": "00:00:20", "interval": 60},
            },
        },
        "ai_subtitle": {
            "model": "base",       
            "source_lang": "auto", 
            "target_lang": "id",   
            "engine": "Whisper-AI"
        },
        "mux":      {"sub_codec": "copy"},
        "merge":    {"map": True, "fix_blank": False},
        "convert":  {"convert_list": [720, 480]},
        "metadata": {
            "enabled": False, "mode": "preset",
            "preset": {
                "title": "", "author": "", "year": "", "comment": "", "genre": "Encoded",
            },
            "custom": "",
        },
        "select_stream": False, "stream": "ENG",
        "split_video": False, "split": "2GB",
        "upload_tg": True, "rclone": False, "rclone_config_link": False, "drive_name": False,
        "custom_thumbnail": False, "custom_name": False,
        "detailed_messages": True, "show_stats": True, "show_botuptime": True,
        "update_time": 7, "ffmpeg_log": True, "ffmpeg_size": True,
        "ffmpeg_ptime": True, "auto_drive": False, "show_time": True,
        "gen_ss": False, "ss_no": 5, "gen_sample": False,
        "tgdownload": "Pyrogram", "tgupload": "Pyrogram",
        "multi_tasks": False, "upload_all": True, "custom_metadata": False,
        
        # [NEW v4.3] Sistem Dompet Saldo (Point System)
        "balance_points": 0,
    }

    return {
        "active_profile": "Default",
        "profiles": {
            "Default": copy.deepcopy(default_settings),
        },
        **copy.deepcopy(default_settings),
    }

def get_active_settings(user_id: int) -> dict:
    user_data      = DATA.get(user_id, {})
    active_profile = user_data.get("active_profile", "Default")
    profiles       = user_data.get("profiles", {})
    return profiles.get(active_profile, user_data)


# ═══════════════════════════════════════════════════════════════════════
#  SISTEM SALDO POIN (PAY-AS-YOU-GO)
# ═══════════════════════════════════════════════════════════════════════

def get_user_balance(user_id: int) -> int:
    """Mengambil saldo poin user saat ini dari memori (Sangat Cepat)."""
    return DATA.get(user_id, {}).get("balance_points", 0)

async def add_user_balance(user_id: int, amount: int, dbsave: bool = True) -> bool:
    """Menambah saldo poin user (Untuk verifikasi top-up)."""
    if user_id not in DATA:
        await new_user(user_id, dbsave)
    
    async with _DATA_LOCK:
        current = DATA[user_id].get("balance_points", 0)
        DATA[user_id]["balance_points"] = current + amount
    
    if dbsave:
        return await _save_to_db({user_id: DATA[user_id]})
    return True

async def deduct_user_balance(user_id: int, amount: int, dbsave: bool = True) -> bool:
    """
    Memotong saldo poin user.
    Return False jika saldo tidak cukup (Aman dari minus).
    """
    if user_id not in DATA:
        await new_user(user_id, dbsave)
        
    async with _DATA_LOCK:
        current = DATA[user_id].get("balance_points", 0)
        if current < amount:
            return False # Saldo kurang!
        DATA[user_id]["balance_points"] = current - amount
        
    if dbsave:
        return await _save_to_db({user_id: DATA[user_id]})
    return True


# ═══════════════════════════════════════════════════════════════════════
#  GET DATA & USER MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

def get_data() -> dict:
    return DATA

async def get_fresh_user_data(user_id: int) -> dict:
    if not Config.SAVE_TO_DATABASE:
        return DATA.get(user_id, {})

    db = get_db()
    if db is None:
        return DATA.get(user_id, {})

    try:
        fresh_data_str = await db.get_data(Config.SAVE_ID, Config.COLLECTION_NAME)
        if not fresh_data_str:
            return DATA.get(user_id, {})

        fresh_data = _deserialize(fresh_data_str)

        async with _DATA_LOCK:
            for key, val in fresh_data.items():
                if key not in DATA:
                    DATA[key] = val

        return fresh_data.get(user_id, DATA.get(user_id, {}))

    except Exception as e:
        LOGGER.error(f"❌ get_fresh_user_data error untuk user {user_id}: {e}", exc_info=True)
        return DATA.get(user_id, {})


async def new_user(user_id: int, dbsave: bool) -> bool:
    async with _DATA_LOCK:
        DATA[user_id] = _get_default_user_data()

    LOGGER.info(f"✅ User baru dibuat: {user_id}")

    if dbsave:
        return await _save_to_db({user_id: DATA[user_id]})
    return True


async def ensure_user_data_structure(user_id: int) -> None:
    if user_id not in DATA:
        await new_user(user_id, Config.SAVE_TO_DATABASE)
        return

    default_data = _get_default_user_data()
    user_data    = DATA[user_id]
    changes      = []

    # [FIX v4.3] Tambahkan premium_expiry_date dan total_vip_duration ke daftar hapus
    obsolete_keys = ["softmux", "softremux", "is_premium", "premium_expiry_date", "total_vip_duration"]

    async with _DATA_LOCK:
        for key in obsolete_keys:
            if key in user_data:
                del user_data[key]
                changes.append(f"DELETE {key}")

        for key, default_val in default_data.items():
            if key not in user_data:
                user_data[key] = copy.deepcopy(default_val)
                changes.append(f"ADD {key}")

            elif isinstance(default_val, dict):
                if not isinstance(user_data.get(key), dict):
                    user_data[key] = copy.deepcopy(default_val)
                    changes.append(f"FIX {key} (bukan dict)")
                else:
                    for sub_key, sub_default in default_val.items():
                        if sub_key not in user_data[key]:
                            user_data[key][sub_key] = copy.deepcopy(sub_default)
                            changes.append(f"ADD {key}.{sub_key}")
                        
                        elif key == "watermark" and isinstance(sub_default, dict):
                            if not isinstance(user_data[key].get(sub_key), dict):
                                user_data[key][sub_key] = copy.deepcopy(sub_default)
                                changes.append(f"FIX {key}.{sub_key}")
                            else:
                                for deep_key, deep_default in sub_default.items():
                                    if deep_key not in user_data[key][sub_key]:
                                        user_data[key][sub_key][deep_key] = copy.deepcopy(deep_default)
                                        changes.append(f"ADD {key}.{sub_key}.{deep_key}")

    if changes:
        LOGGER.info(
            f"🔧 User {user_id} struktur diupdate: "
            f"{len(changes)} perubahan — {', '.join(changes[:5])}"
            f"{'...' if len(changes) > 5 else ''}"
        )
        if Config.SAVE_TO_DATABASE:
            await _save_to_db({user_id: DATA[user_id]})


# ═══════════════════════════════════════════════════════════════════════
#  SAVE OPTIONS & CONFIG
# ═══════════════════════════════════════════════════════════════════════

async def saveoptions(user_id: int, dname: str, value: Any, dbsave: bool) -> bool:
    try:
        if user_id not in DATA:
            await new_user(user_id, dbsave)

        async with _DATA_LOCK:
            DATA[user_id][dname] = value

        if dbsave:
            return await _save_to_db({user_id: DATA[user_id]})
        return True

    except Exception as e:
        LOGGER.error(f"❌ saveoptions error (user={user_id}, key={dname}): {e}", exc_info=True)
        return False


async def saveconfig(user_id: int, dname: str, pos: str, value: Any, dbsave: bool) -> bool:
    try:
        if user_id not in DATA:
            await new_user(user_id, dbsave)

        async with _DATA_LOCK:
            if dname not in DATA[user_id]:
                DATA[user_id][dname] = {}
            DATA[user_id][dname][pos] = value

        if dbsave:
            return await _save_to_db({user_id: DATA[user_id]})
        return True

    except Exception as e:
        LOGGER.error(f"❌ saveconfig error (user={user_id}, {dname}.{pos}): {e}", exc_info=True)
        return False


# ═══════════════════════════════════════════════════════════════════════
#  RESET DATABASE
# ═══════════════════════════════════════════════════════════════════════

async def resetdatabase(dbsave: bool) -> bool:
    global _RESETTING
    if _RESETTING:
        LOGGER.warning("⚠️ resetdatabase dipanggil saat reset sedang berlangsung")
        return False

    try:
        _RESETTING = True

        async with _DATA_LOCK:
            global_keys = ["restart", "claimed_order_ids"]
            global_data = {k: DATA[k] for k in global_keys if k in DATA}

            user_ids = [
                uid for uid in list(DATA.keys())
                if uid not in global_keys
            ]

            DATA.clear()
            DATA.update(global_data)

        for uid in user_ids:
            async with _DATA_LOCK:
                DATA[uid] = _get_default_user_data()

        if dbsave:
            await _save_to_db(DATA)

        LOGGER.info(f"✅ Database reset selesai — {len(user_ids)} user direset")
        return True

    except Exception as e:
        LOGGER.error(f"❌ resetdatabase error: {e}", exc_info=True)
        return False

    finally:
        _RESETTING = False


# ═══════════════════════════════════════════════════════════════════════
#  RESTART DATA
# ═══════════════════════════════════════════════════════════════════════

async def save_restart(chat_id: int, msg_id: int) -> bool:
    try:
        async with _DATA_LOCK:
            if "restart" not in DATA:
                DATA["restart"] = []
            DATA["restart"].append([chat_id, msg_id])

        if Config.SAVE_TO_DATABASE:
            return await _save_to_db({"restart": DATA["restart"]})
        return True

    except Exception as e:
        LOGGER.error(f"❌ save_restart error: {e}", exc_info=True)
        return False


async def clear_restart() -> bool:
    try:
        async with _DATA_LOCK:
            if "restart" in DATA:
                DATA["restart"] = []

        if Config.SAVE_TO_DATABASE:
            return await _save_to_db({"restart": []})
        return True

    except Exception as e:
        LOGGER.error(f"❌ clear_restart error: {e}", exc_info=True)
        return False


# ═══════════════════════════════════════════════════════════════════════
#  UTILITY
# ═══════════════════════════════════════════════════════════════════════

def is_resetting() -> bool:
    return _RESETTING


async def sync_user_to_db(user_id: int) -> bool:
    if user_id not in DATA:
        return False
    return await _save_to_db({user_id: DATA[user_id]})


async def get_all_user_ids() -> list[int]:
    exclude = {"restart", "claimed_order_ids"}
    return [uid for uid in DATA.keys() if uid not in exclude and isinstance(uid, int)]


# ═══════════════════════════════════════════════════════════════════════
#  SUBTITLE EDITOR HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def get_subtitle_page(user_id: int, page: int, limit: int = 5) -> List[Dict]:
    db = get_db()
    if db is None: return []
    
    skip = (page - 1) * limit
    try:
        cursor = db.db["subtitle_temp"].find({"user_id": user_id}).sort("index", 1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception as e:
        LOGGER.error(f"❌ Error get_subtitle_page: {e}")
        return []

async def get_total_sub_lines(user_id: int) -> int:
    db = get_db()
    if db is None: return 0
    try:
        return await db.db["subtitle_temp"].count_documents({"user_id": user_id})
    except Exception as e:
        LOGGER.error(f"❌ Error get_total_sub_lines: {e}")
        return 0

async def get_single_sub_line(user_id: int, index: int) -> Optional[Dict]:
    db = get_db()
    if db is None: return None
    try:
        return await db.db["subtitle_temp"].find_one({"user_id": user_id, "index": index})
    except Exception as e:
        LOGGER.error(f"❌ Error get_single_sub_line: {e}")
        return None

async def clear_subtitle_temp(user_id: int) -> bool:
    db = get_db()
    if db is None: return False
    try:
        await db.db["subtitle_temp"].delete_many({"user_id": user_id})
        return True
    except Exception as e:
        LOGGER.error(f"❌ Error clear_subtitle_temp: {e}")
        return False
