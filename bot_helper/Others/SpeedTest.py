"""
╔══════════════════════════════════════════════════════════════════════╗
║           bot_helper/Others/SpeedTest.py — v3.1                     ║
║                    Internet Speed Test Utility                       ║
╠══════════════════════════════════════════════════════════════════════╣
║  FIXES dari versi lama:                                              ║
║  [FIX HIGH]  Speedtest sync blocking → asyncio.to_thread()          ║
║  [FIX HIGH]  share() sync HTTP request → asyncio.to_thread()        ║
║  [FIX]       Optional import — tidak crash jika tidak terinstall    ║
║  [FIX]       result['share'] KeyError → .get() dengan fallback      ║
║  [FIX]       Tidak ada error handling → try/except informatif       ║
║  [FIX]       speed_convert() KeyError unbounded → batas units       ║
║  [FIX]       return list → return dict                              ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import asyncio
from typing import Optional

# ── Internal ──────────────────────────────────────────────────────────
from bot_helper.Others.Helper_Functions import get_human_size, get_time_from_string
from config.config import Config

LOGGER = Config.LOGGER

# ── Optional import — tidak crash jika speedtest-cli belum diinstall ─
try:
    from speedtest import Speedtest
    SPEEDTEST_ENABLED = True
except ImportError:
    SPEEDTEST_ENABLED = False
    LOGGER.warning("⚠️  speedtest-cli belum diinstall. Jalankan: pip install speedtest-cli")


def speed_convert(size: float, byte: bool = True) -> str:
    """
    Konversi size (bits atau bytes per detik) ke string human-readable.

    [FIX] Upper bound pada units dict — tidak KeyError jika size sangat besar.

    Args:
        size: Ukuran dalam bits/s (jika byte=False) atau bytes/s (jika byte=True)
        byte: True = input dalam bits/s, konversi ke bytes/s dulu
    """
    if not byte:
        size = size / 8   # bits → bytes

    power = 1024.0
    units = {0: "B/s", 1: "KB/s", 2: "MB/s", 3: "GB/s", 4: "TB/s"}
    idx   = 0

    # [FIX] Batas idx < len(units)-1 — tidak keluar dari dict
    while size > power and idx < len(units) - 1:
        size /= power
        idx  += 1

    return f"{round(size, 2)} {units[idx]}"


def _run_speedtest() -> dict:
    """
    Jalankan speedtest secara synchronous (dipanggil via asyncio.to_thread).
    Dipisah agar mudah di-test dan tidak ada async di dalamnya.

    Returns:
        dict hasil speedtest

    Raises:
        RuntimeError jika speedtest-cli tidak terinstall
        Exception jika test gagal
    """
    if not SPEEDTEST_ENABLED:
        raise RuntimeError(
            "speedtest-cli belum diinstall.\n"
            "Jalankan: `pip install speedtest-cli`"
        )

    test = Speedtest()
    test.get_best_server()
    test.download()
    test.upload()

    # share() melakukan HTTP request ke speedtest.net — bisa gagal
    try:
        test.results.share()
    except Exception as e:
        LOGGER.warning(f"⚠️  speedtest share() gagal (lanjut tanpa image): {e}")

    return test.results.dict()


async def speedtest() -> dict:
    """
    Jalankan internet speed test dan return hasil.

    [FIX HIGH] Semua operasi Speedtest dijalankan via asyncio.to_thread()
               — tidak block event loop selama 30-60 detik.
    [FIX]      try/except dengan pesan error yang informatif.
    [FIX]      Return dict bukan list — lebih jelas untuk caller.

    Returns:
        dict dengan keys:
            'image_url' : str   — URL gambar hasil dari speedtest.net (bisa '')
            'text'      : str   — Formatted HTML string untuk Telegram
            'success'   : bool  — True jika test berhasil
            'error'     : str   — Pesan error jika gagal ('' jika sukses)
    """
    if not SPEEDTEST_ENABLED:
        return {
            "image_url": "",
            "text":      "❌ speedtest-cli belum diinstall.\nJalankan: `pip install speedtest-cli`",
            "success":   False,
            "error":     "speedtest-cli not installed",
        }

    try:
        # [FIX HIGH] asyncio.to_thread() — tidak block event loop
        result = await asyncio.to_thread(_run_speedtest)

    except Exception as e:
        LOGGER.error(f"❌ Speedtest gagal: {e}", exc_info=True)
        return {
            "image_url": "",
            "text":      f"❌ Speedtest gagal:\n`{str(e)[:300]}`",
            "success":   False,
            "error":     str(e),
        }

    # [FIX] .get() dengan fallback — tidak KeyError jika share() gagal
    image_url  = result.get("share") or ""
    upload_spd = speed_convert(result.get("upload", 0), byte=False)
    down_spd   = speed_convert(result.get("download", 0), byte=False)
    ping_ms    = result.get("ping", "N/A")
    timestamp  = get_time_from_string(result.get("timestamp", ""))
    bytes_sent = int(result.get("bytes_sent") or 0)
    bytes_recv = int(result.get("bytes_received") or 0)

    server = result.get("server") or {}
    client = result.get("client") or {}

    text = (
        f"╭─《 🚀 SPEEDTEST INFO 》\n"
        f"├ <b>Upload:</b> <code>{upload_spd}</code>\n"
        f"├ <b>Download:</b> <code>{down_spd}</code>\n"
        f"├ <b>Ping:</b> <code>{ping_ms} ms</code>\n"
        f"├ <b>Time:</b> <code>{timestamp}</code>\n"
        f"├ <b>Data Sent:</b> <code>{get_human_size(bytes_sent)}</code>\n"
        f"╰ <b>Data Received:</b> <code>{get_human_size(bytes_recv)}</code>\n"
        f"╭─《 🌐 SPEEDTEST SERVER 》\n"
        f"├ <b>Name:</b> <code>{server.get('name', 'N/A')}</code>\n"
        f"├ <b>Country:</b> <code>{server.get('country', 'N/A')}, {server.get('cc', '')}</code>\n"
        f"├ <b>Sponsor:</b> <code>{server.get('sponsor', 'N/A')}</code>\n"
        f"├ <b>Latency:</b> <code>{server.get('latency', 'N/A')}</code>\n"
        f"├ <b>Latitude:</b> <code>{server.get('lat', 'N/A')}</code>\n"
        f"╰ <b>Longitude:</b> <code>{server.get('lon', 'N/A')}</code>\n"
        f"╭─《 👤 CLIENT DETAILS 》\n"
        f"├ <b>IP Address:</b> <code>{client.get('ip', 'N/A')}</code>\n"
        f"├ <b>Latitude:</b> <code>{client.get('lat', 'N/A')}</code>\n"
        f"├ <b>Longitude:</b> <code>{client.get('lon', 'N/A')}</code>\n"
        f"├ <b>Country:</b> <code>{client.get('country', 'N/A')}</code>\n"
        f"├ <b>ISP:</b> <code>{client.get('isp', 'N/A')}</code>\n"
        f"╰ <b>ISP Rating:</b> <code>{client.get('isprating', 'N/A')}</code>"
    )

    # [FIX] Return dict — caller tahu field mana yang dipakai
    return {
        "image_url": image_url,
        "text":      text,
        "success":   True,
        "error":     "",
    }
