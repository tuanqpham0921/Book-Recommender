"""The vector query's LIMIT: what it buys, and what it quietly costs.

    poetry run python playground/capped_query_demo.py

`DeferredBookQuery` promises no LIMIT and no ORDER BY — that is what makes two
of them foldable into one WITH clause. `embedding_search_stmt` carries both,
because a vector search does not select a subset: it orders the whole table by
cosine distance and truncates, so the LIMIT *is* the set.

A tracked `capped` attribute and a `compose()` guard were built for that on
2026-08-24 and removed the same day. So the exception now lives in the compiled
SQL and nowhere else, which is exactly what this script reads.

Nothing here connects. Building a `DeferredBookQuery` needs the model, not the
session, so `BookStore(None)` is enough; only `count()` / `score_stats()` /
`materialize()` would need a live connection, and none are called.

Sections:
    1. the invariant, and the one query that breaks it
    2. intersecting the pool keeps cosine order — the payoff
    3. pooling it with "or" loses it — the cost, still unguarded
    4. count is degenerate on the pool; score stats are not
    5. why that cost is easy to miss (a simulation; SQL cannot show it)

Updated 2026-08-24: `BookStore.filter_query` is gone with `Filter_Retrieval`, so the
narrowing in section 2 is `compose(op="and")` against a bound's own deferred query
— which is what `Combine_Intersect` builds. That branch carries the one `score`
through, so the payoff below is now the *intersect's*, and section 3's loss is
`"or"`-only.
"""

import random
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from db.schema.filter_schemas import BookMetadataFilter
from db.schema.models import BookModel
from db.stores import DeferredBookQuery, compile_sql
from db.stores.book_store import BookStore, embedding_search_stmt

# no session: every builder used here reads `self.model` and nothing else
store = BookStore(cast(AsyncSession, None))

POOL_SIZE = 250
FAKE_EMBEDDING = [0.01 * i for i in range(1024)]


def sql(stmt) -> str:
    """Rendered with literal binds, so a LIMIT reads as a number."""
    return compile_sql(stmt, embedding_as="embed(search_text)")


def show(caption: str, stmt) -> None:
    body = "\n".join("    " + line for line in sql(stmt).strip().splitlines())
    print(f"\n  {caption}\n{body}")


def rule(n: int, title: str) -> None:
    print(f"\n\n{'=' * 78}\n{n}. {title}\n{'=' * 78}")


# ---------------------------------------------------------------------------
rule(1, "The invariant, and the one query that breaks it")

title = store.title_query("Dune")
pool = embedding_search_stmt(FAKE_EMBEDDING, limit=POOL_SIZE)

show("title_query — no ORDER BY, no LIMIT, so it composes:", title.stmt)
show("embedding_search_stmt — both, and the 1024-float vector elided:", pool.stmt)

print(
    "\n  Not a shrunk view of a set: the vector search orders the WHOLE catalog\n"
    "  and truncates, so the LIMIT *is* the set. That cannot move to\n"
    "  materialize_stmt, which reproduces a ranking but not a ranking-truncation.\n\n"
    f"  Nothing on the object says so — both repr as {title!r}-style, and\n"
    "  compose() accepts either. The SQL above is the only record."
)


# ---------------------------------------------------------------------------
rule(2, "Intersecting the pool keeps cosine order — the payoff")

# What Combine_Intersect builds for "books like Dune under 300 pages": the bound
# is its own retrieval, and the intersect ANDs the two queries. Exactly one input
# carries a score, so compose() carries it through.
bound = store.numeric_traits_query(BookMetadataFilter(max_pages=300))
narrowed = DeferredBookQuery.compose([pool, bound], op="and", label="intersected")

show("materialize_stmt over the narrowed pool:", narrowed.materialize_stmt(BookModel, limit=10))

final = sql(narrowed.materialize_stmt(BookModel, limit=10))
print(f"\n  ranked by cosine, not by rating : {'ORDER BY final.score DESC' in final}")
print(f"  the LIMIT 250 is still nested   : {'LIMIT 250' in final}")
print(
    "\n  compose(op='and') carries the one `score` through — an intersect result\n"
    "  is a subset of every input, so that column is defined on every output row\n"
    "  — and `materialize_stmt` orders by it. A bound on a similarity pool does\n"
    "  NOT flatten the ranking, which is what makes 'books like Dune under 300\n"
    "  pages' three nodes instead of bounds parsed inside the similarity node.\n\n"
    "  The second line is the honest half: the bound is applied to the nearest\n"
    "  250, so the count means 'of the 250 nearest, N also match'. Accepted, and\n"
    "  nothing records it."
)


# ---------------------------------------------------------------------------
rule(3, 'Pooling it with "or" loses it — the cost, still unguarded')

lexical = store.lexical_query(keywords=["mystery"])

try:
    composed = DeferredBookQuery.compose([pool, lexical], op="or")
    raised = False
except ValueError:
    raised = True

combined = sql(composed.materialize_stmt(BookModel, limit=10))
show("materialize_stmt over compose([pool, lexical]):",
     composed.materialize_stmt(BookModel, limit=10))

print(f"\n  compose() raised                : {raised}")
print(f"  LIMIT 250 applied before UNION  : {'LIMIT 250' in combined}")
print(f"  score survived to the ranking   : {'ORDER BY final.score DESC' in combined}")
print(f"  fell back to rating instead     : {'ORDER BY books.average_rating' in combined}")
print(
    "\n  Two things went wrong and neither is visible in the result. The LIMIT\n"
    "  ran BEFORE the union, so it changed which books qualify rather than only\n"
    "  how many are shown. Then compose() dropped `score`, removing the ranking\n"
    "  that chose them.\n\n"
    "  Section 2 fixed the first of those for `and` and cannot fix it here: an\n"
    "  intersect result is a subset of every input, so one input's score orders\n"
    "  it honestly, while a union contains rows the pool never matched.\n\n"
    "  Truncation commutes with ORDERING (which is why materialize_stmt's own\n"
    "  LIMIT 10 is safe) but not with a UNION. That is the whole rule."
)


# ---------------------------------------------------------------------------
rule(4, "count is degenerate on the pool; score stats are not")

show("pool.count_stmt() — can only ever return min(250, matches):", pool.count_stmt())
show("pool.score_stats_stmt() — what actually describes it:", pool.score_stats_stmt())

numeric = store.numeric_traits_query(BookMetadataFilter(max_pages=300))
print(
    f"\n  numeric_traits_query has no `score`, so score_stats_stmt() is "
    f"{numeric.score_stats_stmt()}"
)
print("  (None, not zeroes: 'no degree of match' and 'all matched at 0.0'\n"
      "   are different facts.)")


# ---------------------------------------------------------------------------
rule(5, "Why that cost is easy to miss")

# Invented numbers, not catalog data — the point is that the error is the same
# shape as a correct answer, which is what makes it survive to production.
random.seed(7)
CATALOG = 5197
catalog = list(range(CATALOG))
# say 1200 books clear MIN_SIMILARITY; the query returns the nearest 250
above_floor = random.sample(catalog, 1200)
truncated = above_floor[:POOL_SIZE]
non_fiction = set(random.sample(catalog, 358))

honest = len(set(above_floor) & non_fiction)
actual = len(set(truncated) & non_fiction)

print("\n  'similar to Dune AND non-fiction', intersected:")
print(f"    against all 1200 books above the floor : {honest:>4} books")
print(f"    against the truncated 250-book pool    : {actual:>4} books")
print(
    f"\n  Both reach the user as a bare integer on `num_books`. A pool answer of\n"
    f"  {actual} is indistinguishable from a genuine catalog answer of {actual} — the\n"
    f"  LIMIT silently became part of the question. Intersect can reach 0 while\n"
    f"  the true answer is substantial, and 0 reads as 'no books match', which\n"
    f"  is a claim the system would be making falsely.\n\n"
    f"  Union has the problem in reverse: 250 of ~1200 similar books pooled with\n"
    f"  all 358 lexical matches over-weights the lexical branch ~4.8:1, purely\n"
    f"  as an artifact of the cap.\n\n"
    f"  A wrong composition here produces a plausible number, never an error.\n"
    f"  Combine_Intersect reaches the `and` path and is safe there (section 2).\n"
    f"  Nothing reaches THIS path: Combine_Union does not exist. Before it does,\n"
    f"  tune MIN_SIMILARITY so the pool needs no LIMIT, or put the guard back."
)

print()
