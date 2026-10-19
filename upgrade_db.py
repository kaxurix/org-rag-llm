"""Idempotent schema upgrade for the local SQLite archive."""
from init_db import inisialisasi_database


if __name__ == "__main__":
    inisialisasi_database()
    print("Untuk memperbarui hasil ekstraksi/embedding, jalankan: python ingest.py --reindex")
