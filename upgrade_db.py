import asyncio
from sqlalchemy import text
from database import engine

async def tambah_kolom():
    async with engine.begin() as conn:
        # Menambahkan kolom page_num ke tabel yang sudah ada
        await conn.execute(text("ALTER TABLE dokumen_arsip ADD COLUMN page_num INTEGER DEFAULT 1;"))
    print("Mantap! Kolom 'page_num' berhasil ditambahkan ke database.")

if __name__ == "__main__":
    asyncio.run(tambah_kolom())