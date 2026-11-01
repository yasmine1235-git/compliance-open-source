# ComplianceOps — Open-source LLMOps platform for financial document compliance

## What this project is
An open-source, production-style rebuild of a multi-agent compliance checker for financial
marketing documents (prospectus + presentation decks), checked against EU rules
(MiFID II, SFDR, PRIIPs) and French AMF guidance.
It must use ONLY public documents and synthetic/public sample data — no proprietary data.

The goal is to demonstrate the full chain: document ingestion → RAG → multi-agent reasoning
→ REST API → evaluation → observability → guardrails → CI/CD → infrastructure-as-code.

## Hard requirements (do not skip)
- Python 3.11, clean, typed (type hints), documented, tested (pytest). Small modules.
- Every feature lands with tests and a short README section.
- No secrets in the repo. Use `.env` + `.env.example`.
- Everything runs locally with `docker compose up`.

## Architecture
```
data/ (public docs) ──► ingestion ──► chunking ──► embeddings ──► vector store (Qdrant or FAISS)
                                                          │
User/API ──► FastAPI ──► LangGraph orchestrator ──► agents (parallel, async)
                                   │                  ├─ content_coherence_agent (RAG over prospectus)
                                   │                  ├─ structure_agent (required sections present)
                                   │                  ├─ language_objectivity_agent (marketing hyperbole)
                                   │                  ├─ disclaimer_agent (mandatory legal mentions, deterministic)
                                   │                  └─ sql_registration_agent (fund/ISIN/market authorisation via SQL)
                                   ▼
                     verdict aggregator (deterministic merge) ──► report with source citations
LLM calls go through a gateway (LiteLLM) ── tracing (Langfuse) ── guardrails (PII masking, AI Act logging)
```

## Components to build, in this order (one PR / commit series each)

### Step 1 — Skeleton (day 1)
- Repo layout: `src/complianceops/{ingestion,rag,agents,orchestrator,api,eval,guardrails}`, `tests/`, `infra/`.
- FastAPI app with `/health` and `POST /check` (accepts a PDF or PPTX, returns a JSON report).
- `Dockerfile` + `docker-compose.yml` (api + vector DB + Langfuse).
- GitHub Actions: lint (ruff), type-check (mypy), tests (pytest).

### Step 2 — Ingestion & RAG
- Parsers: PDF (pymupdf), PPTX (python-pptx), tables; OCR fallback (Tesseract) for images.
- Block-level chunking (one chunk per meaningful text block > 20 chars), keep metadata
  (doc id, page/slide, version).
- Embeddings: BGE-M3 (or multilingual MiniLM for speed); index per rule category.
- **Versioned index**: every chunk carries `doc_version`; queries can target a version.
- Batch ingestion CLI + a simple streaming mode (watch a folder or a Redis/Kafka topic).

### Step 3 — Agents (LangGraph)
- One node per agent, executed in parallel; deterministic aggregator node.
- Hybrid reasoning: LLM for interpretation, deterministic Python/SQL checks for objective rules.
- `sql_registration_agent` uses SQLite with sample fund / ISIN / country-authorisation tables.
- Every verdict = `{rule_id, status, evidence_text, source_doc, page, chunk_id, agent, latency_ms}`.

### Step 4 — LLM gateway & model comparison
- All LLM calls through LiteLLM (OpenAI, Anthropic, Mistral, and a local model via Ollama).
- Config to choose model per agent; a script that runs the same eval set on several models
  and outputs a table: accuracy, hallucination rate, cost per document, p50/p95 latency.
- "Sovereignty" flag: EU-hosted or local models only.

### Step 5 — Evaluation
- `eval/` dataset: ~20 synthetic marketing documents with injected violations + ground truth.
- Metrics: per-rule precision/recall, hallucination rate (RAGAS faithfulness), LLM-as-judge
  relevance, cost, latency. Baseline = single-prompt monolithic LLM.
- Eval runs in CI on a small subset and fails the build on regression.

### Step 6 — Observability & guardrails
- Langfuse tracing for every LLM call and agent step (model, tokens, cost, latency).
- PII detection & masking (spaCy NER or Presidio) before any external API call.
- Data retention: auto-purge uploaded documents after 24 h.
- AI Act-oriented logging: model/version used, inputs hash, decision trace, human-review flag.
- Prompt-injection check on document text.

### Step 7 — Infrastructure-as-code
- `infra/terraform/`: minimal cloud deployment (Azure Container Apps or GCP Cloud Run)
  for the API + managed storage; variables documented.
- CD workflow: build image → push → deploy on tag.

## Definition of done for the README
- One-paragraph pitch, architecture diagram, quickstart (`docker compose up`),
  a results table (models × accuracy / hallucination / cost / latency), and limitations.

## Working rules for Claude Code
- Work one step at a time; propose a plan before coding each step.
- Keep functions small; write tests first for deterministic logic.
- Never invent evaluation numbers: results tables are generated by scripts and committed.
