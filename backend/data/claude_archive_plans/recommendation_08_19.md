# Recommendation filtering: own the bounds, drop the delegation

## Context

`Analyze_Recommend` currently reaches metadata bounds by **delegation**: its arg parse splits the
goal text into `semantic_input` + `filter_query` (natural-language bounds), and `filter_candidates`
wraps its ranked candidate pool as a query (`BookStore.isbn13_query`), runs `FilterRetrievalExecutor`
as a sub-workflow, and re-reads the survivors back into similarity order (`keep_ranked`). That path
is commented out in the working tree right now.

Three problems with it:

1. **The ask is parsed twice** — recommend produces prose, the filter node re-parses that prose into
   a `BookMetadataFilter`. Nothing happens in between; the second call reads only what the first
   wrote. That is a layer that forwards a call.
2. **The sub-workflow has UI side effects that are wrong here.** `FilterRetrievalExecutor.run` sends
   `- N books left after: …` into the chat and streams a preview of the narrowed pool as book cards.
   Sections are opened by the *task runner*, not the workflow, so those cards land inside the
   **Recommendation** section, ahead of the actual recommendations.
3. **It filters after the search rather than inside it.** `search_by_embedding` does not select a
   subset — it orders the whole table by cosine distance and takes the top 50. Bounds applied to
   that capped 50 can leave two survivors for "like Dune, under 300 pages", because most
   Dune-adjacent books are long.

Two live bugs also fall out of the current commented-out state:

- `finalize_result` is `ok = self.result.args is not None and bool(...)`, and `args` is never set —
  so **every recommend run finalizes not-ok**, which the golden eval diff reads.
- `build_search_text(analyzed, node_input.query)` embeds the **raw goal text**, bounds included, so
  "under 300 pages" goes into the vector where it can only blur the result.

**Outcome:** recommend parses and applies its own filter. Numeric bounds go into the vector search's
`WHERE`, so the top 50 is drawn from inside them. Exclusion lists (authors / categories / titles) are
applied as a pure predicate over the returned pool. Both happen before ranking — which is the actual
principle the docs defend, and it survives this change intact. The `semantic_input` prose field
becomes `keywords`. And because this is an **analyze node, it always replies**: an empty pool is an
answer it writes, never an exception.

## Design decisions (settled)

| | |
|---|---|
| `semantic_input` → | `keywords: list[str]`, joined into the embedded text. One vector search, no new store method. |
| Filter fields | Numeric bounds (reuse `BookMetadataFilter`) **and** exclusion lists (reuse `ExclusionBookFilter`) — as two separate fields, not one merged model, because they are applied by two different mechanisms. |
| Bounds applied | In SQL, inside `search_by_embedding`, via the existing `metadata_predicates`. |
| Exclusions applied | In memory over the capped pool — author/category/title matching is fuzzy, and casefolded substring matching is more forgiving than SQL equality. |
| Similarity floor | `similarity_threshold` gets **wired up** (it is currently declared and never used), so candidates have to actually sit near the description. |
| Empty pool | **Always reply.** The node tells the user it could not find books within the criteria. No raise — a raise means a runtime error and a generic "something went wrong" from the layer above. |

## Changes

### 1. `app/domains/books/analyze_recommend/schemas.py`

Replace `RecommendationArgs`' two fields:

```python
class RecommendationArgs(BaseModel):
    """<lightweight internal-tool docstring — what to search for, what to rule out>"""

    keywords: list[str] = Field(default_factory=list, ...)
    bounds: BookMetadataFilter | None = None      # from db.schema — goes into the WHERE
    exclude: ExclusionBookFilter | None = None    # from db.schema — applied to the pool
```

Both models are imported from `db/schema/filter_schemas.py` unchanged. **Note a deliberate
refinement on the option you picked:** the preview showed `RecommendationFilters(BookMetadataFilter)`
with a nested `exclude`. Flat is better here — the two fields travel to two different places, and a
wrapper class would exist only to be immediately unpacked. Say the word if you want the nested shape.

Rewrite the class docstring: it is an **internal tool** (never seen by the planner), so it stays a
short instruction on how to split the ask, keeping the worked examples that teach the split but
retargeting them from "filter_query prose" to keywords + bounds + exclusions.

**Delete** the scratch `GenreEnum` and `embedding_exclusion` at lines 103-156, plus the mid-file
`from enum import Enum` / `from config import BookConstraints` imports — superseded by this change,
and they duplicate `db/schema/filter_schemas.py`.

Leave `RecommendationStrategy`'s catalog docstring alone: it already tells the planner to leave
bounds in the goal description, which is still exactly right.

### 2. `db/stores/book_store.py` — `search_by_embedding` takes bounds and enforces its threshold

```python
async def search_by_embedding(
    self,
    query_embedding: List[float],
    filters: BookMetadataFilter | None = None,
    exclude_isbns: list[str] | None = None,
    similarity_threshold: float = BookConstraints.MIN_SIMILARITY,
    limit: int = 50,
) -> List[Dict[str, Any]]:
```

- **Wire up `similarity_threshold`.** It is declared today and never referenced in the body, so the
  search returns the top 50 by distance no matter how far away they are. Add it as a `WHERE`:
  `(1 - embed_col.cosine_distance(query_embedding)) >= similarity_threshold`. This is what makes the
  result "books near the description" rather than "the 50 least-distant rows in the table".
- `if filters: stmt = stmt.where(*metadata_predicates(self.model, filters))` — reuses the existing
  module-level helper, currently called from exactly one place (`filter_query`).
- An all-None filter yields `[]` predicates and is a harmless no-op here — unlike `filter_query`,
  which refuses it, because there narrowing is the node's whole job and a no-op would report a count
  the user reads as filtered. Worth one comment saying so.
- `exclude_isbns` as a `NOT IN` — closes the standing TODO at `executor.py:258`, which notes that
  filtering the references out in Python shrinks the result below `limit` instead of backfilling it.
  One clause in a `where()` that now exists anyway.
- Rewrite the docstring — it currently asserts the opposite of this change ("Takes no `BooksFilter`:
  metadata narrowing is Filter_Retrieval's job … applied to the composed query rather than here").

**`config/constants.py`** — add `MIN_SIMILARITY = 0.7` to `BookConstraints` rather than leaving the
literal in the signature default, alongside the other domain bounds.

> ⚠️ **0.7 needs an empirical check before it is trusted.** It has never been enforced, so nothing
> here knows what the real score distribution looks like — and on typical text embeddings a 0.7
> cosine floor is strict enough to return very little. Good news: `Book.similarity_score` is already
> persisted into `chat_runs`, so the distribution can be read off past runs before pinning the number.
> With the always-reply behaviour below, a too-strict floor degrades into "I couldn't find anything"
> rather than a crash — but it is still the number most likely to need tuning after this lands.

### 3. `app/domains/books/analyze_recommend/executor.py`

**`run()` becomes:**

1. dependents — unchanged
2. **uncomment the arg parse**, typed `RecommendationArgs` → `self.result.args`
3. `analyze_references` — unchanged
4. `search_text = build_search_text(analyzed, " ".join(args.keywords))` — the keywords, not the raw
   goal text. Keeps bounds prose out of the embedding, which is the reason the split exists.
5. `similarity_search(search_text, exclude_isbns=…, filters=args.bounds)` — what comes back already
   fits the bounds and clears the similarity floor
6. `candidates = apply_exclusions(candidates, args.exclude)` — pure, in memory, before ranking
7. rank **only if there are candidates** (see below)
8. stream + reply + finalize

**New module-level pure function**, in flow order per the slice's reading rule (no `@task` — nothing
is awaited):

```python
def apply_exclusions(candidates: list[Book], exclude: ExclusionBookFilter | None) -> list[Book]:
    """Drop the candidates the ask ruled out, keeping similarity order.

    Casefolded substring matching rather than equality: the model writes
    "Herbert" where the column holds "Frank Herbert". `Book.authors`,
    `.categories` and `.title` are all single strings.
    """
```

`None` or an all-None exclusion returns the list untouched.

**Empty pool is an answer, not an exception.** When nothing clears the search plus the bounds plus
the exclusions, `run` skips ranking and streaming and goes straight to `response_to_user`, which
writes "I couldn't find books matching…". Concretely:

- guard the rank call — `rank_candidates` raises `ValueError("No books were returned…")` on an empty
  list, and that raise must become unreachable from `run`. Keep the guard inside the pure function
  (it is a real precondition, and its test covers it); just never call it with nothing.
- `finalize_result` changes from `ok = args is not None and bool(self.result.books)` to
  **`ok = self.result.args is not None`** — the claim becomes *the ask was parsed and the user got an
  answer*, not *books were chosen*. Zero recommendations is a reported answer, exactly as
  `num_books == 0` is for the filter node. `RecommendationOutput.books`' own docstring already says
  so ("An empty `books` means nothing in the catalog satisfied the anchor plus the filters"), so this
  aligns the code with the shape it already declares. Comment it the way the filter node comments its
  own `ok`.

> **One raise stays in `run`, and it is inconsistent with the above:** step 4's
> `ValueError("Nothing to search on: no references and no semantic input")`, for a goal with no anchor
> *and* no keywords — nothing to embed at all. Left as-is because it is pre-existing and the
> task-runner error path is out of scope this turn. Flagging it as the next thing to revisit under the
> "an analyze node always replies" rule.

**Delete:**

- `filter_candidates` (the whole method — the sub-workflow call, the `isbn13_query` pool, the
  `preview_books` round trip)
- `keep_ranked` — the survivors never leave Python now, so nothing re-orders them
- `from app.domains.books.filter_books import FilterRetrievalExecutor, FilterRetrievalInput`
- the step-6 comment block explaining the delegation

### 4. `generate_response.py` + the reply prompt — teach it the empty case

`summarize_references(references, semantic_input, bounds)` becomes
`summarize_references(references, keywords, bounds, kept=None, of=None)` (or equivalent):

- `asked_for` = `", ".join(keywords)`
- `bounds` = a rendered bounds sentence — **reuse `describe_bounds` from
  `filter_books/executor.py`** rather than writing a second renderer. It is a pure function on
  `BookMetadataFilter`; re-export it from `filter_books/__init__.py` and import that. (This is the one
  import from that slice that stays, and it is a function rather than a workflow — a very different
  coupling from the sub-workflow call being removed.)
- `render_summaries` already emits `- every book shown fits: {bounds}`, which is now *more* true than
  before since the bound went into the SQL. Add a shortfall line when exclusions cut deep, e.g.
  `- only 3 of 50 candidates fit`.

`describe_bounds` also gives the loading message its words:
`send_ui_loading(f"filtering by: {bounds}")`.

**`prompts/response_prompt.txt` needs a zero-books branch.** It is written end to end for the
found-books case — *"The search has already run: the books have been chosen and are on screen in
front of the user as cards"*, *"Lead with the books… 'Here are eight…'"* — and has no idea what to do
with `- 0 books recommended`. Add:

- an **Input format** entry for the `every book shown fits:` and shortfall lines (the first is already
  emitted today and undocumented in the prompt), and
- an explicit branch: when the output is 0 books, say plainly that nothing in the catalog matched what
  was asked for, name the constraint that was too tight if `bounds` says one, and invite a looser ask.
  The existing rules still hold — no technical language, no mention of filters or searches — so this
  is "I couldn't find anything short enough near those books", not "the filter returned 0 rows".

### 5. Removals outside the slice (rule 5)

- **`BookStore.isbn13_query`** — its docstring says outright it exists for the pool→filter hand-off
  being removed, and recommend was its only production caller. Delete it and `TestIsbn13Query` (3
  tests) in `tests/unit/db/stores/test_deferred_query.py`, including the
  `test_narrows_like_any_other_base_query` case that pairs it with `filter_query`.
  ⚠️ That test file has uncommitted edits (`MM`) — confirm before deleting anything in it.
- **`TestKeepRanked`** (3 tests) in `tests/unit/app/domains/books/test_rank_candidates.py`, and the
  module docstring that frames the two functions as "either side of the filter step".
  `TestRankCandidates` is untouched by this change.

### 6. Docs (CLAUDE.md requires these in the same change)

- `docs/design/execution-pipeline-v1.md:92-111` — rewrite the "reaches the filter by delegation"
  section. The claim that survives is *narrowing happens before the choice*; the mechanism changes
  from a sub-workflow to a `WHERE` plus a pure predicate. Its stated cost — *"an ask whose bounds
  exclude everything near the anchor fails the goal rather than answering, which is deliberate"* — is
  now **reversed** and must be rewritten: the node answers. Also fixes the stale class name
  (`DecomposedAsk` → `RecommendationArgs`).
- `docs/design/node-taxonomy-v1.md:175-183` — the sentence citing "decomposing its goal text into a
  `filter_query`".
- `app/domains/README.md:98-108` — the finalize rule currently reads *"recommend claims
  args-parsed-and-books-chosen"*. Update to the new claim.
- **`app/domains/books/filter_books/schemas.py:30-38` — planner-facing, handle with care.** The "Do
  not use to bound a recommendation" paragraph says recommend "runs this same narrowing over its
  candidate pool". Still true in spirit, wrong in detail. **Editing it changes the tool catalog, which
  changes planner behaviour, which moves the golden eval diff** — so make this edit deliberately and
  diff `make tools-catalog` before and after.
- `evals/suites/query_suite.json` notes on cases 62 / 64 / 65 (lines ~433, ~440, ~447) name
  `filter_query` by name; `query_suite_adversarial.json:578` already references a removed `filters`
  field. Notes only — nothing asserts on them — but they encode the design intent.
- `CLAUDE.md` — the `*Args` list says `(FilterRetrievalArgs, DecomposedAsk)`; stale since `9a81c4f`.
- `db/README.md` — check whether it names `isbn13_query`.

### 7. Tests to add

- `apply_exclusions` — drops by author / title / category, casefolded and substring, empty and `None`
  exclusions are no-ops, similarity order preserved.
- `search_by_embedding` — assert the compiled SQL carries the metadata predicates, the similarity
  floor and the `NOT IN`; and that a `None` / all-None filter still compiles.

## Verification

```bash
make tests                  # expect the 2 known pre-existing test_run_recorder.py failures
poetry run pyright app      # currently 0 errors; keep it there
make tools-catalog          # diff against a pre-change capture — only the FilterRetrieval
                            # "Do not use" paragraph should move
```

End-to-end, with `make dev` running:

- `"recommend books like Dune but under 300 pages"` — reply acknowledges the bound; no
  `Filter_Retrieval` node in the plan; every card under 300 pages.
- `"books like Dune but not by Frank Herbert"` — the exclusion path.
- `"something cozy and hopeful"` — no anchor, no bounds; the keyword-only path still embeds.
- **`"books like Dune under 50 pages"` — the empty case.** Must produce a warm plain-language "I
  couldn't find anything that short near those books", **zero cards, no error banner**, and a node
  that finalizes **ok**.
- Then check `chat_runs` for those runs: `args` populated with `keywords` / `bounds` / `exclude`, and
  read the `similarity_score` distribution to sanity-check `MIN_SIMILARITY = 0.7`.

```bash
make query-suite && make suite-goals   # golden diff; cases 62/64/65 are the ones to watch
```
