# backend/evals/app_docs

Sizing work for a different question than the rest of `evals/`. The suites and reports
next door measure **how well the planner plans**; this folder measures **what it would
cost to make the repo itself retrievable** — embedding the code and docs so an assistant
can answer "where does X live" / "how does this flow work" questions about the project.

Nothing here calls OpenAI, touches the database, or needs the backend running. It is
local token counting, so it is free to re-run.

## `token_budget.ipynb`

Counts the tracked repo with `tiktoken` and turns that into chunk counts, index size and
dollars.

```bash
cd backend && poetry run jupyter lab evals/app_docs/token_budget.ipynb
```

It is committed **without outputs** — partly for readable diffs, mostly because the
notebook's own finding is that stored notebook output is the single biggest source of
junk tokens in this repo. Run it to see the numbers.

What it does:

1. Takes the file list from `git ls-files`, so `.gitignore` has already excluded `logs/`,
   `config/.env`, `*backup.sql` and `TODO.*`.
2. Drops what is worthless to embed for code guidance — lockfiles, `.csv`/images,
   `evals/results/**` dumps — and counts notebooks by their **source cells only**.
3. Splits the result into three corpus profiles (core / core+tests / everything) and
   breaks tokens down by area, file type and largest files.
4. Converts tokens to chunks, then to embedding spend and `float32` index size at the
   dimensions `config/.env` actually configures.
5. Compares per-question cost of retrieving the top *k* chunks against just pasting the
   whole corpus into the prompt, cached and uncached.

Chat rates come from [`config/pricing.py`](../../config/pricing.py). Embedding rates are
defined in the notebook, with the same staleness warning — the app does not bill
embeddings today, so they have no home in `pricing.py` yet.

## Headline numbers (2026-08-01, `441d25e`)

| | files | tokens | chunks @800/100 | index MB @1024d | build $ (3-large) |
|---|---|---|---|---|---|
| core (app, db, evals, config, docs, frontend src) | 193 | 169,960 | 345 | 1.41 | $0.0241 |
| core + tests | 226 | 217,690 | 427 | 1.75 | $0.0309 |
| everything tracked | 269 | 301,236 | 571 | 2.34 | $0.0431 |

Three things that shape the decision:

- **Filtering matters more than chunking.** The naive count over the same files is
  ~595k tokens; ~294k of that is stored notebook output, and another ~90k was
  `package-lock.json`.
- **Scope matters more than either.** `backend/playground` and `backend/tests` are ~42%
  of the tracked corpus and answer different questions than "how does this app work".
- **Cost is not the deciding factor.** The core corpus fits in a modern context window;
  cached, pasting all of it into `gpt-5.6-luna` runs ~$0.017/request against ~$0.006 for
  eight retrieved chunks. Retrieval wins on precision and latency, not spend.
