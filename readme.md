# 🎬 STUDIO KHOIRUL BOT — Trinity Edition (v4.1)

A Multi-Feature Telegram Bot designed for automated video production, advanced media manipulation, AI-powered subtitling, and high-speed leeching. Built on the blazing-fast **Trinity Architecture** (Aiogram + Telethon + Pyrogram).

---

### ⚙️ Configuration
To configure this bot, add the environment variables stated below. You can add them in `sample_config.env` and rename the file to `config.env`, or set the environment variable `CONFIG_FILE_URL` with a direct link to your configuration file.

#### 🔑 Core Variables
- `API_ID` - (Required) Get it by creating an app on [my.telegram.org](https://my.telegram.org).
- `API_HASH` - (Required) Get it by creating an app on [my.telegram.org](https://my.telegram.org).
- `TOKEN` - (Required) Get your bot token from [@BotFather](https://t.me/BotFather).
- `OWNER_ID` - (Required) Numerical User ID of the bot owner.
- `SUDO_USERS` - (Required) Numerical User IDs of sudo admins, separated by space.

#### 🚀 System & Performance
- `RUNNING_TASK_LIMIT` - (Required) Number of concurrent tasks the bot can handle.
- `UNFINISHED_PROGRESS_STR` - (Required) Character for unfinished progress bar (e.g., `░`).
- `FINISHED_PROGRESS_STR` - (Required) Character for finished progress bar (e.g., `█`).
- `TIMEZONE` - (Optional) Timezone for clock time in status (Default: `Asia/Jakarta`).

#### 💽 Database & Storage
- `SAVE_TO_DATABASE` - (Required) Set `True` if you want to use a MongoDB Database, else `False`.
- `MONGODB_URI` - (Optional*) MongoDB URL to save data (Required if `SAVE_TO_DATABASE` is True).
- `Use_Session_String` - (Required) Set `True` to use a Telethon user session to bypass the 2GB upload limit.
- `Session_String` - (Optional*) Telethon Session String (Required if `Use_Session_String` is True).

#### 📺 Third-Party API (Optional for Premium Features)
- `TRAKTEER_API_KEY` - Your Trakteer Creator API Key for automatic VIP verification via `/verify`.
- `YOUTUBE_API_KEY` - Ensure `client_secret.json` and `token.json` are present in the root directory for `/ytupload`.

#### 🔄 Updates & Notifications
- `UPDATE_PACKAGES` - (Optional) Set `True` to update packages automatically.
- `UPSTREAM_REPO` - (Optional) Your GitHub repository link for updates.
- `UPSTREAM_BRANCH` - (Optional) Upstream branch to pull updates from.
- `RESTART_NOTIFY_ID` - (Optional) Numerical ID (User/Chat) to notify on bot start. Set `False` to disable.
- `AUTO_SET_BOT_CMDS` - (Required) Set `True` to let the bot auto-configure its commands menu.

---

### 📝 Available Commands

```text
# ═══ 🎬 STUDIO PRODUKSI & AI ═══
recap - Rangkum film otomatis dgn AI & Voiceover
clip - Potong video jadi Shorts/Reels dari file .txt
verdict - Buat video ulasan game/film (Tema Merah)
toptier - Buat video peringkat/tier list (Tema Emas)
lore - Buat video teori & fakta (Tema Netflix)
radar - Buat video game/film baru (Tema Cyber)
patch - Buat video berita/update kilat
archives - Buat video sejarah/arsip (Tema Retro)
ytupload - Upload video langsung ke YouTube

# ═══ 🤖 AI SUBTITLES & TRANSLATION ═══
autosub - Buat subtitle otomatis dari Video/Audio (Whisper AI)
autotranslate - Terjemahkan file .srt ke bahasa apapun

# ═══ 🎮 MANAJEMEN ASET STUDIO ═══
addgameplay - Simpan video gameplay ke server bot
listgameplay - Lihat daftar gameplay yang tersimpan
deletegameplay - Hapus gameplay dari server
addsfx - Tambahkan efek suara (SFX) kustom

# ═══ ✂️ MANIPULASI VIDEO LANJUTAN ═══
trim - Pangkas durasi awal dan akhir video
split - Bagi video berdasarkan durasi/ukuran/jumlah
cut - Buang bagian tengah video yang tidak diinginkan
crop - Potong rasio layar video (16:9, 9:16, dll)
autocrop - Otomatis buang black bar pada video
rotate - Putar atau balikkan arah video
speed - Ubah kecepatan pemutaran video (Lambat/Cepat)
mute - Hapus seluruh suara/audio dari video
dubbing - Ganti suara asli video dengan file audio baru

# ═══ 🛠 PEMROSESAN MEDIA DASAR ═══
compress - Kompres ukuran video
merge - Gabungkan beberapa video menjadi satu
watermark - Tambahkan gambar/teks watermark ke video
convert - Ubah format video tanpa ubah resolusi
hardmux - Tanam subtitle permanen ke dalam video
softmux - Tambahkan subtitle sebagai stream
softremux - Hapus sub lama & tambahkan yang baru
extension - Ubah ekstensi file (contoh: mkv ke mp4)
extract - Ekstrak audio, subtitle, thumbnail HD, atau frame ZIP
gensample - Buat cuplikan video pendek
genss - Buat kolase screenshot dari video
changemetadata - Ubah judul dan metadata video/audio
changeindex - Ubah susunan stream audio/subtitle
mediainfo - Cek informasi resolusi & bitrate file

# ═══ 📥 UNDUH & CLOUD ═══
leech - Unduh dari tautan lalu kirim ke Telegram
mirror - Unduh dari tautan lalu upload ke Google Drive

# ═══ ⚙️ PENGATURAN PENGGUNA ═══
settings - Buka menu pengaturan bot utama
savewatermark - Simpan gambar watermark default
savethumb - Simpan gambar thumbnail default
saveconfig - Simpan konfigurasi rclone Google Drive

# ═══ 👑 SISTEM VIP & DONASI ═══
myvip - Cek masa aktif VIP Anda
verify - Verifikasi donasi Trakteer untuk klaim VIP

# ═══ 💻 SISTEM & ADMIN BOT ═══
status - Cek proses antrian yang sedang berjalan
cancel - Batalkan proses upload/render
time - Cek waktu aktif bot (Uptime)
stats - Cek statistik CPU, RAM, & Disk server
speedtest - Tes kecepatan internet server bot
tasklimit - Ubah batas antrian maksimal bot
log - Lihat log error singkat bot
logs - Unduh file log lengkap bot
renew - Bersihkan file sampah di server
resetdb - Hapus semua data dari database
changeconfig - Ubah variabel environment bot
clearconfigs - Kembalikan pengaturan bot ke default
checksudo - Lihat daftar admin bot
addsudo - Tambahkan admin baru
delsudo - Hapus hak admin
add_vip - Tambah akses VIP manual ke user
delete_vip - Cabut akses VIP user
view_vip - Lihat daftar semua user VIP
yttoken - Update token rahasia YouTube API
restart - Mulai ulang mesin bot
herokurestart - Mulai ulang Dyno Heroku
help - Buka panduan lengkap bot
start - Mulai interaksi bot



### Copyright & License
- Copyright &copy; 2023 &mdash; [Nik66](https://github.com/sahilgit55)
- Licensed under the terms of the [GNU General Public License Version 3 &dash; 29 June 2007](./LICENSE)
