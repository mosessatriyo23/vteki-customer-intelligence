import sys
import importlib.util
from pathlib import Path

# Daftar library dan modul terlarang yang dilarang keras ada di basis kode (TRD §13.8, §16.2 / NFR-10)
PROHIBITED_PACKAGES = [
    "smtplib",      # Modul standar pengiriman email SMTP
    "twilio",       # SDK WhatsApp & SMS Twilio
    "sendgrid",     # SDK Email SendGrid
    "mailgun",      # SDK Mailgun
    "boto3",        # AWS SDK (mencegah akses AWS SES / SNS)
    "telebot",      # Telegram Bot API client
    "python-telegram-bot",
    "slack_sdk",    # Slack WebClient
]

def test_no_prohibited_modules_installed_or_imported():
    """
    T-SEC-03: Memastikan tidak ada modul dependensi yang mampu melakukan pengiriman
    pesan eksternal nyata yang terpasang di runtime environment.
    """
    for package in PROHIBITED_PACKAGES:
        spec = importlib.util.find_spec(package)
        assert spec is None, (
            f"[PELANGGARAN NFR-10 / T-SEC-03] Paket eksternal terlarang '{package}' "
            f"terdeteksi di environment! Sistem harus menggunakan Channel Simulator murni."
        )

def test_no_prohibited_imports_in_source_code():
    """
    T-SEC-03: Memindai seluruh berkas Python di dalam services/ dan api/
    untuk memastikan tidak ada import smtplib atau SDK pesan keluar lainnya.
    """
    root_dir = Path(__file__).resolve().parents[2]
    target_dirs = [root_dir / "services", root_dir / "api", root_dir / "worker"]
    
    violations = []

    for directory in target_dirs:
        if not directory.exists():
            continue
        for py_file in directory.rglob("*.py"):
            with open(py_file, "r", encoding="utf-8", errors="ignore") as f:
                for line_no, line in enumerate(f, 1):
                    clean_line = line.strip()
                    # Abaikan baris komentar
                    if clean_line.startswith("#"):
                        continue
                    
                    for package in PROHIBITED_PACKAGES:
                        if f"import {package}" in clean_line or f"from {package}" in clean_line:
                            violations.append(
                                f"{py_file.name}:{line_no} mengimpor paket terlarang '{package}' -> '{clean_line}'"
                            )

    assert not violations, (
        "[PELANGGARAN NFR-10 / T-SEC-03] Ditemukan impor paket terlarang pada kode sumber:\n"
        + "\n".join(violations)
    )
