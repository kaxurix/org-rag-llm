from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import pymupdf  # PyMuPDF untuk membaca PDF 
from sentence_transformers import SentenceTransformer

from database import AsyncSessionLocal, engine, Base
from models import DokumenArsip
from sqlalchemy import select, text

from pydantic import BaseModel
import httpx


app = FastAPI(title="CampusOrg GraphRAG API")

# 1. Buat fungsi lifespan untuk menangani startup dan shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- PROSES STARTUP (Sebelum aplikasi siap menerima request) ---
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database dan Tabel berhasil disiapkan!")
    
    yield  # <-- Titik di mana aplikasi FastAPI berjalan melayani request
    
    # --- PROSES SHUTDOWN (Saat aplikasi dimatikan dengan Ctrl+C) ---
    print("🛑 Mematikan server GraphRAG...")

# 2. Inisialisasi FastAPI dengan parameter lifespan
app = FastAPI(title="CampusOrg GraphRAG API", lifespan=lifespan)

# Load model embedding (384 dimensi) - akan otomatis terunduh saat pertama kali jalan
print("Loading Embedding Model...")
embedder = SentenceTransformer("all-MiniLM-L6-v2")
print("Model Ready!")

# Dependency untuk mendapatkan sesi database
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@app.get("/")
def read_root():
    return {"status": "success", "message": "Backend GraphRAG menyala!"}
 

def chunk_pdf_smart(page_text: str, max_chars: int = 600, overlap: int = 100):
    # Pecah berdasarkan baris kosong ganda atau baris biasa jika terlalu panjang
    lines = page_text.split("\n")
    chunks = []
    current_chunk = ""
    
    for line in lines:
        if len(current_chunk) + len(line) + 1 <= max_chars:
            current_chunk += (line + "\n")
        else:
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            # Handle overlap sederhana atau potong dari baris saat ini
            current_chunk = line + "\n"
            
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
        
    return [c for c in chunks if len(c.strip()) >= 20]

@app.post("/upload")
async def upload_dokumen_pdf(
    file: UploadFile = File(...),
    divisi: str = Form(...),
    tahun: int = Form(...),
    db: AsyncSession = Depends(get_db)
):
    file_bytes = await file.read()
    chunk_tersimpan = 0
    
    with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:
        for page_index, page in enumerate(doc):
            page_text = page.get_text()
            p_num = page_index + 1
            
            page_chunks = chunk_pdf_smart(page_text, max_chars=600)
            
            for chunk_str in page_chunks:
                vektor = embedder.encode(chunk_str).tolist()
                db.add(DokumenArsip(
                    nama_file=file.filename,
                    divisi=divisi,
                    tahun=tahun,
                    page_num=p_num,
                    konten_teks=chunk_str,
                    embedding=vektor
                ))
                chunk_tersimpan += 1
                
    await db.commit()
    
    # [BARU] Format API yang distandarisasi
    return {
        "status": "success",
        "message": "Dokumen berhasil diproses dan disimpan ke database vektor.",
        "data": {
            "nama_file": file.filename,
            "kategori": divisi,
            "tahun_dokumen": tahun,
            "total_chunks_tersimpan": chunk_tersimpan
        }
    }

class ChatMessage(BaseModel):
    role: str # "user" atau "assistant"
    content: str

class PertanyaanRequest(BaseModel):
    pertanyaan: str
    divisi: str | None = None
    history: list[ChatMessage] | None = None # Riwayat percakapan sebelumnya

@app.post("/ask")
async def tanya_ai(req: PertanyaanRequest, db: AsyncSession = Depends(get_db)):
    vektor_tanya = embedder.encode(req.pertanyaan).tolist()
    dist_expr = DokumenArsip.embedding.cosine_distance(vektor_tanya)
    
    # HAPUS PERCOBAAN KETAT DAN FALLBACK. 
    # Langsung ambil Top 8 teratas, apapun yang terjadi!
    kueri = select(DokumenArsip).order_by(dist_expr).limit(8)
    
    if req.divisi:
        kueri = kueri.where(DokumenArsip.divisi == req.divisi)
        
    hasil = await db.execute(kueri)
    semua_dokumen = hasil.scalars().all()
    
    # [BARU] Filter duplikat: Pastikan LLM hanya membaca teks yang unik
    teks_unik = set()
    dokumen_relevan = []
    
    for doc in semua_dokumen:
        if doc.konten_teks not in teks_unik:
            teks_unik.add(doc.konten_teks)
            dokumen_relevan.append(doc)
            
    # Baru setelah itu rangkai konteksnya
    konteks = "\n---\n".join([f"[Hal {doc.page_num}] {doc.konten_teks}" for doc in dokumen_relevan]) if dokumen_relevan else "Tidak ada konteks spesifik."
    # [BARU] Merapikan array referensi agar berupa objek, bukan sekadar string panjang
    referensi_unik = {}
    if dokumen_relevan:
        for doc in dokumen_relevan:
            key = f"{doc.nama_file}_{doc.page_num}"
            if key not in referensi_unik:
                referensi_unik[key] = {
                    "file": doc.nama_file,
                    "halaman": doc.page_num
                }
    daftar_sumber = list(referensi_unik.values())
    
    # Rangkai history chat
    history_str = ""
    if req.history:
        recent_history = req.history[-4:]
        history_str = "\n".join([f"{msg.role.upper()}: {msg.content}" for msg in recent_history])
        history_str = f"\nRiwayat Percakapan:\n{history_str}\n"

    prompt = f"""Anda adalah second brain assistant. Baca seluruh konteks arsip di bawah dengan teliti sebelum menjawab.
- Ekstrak fakta secara eksplisit dari teks jika ada.
- Jangan bilang "tidak tahu" jika informasi tersebut ada di salah satu potongan halaman konteks di bawah.

Konteks Arsip:
{konteks}

Riwayat Percakapan:
{history_str}

Pertanyaan: {req.pertanyaan}
"""

    async with httpx.AsyncClient() as client:
        respon_ollama = await client.post(
            "http://127.0.0.1:11434/api/generate",
            json={
                "model": "qwen2.5-coder:7b",
                "prompt": prompt,
                "stream": False
            },
            timeout=120.0
        )
        
    jawaban_ai = respon_ollama.json().get("response", "Gagal menghubungi Ollama.")
    
    # [BARU] Format API Response yang Elegan
    return {
        "status": "success",
        "message": "Berhasil melakukan inferensi AI.",
        "data": {
            "query_asli": req.pertanyaan,
            "jawaban_ai": jawaban_ai,
            "referensi": daftar_sumber,
            "metadata": {
                "total_referensi_ditemukan": len(daftar_sumber),
                "model_llm": "qwen2.5-coder:7b",
                "debug_konteks": konteks
            }
        }
    }