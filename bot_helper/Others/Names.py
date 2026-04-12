"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Others/Names.py — v4.3                         ║
║                    Konstanta Nama Proses Bot                         ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v4.3:                                                     ║
║  [NEW]  Menambahkan label UI untuk fitur Studio Khoirul yang baru    ║
║         (Verdict, TopTier, Archives, Lore, Radar, Patch).            ║
║  [NEW]  subedit (Integrasi Manual Subtitle Editor)                   ║
║  [NEW]  autosub, autotranslate (Whisper AI & Deep Trans)             ║
║  [FIX]  Sinkronisasi label status UI untuk semua fitur baru.         ║
║  [FIX]  Konsistensi string agar dikenali oleh FFMPEG Commands        ║
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
    encode         = "encode"       # Default handler untuk dubbing & hardmux
    custom_encode  = "custom_encode"# Fitur Bebas Encode (Raw FFmpeg Command)
    hardmux        = "Hardmux"
    trim           = "Trim"
    fast_trim      = "fast_trim"    # Cut tanpa re-encode
    split          = "Split"
    cut            = "Cut"
    crop           = "Crop"
    autocrop       = "Autocrop"
    rotate         = "Rotate"
    speed          = "speed"        # Ubah kecepatan video
    mute           = "mute"         # Hapus audio
    dubbing        = "dubbing"      # Ganti audio video
    extension      = "Extension"
    extract        = "Extract"
    mediainfo      = "MediaInfo"
    changeMetadata = "ChangeMetadata"
    changeindex    = "ChangeIndex"

    # ── Proses AI & Subtitle Editor (BARU) ───────────────────────────
    autosub        = "AutoSubtitle"
    autotranslate  = "AutoTranslate"
    subedit        = "SubEdit"       # [NEW] Manual Subtitle Editor

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

    # ── Proses Video Production ──────────────────────────────────────
    ytupload       = "YouTubeUpload" 
    autoclip       = "AutoClip"      
    movierecap     = "MovieRecap"    
    top            = "Top"           
    review         = "Review"        
    short_vid      = "Short"         

    # ── Status Map (process_type → label UI) ─────────────────────────
    STATUS = {
        # FFmpeg processes
        compress:       "🏮 Mengompresi",
        watermark:      "🛺 Menambah Watermark",
        merge:          "🍧 Menggabungkan",
        softmux:        "🎮 SoftMux Subtitle",
        softremux:      "🛩 SoftReMux Subtitle",
        convert:        "🚜 Mengonversi Video",
        encode:         "⚙️ Meng-Encode Video",
        custom_encode:  "🎛️ Custom Encoding",
        hardmux:        "🚍 HardMux Subtitle",
        trim:           "✂️ Memotong Video",
        fast_trim:      "⚡ Memotong Cepat",    
        split:          "✂️ Memisah Video",  
        cut:            "🔪 Memotong Segmen",
        crop:           "✂️ Crop Video",
        autocrop:       "✨ Autocrop Video",
        rotate:         "🔄 Memutar Video",
        speed:          "⚡ Mengubah Kecepatan", 
        mute:           "🔇 Membisukan Video",   
        dubbing:        "🎙 Melakukan Dubbing", 
        extension:      "🔀 Ganti Container",
        extract:        "📤 Ekstrak Stream",
        mediainfo:      "🔍 Media Info",
        changeMetadata: "🪀 Ubah Metadata",
        changeindex:    "🎨 Ubah Index",

        # AI & Editor Processes (NEW)
        autosub:        "🧠 AI Transcribing",
        autotranslate:  "🌐 AI Translating",
        subedit:        "📝 Editing Subtitle", 
        
        # Video production processes
        "YouTubeUpload": "⬆️ Mengunggah YouTube",
        "AutoClip":      "✂️ Memotong Clip",
        "MovieRecap":    "🎬 Merangkum Film",
        "Top":           "🕹 Merender TOP",
        "Review":        "🎬 Merender Review",
        "Short":         "📱 Merender Short",
        
        # Studio Khoirul Produksi Baru (v6.0+)
        "PRODUKSI STUDIO (THE VERDICT)":          "🎬 Merender Verdict",
        "PRODUKSI STUDIO (TOP TIER)":             "🏆 Merender Top Tier",
        "PRODUKSI STUDIO (THE ARCHIVES)":         "📜 Merender Archives",
        "PRODUKSI STUDIO (LORE & CONSPIRACIES)":  "🧠 Merender Lore",
        "PRODUKSI STUDIO (ON THE RADAR)":         "📡 Merender Radar",
        "PRODUKSI STUDIO (THE LATEST PATCH)":     "🗞️ Merender Patch",
    }

    # ── Daftar proses yang pakai FFmpeg ──────────────────────────────
    FFMPEG_PROCESSES = [
        compress,
        watermark,
        merge,
        softmux,
        softremux,
        convert,
        encode,         
        custom_encode,
        hardmux,
        trim,
        fast_trim,      
        split,
        cut,
        crop,
        autocrop,
        rotate,
        speed,          
        mute,            
        dubbing,        
        extension,
        extract,
        changeMetadata,
        changeindex,
    ]

    # ── Status Labels (dipakai Aria2, Process_Status, UI) ────────────
    STATUS_UPLOADING   = "🔼 Mengunggah"
    STATUS_CLONING     = "🧬 Mengkloning"
    STATUS_DOWNLOADING = "🔽 Mengunduh"
    STATUS_COPYING     = "🔁 Menyalin"
    STATUS_ARCHIVING   = "🔐 Mengarsip"
    STATUS_EXTRACTING  = "📂 Mengekstrak"
    STATUS_SPLITTING   = "✂️ Memisah"
    STATUS_SYNCING     = "🔄 Menyinkronkan"
    STATUS_WAITING     = "⏳ Antrian" 
    STATUS_PAUSED      = "⏸ Dijeda"
    STATUS_CHECKING    = "🔍 Memeriksa"
    STATUS_SEEDING     = "🌱 Seeding"
