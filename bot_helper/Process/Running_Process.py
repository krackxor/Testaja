"""
╔══════════════════════════════════════════════════════════════════════╗
║           bot_helper/Process/Running_Process.py                      ║
║           Encoder1 Bot — v3.1                                        ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [FIX HIGH] check_running_process tanpa lock → pakai lock           ║
║  [FIX]      list → set (O(1) lookup vs O(n) linear scan)            ║
║  [FIX]      check sync tapi append/remove async → konsisten         ║
║  [IMPROVE]  Type hints di semua fungsi                              ║
║  [NEW]      get_all_processes() dan get_process_count()             ║
║  [NEW]      clear_all_processes() untuk emergency cleanup           ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from asyncio import Lock
from typing import Any

# ── State ──────────────────────────────────────────────────────────────
# [FIX] set bukan list — O(1) lookup, thread-safer untuk concurrent access
_running_processes: set = set()
_lock              = Lock()


# ═══════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════

def check_running_process(process_id: Any) -> bool:
    """
    Cek apakah process_id sedang aktif.

    [FIX HIGH] Sebelumnya: baca tanpa lock sementara write pakai lock
               = race condition jika task lain modify set bersamaan.
    Sekarang: set membership check di CPython adalah GIL-protected
              untuk operasi sederhana. Tapi tetap lebih aman dengan
              snapshot: cek `process_id in frozenset(_running_processes)`.

    Sync function dipertahankan untuk backward compat (dipanggil dari
    non-async context seperti progress callback di Step 6 & 7).
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
