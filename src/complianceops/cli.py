"""Command line interface for ingestion and search."""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from qdrant_client import QdrantClient

from complianceops.config import get_settings
from complianceops.ingestion.models import Category
from complianceops.ingestion.pipeline import SUPPORTED_SUFFIXES, ingest_file
from complianceops.ingestion.watcher import FolderWatcher
from complianceops.rag.embeddings import Embedder, SentenceTransformerEmbedder
from complianceops.rag.store import VectorStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="complianceops")
    commands = parser.add_subparsers(dest="command", required=True)
    categories = [category.value for category in Category]

    ingest = commands.add_parser("ingest", help="index a file or every document in a folder")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--doc-version", required=True)
    ingest.add_argument("--category", required=True, choices=categories)
    ingest.add_argument("--doc-id", help="defaults to the file name; single files only")

    watch = commands.add_parser("watch", help="index documents as they appear in a folder")
    watch.add_argument("folder", type=Path)
    watch.add_argument("--doc-version", required=True)
    watch.add_argument("--category", required=True, choices=categories)
    watch.add_argument("--interval", type=float, default=5.0, help="seconds between scans")

    search = commands.add_parser("search", help="search an index")
    search.add_argument("query")
    search.add_argument("--category", required=True, choices=categories)
    search.add_argument("--doc-id")
    search.add_argument("--doc-version")
    search.add_argument("--limit", type=int, default=5)
    return parser


def _find_documents(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(
        file
        for file in path.rglob("*")
        if file.is_file() and file.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _ingest(args: argparse.Namespace, store: VectorStore, embedder: Embedder) -> int:
    if args.doc_id and not args.path.is_file():
        print("--doc-id can only be used with a single file.", file=sys.stderr)
        return 2
    documents = _find_documents(args.path)
    if not documents:
        print(f"No PDF or PPTX files found at {args.path}.", file=sys.stderr)
        return 1
    failures = 0
    for document in documents:
        try:
            count = ingest_file(
                document,
                args.doc_version,
                Category(args.category),
                store,
                embedder,
                doc_id=args.doc_id,
            )
        except Exception as error:
            failures += 1
            print(f"FAILED {document}: {error}", file=sys.stderr)
        else:
            print(f"{document}: {count} chunks")
    return 1 if failures else 0


def _watch(args: argparse.Namespace, store: VectorStore, embedder: Embedder) -> int:
    category = Category(args.category)

    def ingest(path: Path) -> int:
        return ingest_file(path, args.doc_version, category, store, embedder)

    print(f"Watching {args.folder}. Press Ctrl+C to stop.")
    try:
        FolderWatcher(args.folder, ingest).run(args.interval)
    except KeyboardInterrupt:
        pass
    return 0


def _search(args: argparse.Namespace, store: VectorStore, embedder: Embedder) -> int:
    results = store.search(
        Category(args.category),
        embedder.embed([args.query])[0],
        limit=args.limit,
        doc_id=args.doc_id,
        doc_version=args.doc_version,
    )
    if not results:
        print("No results.")
    for result in results:
        chunk = result.chunk
        location = f"{chunk.source_doc} v{chunk.doc_version} p.{chunk.page} [{chunk.kind.value}]"
        print(f"{result.score:.3f}  {location}\n{chunk.text}\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line interface and return its exit code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = _build_parser().parse_args(argv)
    settings = get_settings()
    store = VectorStore(QdrantClient(url=settings.qdrant_url))
    embedder = SentenceTransformerEmbedder(settings.embedding_model)
    commands = {"ingest": _ingest, "watch": _watch, "search": _search}
    return commands[args.command](args, store, embedder)


if __name__ == "__main__":
    sys.exit(main())
