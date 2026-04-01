"""
╔══════════════════════════════════════════════════════════════════════╗
║           bot_helper/Others/Names.py — v3.1                         ║
║                    Konstanta Nama Proses Bot                         ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG:                                                          ║
║  [FIX]  split tidak ada di STATUS dict → ditambahkan                ║
║  [FIX]  '쪼Splitting Video' karakter Korean → emoji ✂️             ║
║  [FIX]  STATUS_* string tanpa emoji → ditambahkan emoji            ║
║  [NEW]  ytupload, autoclip, movierecap (Step 14-16)                ║
║  [NEW]  top, review, short_vid (Step 17 Gameplay.py)               ║
║  [IMPROVE] Indentasi 4-space standard                               ║
╚══════════════════════════════════════════════════════════════════════╝
"""


class Names:
    # ── Proses FFmpeg ─────────────────────────────────────────────────
    compress       = "Compress"
    watermark      = "Watermark"
    merge          = "Merge"
    softmux        = "SoftMux"
    softremux      = "SoftReMux"
    convert        = "Convert"
    hardmux        = "Hardmux"
    trim           = "Trim"
    split          = "Split"
    cut            = "Cut"
    crop           = "Crop"
    autocrop       = "Autocrop"
    rotate         = "Rotate"
    extension      = "Extension"
    extract        = "Extract"
    mediainfo      = "MediaInfo"
    changeMetadata = "ChangeMetadata"
    changeindex    = "ChangeIndex"

    # ── Proses Sistem ─────────────────────────────────────────────────
    pre_download   = "PreDownload"
    gensample      = "VideoSample"
    genss          = "GenSS"
    leech          = "Leech"
    mirror         = "Mirror"

    # ── Engine / Protokol ─────────────────────────────────────────────
    aria           = "Aria"
    ffmpeg         = "FFMPEG"
    telethon       = "Telethon"
    pyrogram       = "Pyrogram"
    rclone         = "Rclone"

    # ── [NEW] Proses Video Production (Step 14-17) ───────────────────
    ytupload       = "YouTubeUpload"   # YTUpload.py
    autoclip       = "AutoClip"        # AutoClip.py
    movierecap     = "MovieRecap"      # MovieRecap.py
    top            = "Top"             # Gameplay.py /top
    review         = "Review"          # Gameplay.py /review
    short_vid      = "Short"           # Gameplay.py /short

    # ── Status Map (process_type → label UI) ─────────────────────────
    # Keys = nilai string dari attribute di atas (bukan nama attribute)
    STATUS = {
        # FFmpeg processes
        compress:       "🏮 Mengompresi",
        watermark:      "🛺 Menambah Watermark",
        merge:          "🍧 Menggabungkan",
        softmux:        "🎮 SoftMux Subtitle",
        softremux:      "🛩 SoftReMux Subtitle",
        convert:        "🚜 Mengonversi Video",
        hardmux:        "🚍 HardMux Subtitle",
        trim:           "✂️ Memotong Video",
        split:          "✂️ Memisah Video",       # [FIX] ditambahkan — sebelumnya tidak ada
        cut:            "🔪 Memotong Segmen",
        crop:           "✂️ Crop Video",
        autocrop:       "✨ Autocrop Video",
        rotate:         "🔄 Memutar Video",
        extension:      "🔀 Ganti Container",
        extract:        "📤 Ekstrak Stream",
        mediainfo:      "🔍 Media Info",
        changeMetadata: "🪀 Ubah Metadata",
        changeindex:    "🎨 Ubah Index",
        # [NEW] Video production processes
        "YouTubeUpload": "⬆️ Mengunggah YouTube",
        "AutoClip":      "✂️ Memotong Clip",
        "MovieRecap":    "🎬 Merangkum Film",
        "Top":           "🕹 Merender TOP",
        "Review":        "🎬 Merender Review",
        "Short":         "📱 Merender Short",
    }

    # ── Daftar proses yang pakai FFmpeg ──────────────────────────────
    FFMPEG_PROCESSES = [
        compress,
        watermark,
        merge,
        softmux,
        softremux,
        convert,
        hardmux,
        trim,
        split,
        cut,
        crop,
        autocrop,
        rotate,
        extension,
        extract,
        changeMetadata,
        changeindex,
    ]

    # ── Status Labels (dipakai Aria2, Process_Status, UI) ────────────
    # [FIX] Ditambahkan emoji agar konsisten dengan STATUS dict
    STATUS_UPLOADING   = "🔼 Mengunggah"
    STATUS_CLONING     = "🧬 Mengkloning"
    STATUS_DOWNLOADING = "🔽 Mengunduh"
    STATUS_COPYING     = "🔁 Menyalin"
    STATUS_ARCHIVING   = "🔐 Mengarsip"
    STATUS_EXTRACTING  = "📂 Mengekstrak"
    STATUS_SPLITTING   = "✂️ Memisah"
    STATUS_SYNCING     = "🔄 Menyinkronkan"
    STATUS_WAITING     = "⏳ Antrian"      # [FIX] sebelumnya "Queue" tanpa emoji
    STATUS_PAUSED      = "⏸ Dijeda"       # [FIX] sebelumnya "Pause" tanpa emoji
    STATUS_CHECKING    = "🔍 Memeriksa"   # [FIX] sebelumnya "CheckUp" tanpa emoji
    STATUS_SEEDING     = "🌱 Seeding"     # [FIX] sebelumnya "Seed" tanpa emoji
