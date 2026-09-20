import asyncio
from sqlalchemy import text
from database import engine

async def clear_tabel():
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE dokumen_arsip;"))
    print("Mantap! Tabel dokumen_arsip sudah bersih.")

if __name__ == "__main__":
    asyncio.run(clear_tabel())