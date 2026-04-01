"""
╔══════════════════════════════════════════════════════════════════════╗
║                        start.py — v3.1                              ║
║              Entry Point: Import semua handler modules              ║
╠══════════════════════════════════════════════════════════════════════╣
║  File ini hanya berisi import — semua logic ada di:                 ║
║    bot/shared.py                              ← shared utilities    ║
║    bot/admin_handlers.py                      ← system commands    ║
║    bot/vip_handlers.py                        ← VIP management     ║
║    bot/media_handlers.py                      ← FFmpeg commands    ║
║    bot/advanced_media_handlers.py             ← trim/cut/crop      ║
║    bot/callbacks.py                           ← settings UI        ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Registrasi semua handlers via package import ──────────────────────
# @TELETHON_CLIENT.on() dekorator sudah dieksekusi saat module dimuat.
# Urutan: shared → admin → vip → media → advanced_media → callbacks
from bot import (   # noqa: F401
    admin_handlers,
    vip_handlers,
    media_handlers,
    advanced_media_handlers,
    callbacks,
    Gameplay,
    AutoClip,    
    MovieRecap, 
    YTUpload,
)

# ── Re-export untuk backward compatibility ────────────────────────────
# Kode lain yang import dari start.py langsung masih bisa berjalan.
from bot.shared import (   # noqa: F401
    command,
    user_auth_checker,
    sudo_user_checker_event,
    sudo_user_checker_id,
    owner_checker,
    is_vip_or_admin,
    vip_check,
    safe_reply,
    safe_edit,
    get_mention,
    get_username,
    is_magnet,
    create_direc,
    check_file,
    dw_file_from_url,
    get_link,
    get_custom_name,
    get_url_from_message,
    get_sudo_user_id,
    ask_text,
    ask_text_event,
    ask_text_list,
    ask_media_OR_url,
    ask_url,
    get_thumbnail,
    ask_watermark,
    ask_thumbnail_file,
    build_task,
    submit_task,
    update_status_message,
    CMD_SUFFIX,
    LOGGER,
    SAVE_TO_DATABASE,
    TELETHON_CLIENT,
    owner_id,
    sudo_users,
)
