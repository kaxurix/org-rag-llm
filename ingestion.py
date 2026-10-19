"""Page-aware extraction, division detection, bounded chunks and repeatable import."""
import hashlib
import logging
import re
import unicodedata
from datetime import date
from pathlib import Path

import pymupdf

from config import Settings
from database import Repository

logger = logging.getLogger(__name__)
DIVISIONS = {
    "acara": "Acara", "humas": "Humas", "usdan": "Usdan", "pdd": "PDD",
    "atp": "ATP", "konsumsi": "Konsumsi", "keamanan": "Keamanan",
    "sekbend": "Sekbend", "sekben": "Sekbend", "sekretaris dan bendahara": "Sekbend",
}
MONTHS = {name: i for i, name in enumerate(
    "januari februari maret april mei juni juli agustus september oktober november desember".split(), 1)}


class InvalidPDF(ValueError):
    pass


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\u200b", "").replace("\x00", "")
    return "\n".join(re.sub(r"[^\S\n]+", " ", line).strip() for line in text.splitlines()).strip()


def chunk_pdf_smart(page_text: str, max_chars: int = 1200, overlap: int = 180) -> list[str]:
    if not 0 <= overlap < max_chars:
        raise ValueError("overlap harus >= 0 dan lebih kecil dari max_chars")
    text = clean_text(page_text)
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = max(text.rfind("\n", start + max_chars // 2, end),
                           text.rfind(" ", start + max_chars // 2, end))
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def meeting_metadata(text: str) -> tuple[int | None, str | None]:
    number = re.search(r"Rapat ke\s*[:\-]?\s*(\d+)", text, re.I)
    match = re.search(r"Tanggal\s*[:\-]?\s*(\d{1,2})\s+(\w+)\s+(\d{4})", text, re.I)
    meeting_date = None
    if match and match[2].lower() in MONTHS:
        try:
            meeting_date = date(int(match[3]), MONTHS[match[2].lower()], int(match[1])).isoformat()
        except ValueError:
            pass
    return int(number[1]) if number else None, meeting_date


def extract_pdf(pdf: bytes, settings: Settings, default_division: str):
    if not pdf.startswith(b"%PDF-"):
        raise InvalidPDF("Isi berkas bukan PDF yang valid.")
    chunks, empty_pages = [], []
    try:
        with pymupdf.open(stream=pdf, filetype="pdf") as document:
            if document.needs_pass:
                raise InvalidPDF("PDF terkunci. Unggah salinan tanpa kata sandi.")
            if not 1 <= len(document) <= settings.max_pdf_pages:
                raise InvalidPDF(f"PDF harus berisi 1–{settings.max_pdf_pages} halaman.")
            first_page = clean_text(document[0].get_text(sort=True))
            meeting_number, meeting_date = meeting_metadata(first_page)
            current_meeting, current_date = meeting_number, meeting_date
            current_division = default_division
            for page_number, page in enumerate(document, 1):
                raw = clean_text(page.get_text(sort=True))
                if len(raw) < 20:
                    empty_pages.append(page_number)
                    continue
                # Some supplied PDFs concatenate several meetings. Metadata follows the content,
                # not the filename or the first page of the file.
                page_meeting, page_date = meeting_metadata(raw)
                if page_meeting is not None and page_date is not None:
                    current_meeting, current_date = page_meeting, page_date
                    current_division = default_division
                lines = [line for line in raw.splitlines() if not (
                    line.startswith(("HIMPUNAN MAHASISWA INFORMATIKA", "FAKULTAS TEKNIK",
                        "UNIVERSITAS JENDERAL SOEDIRMAN", "Sekretariat :", "Jalan Mayjend",
                        "Website:", "Website :"))
                )]
                section = []

                def flush():
                    for text in chunk_pdf_smart("\n".join(section)):
                        chunks.append({"page_num": page_number, "divisi": current_division,
                            "meeting_number": current_meeting, "meeting_date": current_date, "konten_teks": text})

                for line in lines:
                    heading = re.fullmatch(r"\d+\s*[.)]\s*([A-Za-z ]+)\s*:?", line)
                    division = DIVISIONS.get(heading[1].strip().lower()) if heading else None
                    if division:
                        flush()
                        section = []
                        current_division = division
                    section.append(line)
                flush()
            if not chunks:
                raise InvalidPDF("Tidak ada teks yang bisa dibaca. PDF hasil pindai perlu OCR terlebih dahulu.")
            return chunks, {
                "total_pages": len(document), "empty_pages": empty_pages,
                "meeting_number": meeting_number, "meeting_date": meeting_date,
            }
    except InvalidPDF:
        raise
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise InvalidPDF("PDF rusak atau tidak dapat dibaca.") from exc


def ingest_pdf(repository: Repository, settings: Settings, pdf: bytes, filename: str,
               divisi: str = "Umum", tahun: int = 2026, semantic=None, reindex: bool = False):
    if len(pdf) > settings.max_upload_mb * 1024 * 1024:
        raise InvalidPDF(f"Ukuran PDF melebihi {settings.max_upload_mb} MB.")
    filename = Path(filename.replace("\\", "/")).name
    if not filename.lower().endswith(".pdf") or len(filename) > 255:
        raise InvalidPDF("Nama berkas harus berakhiran .pdf dan maksimal 255 karakter.")
    divisi = DIVISIONS.get(divisi.strip().lower(), divisi.strip())
    if not divisi or len(divisi) > 100 or not 2000 <= tahun <= 2100:
        raise InvalidPDF("Divisi atau tahun dokumen tidak valid.")
    checksum = hashlib.sha256(pdf).hexdigest()
    existing = repository.find_checksum(checksum)
    if existing and not reindex:
        return {"document": existing, "imported": False, "duplicate": True}
    chunks, metadata = extract_pdf(pdf, settings, divisi)
    metadata.update(checksum=checksum, nama_file=filename, divisi=divisi, tahun=tahun)
    embedding_warning = None
    if semantic is not None:
        try:
            vectors = semantic.encode([c["konten_teks"] for c in chunks])
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.update(embedding=vector, embedding_model=settings.embedding_model)
        except Exception:
            logger.exception("Embedding gagal; PDF tetap diimpor untuk pencarian BM25")
            embedding_warning = "Embedding belum tersedia; PDF diindeks dengan BM25. Jalankan --reindex setelah model siap."
    document_id, imported = repository.save_document(metadata, pdf, chunks, reindex)
    return {"document": repository.document(document_id), "imported": imported,
            "duplicate": not imported, "warning": embedding_warning}


def import_datasets(repository: Repository, settings: Settings, semantic=None, reindex=False):
    results = []
    for path in sorted(settings.dataset_dir.glob(settings.dataset_glob)):
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > settings.max_upload_mb * 1024 * 1024:
                raise InvalidPDF("Dataset melebihi batas ukuran unggahan.")
            year = re.search(r"\b(20\d{2})\b", path.stem)
            result = ingest_pdf(repository, settings, path.read_bytes(), path.name,
                                tahun=int(year[1]) if year else 2026, semantic=semantic, reindex=reindex)
            results.append({"file": path.name, **result})
        except Exception as exc:
            logger.exception("Impor gagal: %s", path.name)
            results.append({"file": path.name, "error": str(exc)})
    return results
