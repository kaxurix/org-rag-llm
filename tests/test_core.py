import asyncio
import json
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import httpx
import pymupdf
from fastapi.testclient import TestClient

from answering import GenerationUnavailable, answer_question, explicit_role_answer, generation_context, preload_model
from config import ROOT, Settings
from database import Repository
from ingestion import InvalidPDF, chunk_pdf_smart, clean_text, import_datasets, ingest_pdf
from repair_datasets import plan_pdf
from main import create_app
from models import PertanyaanRequest
from retrieval import references, retrieve


def make_pdf(texts=None):
    with pymupdf.open() as document:
        for text in texts or ["Rapat ke\n04\nTanggal\n07 Oktober 2026\n1. Humas\nPembicara: Meydina\nJobdesk pembicara seminar."]:
            page = document.new_page()
            if text:
                page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=11)
        return document.tobytes()


class RepositoryFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = replace(Settings(), data_dir=Path(self.temp.name), auto_import=False,
                                answer_mode="extractive", semantic_search=False, api_key="", ollama_preload=False)
        self.repository = Repository(self.settings.db_path)
        self.repository.initialize()

    def ingest(self, pdf=None, **kwargs):
        return ingest_pdf(self.repository, self.settings, pdf or make_pdf(), "notula.pdf", **kwargs)


class StorageTests(RepositoryFixture):
    def test_repaired_pdf_replaces_existing_entry_and_preserves_id(self):
        original = make_pdf()
        existing = self.ingest(original)["document"]
        fixed = make_pdf(["Rapat ke\n04\nTanggal\n07 Oktober 2026\n1. Humas\nPembicara: Sari dan persiapan seminar."])
        from hashlib import sha256
        from ingestion import extract_pdf
        chunks, metadata = extract_pdf(fixed, self.settings, "Umum")
        metadata.update(checksum=sha256(fixed).hexdigest(), nama_file="notula.pdf", divisi="Umum", tahun=2026)
        document_id, changed = self.repository.save_document(metadata, fixed, chunks,
            replace_checksum=existing["checksum"])
        self.assertTrue(changed)
        self.assertEqual(document_id, existing["id"])
        self.assertEqual(self.repository.stats()["total_documents"], 1)
        self.assertIsNone(self.repository.find_checksum(existing["checksum"]))
        self.assertEqual(self.repository.document(document_id, True)["pdf"], fixed)
        self.assertEqual(retrieve(self.repository, self.settings, PertanyaanRequest(pertanyaan="Meydina"))[0], [])

    def test_import_preserves_pdf_and_metadata(self):
        pdf = make_pdf()
        result = self.ingest(pdf)
        document = self.repository.document(result["document"]["id"], include_pdf=True)
        self.assertEqual(document["pdf"], pdf)
        self.assertEqual(document["meeting_date"], "2026-10-07")
        self.assertEqual(document["meetings"], [{"meeting_number": 4, "meeting_date": "2026-10-07"}])

    def test_duplicate_bytes_do_not_duplicate_rows(self):
        pdf = make_pdf()
        self.ingest(pdf)
        first = self.repository.stats()
        duplicate = ingest_pdf(self.repository, self.settings, pdf, "another-name.pdf")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(first, self.repository.stats())

    def test_concurrent_duplicate_import(self):
        pdf = make_pdf()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.ingest(pdf), range(4)))
        self.assertEqual(sum(r["imported"] for r in results), 1)
        self.assertEqual(self.repository.stats()["total_documents"], 1)

    def test_reindex_replaces_chunks_and_fts(self):
        pdf = make_pdf()
        first = self.ingest(pdf)
        self.ingest(pdf, reindex=True)
        self.assertEqual(self.repository.stats()["total_chunks"], first["document"]["total_chunks"])
        with self.repository.connect() as conn:
            conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('integrity-check')")
        hits, _ = retrieve(self.repository, self.settings, PertanyaanRequest(pertanyaan="pembicara"))
        self.assertTrue(hits)

    def test_failed_transaction_leaves_no_partial_document(self):
        metadata = dict(checksum="broken", nama_file="broken.pdf", divisi="Umum", tahun=2026,
                        meeting_number=None, meeting_date=None, total_pages=1, empty_pages=[])
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository.save_document(metadata, b"pdf", [{"page_num": 1, "divisi": None, "konten_teks": "text"}])
        self.assertEqual(self.repository.stats()["total_documents"], 0)

    def test_backup_contains_pdf_and_search_index(self):
        pdf = make_pdf()
        result = self.ingest(pdf)
        backup = Path(self.temp.name) / "backup.sqlite3"
        self.repository.backup(backup)
        restored = Repository(backup)
        self.assertEqual(self.repository.stats(), restored.stats())
        self.assertEqual(restored.document(result["document"]["id"], True)["pdf"], pdf)
        self.assertTrue(retrieve(restored, self.settings, PertanyaanRequest(pertanyaan="pembicara"))[0])

    def test_concatenated_meetings_follow_each_page(self):
        pdf = make_pdf(["Rapat ke\n01\nTanggal\n20 Mei 2026\n1. Humas\nPembicara: Budi",
                        "Rapat ke\n03\nTanggal\n26 Agustus 2026\n1. Humas\nPembicara: Sari"])
        self.ingest(pdf)
        hits, _ = retrieve(self.repository, self.settings, PertanyaanRequest(pertanyaan="pembicara rapat ke-3"))
        self.assertTrue(hits)
        self.assertTrue(all(h["meeting_number"] == 3 and h["page_num"] == 2 for h in hits))
        self.assertIn("Sari", hits[0]["konten_teks"])

    def test_scan_only_pdf_is_rejected(self):
        with self.assertRaisesRegex(InvalidPDF, "OCR"):
            self.ingest(make_pdf([""]))

    def test_corrupt_pdf_is_rejected(self):
        for payload in (b"not a pdf", b"%PDF-1.7\ninvalid"):
            with self.subTest(payload=payload), self.assertRaises(InvalidPDF):
                self.ingest(payload)

    def test_mixed_pdf_reports_empty_pages(self):
        result = self.ingest(make_pdf(["", "1. Humas\nPembicara: Meydina dan pembahasan seminar."]))
        self.assertEqual(result["document"]["empty_pages"], [1])

    def test_unavailable_embedding_does_not_lose_pdf(self):
        class BrokenEncoder:
            def encode(self, texts):
                raise RuntimeError("model unavailable")
        result = self.ingest(semantic=BrokenEncoder())
        self.assertTrue(result["warning"])
        self.assertEqual(self.repository.stats()["total_documents"], 1)

    def test_safe_filename(self):
        result = ingest_pdf(self.repository, self.settings, make_pdf(), "../../private/notula.pdf")
        self.assertEqual(result["document"]["nama_file"], "notula.pdf")


class ChunkTests(unittest.TestCase):
    def test_long_line_is_bounded_without_losing_text(self):
        text = "a" * 4001
        chunks = chunk_pdf_smart(text, max_chars=600, overlap=100)
        self.assertTrue(all(len(c) <= 600 for c in chunks))
        self.assertEqual(len(chunks[0]) + sum(len(c) - 100 for c in chunks[1:]), len(text))

    def test_overlap_is_used(self):
        chunks = chunk_pdf_smart("0123456789" * 200, max_chars=600, overlap=100)
        self.assertEqual(chunks[0][-100:], chunks[1][:100])

    def test_short_important_text_is_not_discarded(self):
        self.assertEqual(chunk_pdf_smart("PJ: Echa"), ["PJ: Echa"])

    def test_bad_overlap_is_rejected(self):
        for overlap in (-1, 600, 601):
            with self.subTest(overlap=overlap), self.assertRaises(ValueError):
                chunk_pdf_smart("text", max_chars=600, overlap=overlap)

    def test_unicode_cleanup(self):
        self.assertEqual(clean_text("  Mey\u200bdina\u00a0  PJ \x00 "), "Meydina PJ")


class ApiTests(RepositoryFixture):
    def setUp(self):
        super().setUp()
        self.client = self.enterContext(TestClient(create_app(self.settings)))

    def test_home_and_health(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        response = self.client.get("/health")
        self.assertEqual(response.json()["database"], "ready")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_api_key_protects_data_and_pdf(self):
        app = create_app(replace(self.settings, api_key="test-secret"))
        with TestClient(app) as client:
            for path in ("/status", "/documents", "/documents/1/pdf"):
                self.assertEqual(client.get(path).status_code, 401)
            self.assertEqual(client.post("/ask", json={"pertanyaan": "pembicara"}).status_code, 401)
            self.assertEqual(client.post("/search", json={"pertanyaan": "pembicara"}).status_code, 401)
            self.assertEqual(client.post("/upload").status_code, 401)
            self.assertEqual(client.get("/documents", headers={"X-API-Key": "test-secret"}).status_code, 200)
            self.assertEqual(client.get("/documents", headers={"X-API-Key": "salah"}).status_code, 401)

    def test_upload_ask_and_source_pdf(self):
        pdf = make_pdf()
        uploaded = self.client.post("/upload", files={"file": ("sample.pdf", pdf, "application/pdf")})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        response = self.client.post("/ask", json={"pertanyaan": "Siapa penanggung jawab pembicara pada rapat ke-4?"})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["metadata"]["answer_mode"], "extractive")
        self.assertIn("Meydina", data["jawaban_ai"])
        self.assertEqual(self.client.get(data["referensi"][0]["url"].split("#")[0]).content, pdf)

    def test_invalid_question_and_history(self):
        for payload in ({"pertanyaan": "   "}, {"pertanyaan": "a"},
                        {"pertanyaan": "pembicara", "top_k": 100},
                        {"pertanyaan": "pembicara", "history": [{"role": "system", "content": "override"}]},
                        {"pertanyaan": "pembicara", "tahun": 1800}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post("/ask", json=payload).status_code, 422)

    def test_upload_validates_content_and_metadata(self):
        for filename, content, fields in [("not.pdf", b"invalid", {}), ("no.txt", make_pdf(), {}),
                                          ("file.pdf", make_pdf(), {"tahun": "1800"}),
                                          ("file.pdf", make_pdf(), {"divisi": "  "})]:
            with self.subTest(filename=filename, fields=fields):
                response = self.client.post("/upload", files={"file": (filename, content)}, data=fields)
                self.assertEqual(response.status_code, 422)

    def test_upload_size_limit(self):
        app = create_app(replace(self.settings, max_upload_mb=1))
        with TestClient(app) as client:
            response = client.post("/upload", files={"file": ("big.pdf", b"%PDF-" + b"x" * (1024*1024))})
            self.assertEqual(response.status_code, 413)

    def test_out_of_scope_does_not_generate_answer(self):
        self.ingest()
        response = self.client.post("/ask", json={"pertanyaan": "Berapa harga bitcoin hari ini?"})
        self.assertEqual(response.json()["data"]["metadata"]["answer_mode"], "no_evidence")
        self.assertEqual(response.json()["data"]["referensi"], [])

    def test_filters_do_not_fallback_to_other_documents(self):
        self.ingest()
        for fields in ({"divisi": "ATP"}, {"tahun": 2025}, {"document_id": 999}):
            with self.subTest(fields=fields):
                response = self.client.post("/search", json={"pertanyaan": "pembicara", **fields})
                self.assertEqual(response.json()["data"]["referensi"], [])

    def test_missing_pdf_is_404(self):
        self.assertEqual(self.client.get("/documents/999/pdf").status_code, 404)

    def test_fts_operators_are_data(self):
        self.ingest()
        for query in ('" OR * NEAR(', "pembicara'; DROP TABLE chunks; --"):
            self.assertEqual(self.client.post("/search", json={"pertanyaan": query}).status_code, 200)
        self.assertEqual(self.repository.stats()["total_documents"], 1)

    def test_busy_llm_does_not_block_search_or_empty_evidence(self):
        self.ingest()
        app = create_app(replace(self.settings, answer_mode="auto"))
        with TestClient(app) as client:
            app.state.generation_slots = asyncio.Semaphore(0)
            response = client.post("/ask", json={"pertanyaan": "pembicara"})
            self.assertEqual(response.json()["data"]["metadata"]["answer_mode"], "extractive")
            self.assertIn("pertanyaan lain", response.json()["data"]["metadata"]["warning"])
            response = client.post("/ask", json={"pertanyaan": "harga bitcoin"})
            self.assertEqual(response.json()["data"]["metadata"]["answer_mode"], "no_evidence")

    def test_explicit_judge_answer_bypasses_a_busy_llm(self):
        self.ingest(make_pdf(["Rapat ke\n04\nTanggal\n07 Oktober 2026\n1. Acara\n"
                              "Juri sudah fiks dengan Pak Ihsan dan menunggu Pak Irham yang belum pasti hadir."]))
        app = create_app(replace(self.settings, answer_mode="auto"))
        with TestClient(app) as client:
            app.state.generation_slots = asyncio.Semaphore(0)
            response = client.post("/ask", json={"pertanyaan": "Siapa yang akan menjadi juri?"})
            self.assertEqual(response.status_code, 200)
            data = response.json()["data"]
            self.assertEqual(data["metadata"]["answer_mode"], "source_match")
            self.assertTrue(data["metadata"]["llm_skipped"])
            self.assertIn("belum pasti hadir", data["jawaban_ai"])


class AnsweringTests(unittest.TestCase):
    def setUp(self):
        self.settings = replace(Settings(), answer_mode="auto", llm_provider="ollama", ollama_model="test:7b")
        self.req = PertanyaanRequest(pertanyaan="Jelaskan informasi pembicara.")
        self.sources = [{"id": "S1", "file": "notula.pdf", "halaman": 1,
                         "tanggal_rapat": "2026-10-07", "kutipan": "Pembicara: Meydina."}]

    def call(self, transport, settings=None, sources=None):
        async def run():
            async with httpx.AsyncClient(transport=transport) as client:
                return await answer_question(settings or self.settings, client, self.req,
                                              self.sources if sources is None else sources)
        return asyncio.run(run())

    def model_transport(self, answer):
        def handler(request):
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "test:7b"}]})
            return httpx.Response(200, json={"message": {"content": json.dumps(answer)}})
        return httpx.MockTransport(handler)

    def test_no_evidence_never_calls_llm(self):
        def forbidden(request):
            self.fail("LLM must not be called without evidence")
        answer, meta = self.call(httpx.MockTransport(forbidden), sources=[])
        self.assertEqual(meta["answer_mode"], "no_evidence")

    def test_connection_failure_uses_quotes(self):
        def unavailable(request):
            raise httpx.ConnectError("offline", request=request)
        answer, meta = self.call(httpx.MockTransport(unavailable))
        self.assertIn("Pembicara: Meydina.", answer)
        self.assertEqual(meta["answer_mode"], "extractive")

    def test_valid_citations_allow_generation(self):
        answer, meta = self.call(self.model_transport({"paragraf": [{"teks": "Meydina", "sumber": ["S1"]}]}))
        self.assertEqual(answer, "Meydina [S1]")
        self.assertEqual(meta["model_llm"], "test:7b")

    def test_invalid_citations_fall_back(self):
        for paragraph in ({"teks": "Meydina", "sumber": []}, {"teks": "Meydina", "sumber": ["S99"]},
                          {"teks": "Meydina [S99]", "sumber": ["S1"]}):
            with self.subTest(paragraph=paragraph):
                result, meta = self.call(self.model_transport({"paragraf": [paragraph]}))
                self.assertEqual(meta["answer_mode"], "extractive")

    def test_invalid_model_output_falls_back(self):
        for payload in ([], {"paragraf": 42}, {"paragraf": []}, {},
                        {"paragraf": [{"teks": " ", "sumber": ["S1"]}]}):
            with self.subTest(payload=payload):
                _, meta = self.call(self.model_transport(payload))
                self.assertEqual(meta["answer_mode"], "extractive")

    def test_strict_mode_returns_failure(self):
        with self.assertRaises(GenerationUnavailable):
            self.call(self.model_transport({"paragraf": [{"teks": "Tanpa sumber", "sumber": []}]}),
                      replace(self.settings, answer_mode="ollama"))

    def test_http_error_uses_quotes(self):
        _, meta = self.call(httpx.MockTransport(lambda req: httpx.Response(500)))
        self.assertEqual(meta["answer_mode"], "extractive")

    def test_wall_clock_deadline_covers_multiple_http_requests(self):
        async def slow(request):
            await asyncio.sleep(0.04)
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "test:7b"}]})
            return httpx.Response(200, json={"message": {"content": "{}"}})
        started = time.perf_counter()
        _, metadata = self.call(httpx.MockTransport(slow), replace(self.settings, ollama_timeout=0.06))
        self.assertEqual(metadata["fallback_reason"], "llm_timeout")
        self.assertLess(time.perf_counter() - started, 0.5)

    def test_explicit_judge_statement_never_calls_llm(self):
        def forbidden(request):
            self.fail("An explicit archive statement should not wait for Ollama")
        self.req = PertanyaanRequest(pertanyaan="Siapa yang akan menjadi juri?")
        sources = [{**self.sources[0], "kutipan": "● Juri sudah fiks dengan Pak Ihsan dan menunggu Pak Irham\n"
                    "yang belum pasti hadir.\n● Juri eksternal masih difollow up."}]
        answer, metadata = self.call(httpx.MockTransport(forbidden), sources=sources)
        self.assertEqual(metadata["answer_mode"], "source_match")
        self.assertIn("Pak Ihsan", answer)
        self.assertIn("belum pasti hadir", answer)
        self.assertNotIn("eksternal", answer)
        self.assertIn("[S1]", answer)

    def test_jobdesk_coordinator_is_not_claimed_to_be_a_judge(self):
        self.req = PertanyaanRequest(pertanyaan="Siapa yang menjadi juri?")
        sources = [{**self.sources[0], "kutipan": "1. Humas\nPembagian Job desk:\n● Juri: Echa & Radit."}]
        self.assertIsNone(explicit_role_answer(self.req, sources))
        coordinator = PertanyaanRequest(pertanyaan="Siapa penanggung jawab juri?")
        answer, metadata = explicit_role_answer(coordinator, sources)
        self.assertIn("pembagian jobdesk", answer)
        self.assertIn("Echa & Radit", answer)

    def test_forced_ollama_does_not_use_direct_answer(self):
        self.req = PertanyaanRequest(pertanyaan="Siapa pembicara?")
        answer, metadata = self.call(self.model_transport({"paragraf": [{"teks": "Meydina", "sumber": ["S1"]}]}),
                                    replace(self.settings, answer_mode="ollama"))
        self.assertEqual(metadata["answer_mode"], "ollama")

    def test_context_and_history_are_bounded(self):
        req = PertanyaanRequest(pertanyaan="Bandingkan semua pembahasan juri", history=[
            {"role": "user", "content": "a" * 4000} for _ in range(20)])
        sources = [{**self.sources[0], "id": f"S{i}", "kutipan": "juri " * 2000} for i in range(1, 13)]
        context, history = generation_context(self.settings, req, sources)
        self.assertEqual(len(context), self.settings.ollama_max_sources)
        self.assertTrue(all(len(source["teks"]) <= self.settings.ollama_source_chars for source in context))
        self.assertLessEqual(sum(len(message["content"]) for message in history), 1200)

    def test_model_cannot_cite_source_omitted_from_prompt(self):
        sources = [{**self.sources[0], "id": f"S{i}"} for i in range(1, 6)]
        _, metadata = self.call(self.model_transport({"paragraf": [{"teks": "Tidak didukung", "sumber": ["S5"]}]}),
                                sources=sources)
        self.assertEqual(metadata["fallback_reason"], "invalid_citations")

    def test_preload_and_generation_use_matching_load_options(self):
        requests = []
        def handler(request):
            if request.url.path == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "test:7b"}]})
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"message": {"content": json.dumps(
                {"paragraf": [{"teks": "Meydina", "sumber": ["S1"]}]})}})
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                await preload_model(self.settings, client)
                await answer_question(self.settings, client, self.req, self.sources)
        asyncio.run(run())
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["messages"], [])
        self.assertEqual(requests[0]["options"], requests[1]["options"])


class RealDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.settings = replace(Settings(), data_dir=Path(cls.temp.name), dataset_dir=ROOT,
                               auto_import=False, semantic_search=False)
        cls.repository = Repository(cls.settings.db_path)
        cls.repository.initialize()
        cls.results = import_datasets(cls.repository, cls.settings)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_four_datasets_and_57_pages(self):
        self.assertEqual(len(self.results), 4)
        self.assertFalse(any("error" in r for r in self.results))
        self.assertEqual(self.repository.stats()["total_pages"], 57)

    def test_each_repaired_pdf_contains_only_its_own_meeting(self):
        for number, document in enumerate(self.repository.documents(), 1):
            with self.subTest(document=document["nama_file"]):
                self.assertEqual([meeting["meeting_number"] for meeting in document["meetings"]], [number])

    def test_closing_paragraphs_survive_shared_page_repair(self):
        with pymupdf.open(ROOT / "NOTULA RABES STECH 2026 1.pdf") as document:
            self.assertIn("wassalam", document[-1].get_text().lower())
            self.assertNotIn("04 Juli 2026", document[-1].get_text())
        with pymupdf.open(ROOT / "NOTULA RABES STECH 2026 2.pdf") as document:
            self.assertIn("Untuk sop ini aku setuju dengan yona, jadi bisa disahkan", document[-1].get_text())
            self.assertNotIn("26 Agustus 2026", document[-1].get_text())

    def test_meeting_four_pic_is_meydina(self):
        hits, _ = retrieve(self.repository, self.settings, PertanyaanRequest(
            pertanyaan="Siapa penanggung jawab pembicara pada rapat ke-4?"))
        self.assertIn("Meydina", hits[0]["konten_teks"])
        self.assertEqual(hits[0]["meeting_number"], 4)

    def test_comparison_covers_all_four_meetings(self):
        hits, _ = retrieve(self.repository, self.settings, PertanyaanRequest(
            pertanyaan="Bandingkan perkembangan sponsorship pada semua rapat."))
        self.assertEqual({h["meeting_number"] for h in hits}, {1, 2, 3, 4})

    def test_latest_never_uses_older_meeting(self):
        hits, _ = retrieve(self.repository, self.settings, PertanyaanRequest(pertanyaan="pembicara terbaru"))
        self.assertTrue(hits)
        self.assertTrue(all(h["meeting_date"] == "2026-10-07" for h in hits))

    def test_division_atp_does_not_include_other_divisions(self):
        hits, _ = retrieve(self.repository, self.settings, PertanyaanRequest(pertanyaan="Apa kendala divisi ATP pada rapat ke-2?"))
        self.assertTrue(hits)
        self.assertTrue(all(h["divisi"] == "ATP" and h["meeting_number"] == 2 for h in hits))

    def test_sekbend_aliases_are_detected(self):
        hits, _ = retrieve(self.repository, self.settings, PertanyaanRequest(pertanyaan="Apa progress Sekbend pada rapat ke-4?"))
        self.assertTrue(hits)
        self.assertTrue(all(h["divisi"] == "Sekbend" for h in hits))

    def test_unknown_subject_does_not_match_generic_price(self):
        hits, _ = retrieve(self.repository, self.settings, PertanyaanRequest(pertanyaan="Berapa harga bitcoin hari ini?"))
        self.assertEqual(hits, [])

    def test_year_in_question_is_a_filter(self):
        hits, _ = retrieve(self.repository, self.settings, PertanyaanRequest(pertanyaan="perkembangan sponsor tahun 2025"))
        self.assertEqual(hits, [])

    def test_user_judge_question_prefers_latest_confirmed_status(self):
        req = PertanyaanRequest(pertanyaan="Siapa yang akan menjadi juri?")
        hits, metadata = retrieve(self.repository, self.settings, req)
        self.assertTrue(hits)
        self.assertEqual(metadata["as_of"], "2026-10-07")
        self.assertTrue(all(hit["meeting_number"] == 4 for hit in hits))
        self.assertEqual(hits[0]["page_num"], 12)
        self.assertIn("pak ihsan", hits[0]["konten_teks"].lower())
        self.assertTrue(any("pak Axl" in hit["konten_teks"] for hit in hits))

    def test_explicit_historical_judge_question_keeps_its_meeting(self):
        hits, metadata = retrieve(self.repository, self.settings,
            PertanyaanRequest(pertanyaan="Siapa yang akan menjadi juri pada rapat ke-1?"))
        self.assertTrue(hits)
        self.assertTrue(all(hit["meeting_number"] == 1 for hit in hits))

    def test_judge_comparison_keeps_all_meetings(self):
        hits, metadata = retrieve(self.repository, self.settings,
            PertanyaanRequest(pertanyaan="Siapa saja juri pada semua rapat?"))
        self.assertEqual({hit["meeting_number"] for hit in hits}, {1, 2, 3, 4})


class SemanticTests(RepositoryFixture):
    class Encoder:
        def encode(self, texts):
            return [[1.0, 0.0] for text in texts]

    def test_semantic_search_preserves_filters(self):
        self.ingest(semantic=self.Encoder())
        settings = replace(self.settings, semantic_search=True)
        hits, metadata = retrieve(self.repository, settings,
            PertanyaanRequest(pertanyaan="narasumber", divisi="ATP"), self.Encoder())
        self.assertEqual(hits, [])

    def test_semantic_model_mismatch_uses_bm25(self):
        self.ingest(semantic=self.Encoder())
        settings = replace(self.settings, semantic_search=True, embedding_model="different-model")
        hits, metadata = retrieve(self.repository, settings,
            PertanyaanRequest(pertanyaan="pembicara"), self.Encoder())
        self.assertTrue(hits)
        self.assertEqual(metadata["retrieval"], "bm25")
        self.assertIsNotNone(metadata["warning"])

    def test_hybrid_fuses_semantic_and_keyword_results(self):
        self.ingest(semantic=self.Encoder())
        hits, metadata = retrieve(self.repository, self.settings,
            PertanyaanRequest(pertanyaan="narasumber"), self.Encoder())
        self.assertTrue(hits)
        self.assertEqual(metadata["retrieval"], "hybrid")


class PDFRepairTests(unittest.TestCase):
    def test_single_meeting_pdf_stays_byte_identical(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "notula.pdf"
            pdf = make_pdf()
            path.write_bytes(pdf)
            result = plan_pdf(path, 4)
            self.assertFalse(result["changed"])
            self.assertEqual(result["pdf"], pdf)
            self.assertEqual(path.read_bytes(), pdf)

    def test_wrong_meeting_header_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "notula.pdf"
            pdf = make_pdf()
            path.write_bytes(pdf)
            with self.assertRaises(ValueError):
                plan_pdf(path, 1)
            self.assertEqual(path.read_bytes(), pdf)

    def test_shared_page_keeps_closing_text_and_removes_later_meeting(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "notula.pdf"
            pdf = make_pdf(["Rapat ke\n01\nTanggal\n20 Mei 2026\n1. Humas\nPembahasan rapat pertama.",
                "Penutup rapat pertama tetap utuh." + "\n" * 8 +
                "Kegiatan\nRapat Besar S-TECH 2026\nRapat ke\n02\nTanggal\n04 Juli 2026\nMateri rapat kedua."])
            path.write_bytes(pdf)
            result = plan_pdf(path, 1)
            self.assertTrue(result["changed"])
            with pymupdf.open(stream=result["pdf"], filetype="pdf") as document:
                self.assertEqual(len(document), 2)
                self.assertIn("Penutup rapat pertama tetap utuh.", document[-1].get_text())
                self.assertNotIn("Materi rapat kedua", document[-1].get_text())
                self.assertNotIn("04 Juli 2026", document[-1].get_text())
            self.assertEqual(path.read_bytes(), pdf)


if __name__ == "__main__":
    unittest.main()
