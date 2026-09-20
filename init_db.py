import asyncio
from sqlalchemy import text
from database import engine
from models import Base

async def inisialisasi_database():
    print("Menghubungkan ke database Docker...")
    async with engine.begin() as conn:
        # Langkah Wajib: Mengaktifkan ekstensi pgvector di PostgreSQL
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        
        # Mencetak semua tabel yang ada di models.py
        await conn.run_sync(Base.metadata.create_all)
        
    print("Sukses! Ekstensi pgvector dan tabel 'dokumen_arsip' berhasil dibuat.")

if __name__ == "__main__":
    asyncio.run(inisialisasi_database())