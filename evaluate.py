"""Repeatable retrieval evaluation against actual PDFs, isolated from the live database."""
import argparse
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from config import ROOT, Settings
from database import Repository
from ingestion import import_datasets
from models import PertanyaanRequest
from retrieval import retrieve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Simpan laporan Markdown.")
    args = parser.parse_args()
    cases = json.loads((ROOT / "eval_cases.json").read_text(encoding="utf-8"))
    results = []
    with tempfile.TemporaryDirectory() as directory:
        settings = replace(Settings(), data_dir=Path(directory), dataset_dir=ROOT, semantic_search=False)
        repository = Repository(settings.db_path)
        repository.initialize()
        imports = import_datasets(repository, settings)
        if len(imports) != 4 or any("error" in result for result in imports):
            raise SystemExit("Evaluasi membutuhkan keempat PDF notulen asli yang dapat dibaca.")
        for case in cases:
            chunks, _ = retrieve(repository, settings, PertanyaanRequest(pertanyaan=case["query"]))
            text = "\n".join(chunk["konten_teks"] for chunk in chunks).casefold()
            meetings = {chunk["meeting_number"] for chunk in chunks}
            failures = []
            if case.get("no_evidence"):
                if chunks:
                    failures.append("Arsip tidak relevan dikembalikan")
            else:
                if not chunks:
                    failures.append("Tidak ada hasil")
                for expected in case.get("contains", []):
                    if expected.casefold() not in text:
                        failures.append(f"Bukti tidak ditemukan: {expected}")
                if not set(case.get("meetings", [])) <= meetings:
                    failures.append("Cakupan rapat kurang")
                if "only_meeting" in case and meetings != {case["only_meeting"]}:
                    failures.append("Filter rapat terbaru keliru")
                if "only_division" in case and any(c["divisi"] != case["only_division"] for c in chunks):
                    failures.append("Filter divisi keliru")
            results.append({"query": case["query"], "passed": not failures, "failures": failures})
        stats = repository.stats()
    passed = sum(result["passed"] for result in results)
    lines = ["# Evaluasi pencarian arsip", "", f"Hasil: **{passed}/{len(results)} kasus lulus**.", "",
        f"Dataset: {stats['total_documents']} PDF, {stats['total_pages']} halaman, {stats['total_chunks']} chunks.", "",
        "Mode: BM25, top 8. Data evaluasi diimpor ulang ke database sementara; database pengguna tidak diubah.", "",
        "| Pertanyaan | Hasil | Catatan |", "| --- | --- | --- |"]
    for result in results:
        lines.append(f"| {result['query']} | {'Lulus' if result['passed'] else 'Gagal'} | {'; '.join(result['failures']) or 'Bukti dan filter sesuai'} |")
    lines.extend(["", "Evaluasi ini mengukur keberadaan bukti di hasil pencarian dan kepatuhan filter, bukan akurasi semua jawaban AI.",
        "Kasus mencakup fakta, tanggal, divisi, rapat terbaru, perbandingan empat rapat, dan penolakan pertanyaan di luar arsip.",
        "Cakupan terbatas pada kasus yang dicantumkan di eval_cases.json; tambahkan kasus baru sesuai penggunaan nyata.", ""])
    report = "\n".join(lines)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    print(report)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
