"""Online generation contract and failure handling, without real API calls."""
import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from answering import GenerationUnavailable, answer_question
from config import Settings
from main import create_app
from models import PertanyaanRequest


class GeminiTests(unittest.TestCase):
    def setUp(self):
        self.settings = replace(Settings(), llm_provider="gemini", answer_mode="auto",
                                gemini_api_key="test-secret", gemini_model="gemini-3.8-flash")
        self.req = PertanyaanRequest(pertanyaan="Jelaskan informasi pembicara.")
        self.sources = [{"id": "S1", "file": "notula.pdf", "halaman": 1,
                         "tanggal_rapat": "2026-10-07", "kutipan": "Pembicara: Meydina."}]

    def call(self, handler, settings=None, sources=None):
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await answer_question(settings or self.settings, client, self.req,
                                              self.sources if sources is None else sources)
        return asyncio.run(run())

    def response(self, paragraph=None, status="completed"):
        return httpx.Response(200, json={"status": status, "steps": [
            {"type": "thought", "content": [{"type": "text", "text": "private reasoning"}]},
            {"type": "model_output", "content": [{"type": "text", "text": json.dumps({
                "paragraf": [paragraph or {"teks": "Meydina", "sumber": ["S1"]}]})}]}],
            "usage": {"total_input_tokens": 100, "total_output_tokens": 20}})

    def test_request_and_citations(self):
        requests = []
        def handler(request):
            requests.append(request)
            return self.response()
        answer, meta = self.call(handler)
        self.assertEqual(answer, "Meydina [S1]")
        self.assertEqual(meta["answer_mode"], "gemini")
        self.assertEqual(meta["llm_prompt_tokens"], 100)
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(str(request.url), "https://generativelanguage.googleapis.com/v1beta/interactions")
        self.assertEqual(request.headers["x-goog-api-key"], "test-secret")
        self.assertNotIn("test-secret", str(request.url))
        body = json.loads(request.content)
        self.assertFalse(body["store"])
        self.assertNotIn("tools", body)
        self.assertEqual(json.loads(body["input"])["SUMBER"][0]["id"], "S1")

    def test_missing_key_never_calls_provider(self):
        def forbidden(request):
            self.fail("Missing key must not issue network requests")
        answer, meta = self.call(forbidden, replace(self.settings, gemini_api_key=""))
        self.assertEqual(meta["fallback_reason"], "api_key_missing")
        self.assertIn("Meydina", answer)

    def test_no_evidence_never_calls_provider(self):
        def forbidden(request):
            self.fail("No evidence must not issue network requests")
        _, meta = self.call(forbidden, sources=[])
        self.assertEqual(meta["answer_mode"], "no_evidence")

    def test_errors_use_quotes_without_retrying(self):
        for status, reason in [(400, "invalid_request"), (401, "api_key_invalid"),
                               (403, "api_key_invalid"), (404, "model_missing"), (429, "rate_limited")]:
            with self.subTest(status=status):
                requests = []
                def handler(request):
                    requests.append(request)
                    return httpx.Response(status, json={"error": "test-secret"})
                answer, meta = self.call(handler)
                self.assertEqual(meta["fallback_reason"], reason)
                self.assertEqual(meta["answer_mode"], "extractive")
                self.assertNotIn("test-secret", answer + str(meta))
                self.assertEqual(len(requests), 1)

    def test_incomplete_or_invalid_citations_use_quotes(self):
        for response in [self.response(status="failed"), self.response({"teks": "Meydina", "sumber": ["S99"]}),
                         self.response({"teks": "Meydina [S99]", "sumber": ["S1"]}),
                         httpx.Response(200, json={"status": "completed", "steps": []})]:
            with self.subTest(response=response):
                _, meta = self.call(lambda request: response)
                self.assertEqual(meta["answer_mode"], "extractive")

    def test_timeout_uses_quotes(self):
        async def slow(request):
            await asyncio.sleep(0.1)
            return self.response()
        _, meta = self.call(slow, replace(self.settings, gemini_timeout=0.01))
        self.assertEqual(meta["fallback_reason"], "llm_timeout")

    def test_forced_gemini_returns_failure(self):
        with self.assertRaises(GenerationUnavailable):
            self.call(lambda request: httpx.Response(429), replace(self.settings, answer_mode="gemini"))

    def test_gemini_status_does_not_preload_ollama_or_expose_key(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(replace(self.settings, data_dir=Path(directory), auto_import=False))
            with TestClient(app) as client:
                async def handler(request):
                    self.assertEqual(request.url.path, "/v1beta/models/gemini-3.8-flash")
                    return httpx.Response(200, json={"name": "models/gemini-3.8-flash"})
                app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
                try:
                    response = client.get("/status")
                    self.assertNotIn("test-secret", response.text)
                    self.assertTrue(response.json()["data"]["ai"]["model_ready"])
                    self.assertEqual(app.state.model_warmup, "disabled")
                finally:
                    client.portal.call(app.state.http_client.aclose)

    def test_missing_key_status_keeps_archive_available(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(replace(self.settings, data_dir=Path(directory), auto_import=False, gemini_api_key=""))
            with TestClient(app) as client:
                self.assertEqual(client.get("/health").status_code, 200)
                ai = client.get("/status").json()["data"]["ai"]
                self.assertFalse(ai["configured"])
                self.assertFalse(ai["model_ready"])
                self.assertEqual(ai["error"], "api_key_missing")
