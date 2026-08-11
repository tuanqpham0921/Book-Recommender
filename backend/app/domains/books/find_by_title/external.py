from app.domains.books.schemas import BookRetrievalOutput


class FindByTitleOutput(BookRetrievalOutput):
    """`num_books` is how many titles matched and `query` is how to reach them;
    this node counts and does not fetch. `num_books == 0` means the catalog has
    no such title — a real answer, and the moment to ask the user for a better
    one rather than to fail the node."""