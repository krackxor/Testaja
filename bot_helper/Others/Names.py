"""
╔══════════════════════════════════════════════════════════════════════╗
║            bot_helper/Others/Names.py — v3.2                         ║
║                    Konstanta Nama Proses Bot                         ║
╠══════════════════════════════════════════════════════════════════════╣
║  CHANGELOG v3.2:                                                     ║
║  [NEW]  fast_trim, speed, mute, dubbing (Optimasi & Fitur Baru)      ║
║  [NEW]  Mendaftarkan proses baru ke STATUS & FFMPEG_PROCESSES        ║
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
    encode         = "encode"       # [NEW] Default handler untuk dubbing & hardmux di FFMPEG
    hardmux        = "Hardmux"
    trim           = "Trim"
    fast_trim      = "fast_trim"    # [NEW] Cut tanpa re-encode
    split          = "Split"
    cut            = "Cut"
    crop           = "Crop"
    autocrop       = "Autocrop"
    rotate         = "Rotate"
    speed          = "speed"        # [NEW] Ubah kecepatan video
    mute           = "mute"         # [NEW] Hapus audio
    dubbing        = "dubbing"      # [NEW] Ganti audio video
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
        
        # Video production processes
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
        encode,         
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
