import asyncio
import hmac
import logging
import sqlite3
import time
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from answering import GEMINI_API, GenerationUnavailable, answer_question, explicit_role_answer, extractive_answer, preload_model
from config import ROOT, Settings
from database import Repository
from ingestion import InvalidPDF, import_datasets, ingest_pdf
from models import PertanyaanRequest
from retrieval import SemanticEncoder, references, retrieve

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    repository = Repository(settings.db_path)
    semantic = SemanticEncoder(settings) if settings.semantic_search else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_in_threadpool(repository.initialize)
        app.state.import_results = []
        if settings.auto_import:
            app.state.import_results = await run_in_threadpool(import_datasets, repository, settings, semantic)
        async with httpx.AsyncClient(trust_env=False, limits=httpx.Limits(max_connections=10)) as client:
            app.state.http_client = client
            app.state.generation_slots = asyncio.Semaphore(1)
            app.state.model_warmup = "disabled"

            async def warmup():
                async with app.state.generation_slots:
                    app.state.model_warmup = "loading"
                    try:
                        await preload_model(settings, client)
                        app.state.model_warmup = "ready"
                    except Exception as exc:
                        app.state.model_warmup = "unavailable"
                        logger.info("Pemuatan awal AI belum berhasil: %s", type(exc).__name__)

            task = asyncio.create_task(warmup()) if (settings.provider == "ollama" and settings.ollama_preload
                                                     and settings.answer_mode != "extractive") else None
            try:
                yield
            finally:
                if task:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task

    app = FastAPI(title="CampusOrg · Soedirman Technophoria", version="2.0.0", lifespan=lifespan,
                  description="Pencarian notulen dengan rujukan halaman dan AI Gemini atau Ollama.")
    app.state.repository = repository
    app.state.settings = settings

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if request.url.path == "/upload":
            try:
                length = int(request.headers.get("Content-Length", "0"))
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Content-Length tidak valid."})
            if length > (settings.max_upload_mb + 1) * 1024 * 1024:
                return JSONResponse(status_code=413, content={"detail": f"Ukuran PDF maksimal {settings.max_upload_mb} MB."})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'")
        if request.url.path in {"/docs", "/redoc"}:
            # FastAPI's bundled documentation HTML uses inline initialization and CDN assets.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; font-src 'self' https://fonts.gstatic.com; "
                "connect-src 'self'; worker-src blob:; object-src 'none'; base-uri 'self'")
        return response

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        logger.exception("Database gagal", exc_info=exc)
        return JSONResponse(status_code=503, content={"detail": "Database belum siap. Coba kembali dan periksa log server."})

    async def authorized(request: Request):
        if settings.api_key and not hmac.compare_digest(
                request.headers.get("X-API-Key", "").encode(), settings.api_key.encode()):
            raise HTTPException(401, "API key diperlukan atau tidak valid.")

    protected = [Depends(authorized)]

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/health")
    async def health():
        await run_in_threadpool(repository.stats)
        return {"status": "ok", "database": "ready"}

    @app.get("/status", dependencies=protected)
    async def status(request: Request):
        stats = await run_in_threadpool(repository.stats)
        ollama = {"available": False, "model": settings.ollama_model, "model_ready": False,
                  "model_loaded": False, "processor": None, "warmup": request.app.state.model_warmup}
        if settings.provider == "ollama" and settings.answer_mode != "extractive":
            try:
                result = await request.app.state.http_client.get(settings.ollama_base_url + "/api/tags", timeout=2)
                result.raise_for_status()
                names = {m.get("name") for m in result.json().get("models", [])}
                ollama.update(available=True, model_ready=(settings.ollama_model in names or
                                                          settings.ollama_model + ":latest" in names))
                running = await request.app.state.http_client.get(settings.ollama_base_url + "/api/ps", timeout=2)
                running.raise_for_status()
                model = next((model for model in running.json().get("models", []) if model.get("name") in
                    {settings.ollama_model, settings.ollama_model + ":latest"}), None)
                if model:
                    ollama.update(model_loaded=True, processor="gpu" if model.get("size_vram", 0) > 0 else "cpu",
                                  context_tokens=model.get("context_length"))
            except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                pass
        ai = {"provider": settings.provider, "model": settings.ollama_model,
              "configured": True, "available": ollama["available"], "model_ready": ollama["model_ready"]}
        if settings.provider == "gemini":
            configured = bool(settings.gemini_api_key.strip())
            ai.update(model=settings.gemini_model, configured=configured, available=False, model_ready=False,
                      error="api_key_missing" if not configured else None)
            if configured and settings.answer_mode != "extractive":
                try:
                    response = await request.app.state.http_client.get(
                        GEMINI_API + "/models/" + settings.gemini_model,
                        headers={"x-goog-api-key": settings.gemini_api_key}, timeout=3)
                    response.raise_for_status()
                    ai.update(available=True, model_ready=True)
                except httpx.HTTPError:
                    ai["error"] = "provider_unavailable"
        errors = [{"file": r["file"], "error": r["error"]} for r in request.app.state.import_results if "error" in r]
        warnings = [{"file": r["file"], "warning": r["warning"]} for r in request.app.state.import_results if r.get("warning")]
        return {"status": "success", "data": {**stats, "ollama": ollama, "ai": ai,
                "answer_mode": settings.answer_mode, "semantic_enabled": settings.semantic_search,
                "max_upload_mb": settings.max_upload_mb, "import_errors": errors, "import_warnings": warnings}}

    @app.get("/documents", dependencies=protected)
    def documents():
        return {"status": "success", "data": repository.documents()}

    @app.get("/documents/{document_id}/pdf", dependencies=protected)
    def document_pdf(document_id: int):
        document = repository.document(document_id, include_pdf=True)
        if not document:
            raise HTTPException(404, "Dokumen tidak ditemukan.")
        return Response(document["pdf"], media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="arsip-{document_id}.pdf"'})

    @app.post("/upload", dependencies=protected)
    async def upload(file: UploadFile = File(...), divisi: str = Form("Umum", min_length=1, max_length=100),
                     tahun: int = Form(2026, ge=2000, le=2100)):
        try:
            limit = settings.max_upload_mb * 1024 * 1024
            content = bytearray()
            while block := await file.read(1024 * 1024):
                content.extend(block)
                if len(content) > limit:
                    raise HTTPException(413, f"Ukuran PDF maksimal {settings.max_upload_mb} MB.")
            result = await run_in_threadpool(ingest_pdf, repository, settings, bytes(content),
                                             file.filename or "", divisi, tahun, semantic)
            document = result["document"]
            return {"status": "success", "message": "Dokumen sudah terindeks." if result["duplicate"] else "Dokumen berhasil diimpor.",
                "data": {**document, "nama_file": document["nama_file"], "kategori": document["divisi"],
                    "tahun_dokumen": document["tahun"], "total_chunks_tersimpan": document["total_chunks"],
                    "duplicate": result["duplicate"], "warning": result.get("warning")}}
        except InvalidPDF as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            await file.close()

    @app.post("/search", dependencies=protected)
    async def search(req: PertanyaanRequest):
        chunks, metadata = await run_in_threadpool(retrieve, repository, settings, req, semantic)
        return {"status": "success", "data": {"referensi": references(chunks), "metadata": metadata}}

    @app.post("/ask", dependencies=protected)
    async def ask(req: PertanyaanRequest, request: Request):
        start = time.perf_counter()
        # A short follow-up may reuse the last user's topic, never an assistant's claims.
        retrieval_req = req
        followup = any(word in req.pertanyaan.lower().split() for word in ("itu", "tersebut", "mereka", "bagaimana?"))
        if followup and req.history:
            prior = next((m.content for m in reversed(req.history) if m.role == "user"), "")
            if prior:
                retrieval_req = req.model_copy(update={"pertanyaan": req.pertanyaan + " " + prior[:600]})
        chunks, retrieval_metadata = await run_in_threadpool(retrieve, repository, settings, retrieval_req, semantic)
        retrieval_ms = round((time.perf_counter() - start) * 1000)
        sources = references(chunks)
        try:
            direct = explicit_role_answer(req, sources) if settings.answer_mode == "auto" else None
            if direct:
                answer, generation_metadata = direct
            elif not sources or settings.answer_mode == "extractive":
                answer, generation_metadata = await answer_question(settings, request.app.state.http_client, req, sources)
            else:
                try:
                    await asyncio.wait_for(request.app.state.generation_slots.acquire(), timeout=0.1)
                except TimeoutError:
                    if settings.answer_mode in {"ollama", "gemini"}:
                        raise HTTPException(503, "AI sedang memproses pertanyaan lain. Coba kembali sebentar lagi.")
                    answer = extractive_answer(sources, req)
                    warming = request.app.state.model_warmup == "loading"
                    generation_metadata = {"answer_mode": "extractive", "model_llm": None,
                        "warning": "AI sedang disiapkan; kutipan asli ditampilkan." if warming else
                            "AI sedang memproses pertanyaan lain; kutipan asli ditampilkan.",
                        "fallback_reason": "llm_warming" if warming else "llm_busy"}
                else:
                    try:
                        answer, generation_metadata = await answer_question(settings, request.app.state.http_client, req, sources)
                    finally:
                        request.app.state.generation_slots.release()
        except GenerationUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        warnings = [m["warning"] for m in (retrieval_metadata, generation_metadata) if m.get("warning")]
        return {"status": "success", "message": "Pencarian arsip selesai.", "data": {
            "query_asli": req.pertanyaan, "jawaban_ai": answer, "referensi": sources,
            "metadata": {**retrieval_metadata, **generation_metadata, "warning": " ".join(warnings) or None,
                "retrieval_ms": retrieval_ms,
                "total_referensi_ditemukan": len(sources), "duration_ms": round((time.perf_counter() - start) * 1000)}}}

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app


app = create_app()
