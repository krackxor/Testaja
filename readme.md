# A Multi-Feature Telegram Bot


### Configuration
To configure this bot add the environment variables stated below. Or add them in [sample_config.env](./sample_config.env) and change the name to `config.env`. Or add the environment variable `CONFIG_FILE_URL` and put config.env direct url in it.
- `API_ID` - (Required)Get it by creating an app on [https://my.telegram.org](https://my.telegram.org)
- `API_HASH` - (Required)Get it by creating an app on [https://my.telegram.org](https://my.telegram.org)
- `TOKEN` - (Required)Get it by creating a bot on [https://t.me/BotFather](https://t.me/BotFather)
- `OWNER_ID` - (Required)Numerical User ID of bot owner
- `SUDO_USERS` - (Required)Numerical User IDs of sudo users separated by space.
- `AUTH_GROUP_ID` - (Optional)Numerical chat id of group, required if you want to use pyrogram download/upload in group.
- `RESTART_NOTIFY_ID` - (Optional)Numerical user id of user or chat id of group/channel to notify on bot start, set it False if you don't want notification on start.
- `AUTO_SET_BOT_CMDS` - (Required)Set True if you want bot to setup its commands by itself otherwise set it False.
- `RUNNING_TASK_LIMIT` - (Required)Number Of Concurrent Tasks.
- `UNFINISHED_PROGRESS_STR` - (Required)Unfinished progress bar string value.
- `FINISHED_PROGRESS_STR` - (Required)Finished progress bar string value.
- `UPDATE_PACKAGES` - (Optional)Set True if you want to update the packages.
- `UPSTREAM_REPO` - (Optional)Your github repository link, if your repo is private add https://username:{githubtoken}@github.com/{username}/{reponame} format.
- `UPSTREAM_BRANCH` - (Optional)Upstream branch for update.
- `TIMEZONE` - (Optional)Timezone for clock time in status. Default is `Asia/Kolkata`.
- `SAVE_TO_DATABASE` - (Required)Set value True if you want to use MongoDB Database else False.
- `MONGODB_URI` - (Optional*)MongoDB URL to save data, only required when SAVE_TO_DATABASE's value is True.
- `Use_Session_String` - (Required)Set value True if you want to use Telegram user session string to upload 4GB file to telegram else False.
- `Session_String` - (Optional*)Telethon Session String, only required when Use_Session_String's value is True.

### Commands
```
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

# ═══ 🛠 PEMROSESAN MEDIA DASAR ═══
compress - Kompres ukuran video
merge - Gabungkan beberapa video menjadi satu
watermark - Tambahkan gambar/teks watermark ke video
convert - Ubah format video tanpa ubah resolusi
hardmux - Tanam subtitle permanen ke dalam video
softmux - Tambahkan subtitle sebagai stream
softremux - Hapus sub lama & tambahkan yang baru
extension - Ubah ekstensi file (contoh: mkv ke mp4)
extract - Ekstrak audio atau subtitle dari video
gensample - Buat cuplikan video pendek
genss - Buat kolase screenshot dari video
changemetadata - Ubah judul dan metadata video/audio
changeindex - Ubah susunan stream audio/subtitle
mediainfo - Cek informasi resolusi & bitrate file

# ═══ 📥 UNDUH & CLOUD ═══
leech - Unduh dari tautan lalu kirim ke Telegram
mirror - Unduh dari tautan lalu upload ke Google Drive

# ═══ ⚙️ PENGATURAN PENGGUNA ═══
settings - Buka menu pengaturan bot
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
```



### Copyright & License
- Copyright &copy; 2023 &mdash; [Nik66](https://github.com/sahilgit55)
- Licensed under the terms of the [GNU General Public License Version 3 &dash; 29 June 2007](./LICENSE)
