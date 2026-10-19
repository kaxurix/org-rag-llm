"""Remove appended meetings from the supplied PDFs, preserving their closing paragraphs.

Default: inspect only. --apply creates byte-identical backups, repairs the actual PDFs,
verifies text and rendering, and replaces their existing database entries by checksum.
"""
import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

from config import ROOT, Settings
from database import Repository
from ingestion import clean_text, extract_pdf, import_datasets, meeting_metadata
from retrieval import SemanticEncoder


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plan_pdf(path: Path, expected_meeting: int) -> dict:
    original = path.read_bytes()
    with pymupdf.open(stream=original, filetype="pdf") as source:
        headers = []
        for index, page in enumerate(source):
            number, day = meeting_metadata(clean_text(page.get_text(sort=True)))
            if number is not None and day is not None:
                headers.append((index, number, day))
        if not headers or headers[0][0] != 0 or headers[0][1] != expected_meeting:
            raise ValueError(f"Header awal {path.name} tidak sesuai; tidak ada perubahan.")
        foreign = next((header for header in headers if header[1] != expected_meeting), None)
        report = {"file": path.name, "meeting_number": expected_meeting, "original_pages": len(source),
                  "original_sha256": digest(original), "changed": foreign is not None}
        if foreign is None:
            return {**report, "pages": len(source), "sha256": digest(original), "pdf": original}
        boundary_index = foreign[0]
        boundary_page = source[boundary_index]
        lines = [(clean_text("".join(span["text"] for span in line["spans"])), line["bbox"])
                 for block in boundary_page.get_text("dict")["blocks"] if "lines" in block
                 for line in block["lines"]]
        meeting_labels = [bounds[1] for text, bounds in lines if text.lower() == "rapat ke"]
        starts = [bounds[1] for text, bounds in lines if text.lower() == "kegiatan"]
        if len(meeting_labels) != 1 or len(starts) != 1 or not 0 < meeting_labels[0] - starts[0] < 60:
            raise ValueError(f"Batas rapat pada {path.name} ambigu; tidak ada perubahan.")
        # Use stable decimal coordinates for the cut between the two meeting sections.
        cutoff = round(starts[0] - 2, 1)
        if cutoff < 110:
            raise ValueError("Metode ini membutuhkan halaman batas yang memuat penutup rapat sebelumnya.")
        clip = pymupdf.Rect(0, 0, boundary_page.rect.width, cutoff)
        retained_text = boundary_page.get_text(sort=True, clip=clip)
        before_render = boundary_page.get_pixmap(matrix=pymupdf.Matrix(0.75, 0.75),
            clip=pymupdf.Rect(0, 0, clip.width, cutoff - 2), alpha=False)
        before_pixels = before_render.samples
        with pymupdf.open() as repaired:
            repaired.insert_pdf(source, from_page=0, to_page=boundary_index)
            repaired.set_metadata(source.metadata)
            last_page = repaired[-1]
            last_page.add_redact_annot(pymupdf.Rect(0, cutoff, last_page.rect.width, last_page.rect.height),
                                       fill=(1, 1, 1), cross_out=False)
            last_page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                text=pymupdf.PDF_REDACT_TEXT_REMOVE)
            result = repaired.tobytes(garbage=4, deflate=True)
        with pymupdf.open(stream=result, filetype="pdf") as checked:
            if " ".join(clean_text(checked[-1].get_text(sort=True)).split()) != " ".join(clean_text(retained_text).split()):
                raise ValueError("Teks penutup berubah saat perbaikan PDF.")
            after_render = checked[-1].get_pixmap(matrix=pymupdf.Matrix(0.75, 0.75),
                clip=pymupdf.Rect(0, 0, clip.width, cutoff - 2), alpha=False)
            after_pixels = after_render.samples
            if len(before_pixels) != len(after_pixels):
                raise ValueError("Ukuran render bagian yang dipertahankan berubah.")
            differences = [abs(a - b) for a, b in zip(before_pixels, after_pixels)]
            mean_difference = sum(differences) / len(differences)
            # Rewriting a PDF may change font antialiasing slightly. Reject actual layout,
            # color, or image changes while permitting small edge-rendering differences.
            if mean_difference > 0.5 or max(differences, default=0) > 64:
                raise ValueError(f"Tampilan bagian yang dipertahankan pada {path.name} berubah.")
            for index in range(boundary_index):
                if source[index].get_text() != checked[index].get_text():
                    raise ValueError("Teks halaman yang dipertahankan berubah.")
            for page in checked:
                number, _ = meeting_metadata(clean_text(page.get_text(sort=True)))
                if number is not None and number != expected_meeting:
                    raise ValueError("Header rapat lain masih ada dalam PDF hasil perbaikan.")
            return {**report, "pages": len(checked), "sha256": digest(result), "pdf": result,
                    "last_original_page_retained": boundary_index + 1,
                    "removed_from_y": round(cutoff, 3),
                    "closing_text_verified": True, "closing_render_verified": True,
                    "closing_render_mean_difference": round(mean_difference, 6)}


def public_report(plan: dict) -> dict:
    return {key: value for key, value in plan.items() if key != "pdf"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Perbaiki PDF dan sinkronkan database setelah backup.")
    args = parser.parse_args()
    settings = Settings()
    plans = [plan_pdf(ROOT / f"NOTULA RABES STECH 2026 {number}.pdf", number) for number in range(1, 5)]
    changed = [plan for plan in plans if plan["changed"]]
    if not args.apply or not changed:
        print(json.dumps({"applied": False, "files": [public_report(plan) for plan in plans]}, ensure_ascii=False, indent=2))
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup_dir = settings.data_dir / "backups" / f"pdf-originals-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    repository = Repository(settings.db_path)
    if repository.path.exists():
        repository.backup(backup_dir / "archive-before-repair.sqlite3")
    for plan in plans:
        source = ROOT / plan["file"]
        shutil.copy2(source, backup_dir / source.name)
        if digest((backup_dir / source.name).read_bytes()) != plan["original_sha256"]:
            raise ValueError("Verifikasi backup gagal; PDF sumber belum diubah.")
    manifest = {"applied_at": stamp, "files": [public_report(plan) for plan in plans]}
    (backup_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for plan in changed:
        source = ROOT / plan["file"]
        staged = backup_dir / f"repaired-{source.name}"
        staged.write_bytes(plan["pdf"])
        if digest(source.read_bytes()) != plan["original_sha256"]:
            raise ValueError("PDF sumber berubah setelah pemeriksaan; proses dihentikan.")
        os.replace(staged, source)
    repository.initialize()
    semantic = SemanticEncoder(settings) if settings.semantic_search else None
    for plan in changed:
        existing = repository.find_checksum(plan["original_sha256"])
        chunks, metadata = extract_pdf(plan["pdf"], settings, existing["divisi"] if existing else "Umum")
        metadata.update(checksum=plan["sha256"], nama_file=plan["file"],
                        divisi=existing["divisi"] if existing else "Umum", tahun=existing["tahun"] if existing else 2026)
        if semantic is not None:
            vectors = semantic.encode([chunk["konten_teks"] for chunk in chunks])
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.update(embedding=vector, embedding_model=settings.embedding_model)
        repository.save_document(metadata, plan["pdf"], chunks, reindex=True,
                                 replace_checksum=plan["original_sha256"])
    results = import_datasets(repository, settings, semantic)
    if any("error" in result for result in results):
        raise ValueError("PDF sudah diperbaiki; ada galat saat mengimpor ulang. Lihat log dan backup.")
    print(json.dumps({"applied": True, "backup_dir": str(backup_dir.resolve()),
        "files": [public_report(plan) for plan in plans], "archive": repository.stats()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
