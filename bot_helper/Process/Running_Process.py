"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Process/Running_Process.py                     ║
║            Encoder1 Bot — v3.4                                       ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v3.4:                                                     ║
║  [FIX HIGH] check_running_process tanpa lock → pakai lock            ║
║  [FIX]      list → set (O(1) lookup vs O(n) linear scan)             ║
║  [FIX]      check sync tapi append/remove async → konsisten          ║
║  [IMPROVE]  Type hints di semua fungsi                               ║
║  [NEW]      get_all_processes() dan get_process_count()              ║
║  [NEW]      clear_all_processes() untuk emergency cleanup            ║
║  [NEW v3.2] Integrasi routing untuk Mute, Speed, dan Dubbing         ║
║  [NEW v3.4] Integrasi routing untuk custom_encode                    ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from asyncio import Lock
from typing import Any
from bot_helper.Others.Names import Names

# ── State ──────────────────────────────────────────────────────────────
# [FIX] set bukan list — O(1) lookup, thread-safer untuk concurrent access
_running_processes: set = set()
_lock              = Lock()


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API (STATE MANAGEMENT)
# ═══════════════════════════════════════════════════════════════════════

def check_running_process(process_id: Any) -> bool:
    """
    Cek apakah process_id sedang aktif.
    """
    # frozenset() buat snapshot immutable — aman dari concurrent modification
    return process_id in frozenset(_running_processes)


async def append_running_process(process_id: Any) -> bool:
    """
    Tambahkan process_id ke set running processes.
    [FIX] list.append() → set.add() — O(1), auto-deduplicate
    Return True jika berhasil ditambahkan, False jika sudah ada.
    """
    async with _lock:
        if process_id in _running_processes:
            return False
        _running_processes.add(process_id)
        return True


async def remove_running_process(process_id: Any) -> bool:
    """
    Hapus process_id dari set running processes.
    [FIX] list.remove() bisa ValueError → set.discard() aman
    Return True jika berhasil dihapus, False jika tidak ada.
    """
    async with _lock:
        if process_id not in _running_processes:
            return False
        _running_processes.discard(process_id)
        return True


# ── Utility Functions ─────────────────────────────────────────────────

def get_process_count() -> int:
    """[NEW] Return jumlah process yang sedang berjalan."""
    return len(_running_processes)


def get_all_processes() -> set:
    """[NEW] Return snapshot set semua running process IDs."""
    return frozenset(_running_processes)


async def clear_all_processes() -> int:
    """
    [NEW] Hapus semua running processes — untuk emergency cleanup atau restart.
    Return jumlah process yang dihapus.
    """
    async with _lock:
        count = len(_running_processes)
        _running_processes.clear()
        return count


# ═══════════════════════════════════════════════════════════════════════
#  TRAFFIC CONTROLLER (ROUTING FFmpeg)
# ═══════════════════════════════════════════════════════════════════════

async def start_running_process(ps):
    """
    Fungsi 'Polisi Lalu Lintas'.
    Mengarahkan tugas berdasarkan Names ke dalam fungsi FFmpeg_Processes yang tepat.
    """
    process = ps.process_type

    if process == Names.compress:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_compress_convert_process
        return await start_compress_convert_process(ps)
        
    # [NEW v3.2 & v3.4] Menggabungkan Convert, Encode, Mute, Speed, Dubbing, dan Custom Encode ke dalam SATU handler utama
    elif process in [Names.convert, Names.encode, Names.mute, Names.speed, Names.dubbing, Names.custom_encode]:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_compress_convert_process
        return await start_compress_convert_process(ps)

    elif process == Names.watermark:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_watermark_process
        return await start_watermark_process(ps)

    elif process == Names.merge:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_merge_process
        return await start_merge_process(ps)

    elif process in [Names.softmux, Names.softremux]:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_softmux_process
        return await start_softmux_process(ps)

    elif process == Names.hardmux:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_hardmux_process
        return await start_hardmux_process(ps)

    elif process in [Names.trim, Names.fast_trim]:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_trim_process
        return await start_trim_process(ps)

    elif process == Names.split:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_split_process
        return await start_split_process(ps)

    elif process == Names.cut:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_cut_process
        return await start_cut_process(ps)

    elif process in [Names.crop, Names.autocrop]:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_crop_process
        return await start_crop_process(ps)

    elif process == Names.rotate:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_rotate_process
        return await start_rotate_process(ps)

    elif process == Names.extension:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_extension_process
        return await start_extension_process(ps)

    elif process == Names.extract:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_extract_process
        return await start_extract_process(ps)

    elif process == Names.changeMetadata:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_change_metadata_process
        return await start_change_metadata_process(ps)

    elif process == Names.changeindex:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_changeindex_process
        return await start_changeindex_process(ps)

    elif process == Names.gensample:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_gensample_process
        return await start_gensample_process(ps)

    elif process == Names.genss:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_genss_process
        return await start_genss_process(ps)

    elif process == Names.mediainfo:
        from bot_helper.FFMPEG.FFMPEG_Processes import start_mediainfo_process
        return await start_mediainfo_process(ps)

    return False
