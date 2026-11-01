# ComplianceOps

An open-source LLMOps platform for checking financial marketing documents against EU rules
(MiFID II, SFDR, PRIIPs) and French AMF guidance. It uses only public documents and synthetic data.

**Status: in development.** Rule-based checks work, but no LLM is connected yet, so reports cannot
be `compliant` and at best say `incomplete`. The rules are drafts that no compliance professional has
reviewed, and the results are not legal advice.

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
curl -F "file=@document.pdf" -F "target_country=FR" http://localhost:8000/check
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

## Compliance checks

Five agents run in parallel, and their verdicts are merged by deterministic code.

| Agent | Method | Checks |
|---|---|---|
| `structure_agent` | Patterns | Risks alongside rewards, investment policy, cost and leverage explanations |
| `disclaimer_agent` | Patterns | Marketing label, prospectus and KID reference, required statements |
| `language_objectivity_agent` | Phrase list and LLM | Hyperbole and misleading language |
| `content_coherence_agent` | RAG and LLM | Claims are consistent with the prospectus |
| `sql_registration_agent` | SQLite | ISIN validity, registry entry, authorisation in the target country |

The rules are in [`rules.yaml`](src/complianceops/agents/rules.yaml). Each one cites its source,
mostly [ESMA's guidelines on marketing communications](https://www.esma.europa.eu/sites/default/files/library/esma34-45-1272_guidelines_on_marketing_communications.pdf).
The fund registry contains fictional sample data.

A report's `status` is one of these:

| Status | Meaning |
|---|---|
| `compliant` | Every rule was evaluated and none failed |
| `non_compliant` | At least one rule failed |
| `incomplete` | Nothing failed, but at least one rule could not be evaluated |

A rule is `not_evaluated` when its agent crashes, needs an LLM that is not configured, or lacks an
input, so an unknown result can never look like a pass.

**Known limitations:**

- Pattern rules check that text is present, not that it is prominent, correctly placed or correctly
  worded in the sense the guidelines require. A `pass` from them is not a legal assessment.
- The French patterns are unofficial translations.
- Rules only cover part of the guidelines. MiFID II, SFDR, PRIIPs and AMF texts are not covered yet.

## API

- `GET /health` reports that the API is running.
- `POST /check` takes a PDF or PPTX as the multipart field `file` and returns a JSON report. The
  document is not stored. Optional form fields: `target_country` (such as `FR`), `prospectus_id`
  and `prospectus_version`.

| Response | Meaning |
|---|---|
| `400` | The file is empty |
| `413` | The file exceeds `COMPLIANCEOPS_MAX_UPLOAD_BYTES` (default 50 MB) |
| `415` | The file is not a valid PDF or PPTX |
| `422` | The request has no `file` field, a field is invalid, or the file cannot be read |

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
