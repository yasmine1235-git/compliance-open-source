# ComplianceOps

An open-source LLMOps platform for checking financial marketing documents against EU rules
(MiFID II, SFDR, PRIIPs) and French AMF guidance. It uses only public documents and synthetic data.

**Status: early skeleton.** The API accepts documents but does not run compliance checks yet.
Every report has the status `not_evaluated` and no verdicts, which does not mean a document passed.

## Quickstart

```bash
docker compose up --build
```

| Service | URL |
|---|---|
| API docs | http://localhost:8000/docs |
| Qdrant | http://localhost:6333/dashboard |
| Langfuse | http://localhost:3000 |

Check a document:

```bash
curl -F "file=@document.pdf" http://localhost:8000/check
```

## Ingestion and search

Put documents in `data/`, then index and search them. Each category has its own index:
`mifid_ii`, `sfdr`, `priips`, `amf` or `prospectus`.

```bash
docker compose exec api complianceops ingest data/prospectus.pdf --doc-version 2024-01 --category prospectus
docker compose exec api complianceops search "management fee" --category prospectus --doc-version 2024-01
docker compose exec api complianceops watch data/inbox --doc-version 2024-01 --category prospectus
```

The first command downloads the embedding model, about 500 MB, into a Docker volume.

- **Parsing:** PDF and PPTX text and tables. Pages and images without text go through Tesseract OCR
  (French and English).
- **Chunking:** one chunk per text block over 20 characters, with its document, version, page or
  slide, and source file.
- **Versioning:** ingesting a document again replaces that version only, and searches can target
  a version with `--doc-version`.
- **Watching:** `watch` polls a folder and indexes each new or changed file once it stops changing.

**Known limitation:** blocks are not split, and embedding models only read the start of a long
text (128 tokens for MiniLM). The rest of a long block is stored but does not affect search.

## API

- `GET /health` reports that the API is running.
- `POST /check` takes a PDF or PPTX as the multipart field `file`, validates its type and content,
  and returns a JSON report. The document is not stored.

| Response | Meaning |
|---|---|
| `400` | The file is empty |
| `413` | The file exceeds `COMPLIANCEOPS_MAX_UPLOAD_BYTES` (default 50 MB) |
| `415` | The file is not a valid PDF or PPTX |
| `422` | The request has no `file` field |

## Development

Requires Python 3.11.

```bash
py -3.11 -m venv .venv            # Windows; elsewhere: python3.11 -m venv .venv
source .venv/Scripts/activate     # Windows Git Bash; elsewhere: source .venv/bin/activate
pip install -e ".[dev]"

ruff check . && ruff format --check . && mypy && pytest
```

To run embeddings outside Docker, also install `pip install -e ".[embeddings]"`. OCR tests are
skipped when Tesseract is not installed; CI always runs them.

Configuration lives in `.env`; see `.env.example`. The defaults are for local use only.

## License

[AGPL-3.0](LICENSE), matching the license of the PyMuPDF dependency.
