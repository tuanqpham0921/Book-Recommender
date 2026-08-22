"""`Book`, and the output-shape vocabulary node docstrings are written in.

`Book` is the one book model: every books-table column except the embedding.
Narrow at the point of use, never by declaring a second, smaller model.

The shape *classes* live next door in `external.py`, which is what the layers
outside this domain import.

## The output-shape vocabulary

Node docstrings name what they return, and what they may depend on, using these
shape names, so the planner can tell which nodes may feed which:

- `BookRetrievalOutput` — a match: how many books, and the query reaching them.
  Never the rows. Every retrieval and combine node. The only shape "depends on
  books" consumes. It splits in two by whether the match can be anchored on:
  - `BookAnchorOutput` — the user named these books (`Retrieve_by_Title`), so a
    later step can fold them into a description of what to look for next.
  - `BookCandidateOutput` — these books match a description
    (`Retrieve_by_Author`, `Retrieve_by_Category`, `Retrieve_by_Numeric_Traits`,
    and `Analyze_Similar_Books`' chosen pool, whose description the system wrote
    rather than the user). A set, not a reference; nothing may anchor on it.
- `AnalyzeBooksOutput` — a written report about books. Names books without
  being a book list, so nothing may treat it as a retrieval.
- `ActionConfirmationOutput` — a record of a write (shelf actions, feedback).

The first three are real classes (in `external.py`), and a node's output
subclasses the shape its docstring claims, so `Returns:` is checkable. The last
two are reserved names — add the class alongside the first node that produces
the shape. See docs/design/node-taxonomy-v1.md.

Node-specific fields live on the slice's own output in
`app/domains/books/<node>/external.py`, which subclasses the shape it returns.
"""

from pydantic import BaseModel


class Book(BaseModel):
    """One book above the database layer: every `books` column except the
    embedding, matching what `BookModel.to_dict()` hands back.

    The embedding's absence is load-bearing. These models are serialized into
    `chat_runs` JSONB; a 1536-float vector per book would bloat every run record
    for something no reader of it can use. A caller needing vectors goes to the
    store.

    There is deliberately no narrower book model — the prompt-facing renderers
    already select fields by hand, so a second model was only a field list free
    to drift from this one. Narrow at the point of use instead.

    Field names are a persisted contract: they land in `chat_runs.tasks` and are
    read back by the review page and the eval reports, so a rename breaks
    readers against older rows. Every field needs a default except the two that
    identify a book, because `Workflow.__init__` builds envelopes before there
    is anything to put in them.
    """

    isbn13: str
    title: str
    isbn10: str | None = None
    authors: str | None = None
    categories: str | None = None
    genre: str | None = None
    published_year: int | None = None
    num_pages: int | None = None
    average_rating: float | None = None
    ratings_count: int | None = None
    is_children: bool | None = None
    description: str | None = None
    thumbnail: str | None = None
    title_and_subtiles: str | None = None

    # Not a column: `BookStore.search_similar` attaches it, and it is the
    # only record of how close a recommendation was — so "why these books" stays
    # answerable from the run log. None on a book that arrived another way.
    similarity_score: float | None = None






