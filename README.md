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

Configuration lives in `.env`; see `.env.example`. The defaults are for local use only.
