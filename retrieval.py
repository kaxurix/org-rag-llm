"""FTS5/BM25 retrieval with optional multilingual vectors and explicit filters."""
import json
import difflib
import logging
import math
import re
import threading

from config import Settings
from database import Repository
from models import PertanyaanRequest
from ingestion import DIVISIONS

logger = logging.getLogger(__name__)
STOPWORDS = set("""apa apakah siapa siapakah berapa berapakah kapan kapankah dimana bagaimana mengapa
kenapa yang dan atau di ke dari pada untuk dengan dalam tentang terkait mengenai adalah ada
itu ini tersebut nya saya aku kami kita kamu anda tolong coba jelaskan sebutkan tuliskan
berikan tampilkan carikan cari ingin tahu dong ya apakah saja masih sudah belum telah
menurut berdasarkan notula notulen arsip dokumen rapat rabes besar stech s tech soedirman
technophoria tahun acara kegiatan sebuah secara semua seluruh masing masingnya ringkas
ringkasan rangkum rangkuman bandingkan perbandingan perkembangan perubahan antar antara
terbaru terakhir terkini pertama kedua ketiga keempat satu dua tiga empat lalu sebelumnya
hingga sampai saat sekarang juga bisa dapat oleh apa pun serta lebih lanjut ada banyak
divisi jawab hari saja ditanyakan informasi informasinya status akan menjadi seorang sebagai
nantinya nanti bakal bakalan singkat ringkasnya rinci detail lengkap""".split())
SYNONYMS = [
    {"sponsor", "sponsorship", "sponsoran"},
    {"kendala", "hambatan", "masalah", "kesulitan"},
    {"progres", "progress", "perkembangan"},
    {"jobdesk", "job", "tugas", "tanggung", "penanggung", "pj", "pic", "bertanggung", "mengurus", "menangani"},
    {"venue", "lokasi", "tempat"},
    {"pembicara", "narasumber", "speaker"},
    {"medpart", "partner", "partnership"},
    {"anggaran", "rab", "biaya", "budget", "dana"},
    {"tanggal", "jadwal", "pelaksanaan", "dilaksanakan", "kapan"},
    {"ditetapkan", "dipilih", "fiksasi", "fiks", "fix", "memfiksasi", "ditentukan"},
    {"pendaftaran", "pendaftar", "peserta", "registrasi"},
]


class SemanticEncoder:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = None
        self.lock = threading.Lock()

    def encode(self, texts: list[str]) -> list[list[float]]:
        with self.lock:
            if self.model is None:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer(self.settings.embedding_model,
                    local_files_only=self.settings.embedding_local_only)
            return self.model.encode(texts, normalize_embeddings=True, batch_size=32,
                                     show_progress_bar=False).tolist()


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", text.lower(), flags=re.UNICODE))


def query_groups(query: str) -> list[set[str]]:
    if re.search(r"\bkapan\b", query, re.I):
        query += " tanggal"
    query = re.sub(r"(?:rapat|rabes)(?:\s+besar)?\s*(?:ke\s*[-:]?\s*)?\d+", " ", query, flags=re.I)
    query = re.sub(r"\bdivisi\s+(?:" + "|".join(DIVISIONS) + r")\b", " ", query, flags=re.I)
    tokens = sorted(t for t in tokenize(query) if t not in STOPWORDS and len(t) > 1 and not t.isdigit())
    groups = []
    for token in tokens[:24]:
        group = next((synonyms for synonyms in SYNONYMS if token in synonyms), {token})
        if group not in groups:
            groups.append(group)
    return groups


def build_filters(req: PertanyaanRequest):
    conditions, parameters = [], []
    division = req.divisi
    if not division:
        explicit = re.search(r"\bdivisi\s+(" + "|".join(DIVISIONS) + r")\b", req.pertanyaan, re.I)
        if explicit:
            division = DIVISIONS[explicit[1].lower()]
        else:
            division = next((DIVISIONS[token] for token in tokenize(req.pertanyaan)
                if token in DIVISIONS and token != "acara"), None)
    if division:
        division = DIVISIONS.get(division.lower(), division)
        conditions.append("(c.divisi = ? COLLATE NOCASE OR d.divisi = ? COLLATE NOCASE)")
        parameters.extend([division, division])
    requested_year = re.search(r"\b(20\d{2})\b", req.pertanyaan)
    year = req.tahun or (int(requested_year[1]) if requested_year else None)
    if year:
        conditions.append("coalesce(CAST(substr(c.meeting_date,1,4) AS INTEGER),d.tahun) = ?")
        parameters.append(year)
    if req.document_id:
        conditions.append("d.id = ?")
        parameters.append(req.document_id)
    number = re.search(r"(?:rapat|rabes)(?:\s+besar)?\s*(?:ke\s*[-:]?\s*)?(\d{1,3})\b", req.pertanyaan, re.I)
    ordinal = re.search(r"(?:rapat|rabes)(?:\s+besar)?\s+(pertama|kedua|ketiga|keempat)\b", req.pertanyaan, re.I)
    if number or ordinal:
        value = int(number[1]) if number else {"pertama": 1, "kedua": 2, "ketiga": 3, "keempat": 4}[ordinal[1].lower()]
        conditions.append("c.meeting_number = ?")
        parameters.append(value)
    return conditions, parameters


def person_question(query: str) -> bool:
    return bool(re.search(r"\bsiapa(?:kah)?\b", query, re.I))


def comparison_question(query: str) -> bool:
    return bool(re.search(r"\b(bandingkan|perbandingan|perkembangan|perubahan|antar|semua|seluruh|riwayat)\b", query, re.I))


def retrieve(repository: Repository, settings: Settings, req: PertanyaanRequest, semantic=None):
    groups = query_groups(req.pertanyaan)
    if not groups:
        return [], {"retrieval": "bm25", "warning": None}
    conditions, parameters = build_filters(req)
    columns = "c.*,d.nama_file,d.tahun,d.meeting_number source_meeting_number"
    join = " FROM chunks c JOIN documents d ON d.id=c.document_id "
    explicit_latest = bool(re.search(r"\b(terbaru|terakhir|terkini)\b", req.pertanyaan, re.I))
    compare = comparison_question(req.pertanyaan)
    historical = bool(re.search(r"\b(pertama|kedua|ketiga|keempat|awal|dulu|sebelumnya)\b", req.pertanyaan, re.I))
    specific_meeting = any("c.meeting_number" in condition for condition in conditions)
    implicit_latest = person_question(req.pertanyaan) and not (compare or historical or specific_meeting)
    latest = explicit_latest or implicit_latest
    as_of = None
    with repository.connect() as conn:
        if latest:
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            row = conn.execute("SELECT max(c.meeting_date)" + join + where, parameters).fetchone()
            if row[0]:
                as_of = row[0]
                conditions.append("c.meeting_date=?")
                parameters.append(row[0])
        where = " AND " + " AND ".join(conditions) if conditions else ""
        # Only alphanumeric tokens reach MATCH; user FTS operators are never executed.
        expression = " OR ".join('"' + word + '"' for group in groups for word in sorted(group))
        rows = conn.execute("SELECT " + columns + ", bm25(chunks_fts, 1.0, 0.35) bm25_score" + join +
            " JOIN chunks_fts ON chunks_fts.rowid=c.id WHERE chunks_fts MATCH ?" + where +
            " ORDER BY bm25_score, c.id LIMIT 120", [expression, *parameters]).fetchall()
        candidates = {row["id"]: {**dict(row), "rrf": 1 / (60 + rank)} for rank, row in enumerate(rows, 1)}
        warning = None
        strategy = "bm25"
        if semantic is not None:
            try:
                vector = semantic.encode([req.pertanyaan])[0]
                semantic_rows = conn.execute("SELECT " + columns + join +
                    " WHERE c.embedding_model=? AND c.embedding IS NOT NULL" + where,
                    [settings.embedding_model, *parameters]).fetchall()
                scored = []
                for row in semantic_rows:
                    embedding = json.loads(row["embedding"])
                    if len(embedding) != len(vector):
                        continue
                    denominator = math.sqrt(sum(x*x for x in vector) * sum(x*x for x in embedding))
                    score = sum(x*y for x, y in zip(vector, embedding)) / denominator if denominator else 0
                    if score >= 0.58:
                        scored.append((score, dict(row)))
                for rank, (score, row) in enumerate(sorted(scored, key=lambda pair: pair[0], reverse=True)[:60], 1):
                    candidate = candidates.setdefault(row["id"], {**row, "rrf": 0})
                    candidate["rrf"] += 1 / (60 + rank)
                    candidate["semantic_score"] = score
                strategy = "hybrid" if semantic_rows else "bm25"
                if not semantic_rows:
                    warning = "Belum ada embedding untuk model aktif. Jalankan ingest.py --reindex."
            except Exception:
                logger.exception("Pencarian semantik gagal; menggunakan BM25")
                warning = "Pencarian semantik tidak tersedia; hasil menggunakan pencarian kata kunci."

    qualified = []
    # Unknown subjects (e.g. bitcoin) must not match generic words such as "harga".
    # Require each query concept to exist among the filtered candidate texts.
    corpus_tokens = set()
    for candidate in candidates.values():
        corpus_tokens.update(tokenize(candidate["konten_teks"] + " " + candidate["divisi"]))
    missing_concepts = any(not group & corpus_tokens for group in groups)
    for candidate in candidates.values():
        tokens = tokenize(candidate["konten_teks"] + " " + candidate["divisi"])
        coverage = sum(bool(group & tokens) for group in groups) / len(groups)
        minimum = 1.0 if len(groups) <= 2 else 0.6
        if (missing_concepts or coverage < minimum) and candidate.get("semantic_score", 0) < 0.65:
            continue
        candidate["coverage"] = coverage
        # Coverage prevents a single frequent keyword from outranking a precise match.
        candidate["score"] = candidate["rrf"] * (0.4 + 0.6 * coverage)
        if re.search(r"\b(progres|progress|perkembangan)\b", req.pertanyaan, re.I):
            for group in groups:
                topic = "|".join(re.escape(term) for term in group)
                if re.search(r"(?:progress|progres)\s+(?:" + topic + r")\b", candidate["konten_teks"], re.I):
                    candidate["score"] *= 1.7
                    break
        if candidate["meeting_number"] == candidate["source_meeting_number"]:
            candidate["score"] *= 1.12
        # Distinguish the person filling a role from the committee member handling it.
        # A progress/decision sentence is stronger evidence than a jobdesk allocation.
        if person_question(req.pertanyaan) and not re.search(
                r"\b(pj|pic|penanggung|jobdesk|mengurus|menangani)\b", req.pertanyaan, re.I):
            if re.search(r"(?:juri|pembicara|narasumber|moderator|mc)\s+(?:sudah\s+)?(?:fiks|fix|adalah|yaitu|dari|dengan)",
                         candidate["konten_teks"], re.I):
                candidate["score"] *= 1.8
            if re.search(r"\b(?:pak|bu|bapak|ibu|kak|mas)\s+[A-Z]", candidate["konten_teks"], re.I):
                candidate["score"] *= 1.15
            if "Pembagian Job desk" in candidate["konten_teks"] or "Rincian Jobdesk" in candidate["konten_teks"]:
                candidate["score"] *= 0.35
        if re.search(r"\bkapan\s+(?:rapat|rabes)\b", req.pertanyaan, re.I) and re.search(
                r"Rapat ke\s*\d+.*?Tanggal", candidate["konten_teks"], re.I | re.S):
            candidate["score"] *= 2
        qualified.append(candidate)
    qualified.sort(key=lambda c: (-c["score"], c["id"]))
    selected, seen_text = [], set()
    page_counts = {}

    def append(candidate):
        page = (candidate["document_id"], candidate["page_num"])
        normalized = " ".join(candidate["konten_teks"].split()).lower()
        dedup_tokens = tokenize(normalized)
        if normalized in seen_text or page_counts.get(page, 0) >= 2:
            return
        for prior in selected:
            if (candidate["meeting_date"], candidate["divisi"]) == (prior["meeting_date"], prior["divisi"]):
                previous = " ".join(prior["konten_teks"].split()).lower()
                prior_tokens = prior["_dedup_tokens"]
                length_ratio = min(len(normalized), len(previous)) / max(len(normalized), len(previous), 1)
                token_overlap = len(dedup_tokens & prior_tokens) / max(1, len(dedup_tokens | prior_tokens))
                if length_ratio >= 0.75 and token_overlap >= 0.7 and difflib.SequenceMatcher(
                        None, normalized, previous, autojunk=False).ratio() > 0.88:
                    return
        seen_text.add(normalized)
        page_counts[page] = page_counts.get(page, 0) + 1
        candidate["_dedup_tokens"] = dedup_tokens
        selected.append(candidate)

    if compare:
        seen_meetings = set()
        for candidate in qualified:
            meeting = (candidate["meeting_number"], candidate["meeting_date"])
            if meeting == (None, None):
                meeting = (candidate["document_id"], None)
            if meeting not in seen_meetings and len(selected) < req.top_k:
                append(candidate)
                seen_meetings.add(meeting)
    for candidate in qualified:
        if len(selected) >= req.top_k:
            break
        append(candidate)
    return selected, {"retrieval": strategy, "warning": warning,
                      "temporal_scope": "latest_implicit" if implicit_latest else "latest_explicit" if explicit_latest
                        else "specific_meeting" if specific_meeting else "all_meetings",
                      "as_of": as_of}


def references(chunks: list[dict]) -> list[dict]:
    return [{
        "id": f"S{i}", "document_id": chunk["document_id"], "file": chunk["nama_file"],
        "halaman": chunk["page_num"], "divisi": chunk["divisi"], "tahun": chunk["tahun"],
        "tanggal_rapat": chunk["meeting_date"], "rapat_ke": chunk["meeting_number"],
        "kutipan": chunk["konten_teks"], "url": f"/documents/{chunk['document_id']}/pdf#page={chunk['page_num']}",
    } for i, chunk in enumerate(chunks, 1)]
