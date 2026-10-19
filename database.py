"""Transactional SQLite storage. Existing PostgreSQL data is never modified."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Repository:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY,
                    checksum TEXT NOT NULL UNIQUE,
                    nama_file TEXT NOT NULL,
                    divisi TEXT NOT NULL,
                    tahun INTEGER NOT NULL,
                    meeting_number INTEGER,
                    meeting_date TEXT,
                    total_pages INTEGER NOT NULL,
                    empty_pages TEXT NOT NULL,
                    pdf BLOB NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    page_num INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    divisi TEXT NOT NULL,
                    konten_teks TEXT NOT NULL,
                    meeting_number INTEGER,
                    meeting_date TEXT,
                    embedding TEXT,
                    embedding_model TEXT,
                    UNIQUE(document_id, chunk_index)
                );
                CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id);
                CREATE INDEX IF NOT EXISTS chunks_divisi ON chunks(divisi);
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    konten_teks, divisi, content='chunks', content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                );
                CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                    INSERT INTO chunks_fts(rowid, konten_teks, divisi)
                    VALUES (new.id, new.konten_teks, new.divisi);
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, konten_teks, divisi)
                    VALUES ('delete', old.id, old.konten_teks, old.divisi);
                END;
                CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, konten_teks, divisi)
                    VALUES ('delete', old.id, old.konten_teks, old.divisi);
                    INSERT INTO chunks_fts(rowid, konten_teks, divisi)
                    VALUES (new.id, new.konten_teks, new.divisi);
                END;
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(chunks)")}
            for column, kind in (("meeting_number", "INTEGER"), ("meeting_date", "TEXT")):
                if column not in columns:
                    conn.execute(f"ALTER TABLE chunks ADD COLUMN {column} {kind}")
            conn.execute("CREATE INDEX IF NOT EXISTS chunks_meeting ON chunks(meeting_number,meeting_date)")
            conn.execute("PRAGMA user_version=2")

    def find_checksum(self, checksum: str):
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM documents WHERE checksum=?", (checksum,)).fetchone()
        return self.document(row["id"]) if row else None

    def document(self, document_id: int, include_pdf: bool = False):
        columns = "d.*" if include_pdf else """d.id,d.nama_file,d.divisi,d.tahun,d.meeting_number,
            d.meeting_date,d.total_pages,d.empty_pages,d.created_at,d.checksum"""
        with self.connect() as conn:
            row = conn.execute(f"""SELECT {columns},
                (SELECT count(*) FROM chunks WHERE document_id=d.id) total_chunks
                FROM documents d WHERE id=?""", (document_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["empty_pages"] = json.loads(result["empty_pages"])
        with self.connect() as conn:
            result["meetings"] = [dict(row) for row in conn.execute("""SELECT DISTINCT
                meeting_number,meeting_date FROM chunks WHERE document_id=?
                AND meeting_number IS NOT NULL ORDER BY meeting_date""", (document_id,))]
        return result

    def documents(self):
        with self.connect() as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM documents ORDER BY meeting_date, id")]
        return [doc for id_ in ids if (doc := self.document(id_)) is not None]

    def stats(self):
        with self.connect() as conn:
            row = conn.execute("""SELECT count(*) total_documents,
                coalesce(sum(total_pages),0) total_pages,
                (SELECT count(*) FROM chunks) total_chunks FROM documents""").fetchone()
            divisions = [r[0] for r in conn.execute("SELECT DISTINCT divisi FROM chunks ORDER BY divisi")]
        return {**dict(row), "divisi": divisions}

    def save_document(self, metadata: dict, pdf: bytes, chunks: list[dict], reindex: bool = False,
                      replace_checksum: str | None = None):
        # PDF, metadata, chunks, and FTS changes commit together.
        with self.connect() as conn:
            # Acquire the write reservation before deduplication, including across processes.
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT id FROM documents WHERE checksum=?",
                                    (replace_checksum or metadata["checksum"],)).fetchone()
            if existing is None and replace_checksum:
                existing = conn.execute("SELECT id FROM documents WHERE checksum=?", (metadata["checksum"],)).fetchone()
            if existing:
                document_id = existing[0]
                if not reindex and not replace_checksum:
                    return document_id, False
                conn.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
                if replace_checksum:
                    conn.execute("UPDATE documents SET checksum=?,pdf=?,nama_file=? WHERE id=?",
                        (metadata["checksum"], pdf, metadata["nama_file"], document_id))
                conn.execute("""UPDATE documents SET divisi=?, tahun=?, meeting_number=?,
                    meeting_date=?, total_pages=?, empty_pages=? WHERE id=?""",
                    (metadata["divisi"], metadata["tahun"], metadata["meeting_number"],
                     metadata["meeting_date"], metadata["total_pages"], json.dumps(metadata["empty_pages"]), document_id))
            else:
                cursor = conn.execute("""INSERT INTO documents
                    (checksum,nama_file,divisi,tahun,meeting_number,meeting_date,total_pages,empty_pages,pdf)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (metadata["checksum"], metadata["nama_file"], metadata["divisi"], metadata["tahun"],
                     metadata["meeting_number"], metadata["meeting_date"], metadata["total_pages"],
                     json.dumps(metadata["empty_pages"]), pdf))
                document_id = cursor.lastrowid
            conn.executemany("""INSERT INTO chunks
                (document_id,page_num,chunk_index,divisi,konten_teks,embedding,embedding_model,meeting_number,meeting_date)
                VALUES (?,?,?,?,?,?,?,?,?)""", [
                    (document_id, c["page_num"], i, c["divisi"], c["konten_teks"],
                     json.dumps(c["embedding"]) if c.get("embedding") is not None else None,
                     c.get("embedding_model"), c.get("meeting_number"), c.get("meeting_date")) for i, c in enumerate(chunks)
                ])
        return document_id, True

    def backup(self, destination: Path):
        if destination.resolve() == self.path.resolve():
            raise ValueError("Tujuan backup harus berbeda dari database aktif.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
