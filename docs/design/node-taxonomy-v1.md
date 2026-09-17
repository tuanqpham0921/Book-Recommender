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
| `Retrieve_by_Lexical_Traits` | `FindByLexicalTraitsRetrieval` | Core retrieval — keywords, shelf and audience. Registered 2026-08-21 as `Retrieve_by_Category` / `FindByCategoryRetrieval`, renamed 2026-08-24; was sketched before that as `Retrieve_by_Genre` / `FindByGenreRetrieval` with a single `genre: str`. See the records below |
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
> is `Retrieve_by_Lexical_Traits` + `Filter_Retrieval`.
>
> **`categories` dimensioned 2026-08-21** by `Retrieve_by_Lexical_Traits` — see the record at
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

### `Retrieve_by_Lexical_Traits` — words as a search (2026-08-21, renamed 2026-08-24)

`Retrieve_by_Lexical_Traits` (`FindByLexicalTraitsRetrieval`, slice `books/find_by_lexical_traits/`) is
registered: a RETRIEVAL-tier node carrying three facets — subject keywords, fiction-ness
and audience — ANDed into one deferred query. It replaces the sketched
`Retrieve_by_Genre`/`FindByGenreRetrieval`, which never got past a schema fragment.

> **Renamed from `Retrieve_by_Category` on 2026-08-24.** "Category" named the narrowest of
> the three facets and read as a lookup against `books.categories`, which is not what the
> node does — it matches words across title, shelf label *and* blurb, and `categories`
> alone answers almost nothing (480 distinct shelf labels over 5,197 rows). The node is
> better described by its **mechanism**: it searches a book's *lexical* traits, the words
> its text actually contains. That also pairs it with `Retrieve_by_Numeric_Traits`, and the
> two now split the non-identifier half of retrieval on the only line that matters — words
> vs. numbers. The store method renamed with it (`BookStore.category_query` →
> `lexical_query`, `DeferredBookQuery(label="category")` → `"lexical"`), and the request
> docstring and args-parser prompt were reframed from "subject" to "lexical trait" so the
> planner and the parser read the same word. Nothing about the SQL, the facets or the
> anchors/candidates classification changed. **Eval suites: renamed, not re-baselined** —
> `Retrieve_by_Category` → `Retrieve_by_Lexical_Traits` across `query_suite.json` (17),
> `query_suite_adversarial.json` (14) and `query_suite_stress.json` (7), counting both
> `expected_nodes` entries and the notes that name the node, the same precedent
> as the `Analyze_Recommend` rename below. Recorded runs under `evals/results/` and
> `evals/bugs/` keep the old name: they are records of what ran.

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
`tests/unit/db/stores/test_lexical_query.py` asserts both the absence of bind parameters
and that the two copies match.

**Cost:** ~522 catalog tokens on every request; the catalog is now six tools at 2,690.

**~~Known broken downstream: `Retrieve_by_Lexical_Traits` → `Analyze_Recommend`.~~ CLOSED
2026-08-22 — the pairing is now illegal rather than broken.** The original entry, kept
because the resolution inverts it:

> The pairing eval cases 3, 11, 45 and 47 expect fails, and it is not this node's bug.
> `BookWorkflow.fetch_anchor_books` raises `NotImplementedError` when the pooled anchor holds
> more than `MAX_ANCHOR_BOOKS` (5), carrying its own TODO — *"for now, re-query and only get
> the top rated"*. That cap was survivable while every anchor was a title search returning
> one or two books; a subject search returns 358 for "mystery", so the pairing fails every
> time. Verified end-to-end 2026-08-21: "Recommend me a cozy mystery" plans correctly
> (`keywords=["mystery"]` here, *cozy* left to `semantic_input`), the category node finds 358
> and finalizes ok, and the recommend node then dies on the cap.
>
> The fix is the TODO's own sentence and lives in `fetch_anchor_books`, not here.

The expected fix — take the top 5 instead of raising — was **not** taken. Folding the five
best-rated of 358 mysteries into one "ideal book" would answer confidently from a sample
nobody chose, which is a worse failure than the crash because it looks like an answer. The
resolution instead is the anchors/candidates split below: `Retrieve_by_Lexical_Traits` returns a
`BookCandidateOutput`, `Analyze_Similar_Books` declares `list[BookAnchorOutput]`, and the
plan is refused at dispatch naming the field. `fetch_anchor_books` no longer exists.

Eval cases 3, 11, 45 and 47 stay red, and now mean something different: they assert a plan
the taxonomy has decided against, and what "recommend me a cozy mystery" *should* plan to
(the lexical retrieval alone, or a semantic node that needs no anchor) is undecided.

**Deliberately deferred: the embedding arm.** A threshold-only vector query with no
`ORDER BY`/`LIMIT` is a legal `DeferredBookQuery` (verified: ~450ms on this catalog, since
ivfflat only helps an ordered, limited scan), so this node can grow a semantic arm that
still composes. v1 is lexical only, and the slice is shaped as the template for that.

### `Filter_Retrieval` and `Analyze_Recommend` parked (2026-08-22)

> **Neither came back as itself.** `Analyze_Recommend` was unparked the same day as
> `Analyze_Similar_Books` (record below), and `Filter_Retrieval` was **deleted** on
> 2026-08-24 and replaced by `Combine_Intersect` (record at the end of this file). So the
> "unparking is one import and one SPEC line" note below never got used for either. What
> the parking recorded as lost — a bound riding alongside a subject, and second-stage plans
> — is what those two changes gave back.

Both dropped from `books/guide.py` at the owner's request. **Parked, not deleted** — the
slices stay importable, typechecked and unit-tested, and `describe_bounds` still comes from
`filter_books` (`find_by_numeric_traits` imports it and is still registered). Unparking is
re-adding one import and one `SPEC` line each.

The catalog is now **retrieval-only**: 4 tools, all `NodeTier.RETRIEVAL`, 1,644 catalog
tokens against 2,690 before (−39%). `catalog_entries()` drops empty tiers, so the
"Combine —" and "Analyze —" headings no longer render at all, and `NodeTypeEnum` is down to
the four node names plus `unknown`.

**What became unexpressible.** These are consequences of the decision, recorded so they are
not rediscovered as bugs:

- **A bound riding alongside a subject has nowhere to go.** "Fantasy books over 400 pages"
  was `Retrieve_by_Lexical_Traits` → `Filter_Retrieval`; the second half no longer exists. The
  numbers-only rule still holds — `Retrieve_by_Numeric_Traits` is for numeric-only asks —
  so both docstrings now say to send the subject goal alone and leave the bound in its
  description. They say so explicitly because the tempting alternative is worse: two goals
  with no dependency between them are **pooled (OR)**, so emitting the subject node *and*
  the numeric node would answer with more books rather than fewer.
- **Taste, mood and similarity have no node.** "Books like Dune", "something spooky",
  "cozy" — the semantic half of the lexical/semantic split recorded above. The planner will
  refuse these as out of scope, or reach for `Retrieve_by_Lexical_Traits` and match the words
  literally. `FindByLexicalTraitsRetrieval`'s `Do not use:` now tells it to keep the real subject
  word and drop the feel, which is the honest description of what the node can do.
- **No plan has a second stage.** Every plan is a set of independent retrievals. The
  `depends_on` machinery, `TaskRunnerWorkflow`'s dependency resolution and
  `DeferredBookQuery.compose()` are all still live and tested, but nothing registered
  produces a goal that uses them.

**Coverage cost.** `tests/unit/app/domains/test_app_workflow.py` parametrizes three
executor smoke tests over `RUNNABLE_SPECS`, so parking two nodes silently drops six tests
(608 → 602 collected). The parked executors keep their own unit tests
(`test_rank_candidates.py`, `test_parsed_dependents.py`, `test_describe_bounds.py`) but are
no longer checked for constructing against a narrowed context.

**Test coupling worth knowing.** `SystemGoal.target_node_type` is a `NodeTypeEnum`, so any
test naming a node type in a `SystemGoal` breaks the moment that node is parked.
`test_mermaid.py` used `"Analyze_Recommend"` purely as "a second node type" and was moved to
`"Retrieve_by_Lexical_Traits"`, with a docstring note that the names there are arbitrary.

**Eval suites left as they are.** `Analyze_Recommend` appears 81 times across the four
suites and `Filter_Retrieval` 24, which is most of `query_suite.json`. They were not
re-baselined: the same precedent as `Retrieve_by_Genre` while it was parked — the suite
names the target taxonomy and the golden diff reports the gap. Expect a large red block in
`make suite-goals` that reflects the parking rather than a regression.

### Anchors vs candidates — the retrieval output split (2026-08-22)

`BookRetrievalOutput` gained two subclasses in `books/external.py`, and the four registered
nodes were reparented onto them:

- **`BookAnchorOutput`** — the user *named* these books. `Retrieve_by_Title` today,
  `Retrieve_by_ISBN13` when it exists.
- **`BookCandidateOutput`** — these books match a *description* the user gave.
  `Retrieve_by_Author`, `Retrieve_by_Lexical_Traits`, `Retrieve_by_Numeric_Traits`.

Neither adds a field. `build_input` fills by `isinstance`, so **the type is the payload**: a
node declaring `list[BookAnchorOutput]` structurally cannot be handed a subject search.

**What it is for.** The distinction is real today and enforced in the worst possible place —
at run time, inside the consumer, after two round trips.
`BookWorkflow.fetch_anchor_books` raises `NotImplementedError` past `MAX_ANCHOR_BOOKS` (5),
which is the "Known broken downstream" entry above: "mystery" matches 358 books, so
`Retrieve_by_Lexical_Traits` → `Analyze_Recommend` dies every time. On the type, the same refusal
happens at dispatch, and `_prepare` turns it into one skipped goal **naming `anchors`** —
the same move `NodeInput` made over `(query, artifacts: dict[str, Any])`.

**The criterion is *named*, not *small*.** A trigram title search still matches six editions
of the same book, so the type narrows intent, not cardinality: a consumer that folds anchors
into one description still needs `MAX_ANCHOR_BOOKS`. What changes is that the cap becomes the
rare case instead of the usual one.

**Why `Retrieve_by_Author` is a candidate.** It is the closest call: a name is specific, and
twelve Herberts would fold into an anchor perfectly well. It sits on the candidate side
because the node cannot tell whether it returned twelve or eight hundred. The cost is that
**"books like Frank Herbert's" can no longer anchor on the bibliography** — its answer is to
describe the taste semantically instead. That is the one plan this split closes, and it is
the deliberate half of the trade.

**The base stays concrete, and that is load-bearing.** It is what a node declares when it
takes *either* (`Filter_Retrieval` narrows both kinds), and it is what a future
`Combine_Union` can subclass — anchor-shaped over two titles, candidate-shaped over two
subject searches, so a class cannot pick a side at definition time. Landing on the base means
"not anchorable", which is the safe half. A node wanting both explicitly writes
`list[BookAnchorOutput | BookCandidateOutput]`, which is *stricter* than the base: verified,
that union takes both subclasses and rejects a bare `BookRetrievalOutput`.

**Considered and rejected: a pydantic discriminated union.** `_resolve` calls
`isinstance(a, get_args(annotation)[0])`, and for
`list[Annotated[A | B, Field(discriminator="role")]]` that raises `TypeError: Subscripted
generics cannot be used with class and instance checks`. A discriminator fires when *parsing
untyped data into* a model; artifacts arrive as already-constructed instances, so the class is
the discriminator already and a `role` field would restate it while requiring `_resolve` to be
rewritten to read it.

**Vocabulary note.** "Candidate" already meant the ~50-row embedding pool inside
`analyze_recommend` (`rank_candidates`, `apply_exclusions`, `candidates_found`) and — inverted
— the title node's `Returns:` line called its matches "the candidate matches". That line is
fixed. The twelve inside `analyze_recommend` are not: renaming them to `pool` belongs to the
redo of that slice.

**Scope.** Types only, per owner decision. `analyze_recommend/` and `filter_books/` are
untouched and stay on the base — both are parked and are being redone, and both keep working
because `ParsedDependents.from_anchors` gates on `BookRetrievalOutput`, which still matches.
`fetch_anchor_books`' cap and `RecommendationStrategy`'s *"needs a supporting retrieval step"*
constraint are the other half of closing "Known broken downstream", and belong to that redo.
**Resolved the same day by the section below** — the recommend redo landed immediately after
this one. Catalog cost: +24 tokens (1,644 → 1,668), all of it the title node's expanded
`Returns:`.

**One wart to settle in the redo.** When a plan sends both an anchor and a candidate to a
`list[BookAnchorOutput]` field, `build_input` drops the candidate to a `logger.debug` "has no
field for" line and the node never learns its anchor was narrowed. A second
`list[BookCandidateOutput]` field does *not* fix it — `_resolve` does not skip already-claimed
items, so the anchor would be counted twice. The cheap fix is raising that log level. *Still
open after the redo below: it is now less reachable (a candidate beside an anchor is a plan
the planner should not emit at all) but no less silent. It moves with `filter_books`.*

### `Analyze_Recommend` → `Analyze_Similar_Books`, narrowed to one job (2026-08-22)

The node was renamed, cut down to a semantic search, and **unparked**. It is registered
again; the catalog is 5 tools at **2,199 tokens** (1,668 before, +531 — the whole of it this
node's docstring). The slice is `books/find_similar_books/`.

**What it does now, and only this**: pool the anchor books → fold them into one ideal-book
description (one LLM call) → embed and search → hand back the 50 nearest, nearest first.
Three LLM calls became one.

**What it stopped doing.** Deleted, not parked — git holds them until the node that wants
them is written:

| gone | it belonged to |
|---|---|
| `RecommendationArgs`, its parser and prompt | the picker: keywords, bounds, exclusions, `num_requested` |
| `rank_candidates` (the same-author cap), `apply_exclusions` | the picker |
| `generate_response.py` and the response prompt | the picker |

**Nothing writes a chat reply for a book turn any more.** That is a real, accepted gap, not
an oversight: the section's cards are the whole answer until a picker node exists. It is why
`ui_section_collapsible` stays `False`.

> **Closed for recommendations 2026-09-07 by `Generate_Recommendations`** — the picker's
> first piece, as its own slice (`books/write_recommendations/`) in a new
> `NodeTier.GENERATE` rather than as fields returning to this node. It takes the pool as a
> `BookCandidateOutput` dependency, materializes it, streams the cards and writes the
> reply; `ui_section_collapsible` moves with the answer, so this node's section is now
> collapsible and the generation node's is not.
>
> **Superseded 2026-09-08**: the slice survives but the *node* does not. It was
> deregistered into one unregistered stage the orchestrator runs after every plan
> (`app/orchestration/write_recommendations/`), and `NodeTier.GENERATE` was removed with
> it. The gap this note closed stays closed — wider, in fact, since a plain lookup gets
> prose too now. What changed is who decides the reply happens: nobody plans it. See the
> third attempt in [execution-pipeline-v1.md](execution-pipeline-v1.md).
>
> **What it does NOT take back is the rest of the table above**: no `keywords`, no
> `bounds`, no `exclude`, no `num_requested`, and no re-ranking — it presents the pool in
> the order it arrives (cosine, via `materialize_stmt`) and explains it. Splitting the
> picker that way is deliberate: writing the reply needs no argument parse at all, so it
> ships without one, and whatever eventually re-ranks or trims is a separate decision that
> a separate node makes before this one. The gap is closed only for turns whose plan
> contains a recommendation — a plain lookup still gets cards and no prose. See
> [execution-pipeline-v1.md](execution-pipeline-v1.md).

**Anchors only, enforced by type.** `SimilarBooksInput.anchors` is
`list[BookAnchorOutput] = Field(..., min_length=1)`, so only `Retrieve_by_Title` (and
`Retrieve_by_ISBN13` when built) can feed it. A bibliography, a subject search or a numeric
search is a `BookCandidateOutput` and is refused by `build_input` at dispatch, naming the
field — which is what closes "Known broken downstream" above.

Two capabilities left with it, and both were already fictions the docstring maintained:

- **Anchorless thematic asks.** "Something cozy and hopeful" claimed to work via
  `semantic_input`; `check_artifacts` had always raised on an empty anchor. The claim is now
  removed rather than the behaviour changed.
- **Bounds alongside a similarity ask.** "Books like Dune but under 300 pages" used to route
  the bound into this node's own parse and into the vector search's WHERE (recorded in
  execution-pipeline-v1.md, 2026-08-19). With no parse, the bound is silently dropped. It
  cannot move to `Filter_Retrieval`: filtering a ranked pool after the fact throws the
  ranking away, which is what that node's own docstring forbids. `embedding_search_stmt`
  keeps its `filters` parameter, unused, because inside the search is the only place a bound
  on a similarity ask can ever go.

  > **Corrected 2026-08-24.** The last two sentences were wrong, and the error was scoping
  > a property of *rows* to queries generally. Filtering a ranked pool throws the ranking
  > away when the pool is a materialized list — but `BookStore.filter_query` propagates the
  > `score` column through a narrowing, and `DeferredBookQuery.materialize_stmt` orders by
  > it, so a **scored deferred query** comes out of `Filter_Retrieval` still in cosine
  > order. The similarity node now hands on such a query, so the bound *can* move there and
  > `embedding_search_stmt.filters` was deleted rather than kept waiting.
  >
  > What survives of the original argument is a matter of degree, not of kind: the pool is
  > truncated, so a bound applied afterwards still cuts a shortened set rather than the
  > catalog. The cap was raised 50 → 250 (~5% of the catalog) so that cut has something to
  > work with, and "nothing in the 250 nearest passes" is accepted as a real answer — those
  > are not good recommendations — rather than as an artifact. The narrowed count means "of
  > the 250 nearest, N pass", which is a different claim from every other node's count and
  > is the filter node's to phrase when it is unparked.
  >
  > **Resolved 2026-08-24** by `Combine_Intersect`. `Filter_Retrieval` was replaced rather
  > than unparked, so the bound reaches the pool as `Retrieve_by_Numeric_Traits`' own query
  > and `compose(op="and")` — which carries the pool's `score` through — instead of as a
  > `BookMetadataFilter` a filter node parsed. `filter_query` went with that node. The
  > phrasing caveat above is unresolved and now belongs to the intersect node: it cannot
  > tell a truncated pool from any other input without importing the similarity slice, so
  > "of the 250 nearest, N also match" stays documented rather than shown in the UI.

**The blend-vs-separate rule.** The node pools *every* anchor it depends on into one
description, so the number of goals the planner emits decides whether two named books blend
or stay apart, and nothing downstream can undo the wrong choice. "Books like X **and** Y" is
one goal with two `depends_on`; "books like X **or** like Y" is two goals with one each. The
request docstring states it and demonstrates it in `Example queries:`, because it is prose,
not schema — nothing enforces it.

**`fetch_anchor_books` dissolved.** It sat on `BookWorkflow`, which every book node
inherits, with one caller, bundling compose + count + cap + materialize. What is left on the
base is `count_books` (unchanged) and `preview_books` **renamed to `fetch_books`** — the
neutral materialize primitive, since "preview" is what a call site wants and not what the
method does. The node composes the rest itself.

The count round trip went away entirely: every anchor ran its own `COUNT` before handing on
its query, so `ParsedDependents.total()` sums those and the cap is checked **before**
anything is fetched. One round trip where there were two. `ParsedDependents` survives
(dropping only the `reports` pile) and keeps its duck-typed `books` branch on purpose — no
registered anchor carries rows, but it is what lets a test supply reference books with no
database.

**Known limit, deferred by owner decision.** Past `MAX_ANCHOR_BOOKS` (5) the node raises
rather than folding the top 5 — see the closed entry above for why truncation was rejected.
The type split stops a 358-book candidate reaching it, but *one title matching many rows*
can still trip it: `title_query` keeps every row where `title ILIKE 'Dune'` or trigram
similarity > 0.7, so a catalog with six editions of one book fails "books like Dune". **The
fix belongs in `title_query`** — prefer exact matches when there are any, fall back to the
trigram arm only when there are none — because that makes the anchor better rather than the
consumer tolerant of a bad one, and it fixes every consumer at once. In `docs/backlog.md`.
`check_anchors` reports the pooled total on every run, so the traces will show how often the
cap actually fires before anyone spends time on it.

**Eval suites: renamed, not re-baselined.** `Analyze_Recommend` → `Analyze_Similar_Books`
across all four (43 / 12 / 9 / 6 occurrences), so cases fail for the right reason rather than
on an unknown node name. The category- and author-anchored recommend cases (3, 11, 45, 47,
68) still expect a plan the contract now refuses; they stay as written, the same precedent
used while `Retrieve_by_Genre` was parked — the suite names the target taxonomy and the
golden diff reports the gap.

### `Filter_Retrieval` → `Combine_Intersect` (2026-08-24)

`Filter_Retrieval` was **deleted**, not parked again, and `Combine_Intersect` registered in
its place — so `NodeTier.COMBINE` has members for the first time and every plan can now have
a second stage. The catalog is 6 tools at **2,814 tokens** (2,199 at 5).

**The node.** `books/intersect_books/`, four files, no parse: it takes 2+ dependencies of any
book-producing shape and ANDs their queries. It is the first node in the app that makes **no
LLM call at all** — what it does is decided entirely by which goals it depends on, so
`build_input` is its whole "parse" and its body is work → finalize.

**Why replacement rather than unparking.** The old node parsed a `BookMetadataFilter` out of
its own goal text and ANDed the bounds onto *one* upstream query. That made two ways to
express a bound — its `filters` and `Retrieve_by_Numeric_Traits.traits` — separated by
nothing but prose: the "numbers-only" rule, which lived in two docstrings and was held up by
eval cases 76/77 alone. Under the new shape a bound is always a retrieval, and *narrowing by
it* is that retrieval intersected with the subject's. One parse, one narrowing mechanism.

Three things fall out of that:

- **A bound riding alongside a subject has a home again**, which is what the 2026-08-22
  parking recorded as lost. "Fantasy books over 400 pages" is `Retrieve_by_Lexical_Traits` +
  `Retrieve_by_Numeric_Traits` + `Combine_Intersect`.
- **Plans get shorter, not longer.** "What horror books has Stephen King written that are
  over 500 pages?" was four nodes (two retrievals, an intersect, then a filter). It is now
  four with a different shape — three retrievals feeding **one** intersect — because the
  intersect is n-ary rather than the filter being single-input.
- **`BookStore.filter_query` was deleted**, its only caller gone.

**The technical decision: one score survives an intersect.** `compose(op="and")` selected
isbn13 only, so it dropped `score` — which would have ranked "books like Dune under 300
pages" by `average_rating` instead of by cosine similarity, discarding exactly what the
2026-08-24 deferred-query change was built to preserve. It now carries the score through when
**exactly one** input has one. The argument is that an intersect result is a subset of every
input, so that column is defined on every output row and orders the result honestly; two
scored inputs are incommensurable (a trigram score and a `ts_rank`) and both still go.
`compose(op="or")` never carries one, because a union contains rows the scored input never
matched. This is what closes the intersect half of the precondition recorded in
execution-pipeline-v1.md for unparking the combine tier; the union half is unchanged, and
`Combine_Union` still faces it.

**What the node deliberately does not do.**

- **Its output is `BookRetrievalOutput`, neither half of the split.** An intersection of two
  titles is anchor-shaped and one of two subject searches is not, and the class cannot know
  which at definition time — so it lands on the base, which means "not anchorable". This is
  the case the 2026-08-22 split reserved the concrete base for. The cost: `Analyze_Similar_Books`
  requires `list[BookAnchorOutput]` and so cannot depend on an intersection — "books like
  Harry Potter by Rowling" anchors on the title retrieval directly.
- **It cannot say "of the 250 nearest, N also match".** Detecting a truncated similarity pool
  among its inputs would mean importing `find_similar_books` across a slice seam, so the
  caveat stays in the docs rather than in the UI line — the same call `filter_query` made.
- **A failed dependency silently widens the answer.** Three retrievals, one fails, and the
  intersect still has two anchors and runs — answering a looser question than was asked. The
  runner marks the failed goal and the node streams how many conditions it actually
  intersected, so it is visible rather than hidden, but nothing refuses it.

**`min_length=2`, not 1.** An intersection of one is a no-op that would report the upstream
count as though something had narrowed it. `build_input` fills a `list[X]` with every match
and a one-item list is still a *filled* field, so the length is rejected on the input model;
the runner then skips that one goal naming `anchors`.

**Eval suites re-baselined**, unlike the two previous taxonomy changes. `Filter_Retrieval`
appeared in `expected_nodes` on six cases of `query_suite.json` (27, 61, 63, 65, 71, 77) —
the "24 occurrences" quoted in the parking record above counts mentions in `note` prose too.
The precedent for leaving suites alone was for *parked* nodes, where the name would come back;
this one will not, so the cases were rewritten. Cases 56/57/59 were re-decided at the same
time, as case 65's note had been asking for since the combine tier was designed.

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
- **The system can only answer what a `books` row holds** (graduated from
  `backend/TODO.md`, 2026-09-07). The catalog is one row per book — author, published
  year, page count, average rating, shelf/category, genre, and a marketing blurb — so
  *"who wrote Dune"* and *"when was it published"* are answerable and *"who is the main
  character of The Hunger Games"* or *"who's the one with the sword in Dune"* are not.
  Nothing in the schema knows what happens **inside** a book. The `description` blurb is
  the one partial exception and the only prose the system has: it is what the generation
  node grounds a "why this book" in, and it is marketing copy, not a summary. Requests
  that need knowledge from inside the text belong to the clarification/rejection node,
  not to a retrieval node that will happily match the words and answer confidently.
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

  **There are two kinds of compare, and only one of them chains** (graduated from
  `backend/TODO.md`, 2026-09-07). (1) *Compare for information* — "between Dune and IT,
  which is longer" — where the comparison **is** the answer and nothing runs after it.
  (2) *Compare to pick a winner* — "recommend books like whichever of Dune and IT is
  shorter" — where the comparison is an intermediate step whose output feeds a later
  goal. Only (2) needs the dependency contract widened.

  What makes (2) tractable is that the winner does not need to travel as a book: if the
  compare node emits *"Dune is 100 pages longer than IT, so it wins the page
  comparison"*, the downstream goal has a named title to anchor on and a bound to apply,
  which the existing retrieval + intersect nodes already cover. **The comparison must be
  on metadata, not on themes** — "which is better on dystopia" has nothing in the schema
  to compare (see the conversation contract above), so a themed compare is a
  clarification case, not a node. Two open sub-questions: whether the pruning is right in
  `find[a] + find[b] → analyze[a,b] → recommend` (the direct `find → recommend` edges
  look redundant once the analyze step has both, but nothing prunes them today), and
  whether a node is ever more than one hop from what it needs.
- **Book-clamped recommendations** — always attach a recommendation to a successful
  lookup ("do you have Dune? — yes, and I think you'll like these"). Feels consumer-like;
  a candidate once execution is real.
- **HITL re-rank** — the recommendation node is the natural human-in-the-loop point when
  there are many candidates.
