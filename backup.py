"""Consistent backup, including original PDFs, safe while the server runs."""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from config import Settings
from database import Repository


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    settings = Settings()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    output = args.output or settings.data_dir / "backups" / f"campusorg-{stamp}.sqlite3"
    if not settings.db_path.exists():
        parser.error("Database belum tersedia. Jalankan ingest.py terlebih dahulu.")
    if output.exists():
        parser.error("Tujuan backup sudah ada; pilih nama lain.")
    Repository(settings.db_path).backup(output)
    print(f"Backup tersimpan: {output.resolve()}")
