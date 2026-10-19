"""Explicit archive reset with a mandatory backup. Never run during normal startup."""
import argparse
from datetime import datetime, timezone

from config import Settings
from database import Repository


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Konfirmasi penghapusan seluruh arsip lokal.")
    args = parser.parse_args()
    if not args.yes:
        parser.error("Tidak ada perubahan. Gunakan --yes hanya jika ingin mengosongkan seluruh arsip.")
    settings = Settings()
    repository = Repository(settings.db_path)
    if not repository.path.exists():
        parser.error("Database belum tersedia.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup = settings.data_dir / "backups" / f"before-reset-{stamp}.sqlite3"
    repository.backup(backup)
    with repository.connect() as conn:
        conn.execute("DELETE FROM documents")
    print(f"Arsip dikosongkan. Backup: {backup}")
    print("AUTO_IMPORT=true akan mengimpor kembali dataset saat server dimulai.")
