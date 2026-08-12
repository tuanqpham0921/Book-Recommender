# Book Recommender System

A book-recommendation chatbot built to showcase an **LLM-driven planning and
orchestration architecture**: each user message is parsed into structured goals, an LLM
selects strategies from a typed node catalog, and the resulting task plan is streamed
to the user as a Mermaid diagram before anything runs.

**[Video Demo](https://drive.google.com/file/d/1iMLYHvfMU0ECTITtlwgHNjXtJGePy7fE/view?usp=sharing)**
· **[V1 Roadmap](docs/roadmap.md)**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---
## Quick Start

### Prerequisites

- **Backend**: Python 3.11+, Poetry, Docker (for local PostgreSQL)
- **Frontend**: Node.js 18+, npm
- **Services**: OpenAI API key

### Backend Setup

```bash
cd backend

poetry install

# Environment config lives at config/.env (see config/README for structure).
# Core variables: OPENAI_API_KEY + the POSTGRES_* connection settings.

make postgres-start     # local PostgreSQL (+pgvector) via Docker Compose
make postgres-restore   # optional: load data/backup.sql
make dev                # FastAPI with hot reload on :8000

make tests              # unit tests
make tests-integration  # in-process API tests (faked stores, no services needed)
```

### Frontend Setup

```bash
cd frontend

npm install

# .env: VITE_API_URL=http://localhost:8000

npm run dev
```

## Deployment

- **Backend** → Google Cloud Run: `cd backend && gcloud builds submit --config cloudbuild.yaml`
- **Frontend** → Firebase Hosting: see [frontend/README.md](frontend/README.md)
- **Database** → Cloud SQL (PostgreSQL)

---

## Technology Stack

### Backend
- **Framework**: FastAPI (SSE streaming)
- **LLM Integration**: OpenAI
- **Database**: PostgreSQL with pgvector
- **ORM**: SQLAlchemy (async)
- **Dependencies**: Poetry

### Frontend
- **Framework**: React 19
- **Build Tool**: Vite 7
- **Styling**: TailwindCSS 4
- **Routing**: React Router 7
- **Visualization**: Mermaid diagrams (pan/zoom)

---

## Project Structure

```
Book-Recommender/
├── CLAUDE.md                  # Architecture guide (also for AI assistants)
├── docs/                      # Roadmap, backlog, eval strategy, design decisions
├── backend/
│   ├── app/
│   │   ├── api/               # FastAPI routes and request/response schemas
│   │   ├── common/            # App-level workflow base, SSE stream, messages
│   │   ├── domains/           # Node type system: books, planner, project, users
│   │   └── orchestration/     # Orchestrator + request context
│   ├── clients/               # OpenAI client
│   ├── common/                # Workflow / OperationResult infrastructure
│   ├── config/                # Settings (pydantic-settings) + .env
│   ├── db/                    # Async engine, schema SQL, stores, models
│   ├── evals/                 # Query suites, runner, node-expectation reports
│   ├── playground/            # Mock executors + registry extension for scaling tests
│   └── tests/                 # Unit + integration tests
└── frontend/
    └── src/                   # React app: chat, review page, design system
```

Most folders have their own `README.md` with local context.

---

## Features

### Current
- LLM preplanning: user message → structured goals → strategy selection → visible
  Mermaid task plan
- Typed, extensible node catalog (add a schema, register it — the planner picks it up)
- Real-time SSE streaming chat interface
- Review page: browse recorded chat runs, inspect plans, file per-run feedback
- Eval harness: 4 query suites with per-case node expectations and automated reports

### In progress (V1 — see [docs/roadmap.md](docs/roadmap.md))
- End-to-end task execution with real retrieval from the book database
- Clarification/rejection replies for ambiguous or unsupported queries
- Golden-test thresholds as a release gate

### Planned (V1.1+)
- Multi-turn conversation context
- Book comparison and single-book analysis
- Reading lists, ratings, personalization (needs user accounts)

---

## Example Queries

```
"What is the book Dune?"

"Recommend books with the same vibes as The Great Gatsby"

"I want something philosophical but easy to read"
```

---

## Contributing

This is a public release of a personal project. Feedback and suggestions are welcome!

**Contact**: tuanqpham0921@gmail.com

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
