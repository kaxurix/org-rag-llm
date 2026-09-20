from sqlalchemy import String, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import VECTOR
from database import Base

class DokumenArsip(Base):
    __tablename__ = "dokumen_arsip"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    nama_file: Mapped[str] = mapped_column(String(255))
    divisi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tahun: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_num: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    konten_teks: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(VECTOR(384))