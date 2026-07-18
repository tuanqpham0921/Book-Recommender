# V1 Node Taxonomy (decision record)

**Date:** 2026-07-17 · **Status:** accepted — retrieval taxonomy implemented 2026-07-17

**Implementation note:** the retrieval side landed as four concrete single-dimension
nodes (Title, ISBN13, Author, Genre) rather than a single generic "Traits" node with a
one-field filter — `Retrieve_by_Traits` was deleted outright, not narrowed. This matches
the original TODO note ("retrieve author, titles, isbn, genre") more directly than the
narrowed-Traits design first sketched below. The clarification/rejection node and
`Provide_Feedback` registration are **not yet built** — still open roadmap Phase 1 items.

This records which nodes V1 ships with and why. The roadmap phases that implement it
live in [../roadmap.md](../roadmap.md).

## Problem

Three problems drove this decision, all backed by the 2026-07-16 eval campaign
(`backend/evals/results/newest/eval_20260716_002307.md`, 101/159 cases matched):

1. **The Traits ↔ Recommend blur is the #1 misroute.** `FindByTraitsRetrieval`
   (`Retrieve_by_Traits`) and `RecommendationStrategy` (`Analyze_Recommend`) both carry
   filter fields, so the planner has no structural reason to pick one over the other.
   Base-suite cases 11, 25, 30, and 39 expected `Analyze_Recommend` and got
   `Retrieve_by_Traits`; in the 7/13 campaign one run duplicated identical filters into
   both nodes. Prompt tweaks can't fix an ambiguity that exists in the schemas.
2. **`Provide_Feedback` is advertised but refused.** `FeedbackRequest` exists as a schema
   and sits in the `AnyStrategyRequest` union, but it is absent from `NODE_TYPE_TO_CLS`
   ([backend/app/registry.py](../../backend/app/registry.py)), so the planner refuses
   every goal that targets it.
3. **Ambiguous or unsupported queries fail quietly.** The planner can refuse goals, but
   nothing turns a refusal into a helpful reply — the user just gets a smaller plan (or
   none). V1's showcase is the planner, so rejection needs to be a first-class, visible
   behavior.

## Decision: retrieval owns filters — one node per dimension

Retrieval nodes are the only nodes that carry database filters, and each retrieval node
covers exactly **one** dimension — no `BooksFilter`-style multi-field object on any
planner-facing schema. `Analyze_Recommend` loses its `filters` field and becomes the LLM
ranking/response step that runs *after* retrieval (per the owner's note: "analyze is
response generation that always gets attached when the intent is to find books").

### V1 node set (implemented 2026-07-17)

| Node type | Class | Role in V1 |
|---|---|---|
| `Retrieve_by_Title` | `FindByTitleRetrieval` | Core retrieval — `title` + optional `authors` hint |
| `Retrieve_by_ISBN13` | `FindByISBN13Retrieval` | Core retrieval — exact `isbn13` |
| `Retrieve_by_Author` | `FindByAuthorRetrieval` | Core retrieval — `authors: list[str]`, promoted out of `playground/app_mock/extended_request_schemas.py` |
| `Retrieve_by_Genre` | `FindByGenreRetrieval` | Core retrieval — `genre: str`, new |
| `Analyze_Recommend` | `RecommendationStrategy` | LLM ranking/response step, **no filters field** |
| *(new)* clarification/rejection | not yet built | Turns refused or ambiguous goals into a helpful reply — still open |
| `Provide_Feedback` | `FeedbackRequest` | Registered 2026-07-17 (`app/domains/project/registry.py`) — conversational feedback about the app, distinct from the reviewer workflow's `PUT /feedback/review` |
| `Retrieve_Project_Info` | `ProjectInfoRequest` | Kept — cheap, already works |
| `Retrieve_User_Info` | `UserInfoRequest` | Kept |
| `Retrieve_Developer_Info` | `DeveloperInfoRequest` | Kept |

Every retrieval node's structured result is typed via
`app/domains/books/schemas/output_schemas.py` (`BookSummary` + one `Output` class per
node) — the contract downstream nodes and eval/review tooling see. It deliberately
excludes `description`, `thumbnail`, and `embedding`: those are presentation/internal
fields (thumbnail still streams to the UI separately via `send_book_card`), not
reasoning inputs.

**Deferred, not yet dimensioned:** `published_year`, `average_rating`, `num_pages`,
`ratings_count`, `is_children`, `categories` are real `BookModel` columns without their
own retrieval node yet — they stay inside `db/schema/filter_schemas.py`'s `BooksFilter`
for the DB-layer store queries (`book_store.search_by_filters`), just not exposed to the
planner. A cross-column or quantitative query ("sci-fi books over 300 pages") currently
has no node that can serve it — until the clarification node exists, it silently doesn't
route to anything meaningful. Worth a dedicated eval case once the clarification node
lands (roadmap Phase 1, still open).

**Removed from V1:** `Analyze_Compare` (`CompareStrategy`) is unregistered as of
2026-07-17 — pulled from `BOOK_ANALYZE_CLASSES`, `BOOK_NODE_TYPE_TO_CLS`, and
`AnyStrategyRequest`. The class and its mock executor (`CompareBooksExecutor`) stay
defined and directly importable — genuinely parked, not deleted — since the mock
executor was fully canned (never read which books it was "comparing"), which
undercuts the planner showcase more than a clean absence would. It returns once a
real executor exists, likely alongside single-book analysis (owner's note: "need a
single book analyze node"). `Retrieve_by_Traits` (`FindByTraitsRetrieval`) was deleted
outright — not parked, not narrowed — since the four dimension-specific nodes above
replace what it was trying to do.

## V1 conversation contract: clarify-only, single-turn

- Every query stands alone. No history is loaded
  (`app/domains/planner/parse_intent.py` has a NOTE where prior messages would go —
  deliberately not implemented for V1).
- Ambiguous, unsupported, or unimplemented requests always get a clarification or
  rejection **reply**, never a silent plan shrink. No recovery, no goal buffering:
  one query, and the system can or can't finish it — then it directs the user to a
  clearer follow-up query.
- References to prior turns ("the previous one", "that book") are out of scope and
  should trigger the clarification node.
- Multi-turn conversation context is the flagship V1.1 feature (see roadmap deferred
  list). `chat_runs` already records every turn, so history loading can be added
  without schema changes.

## Registry changes

**Done (2026-07-17):**

- Book-domain class tuples and the node_type→class mapping moved out of
  `app/registry.py` into a new [`app/domains/books/registry.py`](../../backend/app/domains/books/registry.py)
  (`BOOK_RETRIEVAL_CLASSES`, `BOOK_ANALYZE_CLASSES`, `BOOK_NODE_TYPE_TO_CLS`);
  `app/registry.py` now composes it rather than defining book entries inline. Other
  domains (users, project) are untouched — still defined inline in `app/registry.py`.
- `FindByTraitsRetrieval` deleted; `FindByAuthorRetrieval` and `FindByGenreRetrieval`
  added (`FindByAuthorRetrieval` promoted out of the playground extension — removed
  from `ExtendedBookNodeTypeEnum`/`extended_request_schemas.py`/`extended_registry.py`
  so the node_type string isn't defined twice).
- `filters` removed from `RecommendationStrategy`.
- Mock executors (`playground/app_mock/executors/books/`) updated to match: 
  `find_by_traits.py` deleted, `find_by_author.py`/`find_by_genre.py` added, and all
  four retrieval mocks now build their `build_data()` payload through the new output
  schemas instead of ad-hoc dicts.

**Still open (roadmap Phase 1):**

- Remove `CompareStrategy` from `NODE_TYPE_TO_CLS`/catalog (class stays parked).
- Register `Provide_Feedback`.
- Add the clarification/rejection node: schema + enum entry + registration + planner
  handling so refused goals produce it.
- Repointing `EXECUTORS_CLS_MAPPING` off the mocks happens later (Phase 3), when real
  executors exist.

## The extension block (manual toggle — by design)

The bottom of `registry.py` folds ~18 scalability-testing schemas from
`playground/app_mock/extended_registry.py` into the live registry (FindByAuthor,
SaveToReadingList, RateBook, ReadingPlan, …). **This is intentional**: the registry is
manual, and commenting the block in/out is the toggle for scaling experiments. Nothing
else in the file needs to change when toggling. Two things follow:

- The extended eval suite (`query_suite_extended.json`) only makes sense with the block
  **in**.
- The V1 release build ships with the block **commented out** — it's an item on the
  release checklist in [../roadmap.md](../roadmap.md), not a code change.

## Future considerations

- **Extension graduation:** an extended node that earns its place gets a real schema
  under `app/domains/`, a registry entry, an executor, and eval cases — the same "how
  to add a node" path documented in `backend/app/domains/README.md`.
- **Compare returns** after single-book analysis exists (owner's note: "need a single
  book analyze node").
- **Book-clamped recommendations** — always attach a recommendation to a successful
  lookup ("do you have Dune? — yes, and I think you'll like these"). Feels consumer-like;
  a candidate once execution is real.
- **HITL re-rank** — the recommendation node is the natural human-in-the-loop point when
  there are many candidates.
