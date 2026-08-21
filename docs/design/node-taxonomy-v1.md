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
| `Retrieve_by_Title` | `FindByTitleRetrieval` | Core retrieval — `title: str` only (the optional `authors` hint was dropped 2026-07-28; see below) |
| `Retrieve_by_ISBN13` | `FindByISBN13Retrieval` | Core retrieval — exact `isbn13` |
| `Retrieve_by_Author` | `FindByAuthorRetrieval` | Core retrieval — `author: str` (was `authors: list[str]`; see the 2026-07-21 split below), promoted out of `playground/app_mock/extended_request_schemas.py` |
| `Retrieve_by_CoAuthors` | `FindByCoAuthorsRetrieval` | Core retrieval — `authors: list[str]` (min 2), joint works only. Added 2026-07-21 |
| `Retrieve_by_Category` | `FindByCategoryRetrieval` | Core retrieval — subject, shelf and audience. Registered 2026-08-21; was sketched as `Retrieve_by_Genre` / `FindByGenreRetrieval` with a single `genre: str`. See the record below |
| `Retrieve_Random` | `RandomBookRetrieval` | Core retrieval — optional `filters: BooksFilter`, one arbitrary pick. Promoted out of `playground/app_mock/extended_request_schemas.py` 2026-07-28; see below |
| `Analyze_Recommend` | `RecommendationStrategy` | LLM ranking/response step, **no filters field** |
| *(new)* clarification/rejection | not yet built | Turns refused or ambiguous goals into a helpful reply — still open |
| `Provide_Feedback` | `FeedbackRequest` | Registered 2026-07-17 (`app/domains/project/registry.py`) — conversational feedback about the app, distinct from the reviewer workflow's `PUT /feedback/review` |
| `Retrieve_Project_Info` | `ProjectInfoRequest` | Kept — cheap, already works |
| `Retrieve_User_Info` | `UserInfoRequest` | Kept |
| `Retrieve_Developer_Info` | `DeveloperInfoRequest` | Kept |

Every retrieval node's structured result is typed via
`app/domains/books/schemas.py` (`Book` + one `Output` class per node) — the contract
downstream nodes and eval/review tooling see. `Book` carries every `books` column
except `embedding`; that one omission is load-bearing, since these models are
serialized into `chat_runs` JSONB and a per-book vector would bloat every run record.

There is deliberately **no narrower book model** (revised 2026-08-07). An earlier
`BookSummary`/`ReferenceBook` pair tried to keep presentation fields out of the LLM
prompts, but the prompt-facing renderers already select fields by hand, so the types
were never what enforced it — only a second field list free to drift from the first,
which it did. Narrowing belongs at the point of use: a renderer picking fields, or
`model_dump(include=...)`.

**Deferred, not yet dimensioned:** `published_year`, `average_rating`, `num_pages`,
`ratings_count`, `is_children`, `categories` are real `BookModel` columns without their
own retrieval node yet — they stay inside `db/schema/filter_schemas.py`'s `BooksFilter`
for the DB-layer store queries (`book_store.search_by_filters`), just not exposed to the
planner. A cross-column or quantitative query ("sci-fi books over 300 pages") currently
has no node that can serve it — until the clarification node exists, it silently doesn't
route to anything meaningful. Worth a dedicated eval case once the clarification node
lands (roadmap Phase 1, still open).

> **Superseded for the four numeric columns (2026-08-20).** `average_rating`,
> `ratings_count`, `num_pages` and `published_year` now have a retrieval node —
> `Retrieve_by_Numeric_Traits`, below. The cross-column shape named here ("sci-fi books
> over 300 pages") is deliberately *not* what that node serves: it has a subject, so it
> is `Retrieve_by_Category` + `Filter_Retrieval`.
>
> **`categories` dimensioned 2026-08-21** by `Retrieve_by_Category` — see the record at
> the end of this file. Every `books` column now has a retrieval node except `isbn10`,
> `thumbnail` and `title_and_subtiles`, none of which is a search dimension.

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

### Author split (2026-07-21)

`FindByAuthorRetrieval` carried `authors: list[str]` and a docstring saying multiple
names were "one combined bibliography search". That made it two nodes wearing one name,
and it could only ever express the OR:

- **union** — "books by Austen and books by Coelho", two independent bibliographies;
- **intersection** — "what did Brian Herbert and Kevin J. Anderson write *together*",
  one set of books credited to both.

A single list field can't distinguish them, so the intersection was unreachable: the
node had no way to say "and", and the executor's `any(...)` match would happily return
Austen's solo novels for a collaboration query. Split accordingly:

- `Retrieve_by_Author` takes `author: str` — exactly one author per node. The union case
  becomes N nodes, one per author, which is the rule `Retrieve_by_Title` already follows
  ("one title per node — for multiple named titles, emit one node per title"). Every
  retrieval node is now single-**valued** as well as single-dimension.
- `Retrieve_by_CoAuthors` takes `authors: list[str]` with `min_length=2` and ANDs them —
  a book is returned only when every named author is credited on it.

The data supports the AND directly: `books.authors` is a semicolon-delimited credit
string (`"Brian Herbert;Kevin J. Anderson"`), so each name is matched as a substring of
the whole credit.

`FindByCoAuthorsOutput` may legitimately come back with an empty `books` — that *is* the
answer to "did they ever write together?". The mock finder (`mock_books.find_by_coauthors`)
therefore deliberately omits the fallback-to-first-book behaviour the other mock finders
have, which would otherwise make the mock lie about the one thing this node exists to
check.

The discrimination risk this adds is the two-name query shape being read as the wrong
one — base eval cases 53 (union → two `Retrieve_by_Author`) and 54 (joint →
`Retrieve_by_CoAuthors`) are deliberately the same shape with opposite expected plans,
so the pair is the actual test. Related: eval-strategy.md's known-failure #4,
"`Retrieve_by_Author` over-triggers whenever an author appears in the query".

### Title/author hint removed (2026-07-28)

`FindByTitleRetrieval` dropped `authors: Optional[list[str]]`. The field was the last
place a retrieval node carried a second dimension, and it was a dimension the node never
actually used: no executor read it, so "Dune by Frank Herbert" and "did Frank Herbert
write Dune" were answered by a title lookup with the author riding along as an
unvalidated string.

A title paired with an author is now expressed the way every other two-dimension request
is — by composition: `Retrieve_by_Title` + `Retrieve_by_Author` + `Combine_Intersect`.
This finishes what the 2026-07-21 author split started: every retrieval node is now
single-dimension *and* single-valued, with no exceptions, so the combine tier is the only
place a plan says "and".

What this buys, beyond consistency: authorship verification becomes real. "Did Jane
Austen write Dune?" used to be a title lookup that could only ever return Dune — the
author hint had no way to contradict it. Intersected against Austen's bibliography, the
empty result *is* the "no", the same way `FindByCoAuthorsOutput`'s empty `books` answers
"did they ever write together?".

What it costs: three nodes where one used to do, and the author leg fetches a whole
bibliography to keep one book. For a common query shape ("find X by Y") that is a real
latency and token increase, and the intersect is now load-bearing — a plan that emits the
two retrievals and forgets the intersect silently answers "Dune OR anything by Herbert".
The pooling-vs-AND discrimination that base case 7 and extended case 119 test was
previously free; it is now something the planner has to get right on an easy query.

### `Retrieve_Random` promoted to V1 core (2026-07-28)

`RandomBookRetrieval` moved out of `playground/app_mock/extended_request_schemas.py` into
`app/domains/books/schemas/request_schemas.py` and is now registered, with a
`RandomBookOutput` result type and a mock executor — the same promotion path
`FindByAuthorRetrieval` took on 2026-07-21. It is the only V1 retrieval node that is not
single-dimension: it carries an optional `BooksFilter`, because a random pick has no
dimension to be single about.

What it settles is the *bare* recommend. "Recommend me a book", with nothing else said,
had no honest plan under the old node set: `Analyze_Recommend` needs a supporting
retrieval, and there is no taste input for one to be built from, so the planner either
invented an anchor or produced a retrieval that answered a question the user hadn't
asked. `Retrieve_Random` is now that plan, **alone** — its docstring says explicitly that
no `Analyze_Recommend` follows it, since the node already returns a book and there is
nothing to rank. The moment the ask carries any taste, mood, or anchor ("a book like
Dune", "something spooky"), it is a real recommendation again and this node is wrong.

**`Filter_Retrieval` may not depend on it.** Stated in both docstrings. Filtering one
arbitrarily chosen book usually discards the pick and answers with nothing — the failure
is silent and looks identical to "no matches". A bounded surprise ("surprise me with a
short sci-fi") puts the bounds in `Retrieve_Random.filters`, so the pick is drawn from
inside them rather than tested against them afterwards. This is the same
search-within-bounds vs. delete-afterwards distinction `Analyze_Recommend` already draws —
as of 2026-08-19 by parsing the bounds out of its own goal text and putting them in its
vector search's WHERE, so the pool it ranks already fits (execution-pipeline-v1.md) — and
it is convention only: nothing in the schema enforces it, so the golden test is what holds
the planner to it.

**Cost:** 345 catalog tokens on every request, and one more node the planner can confuse
with `Analyze_Recommend` — the two are separated by whether the user expressed taste,
which is a judgment call, not a structural one. Worth watching in the adversarial suite.

### Typed `Returns:` / `depends_on:` in every docstring (2026-07-28)

Node docstrings now state their output **shape** and what shapes they may depend on,
in a fixed four-name vocabulary: `BookRetrievalOutput` (a book list — every retrieval
node and the whole combine tier), `BookRecommendationOutput` (books that were chosen,
from `Analyze_Recommend`), `AnalyzeBooksOutput` (a written report — compare, summarize,
themes, reading order/level/time/plan), and `ActionConfirmationOutput` (a write
record). Shapes outside it are named per node (`AuthorInfoOutput`, `ReadingStatsOutput`,
`UserInfoOutput`, …). `depends_on:` is now an audited section in
`evals/tools_catalog.py`, so a new node cannot ship without declaring what it consumes.

The distinction that does the work is **report vs. book list**. `Analyze_Reading_Order`
and `Analyze_Reading_Plan` both name books, and both are reports: they re-sequence or
schedule what they were given and never add a book, so nothing downstream may treat
them as a retrieval. `Retrieve_Reading_List` goes the other way — it looked like an
account-info node but produces books, which is what lets base case 50 ("nothing by
authors I've already read") work at all: the shelf feeds `Analyze_Recommend` as an
anchor or an exclusion source. `Retrieve_Author_Info` and `Retrieve_Reading_Stats` are
the honest negatives — prose about a person and counts respectively, consumable by
nothing that depends on books.

**The vocabulary is planner-facing only, and does not yet exist in code.**
`output_schemas.py` still defines one concrete class per retrieval node
(`FindByTitleOutput`, `FindByGenreOutput`, …), all structurally
`{what_was_searched, books}`, and has no class at all for the recommendation, analyze,
or confirmation shapes. So the docstrings currently describe a contract the executors
do not enforce. Closing that gap means collapsing the per-node classes into a real
`BookRetrievalOutput` and adding the missing three — a change to six classes and six
mock executors, deliberately not taken on the same day as the docstrings. Until it
lands, a plan can wire a report into a node expecting books and nothing will object.

> **Status update (2026-07-18):** `CompareStrategy`/`Analyze_Compare` was re-registered
> (commit `9d0e402`, "registered compare for eval test") — it's back in
> `BOOK_ANALYZE_CLASSES`/`BOOK_NODE_TYPE_TO_CLS`. The "removed from V1" paragraph above
> is the historical decision, not the current registry state; [roadmap.md](../roadmap.md)'s
> Phase 1 checklist and deferred-features table say the same "removed" thing and are
> stale in the same way. Reconcile both whenever Compare's fate is finally settled — see
> the open question below, surfaced by re-enabling it for eval testing.

### `Retrieve_by_Numeric_Traits` — bounds as a subject (2026-08-20)

`Retrieve_by_Numeric_Traits` (`FindByNumericTraitsRetrieval`, slice
`books/find_by_numeric_traits/`) is registered: a RETRIEVAL-tier node carrying a whole
`BookMetadataFilter`, which searches the catalog by measurable traits alone.

**What it fixes.** A request made only of numbers had nowhere to go. `Filter_Retrieval`
is COMBINE-tier and requires an anchor (`FilterRetrievalInput.anchors` is
`Field(..., min_length=1)`), so "find books with fewer than 200 pages" could only be sent
to a clarification node that was never built. Base cases 12 and 58 baselined to *no nodes*
for exactly this reason, and 15, 27 and 34 expected `Retrieve_Popular`, a node that only
ever existed in `playground/app_mock/`. All five are re-baselined.

**Why this is not `Retrieve_by_Traits` coming back.** The deleted node (see above) blurred
with `Analyze_Recommend` because both carried filter fields and nothing structural chose
between them. Three things are different now:

- **The request schema is fieldless.** Under the rule-1a split the planner sees only a
  docstring and a `node_type`; the `BookMetadataFilter` lives on `FindByNumericTraitsArgs`,
  an internal tool the node's own parse ships. No `BooksFilter` is on a planner-facing
  schema, which is the thing the original decision removed.
- **`Analyze_Recommend` no longer competes.** It lost `filters` in 2026-07-17 and since
  2026-08-19 parses its own bounds out of its goal text and applies them *inside* the
  vector search. Bounds on a recommendation were already settled as staying with the
  recommendation.
- **The separation from `Filter_Retrieval` is `depends_on`.** This node takes an empty
  `NodeInput`; that one requires ≥1 anchor. A mis-emitted `Filter_Retrieval` with no anchor
  fails `build_input` and is skipped by the runner naming the field, rather than running.

**The numbers-only rule.** This node fires only when the numbers are the *entire* request.
Any other subject and the bounds narrow that subject instead. Both docstrings carry the
rule, and it is prose — the schemas do not enforce it, since a plan with a genre node and a
numeric node in it is structurally legal. Base cases 76/77 are the same query one word
apart and are what actually hold it, the role cases 53/54 play for the author/co-author
split.

**Superlatives are bounds, not ordering.** "Highest rated" becomes `min_rating: 4.3`.
Deferred queries carry no `ORDER BY` and no `LIMIT` by invariant, and the node emits no
`score` column, so `materialize_stmt` falls back to `average_rating DESC` — right for
"well rated" and "most popular", wrong for "the longest books", which ranks by rating.
Accepted; emitting the named trait as `score` is the one-line fix if evals ask for it.

**Vague language is inferred, and that cost two things.** "Well rated", "obscure",
"the classical period" have to become numbers. The calibration lives on
`BookMetadataFilter`'s **field descriptions**, not in the slice, because the same model is
shipped inside `FilterRetrievalArgs` and `RecommendationArgs.bounds` and the three must not
calibrate "well rated" differently. Two findings from measuring it against the live model
rather than assuming:

- **The shared `basic_fill_schema_prompt` is wrong for this node.** It says "do not use
  prior knowledge" and "do not infer arguments that do not match the query" — correct for
  the parses that lift a title or author out of a sentence, and a direct instruction against
  this node's job. Under it, "obscure books nobody has heard of" and "something really long"
  both parsed to an *empty* filter while literal numbers worked, which made the failure look
  like a schema problem. The slice has its own prompt, the way `analyze_recommend/` does.
- **`reasoning_effort="minimal"` cannot do this parse.** On an eight-phrase calibration set,
  `gpt-5-nano`/minimal scored 2/8 and also corrupted output ("fewer than 200 pages" →
  `min_pages: 200, max_ratings_count: 1000`); `gpt-5-nano`/low scored 8/8. `gpt-5-mini`
  bought nothing over nano at either effort, so the model stays the cheap one and only the
  effort changed. This is the first node to diverge from the template's model settings, and
  it is the reason each slice builds its own `build_arg_parser_request`.
- **"Infer from a vague word" and "invent from nothing" had to be separated explicitly.** A
  first draft of the prompt said *never return an empty filter*, reasoning that every goal
  reaching this node has something measurable in it. Handed a mis-routed goal ("find me a
  book about dragons") the parser duly invented `max_pages: 1000, min_rating: 4.0,
  min_year: 2000` and the node answered with 1,380 books — a confident answer to a question
  nobody asked, and worse than the empty filter it was written to prevent. It also defeated
  the executor's own `if not bounds: raise` guard, which is the node's backstop against
  being handed the wrong goal. The rule now names both halves separately: infer freely from
  a vague word, never invent from nothing, and let an empty filter fail the goal.

**Cost:** ~550 catalog tokens on every request, and `Filter_Retrieval` grew to ~578 after
its docstring took on the numbers-only rule — together 53% of a five-tool catalog. That is
the strongest argument for the merge considered and declined below.

**Considered and declined: optional anchors.** `numeric_traits_query(filters)` and
`filter_query(base, filters)` are the same predicates with and without a base, so one node
with `anchors: list[BookRetrievalOutput] = []` would have absorbed `Filter_Retrieval`
outright and removed the discrimination problem structurally instead of by prose. Declined
by the owner (2026-08-20) pending a clearer read on how `Filter_Retrieval` is actually
being used; it is the obvious shape to revisit when that node is removed, and it would take
the 53% catalog share back down with it.

**Also landed with it:** `BookMetadataFilter` gained `ge`/`le` bounds and an inverted-range
validator, closing adversarial cases 301–303 (negative pages, "year 300 BC", "rated above
9999 stars") for all three consumers at once. `min_year`/`max_year` deliberately take no
upper bound — the catalog ending at 2019 is a fact about the dataset, not about reality, so
"published after 2020" stays a legitimate question whose honest answer is zero.

### `Retrieve_by_Category` — subject as a search (2026-08-21)

`Retrieve_by_Category` (`FindByCategoryRetrieval`, slice `books/find_by_category/`) is
registered: a RETRIEVAL-tier node carrying three facets — subject keywords, fiction-ness
and audience — ANDed into one deferred query. It replaces the sketched
`Retrieve_by_Genre`/`FindByGenreRetrieval`, which never got past a schema fragment.

**What it fixes.** A request that named no title had no legal plan at all — see
[node-refusal-v1.md](node-refusal-v1.md), which opens on exactly this. "Give me a book
about war" routed to `Retrieve_by_Title` and parsed `title="war"`. Twelve base cases sat
red waiting for this node, two of them noted as such in the suite.

**Why it is not one dimension.** This is the **second documented exception** to the
single-valued rule, after `Retrieve_by_Numeric_Traits`. The reason is the same in shape and
different in kind: bounds have no single dimension to be single about, and neither does a
subject, because "non-fiction about history" is one question and not two to intersect. The
facets cut the same rows on different axes rather than naming different columns.

**Why the name changed from `Retrieve_by_Genre`.** The old name is what the planner LLM
reads first, and it biases toward shelf labels — but `books.categories` holds one
Google-Books shelf label per book (480 distinct over 5,197 rows) and cannot answer a topic
at all: `%ninja%`, `%space%` and `%artificial intelligence%` each match **zero** rows there.
The subject lives in `books.description`. A node named for genre would have been named for
the one column that cannot do the job.

**Lexical, not semantic — the line against `Analyze_Recommend`.** Both nodes can be handed
"books about ninjas", so something has to choose. The old fragment tried "what a book is
FILED UNDER, not what it is LIKE", which "cozy mysteries" defeats — *cozy* is neither. The
line that holds is the mechanism: **this node asks whether the catalog's text contains
these words** (`to_tsvector` over title + shelf + blurb) and hands on a composable query
over the whole match; **`Analyze_Recommend` asks which books are near an embedding** and
hands back a ranked terminal choice. "Cozy mysteries" splits cleanly — *mystery* is a word
the text contains, *cozy* is a feel no word search can find. Both docstrings now state it
from their own side. This is the passage in
[execution-pipeline-v1.md](execution-pipeline-v1.md) that had closed the door on a
`keywords` field, reopened deliberately and on a narrower basis.

**Measured, not assumed.** Full-text search rather than ILIKE or trigram, because it stems
("ninjas" finds the one ninja book without a second keyword) and respects word boundaries:
`description ILIKE '%war%'` matches 985 books including "toward" and "warm", while the
tsquery matches 442. `plainto_tsquery` already ANDs the words it is handed, so N keywords
are joined into one probe rather than N ANDed ones.

**The genre trap.** `books.genre` holds exactly four values — `Fiction`, `Nonfiction`,
`Children's Fiction`, `Children's Nonfiction` — and `genre ILIKE '%Fiction'` matches **all
5,197 rows**, because "Nonfiction" ends in "fiction". Genre and audience are therefore
exact set membership over an intersected value set, never a pattern match.

**Audience, and the `is_children` split.** `books.is_children` is NULL on all 5,197 rows,
so `BookMetadataFilter.is_children` has always matched nothing — a silent zero wherever it
is set. This node resolves audience against `books.genre` instead (447 books). It
deliberately did **not** claim the field: `BookMetadataFilter.is_children` stays where it
is by owner decision (2026-08-21), so audience is now reachable by one working path and one
dead one. Both sites carry a comment saying so. The fix, when it is picked up, is deleting
the field and its two lines in `metadata_predicates`.

**The index is load-bearing and fragile.** Unindexed, the document expression is a 520ms
sequential scan. `books_search_idx` (GIN, `db/schema/02_indexes.sql` plus a dated migration,
since that file only runs at container init) takes it to ~5ms. Two things silently disable
it, both of which look like cleanups: passing `'english'` or `''` as Python strings, which
SQLAlchemy binds as parameters that a generic plan cannot match against a constant-folded
index expression; and `concat_ws(' ', ...)`, which is STABLE rather than IMMUTABLE. The
expression is written twice — once in `search_document()`, once as DDL — and
`tests/unit/db/stores/test_category_query.py` asserts both the absence of bind parameters
and that the two copies match.

**Cost:** ~522 catalog tokens on every request; the catalog is now six tools at 2,690.

**Known broken downstream: `Retrieve_by_Category` → `Analyze_Recommend`.** The pairing eval
cases 3, 11, 45 and 47 expect fails, and it is not this node's bug.
`BookWorkflow.fetch_anchor_books` raises `NotImplementedError` when the pooled anchor holds
more than `MAX_ANCHOR_BOOKS` (5), carrying its own TODO — *"for now, re-query and only get
the top rated"*. That cap was survivable while every anchor was a title search returning
one or two books; a subject search returns 358 for "mystery", so the pairing fails every
time. Verified end-to-end 2026-08-21: "Recommend me a cozy mystery" plans correctly
(`keywords=["mystery"]` here, *cozy* left to `semantic_input`), the category node finds 358
and finalizes ok, and the recommend node then dies on the cap.

The fix is the TODO's own sentence and lives in `fetch_anchor_books`, not here:
`materialize()` already takes a `limit` and already orders by the query's `score` (or by
rating once a composition has dropped it), so taking the top `MAX_ANCHOR_BOOKS` instead of
raising is a few lines. It is deliberately **not** part of this change — the owner scoped
this round to the category node and left `Analyze_Recommend` untouched — but it is the
first thing to do next, because it is what makes a subject a usable anchor rather than only
a usable answer.

**Deliberately deferred: the embedding arm.** A threshold-only vector query with no
`ORDER BY`/`LIMIT` is a legal `DeferredBookQuery` (verified: ~450ms on this catalog, since
ivfflat only helps an ordered, limited scan), so this node can grow a semantic arm that
still composes. v1 is lexical only, and the slice is shaped as the template for that.

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

**Done (2026-08-04) — vertical slices and `NodeSpec`:**

- A node is now one folder, not entries scattered across five files.
  `app/domains/<domain>/<node>/` holds `labels.py`, `schemas.py`, `executor.py`
  and an `__init__.py` exporting a single
  [`NodeSpec`](../../backend/app/domains/node_spec.py) (node_type, tier, request,
  output, executor). `app/domains/books/registry.py` became `guide.py` and is now
  just the tuple of that domain's specs — one line per node.
- `app/registry.py` **derives** `NODE_TYPE_TO_CLS`, the tier class tuples,
  `CATALOG_TIERS`, `AnyStrategyRequest`, `NodeTypeEnum` and the executor mapping
  from `SPECS`. Those five used to be maintained by hand and could disagree; they
  now cannot. Parking a node is deleting its SPEC from the guide, replacing the
  comment block that used to explain which three lists a parked class was absent
  from.
- `NodeTypeEnum` is a flat enum built from the specs, not a `Union` of per-domain
  enums. A union renders in the JSON schema as an `anyOf` of one-member enums —
  it grows per node and constrains the model less than one enum. It also ends the
  class of bug where the enum advertised 11 names while the registry held 2; the
  enum and the registry are now the same list by construction. `unknown` stays a
  member so the planner keeps its graceful "no capability fits" refusal.
- `NodeSpec.__post_init__` checks the spec's `node_type` against the request
  schema's `Literal` default. This is the guard for a real bug: a slice written
  as `Retrieve_By_Title` (capital `By`) against a codebase that says
  `Retrieve_by_Title` everywhere would have silently broken the
  `report_system_goals` golden diff.
- Executors subclass `NodeExecutor` (renamed `NodeBaseWorkflow` on 2026-08-07,
  see below — [`app/domains/base_workflow.py`](../../backend/app/domains/base_workflow.py)),
  which pins the `run(task, dependent_results, request_context)` signature the
  task runner calls and resolves the output type from the generic parameter.
- The output-shape vocabulary is now partly real classes:
  `app/domains/books/schemas.py` defines `Book`, `BookRetrievalOutput` and
  `BookRecommendationOutput`, and each node's output subclasses the shape its
  docstring claims. `AnalyzeBooksOutput` and `ActionConfirmationOutput` remain
  reserved names with no class — no registered node produces either yet. This
  closes half of the gap the old `output_schemas.py` module docstring described.

**Done (2026-08-07) — a books-domain executor base:**

- [`app/domains/books/base_workflow.py`](../../backend/app/domains/books/base_workflow.py)
  adds `BookBaseWorkflow`, one layer under `NodeBaseWorkflow`, holding the three
  things every book node was repeating: `self.store` (bound from the request
  context before the slice runs), `preflight()` and `stream_books()`. Book slices
  implement **`execute(query, dependent_results)`**; `run()` belongs to the base
  now, which is what makes the store binding impossible to forget.
- `preflight(query)` is the counts-first opening move as one call: it stamps
  `query`/`query_sql`/`num_books` on the output and returns `(total, sample)` from
  a single `BookStore.preview` round trip. It deliberately does not assign
  `output.books` — whether a sample is the node's answer is the caller's call, so
  that line stays visible in the slice.
- `stream_books()` moved off the generic base with it, which no longer imports
  `Book` (it could only do so under `TYPE_CHECKING`, since `books/schemas.py`
  imports back into it) or the API's `BookOut`.
- Both bases were renamed to say what they are: `node_executor.py`/`NodeExecutor`
  → `base_workflow.py`/`NodeBaseWorkflow`, matching `NodeBaseWorkflow` one layer
  up. **Only the two bases changed**, after weighing a full sweep of "executor"
  → "workflow" (87 Python references, 27 files) and rejecting it. The rule that
  came out of that: **`Base` marks a reusable base class**, since concrete work
  is named `*Workflow` throughout the planner (`PlannerWorkflow`,
  `TaskRunnerWorkflow`); **`Executor` marks the subset of concrete workflows the
  planner can dispatch** — a node with a request schema, a `NodeSpec` and a
  catalog entry, reached through `EXECUTORS_CLS_MAPPING`. So slices keep
  `<node>/executor.py`/`<Node>Executor`, and so do `NodeSpec.executor` and the
  mocks. Written up in `backend/app/domains/README.md`.

**Done (2026-08-07) — argument parsing moved into the slices:**

- `NodeBaseWorkflow.parse_arguments()` and `build_arg_parser_request()` are gone,
  and with them the `tool_cls` class attribute each executor declared to feed
  them (it duplicated `NodeSpec.request` anyway). A slice now writes its own
  module-level `build_arg_parser_request(query)` and calls
  `NodeBaseWorkflow.run_llm_args_parse(req)` directly — the same shape
  `build_analysis_request` / `build_response_request` already had in the
  analyze_recommend slice, so there is one way to build an LLM request instead of
  two.
- The slice also assigns `self.output.args` itself. That line used to be a side
  effect of `parse_arguments`, which meant nothing at the call site said the
  node's parsed arguments had been recorded.
- **The tradeoff is deliberate duplication**: the two builders are near-identical
  today (same prompt, `gpt-5-nano`, minimal reasoning, one `AssistantMessage`).
  Held in a base class, per-node divergence — a bigger model for a node with a
  harder schema, previous messages for a node that needs them — costs a flag or
  an override hook each time. Held in the slice it costs nothing. Only
  `ARG_PARSER_PROMPT_PATH` stays shared, in `app/domains/base_workflow.py`.
- Direction of travel for `NodeBaseWorkflow`: it now pins the `run()` signature,
  resolves the output type, and carries the UI section fields — nothing else.
  The owner's note in `backend/TODO.md` ("you might not need node_workflow …
  since a lot of that is for the app_workflow") is the next step past this one.

**Done (2026-08-08) — one call shape, and services off the context:**

That "next step past this one" landed, and went further than merging the two
bases. `AppBaseWorkflow` and `NodeBaseWorkflow` are now a single **`AppWorkflow`**
(`app/domains/base_workflow.py`), `BookBaseWorkflow` is **`BookWorkflow`**, and
the ladder is three deep: `airglider.Workflow` → `AppWorkflow` → `BookWorkflow`.

- **`run(query, artifacts)` is the signature of *every* unit of work**, not just
  the dispatchable ones. The planner, the parse step, the task runner and both
  book executors answer to it. Previously there were four different `run`
  signatures against one `__call__` passthrough. The shape is
  `node(input)` — a node parses its input, rejects it, or continues with it —
  which is what lets a node sit at any position in a plan.
- **The plan reaches `TaskRunnerWorkflow` as an artifact**, not a named
  `planner_result` parameter. Artifacts are **selected by type**
  (`require_artifact(artifacts, PlannerOutput)`), never by key, generalizing the
  rule `ParsedDependents.from_results` already followed — it iterates
  `dependent_results` and dispatches on the value's shape, ignoring the key.
  Keys stay provenance. `require_artifact` raising `StepFailure` *is* the reject
  arm, written once instead of per node.
- **Services stopped being constructor arguments.** `AppWorkflow.__init__(ctx,
  messages)` is the only `__init__` in the app layer; `sse_stream`,
  `llm_client`, `app_env`, `session_id`, `user_message` and `BookWorkflow.store`
  are properties off the `RequestContext`. Four bespoke `__init__`s went away —
  they existed only to unpack a context the caller already had and forward its
  pieces down by hand. Properties rather than assignments meant ~50 existing
  `self.<service>` reads needed no edit.
- **`BookWorkflow.execute()` is gone**; slices implement `run()` directly. The
  hook existed only to stop a slice from overriding the `run()` that bound
  `self.store`. With `store` a property there is nothing to lose. The comment
  justifying late binding ("an executor is constructed before that session is
  handed to it") was already false — the task runner constructs each executor
  *inside* its own `run()`, where the context has been in scope the whole time.
- **The `Base`-marks-a-reusable-base-class rule is retired.** It was written when
  the ladder was four deep; at three, the file a class lives in already says
  whether it is a base, and `AppBaseWorkflow`/`BookBaseWorkflow` read worse than
  what they name. `Executor` still marks the subset the planner can dispatch.
- Two bugs fell out of the merge. `_generic_output_type` had been *called but
  undefined* since `AppBaseWorkflow` was deleted, so **no book executor could be
  constructed at all** — nothing outside a live request ever built one.
  `NodeWorkflowOutput.id`/`.args` were non-Optional with `None` defaults, so any
  output rejected its own `model_dump_json` on reload — the same defect
  `PlanJaneOutput.out_of_scope` already carried a note about, and it would
  have bitten replaying `chat_runs` rows. `tests/unit/app/domains/test_app_workflow.py`
  now parameterizes over the live registry so a new slice is covered the day it
  is registered.

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
  book analyze node"). Re-registering it early for eval testing (see status update
  above) surfaced the open question directly, via eval case `chat_e35fc1e0`
  (`query_suite` #23, "Compare the themes of Pride and Prejudice and Jane Eyre"):
  should the plan be
  (a) `Retrieve_by_Title` ×2 → `Analyze_Themes` ×2, with the final response-generation
      step doing the compare/synthesis implicitly, no dedicated compare node in the DAG; or
  (b) `Retrieve_by_Title` ×2 → `Analyze_Themes` ×2 → `Analyze_Compare` depending on
      both `Analyze_Themes` task ids, producing the comparison itself?
  (b) matches this note's original intent and keeps "compare" a first-class,
  eval-checkable node, but requires widening `CompareStrategy.depends_on`'s contract —
  its docstring currently says depends_on is "Task ids of the prior retrieval steps,
  one per book being compared," not analyze-tier ids — plus a 3-hop example in
  `2_strategy_classification.txt` (today's only compare example is the 2-hop
  retrieve→compare shown in that prompt). Not yet decided.
- **Book-clamped recommendations** — always attach a recommendation to a successful
  lookup ("do you have Dune? — yes, and I think you'll like these"). Feels consumer-like;
  a candidate once execution is real.
- **HITL re-rank** — the recommendation node is the natural human-in-the-loop point when
  there are many candidates.
