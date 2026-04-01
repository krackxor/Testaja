"""
get_token.py — Generate token.json YouTube untuk Studio Khoirul Bot

Jalankan di VPS atau komputer lokal:
    python3 get_token.py

2 OPSI:
  [1] Manual URL — Copy-paste di HP/browser manapun (VPS headless OK)
  [2] Auto Browser — Otomatis buka browser (hanya jika ada GUI)

Setelah dapat token.json, upload ke bot via:
    /yttoken (reply file token.json)

Requirements: pip install google-auth-oauthlib google-api-python-client
"""

import json
import os
import sys
import urllib.parse as urlparse

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
except ImportError:
    print("Install dulu: pip install google-auth-oauthlib google-api-python-client")
    sys.exit(1)

SCOPES      = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE  = "token.json"
SECRET_FILE = "client_secret.json"


def _check_existing_token() -> bool:
    if not os.path.exists(TOKEN_FILE):
        return False
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds.valid:
            print(f"\nToken sudah valid di '{TOKEN_FILE}'")
            print("Tidak perlu generate ulang.")
            _print_token_info()
            return True
        elif creds.expired and creds.refresh_token:
            print("\nToken expired, mencoba refresh otomatis...")
            creds.refresh(Request())
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
            print("Token berhasil di-refresh.")
            _print_token_info()
            return True
        else:
            print("Token lama tidak valid, akan generate baru...")
            return False
    except Exception as e:
        print(f"Token lama bermasalah ({e}), akan generate baru...")
        return False


def _print_token_info():
    try:
        with open(TOKEN_FILE) as f:
            data = json.load(f)
        has_refresh = bool(data.get("refresh_token"))
        expiry      = data.get("expiry", "Unknown")
        print(f"\n   refresh_token : {'Ada' if has_refresh else 'TIDAK ADA (MASALAH!)'}")
        print(f"   expiry        : {expiry}")
        if not has_refresh:
            print("\n   PERINGATAN: Tidak ada refresh_token!")
            print("   Hapus token.json dan jalankan script ini lagi.")
    except Exception:
        pass


def _check_secret_file() -> bool:
    if os.path.exists(SECRET_FILE):
        return True
    print(f"\nFile '{SECRET_FILE}' tidak ditemukan!")
    print("\nCara mendapatkan client_secret.json:")
    print("  1. Buka https://console.cloud.google.com/")
    print("  2. Buat project atau pilih yang ada")
    print("  3. Aktifkan 'YouTube Data API v3'")
    print("  4. Buat OAuth 2.0 Client ID → pilih 'Desktop app'")
    print("  5. Download JSON → rename jadi 'client_secret.json'")
    print("  6. Taruh di folder yang sama dengan script ini")
    print("  7. Jalankan script ini lagi")
    return False


def _save_credentials(creds) -> bool:
    try:
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

        data        = json.loads(creds.to_json())
        has_refresh = bool(data.get("refresh_token"))

        print(f"\nToken berhasil disimpan ke '{TOKEN_FILE}'")
        print(f"  refresh_token : {'Ada' if has_refresh else 'TIDAK ADA'}")

        if not has_refresh:
            print("\nPERINGATAN: Tidak ada refresh_token!")
            print("Hapus token.json, lalu jalankan ulang.")
            return False

        print("\nLangkah selanjutnya:")
        print("  Upload token.json ke bot dengan perintah:")
        print("  Reply file token.json dengan /yttoken di Telegram")
        print(f"\n  Atau via SCP: scp {TOKEN_FILE} user@vps:/path/to/bot/")
        return True

    except Exception as e:
        print(f"\nGagal simpan token: {e}")
        return False


# ══════════════════════════════════════════════════════════
#  OPSI 1: MANUAL URL (VPS HEADLESS / HP BROWSER)
# ══════════════════════════════════════════════════════════

def option_manual_url():
    """
    Cara kerja:
    1. Script generate URL login Google
    2. Buka URL di browser HP/PC manapun
    3. Login → browser ERROR "localhost refused" → NORMAL
    4. Copy seluruh URL error dari address bar
    5. Paste di sini → token selesai
    """
    print("\n" + "=" * 60)
    print("  OPSI 1: Manual URL (VPS Headless / HP Browser)")
    print("=" * 60)

    flow             = InstalledAppFlow.from_client_secrets_file(SECRET_FILE, SCOPES)
    flow.redirect_uri = "http://localhost:8080/"

    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
    )

    print("\nLANGKAH-LANGKAH:\n")
    print("1. COPY URL di bawah ini dan buka di browser HP/PC kamu:")
    print("\n" + "-" * 60)
    print(auth_url)
    print("-" * 60)
    print("\n2. Login dengan akun Google pemilik channel YouTube.")
    print("   Klik 'Lanjutkan' / 'Allow' untuk izinkan akses.\n")
    print("3. Browser AKAN ERROR (localhost refused to connect) — itu NORMAL!")
    print("   Jangan tutup browser.\n")
    print("4. Lihat address bar browser, ada URL panjang seperti:")
    print("   http://localhost:8080/?state=...&code=4/XXXX...\n")
    print("5. Copy SELURUH URL tersebut (dari http:// sampai akhir).")

    redirected_url = input(
        "\nPASTE URL YANG ERROR TADI DI SINI, lalu tekan ENTER:\n>> "
    ).strip()

    if not redirected_url:
        print("URL kosong. Jalankan ulang script.")
        return False

    try:
        parsed = urlparse.urlparse(redirected_url)
        params = urlparse.parse_qs(parsed.query)
        codes  = params.get("code")

        if not codes:
            print("\nTidak ditemukan 'code' di URL yang kamu paste.")
            print("Pastikan kamu copy SELURUH URL dari address bar browser.")
            print(f"URL yang kamu paste: {redirected_url[:100]}...")
            return False

        code = codes[0]
        print("\nMemproses token dari code...")

        flow.fetch_token(code=code)
        creds = flow.credentials
        return _save_credentials(creds)

    except Exception as e:
        print(f"\nGagal proses URL: {e}")
        print("Pastikan URL yang dipaste lengkap dan benar.")
        return False


# ══════════════════════════════════════════════════════════
#  OPSI 2: AUTO BROWSER (KOMPUTER LOKAL)
# ══════════════════════════════════════════════════════════

def option_auto_browser():
    """Otomatis buka browser. Butuh GUI / komputer lokal."""
    print("\n" + "=" * 60)
    print("  OPSI 2: Auto Browser (Komputer Lokal dengan GUI)")
    print("=" * 60)
    print("\nMembuka browser secara otomatis...")
    print("(Pastikan kamu menggunakan komputer yang punya browser)\n")

    try:
        flow  = InstalledAppFlow.from_client_secrets_file(SECRET_FILE, SCOPES)
        creds = flow.run_local_server(
            port=0,
            prompt="consent",
            access_type="offline",
        )
        return _save_credentials(creds)

    except Exception as e:
        print(f"\nGagal buka browser: {e}")
        print("\nKemungkinan penyebab:")
        print("  - Tidak ada browser di sistem ini (VPS headless)")
        print("  - Port sudah dipakai proses lain")
        print("  Coba gunakan Opsi 1 (Manual URL) sebagai gantinya")
        return False


# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  YouTube Token Generator — Studio Khoirul Bot")
    print("=" * 60)

    # Cek token existing
    if _check_existing_token():
        print("\nUntuk force generate ulang: hapus token.json dulu")
        print(f"Perintah: rm {TOKEN_FILE}")
        return

    # Cek client_secret.json
    if not _check_secret_file():
        sys.exit(1)

    # Pilih opsi
    print("\n" + "-" * 60)
    print("  Pilih metode generate token:")
    print("-" * 60)
    print("\n  [1] Manual URL — Buka URL di browser HP/PC manapun")
    print("        OK untuk VPS headless")
    print("        OK jika tidak ada browser di server")
    print("        Cara yang kamu pakai sebelumnya\n")
    print("  [2] Auto Browser — Browser otomatis terbuka")
    print("        Lebih praktis jika ada GUI")
    print("        OK untuk Windows/Mac/Linux desktop")
    print("        Tidak bisa di VPS headless\n")

    while True:
        choice = input("  Masukkan pilihan [1/2]: ").strip()
        if choice in ("1", "2"):
            break
        print("  Pilihan tidak valid. Masukkan 1 atau 2.")

    print()
    if choice == "1":
        success = option_manual_url()
    else:
        success = option_auto_browser()

    if success:
        print("\n" + "=" * 60)
        print("  SELESAI! token.json siap dipakai.")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("  Gagal generate token. Coba lagi.")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
