"""Import datasets and optionally rebuild their search index."""
import argparse
import json
import logging

from config import Settings
from database import Repository
from ingestion import import_datasets
from retrieval import SemanticEncoder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reindex", action="store_true", help="Bangun ulang chunks/embedding PDF yang sama.")
    args = parser.parse_args()
    settings = Settings()
    repository = Repository(settings.db_path)
    repository.initialize()
    semantic = SemanticEncoder(settings) if settings.semantic_search else None
    results = import_datasets(repository, settings, semantic, args.reindex)
    for result in results:
        document = result.get("document", {})
        print(json.dumps({"file": result["file"], "imported": result.get("imported"),
                          "pages": document.get("total_pages"), "chunks": document.get("total_chunks"),
                          "error": result.get("error")}, ensure_ascii=False))
    print(json.dumps(repository.stats(), ensure_ascii=False))
    return 1 if not results or any("error" in r for r in results) else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
