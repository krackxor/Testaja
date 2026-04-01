"""
╔══════════════════════════════════════════════════════════════════════╗
║           bot_helper/FFMPEG/FFMPEG_ErrorParser.py                    ║
║           Encoder1 Bot — v3.1                                        ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG dari versi lama:                                          ║
║  [FIX]      sync open() → aiofiles (tidak block event loop)         ║
║  [FIX]      Baca head(20)+tail(40) bukan hanya tail(60)             ║
║  [FIX]      except FileNotFoundError → (FileNotFoundError, OSError) ║
║  [FIX]      log_file_path None/empty guard                          ║
║  [IMPROVE]  Pre-compile regex patterns saat module load             ║
║  [IMPROVE]  Return dict {diagnosis, solutions, error_type}          ║
║  [IMPROVE]  LOGGER.info saat error terdeteksi                       ║
║  [IMPROVE]  Type hints lengkap                                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ── Standard Library ──────────────────────────────────────────────────
import re
from typing import TypedDict

# ── Third Party ───────────────────────────────────────────────────────
from aiofiles import open as aio_open

# ── Internal ──────────────────────────────────────────────────────────
from config.config import Config

LOGGER = Config.LOGGER


# ═══════════════════════════════════════════════════════════════════════
#  TYPE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════

class ErrorResult(TypedDict):
    """Return type dari analyze_ffmpeg_error()."""
    error_type:  str         # Kategori error singkat untuk logging
    diagnosis:   str         # Penjelasan penyebab error (Markdown)
    solutions:   list[str]   # List solusi (masing-masing Markdown)
    solutions_text: str      # solutions di-join untuk display langsung


# ═══════════════════════════════════════════════════════════════════════
#  ERROR DEFINITIONS
#  [IMPROVE] Pattern di-compile SEKALI saat module load, bukan setiap call
#  Urutan penting: dari yang paling spesifik ke yang paling umum
# ═══════════════════════════════════════════════════════════════════════

def _build_error_db() -> list[dict]:
    """
    Build error database dengan pre-compiled regex patterns.
    Dipanggil sekali saat module di-import.
    """
    raw_definitions = [

        # ── AUDIO ─────────────────────────────────────────────────────
        {
            "error_type": "audio_profile_mismatch",
            "keywords": [r"Error setting option profile to value", r"aac"],
            "diagnosis": (
                "**Profil Codec Audio Tidak Cocok.**\n"
                "FFmpeg gagal menerapkan profil audio (misalnya `lc`) ke codec `aac`. "
                "Terjadi jika audio sumber sudah punya profil lebih canggih (misalnya `HE-AAC`) "
                "dan dipaksa diubah ke profil lebih dasar."
            ),
            "solutions": [
                "**1. Solusi Terbaik (Cepat & Kualitas Terjaga):**\n"
                "   Salin audio tanpa mengubahnya: `/settings` → `🎧 Audio` → Codec: `copy`.",
                "**2. Solusi Fleksibel (Jika Ingin Re-encode):**\n"
                "   Di menu `🎧 Audio` → **Profil AAC** → `Auto`.",
            ],
        },
        {
            "error_type": "audio_sample_rate",
            "keywords": [r"sample rate.*not supported", r"not supported.*sample rate"],
            "diagnosis": (
                "**Sample Rate Audio Tidak Didukung.**\n"
                "Frekuensi suara (sample rate) file asli tidak kompatibel dengan codec audio yang dipilih."
            ),
            "solutions": [
                "**1. Solusi Terbaik:** `/settings` → `🎧 Audio` → Status: `OFF`.",
                "**2. Solusi Fleksibel:** Di menu `🎧 Audio` → **Sample Rate** → `Auto` atau `48000`.",
            ],
        },
        {
            "error_type": "audio_channel_layout",
            "keywords": [r"channel layout.*not supported"],
            "diagnosis": (
                "**Konfigurasi Channel Audio Tidak Cocok.**\n"
                "Jumlah channel audio (misalnya 7.1 surround) tidak dapat diproses dengan konfigurasi saat ini."
            ),
            "solutions": [
                "**1. Solusi Terbaik:** `/settings` → `🎧 Audio` → Status: `OFF`.",
                "**2. Solusi Fleksibel:** Di menu `🎧 Audio` → **Saluran** → `Auto` atau `stereo`.",
            ],
        },

        # ── VIDEO ─────────────────────────────────────────────────────
        {
            "error_type": "video_pixel_format",
            "keywords": [r"Incompatible pixel format"],
            "diagnosis": (
                "**Format Piksel Video Tidak Cocok.**\n"
                "Format warna video sumber (misalnya 10-bit) tidak kompatibel dengan encoder yang dipilih "
                "(misalnya `libx264` standar yang hanya support 8-bit)."
            ),
            "solutions": [
                "**1. Solusi Kualitas Tertinggi:**\n"
                "   `Pengaturan Video` → `Encoder` → `libx265` (mendukung 10-bit) → `Format Piksel` → `Auto`.",
                "**2. Solusi Kompatibilitas Maksimal:**\n"
                "   `Pengaturan Video` → `Format Piksel` → `yuv420p`.",
            ],
        },
        {
            "error_type": "video_odd_resolution",
            "keywords": [r"height not divisible by 2", r"width not divisible by 2"],
            "diagnosis": (
                "**Resolusi Video Tidak Valid.**\n"
                "Encoder (terutama `libx264`) mengharuskan lebar dan tinggi resolusi berupa angka genap. "
                "Salah satu dimensi saat ini adalah angka ganjil."
            ),
            "solutions": [
                "**1. Solusi Paling Aman:** `Pengaturan Video` → `Resolusi` → `Auto`.",
                "**2. Jika Ingin Custom:** Pastikan kedua angka genap (contoh: `1280x720`, bukan `1281x720`).",
            ],
        },

        # ── FILTER, STREAM, WATERMARK ─────────────────────────────────
        {
            "error_type": "watermark_font_missing",
            "keywords": [r"fontconfig", r"Cannot load font"],
            "diagnosis": (
                "**File Font Watermark Hilang.**\n"
                "Watermark teks aktif, tetapi file font kustom yang diunggah telah terhapus atau tidak bisa diakses."
            ),
            "solutions": [
                "**1. Solusi Cepat:** `Watermark` → `Atur Watermark Teks` → `Hapus Font` (pakai font default).",
                "**2. Solusi Kustom:** Unggah ulang file font (`.ttf` atau `.otf`) di menu yang sama.",
            ],
        },
        {
            "error_type": "watermark_text_error",
            "keywords": [r"Error parsing.*commandline.*option", r"drawtext"],
            "diagnosis": (
                "**Kesalahan pada Teks Watermark.**\n"
                "Ada karakter khusus di teks watermark yang mengacaukan perintah FFmpeg: "
                "tanda kutip (`'`), titik dua (`:`), atau backslash (`\\\\`)."
            ),
            "solutions": [
                "**Solusi:** `Watermark` → `Input Teks` → Tulis ulang tanpa karakter khusus tersebut.",
            ],
        },
        {
            "error_type": "subtitle_codec_container",
            "keywords": [r"Subtitle codec.*not supported", r"mov_text.*not supported"],
            "diagnosis": (
                "**Codec Subtitle Tidak Cocok dengan Kontainer.**\n"
                "Mencoba memasukkan subtitle (`.srt`/`.ass`) ke dalam `.mp4` tanpa konversi. "
                "MP4 memerlukan format subtitle khusus (`mov_text`)."
            ),
            "solutions": [
                "**1. Solusi Otomatis:** `Pengaturan Mux` → `Codec Subtitle` → `mov_text`.",
                "**2. Solusi Alternatif:** `Pengaturan Video` → `Ekstensi` → `MKV` (lebih fleksibel untuk subtitle).",
            ],
        },
        {
            "error_type": "stream_map_error",
            "keywords": [r"Stream map.*does not match", r"Stream #\d+:\d+ does not exist"],
            "diagnosis": (
                "**Pemetaan Stream (Map) Salah.**\n"
                "Anda mencoba memanipulasi stream (misalnya audio ke-3) yang tidak ada di file video asli."
            ),
            "solutions": [
                "**Solusi:** Gunakan `/mediainfo1` untuk melihat daftar stream yang tersedia, "
                "lalu pastikan nomor indeks di `/changeindex1` atau `/changemetadata1` benar.",
            ],
        },

        # ── FILE & SUMBER DAYA ────────────────────────────────────────
        {
            "error_type": "corrupt_file",
            "keywords": [r"Invalid data found when processing input"],
            "diagnosis": (
                "**File Sumber Kemungkinan Rusak (Corrupt).**\n"
                "FFmpeg menemukan data tidak valid di tengah file. File mungkin tidak terdownload sempurna."
            ),
            "solutions": [
                "**Solusi:** Coba putar file asli — jika berhenti/macet di tengah, file memang rusak. "
                "Download ulang dari sumber yang berbeda.",
            ],
        },
        {
            "error_type": "file_not_found",
            "keywords": [r"No such file or directory"],
            "diagnosis": (
                "**File Input Tidak Ditemukan.**\n"
                "File yang seharusnya diproses tidak ada di direktori kerja. "
                "Kemungkinan server restart, pembersihan otomatis, atau error saat download awal."
            ),
            "solutions": [
                "**Solusi:** Jalankan kembali perintah dari awal — biasanya langsung berhasil.",
            ],
        },
        {
            "error_type": "out_of_memory",
            "keywords": [r"Cannot allocate memory", r"Out of memory"],
            "diagnosis": (
                "**Memori Server Penuh!**\n"
                "Proses FFmpeg membutuhkan lebih banyak RAM dari yang tersedia, "
                "terutama saat memproses video 4K atau filter kompleks."
            ),
            "solutions": [
                "**1. Solusi Cepat:**\n"
                "   - Coba saat bot tidak sedang proses banyak tugas lain.\n"
                "   - Turunkan resolusi ke `1080` via `Pengaturan Video` → `Resolusi`.\n"
                "   - Lakukan satu operasi saja (jangan gabung compress + watermark + filter sekaligus).",
                "**2. Hubungi Admin:** Jika sering terjadi, server perlu di-upgrade.",
            ],
        },
        {
            "error_type": "encoder_not_found",
            "keywords": [r"Unknown encoder", r"Encoder.*not found"],
            "diagnosis": (
                "**Encoder Tidak Dikenali.**\n"
                "Codec yang dipilih tidak terinstal di server bot ini."
            ),
            "solutions": [
                "**Solusi:** `Pengaturan Video` atau `Pengaturan Audio` → pilih **Encoder** lain dari daftar.",
            ],
        },
        {
            "error_type": "muxing_queue",
            "keywords": [r"Too many packets buffered", r"muxing queue"],
            "diagnosis": (
                "**Antrian Muxing Penuh.**\n"
                "Terjadi ketidakseimbangan antara stream video dan audio sehingga buffer antrian penuh. "
                "Biasanya terjadi pada file dengan audio delay besar atau frame rate tidak standar."
            ),
            "solutions": [
                "**Solusi:** Tambahkan flag `-max_muxing_queue_size 1024` — "
                "hubungi admin jika perlu mengatur parameter ini secara manual.",
            ],
        },

        # ── UMUM (taruh di akhir — paling broad) ──────────────────────
        {
            "error_type": "invalid_argument",
            "keywords": [r"Invalid argument"],
            "diagnosis": (
                "**Terdapat Pengaturan Tidak Valid.**\n"
                "Ada satu atau lebih parameter yang nilainya tidak masuk akal atau formatnya salah."
            ),
            "solutions": [
                "**Langkah Investigasi:**\n"
                "1. **Metadata Kustom:** Nonaktifkan dulu — jika berhasil, periksa format tulisan.\n"
                "2. **Resolusi Kustom:** Pastikan format `lebarxTinggi` (contoh: `1280x720`).\n"
                "3. **Reset Pengaturan:** Cara tercepat dan paling efektif.",
            ],
        },
        {
            "error_type": "conversion_failed",
            "keywords": [r"Conversion failed!"],
            "diagnosis": (
                "**Konversi Gagal Total.**\n"
                "Error umum — bisa karena keterbatasan memori saat proses video resolusi tinggi "
                "atau kombinasi filter yang sangat kompleks."
            ),
            "solutions": [
                "**1. Reset Pengaturan:** `/settings` → `Profil Pengaturan` → `✨ Reset ke Default`.",
                "**2. Sederhanakan Tugas:** Lakukan satu operasi saja tanpa menggabungkan banyak fitur.",
            ],
        },
    ]

    # Pre-compile semua patterns
    compiled = []
    for defn in raw_definitions:
        compiled.append({
            "error_type": defn["error_type"],
            "patterns":   [re.compile(kw, re.IGNORECASE) for kw in defn["keywords"]],
            "diagnosis":  defn["diagnosis"],
            "solutions":  defn["solutions"],
        })

    return compiled


# Pre-compile saat module di-load — tidak di-compile ulang setiap call
_ERROR_DB: list[dict] = _build_error_db()

# Default response jika tidak ada yang cocok
_DEFAULT_RESULT: ErrorResult = {
    "error_type": "unknown",
    "diagnosis": (
        "**Terjadi Kesalahan Umum FFmpeg.**\n"
        "Proses gagal karena kombinasi pengaturan yang tidak cocok atau masalah tak terduga "
        "pada file sumber yang tidak terdeteksi secara spesifik."
    ),
    "solutions": [
        "**💡 Solusi Paling Efektif (99% Berhasil):**\n"
        "1. Buka `/settings` → `Profil Pengaturan`.\n"
        "2. Tekan `✨ Reset ke Default`.\n"
        "3. Coba jalankan kembali perintah. Pengaturan default hampir selalu berhasil."
    ],
    "solutions_text": (
        "**💡 Solusi Paling Efektif (99% Berhasil):**\n"
        "1. Buka `/settings` → `Profil Pengaturan`.\n"
        "2. Tekan `✨ Reset ke Default`.\n"
        "3. Coba jalankan kembali perintah. Pengaturan default hampir selalu berhasil."
    ),
}


# ═══════════════════════════════════════════════════════════════════════
#  MAIN FUNCTION
# ═══════════════════════════════════════════════════════════════════════

async def analyze_ffmpeg_error(log_file_path: str | None) -> ErrorResult:
    """
    Analisis log FFmpeg dan return diagnosis + solusi.

    [FIX] sync open() → aiofiles (tidak block event loop)
    [FIX] Baca head(20) + tail(40) — cover error di awal DAN akhir log
    [FIX] log_file_path None/empty guard
    [FIX] except lebih lengkap: FileNotFoundError + OSError + PermissionError
    [IMPROVE] Pre-compiled regex (dicompile sekali saat module load)
    [IMPROVE] Return TypedDict dengan solutions sebagai list
    [IMPROVE] LOGGER.info saat error berhasil diidentifikasi

    Args:
        log_file_path: Path ke file log FFmpeg (dari -progress atau FFMPEG_LOG.txt)

    Returns:
        ErrorResult dict dengan keys: error_type, diagnosis, solutions, solutions_text
    """
    # [FIX] Guard: path None atau kosong
    if not log_file_path or not isinstance(log_file_path, str):
        LOGGER.warning("⚠️  analyze_ffmpeg_error dipanggil dengan path kosong/None")
        return _DEFAULT_RESULT

    # [FIX] aiofiles — tidak blocking event loop
    try:
        async with aio_open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = await f.readlines()
    except FileNotFoundError:
        LOGGER.debug(f"Log file tidak ditemukan: {log_file_path}")
        return {
            **_DEFAULT_RESULT,
            "diagnosis": "**File log FFmpeg tidak ditemukan.**\nLog tidak tersedia untuk dianalisis.",
            "solutions_text": _DEFAULT_RESULT["solutions_text"],
        }
    except (OSError, PermissionError) as e:
        LOGGER.warning(f"⚠️  Tidak bisa baca log file {log_file_path}: {e}")
        return _DEFAULT_RESULT

    if not all_lines:
        LOGGER.debug(f"Log file kosong: {log_file_path}")
        return _DEFAULT_RESULT

    # [FIX] Ambil head(20) + tail(40) — bukan hanya tail(60)
    # Error seperti "No such file or directory" muncul di AWAL
    # Error seperti "Conversion failed!" muncul di AKHIR
    head_lines = all_lines[:20]
    tail_lines = all_lines[-40:] if len(all_lines) > 40 else all_lines
    # Gabungkan, hindari duplikat jika file pendek
    if len(all_lines) <= 60:
        log_content = "".join(all_lines)
    else:
        log_content = "".join(head_lines) + "\n...\n" + "".join(tail_lines)

    # [IMPROVE] Match menggunakan pre-compiled patterns
    for error_def in _ERROR_DB:
        patterns = error_def["patterns"]
        # ANY keyword match → identifikasi error ini
        if any(pat.search(log_content) for pat in patterns):
            error_type = error_def["error_type"]
            solutions  = error_def["solutions"]

            # [IMPROVE] Log error yang terdeteksi untuk monitoring
            LOGGER.info(f"🔍 FFmpeg error teridentifikasi: [{error_type}]")

            return {
                "error_type":    error_type,
                "diagnosis":     error_def["diagnosis"],
                "solutions":     solutions,
                "solutions_text": "\n\n".join(solutions),
            }

    # Tidak ada yang cocok
    LOGGER.debug(f"FFmpeg error tidak teridentifikasi spesifik di: {log_file_path}")
    return _DEFAULT_RESULT


# ═══════════════════════════════════════════════════════════════════════
#  BACKWARD COMPATIBILITY WRAPPER
# ═══════════════════════════════════════════════════════════════════════

async def analyze_ffmpeg_error_legacy(log_file_path: str) -> tuple[str, str]:
    """
    Wrapper untuk backward compatibility dengan kode lama yang expect tuple.

    Kode lama:  diagnosis, solutions = await analyze_ffmpeg_error(path)
    Kode baru:  result = await analyze_ffmpeg_error(path)  ← return dict

    Jika ada kode yang belum dimigrasikan, panggil fungsi ini dulu.
    """
    result = await analyze_ffmpeg_error(log_file_path)
    return result["diagnosis"], result["solutions_text"]
