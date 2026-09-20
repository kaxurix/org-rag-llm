from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# URL koneksi ke PostgreSQL di dalam Docker yang tadi kita buat
DATABASE_URL = "postgresql+asyncpg://admin:password123@localhost:5432/capstone_rag"

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()