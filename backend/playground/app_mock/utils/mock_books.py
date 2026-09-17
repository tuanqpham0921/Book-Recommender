"""The 6 books currently seeded in the dev DB (data/test_books.csv),
shaped like BookStore.row_to_dict() so mock retrieval executors can stand
in for real DB calls without touching the database.
"""

MOCK_BOOKS: list[dict] = [
    {
        "isbn13": "9780140251579",
        "title": "The Making of Pride and Prejudice",
        "authors": "Sue Birtwistle;Susie Conklin",
        "categories": "Performing Arts",
        "published_year": 1995,
        "num_pages": 128,
        "average_rating": 4.43,
        "description": (
            "This book reveals in detail how Jane Austen's classic novel is "
            "transformed into a stunning television drama."
        ),
        "thumbnail": "http://books.google.com/books/content?id=ssBRUQiDk74C&printsec=frontcover&img=1&zoom=1&source=gbs_api",
        "ratings_count": 3860,
        "genre": "Nonfiction",
        "is_children": False,
    },
    {
        "isbn13": "9780141439518",
        "title": "Pride and Prejudice",
        "authors": "Jane Austen",
        "categories": "Fiction",
        "published_year": 2003,
        "num_pages": 480,
        "average_rating": 4.25,
        "description": (
            "In early nineteenth-century England, a spirited young woman "
            "copes with the suit of a snobbish gentleman, as well as the "
            "romantic entanglements of her four sisters."
        ),
        "thumbnail": "http://books.google.com/books/content?id=obMP1xBBhh8C&printsec=frontcover&img=1&zoom=1&source=gbs_api",
        "ratings_count": 11552,
        "genre": "Fiction",
        "is_children": False,
    },
    {
        "isbn13": "9780192802385",
        "title": "Pride and Prejudice",
        "authors": "Jane Austen",
        "categories": "Fiction",
        "published_year": 2004,
        "num_pages": 333,
        "average_rating": 4.25,
        "description": (
            "Pride and Prejudice has delighted generations of readers with "
            "its unforgettable cast of characters, carefully choreographed "
            "plot, and a hugely entertaining view of the world and its "
            "absurdities."
        ),
        "thumbnail": "http://books.google.com/books/content?id=8cp-Z_G42g4C&printsec=frontcover&img=1&zoom=1&source=gbs_api",
        "ratings_count": 2369,
        "genre": "Fiction",
        "is_children": False,
    },
    {
        "isbn13": "9780441102679",
        "title": "Chapterhouse: Dune",
        "authors": "Frank Herbert",
        "categories": "Fiction",
        "published_year": 1987,
        "num_pages": 436,
        "average_rating": 3.9,
        "description": (
            "Fifteen thousand years after Leto II's death, the remnants of "
            "the Bene Gesserit contend with the ruthless leaders of an "
            "alien culture to forge a new civilization and preserve the "
            "best of the Old Empire."
        ),
        "thumbnail": "http://books.google.com/books/content?id=ryot4Ag2GGQC&printsec=frontcover&img=1&zoom=1&source=gbs_api",
        "ratings_count": 38651,
        "genre": "Fiction",
        "is_children": False,
    },
    {
        "isbn13": "9780553580334",
        "title": "Dune",
        "authors": "Brian Herbert;Kevin J. Anderson",
        "categories": "Fiction",
        "published_year": 2002,
        "num_pages": 667,
        "average_rating": 3.67,
        "description": (
            "Chronicles the origins of the rivalry between Duke Leto and "
            "Baron Vladimir Harkonnen, the actions that transformed Duncan "
            "Idaho and Gurney Halleck into heroes, the birth of Paul "
            "Atreides, and the creation of the tyrannical Padishah Emperor "
            "Shaddam Corrino."
        ),
        "thumbnail": "http://books.google.com/books/content?id=wb8Z4Bc3_I8C&printsec=frontcover&img=1&zoom=1&source=gbs_api",
        "ratings_count": 11952,
        "genre": "Fiction",
        "is_children": False,
    },
    {
        "isbn13": "9780060527983",
        "title": "Warrior of the Light",
        "authors": "Paulo Coelho",
        "categories": "Fiction",
        "published_year": 2004,
        "num_pages": 142,
        "average_rating": 3.7,
        "description": (
            "Warrior of the Light: A Manual is an inspirational companion "
            "to The Alchemist, an international bestseller that has "
            "beguiled millions of readers around the world."
        ),
        "thumbnail": "http://books.google.com/books/content?id=yH0zlwEACAAJ&printsec=frontcover&img=1&zoom=1&source=gbs_api",
        "ratings_count": 21578,
        "genre": "Fiction",
        "is_children": False,
    },
]


def find_by_title(title: str) -> list[dict]:
    """Case-insensitive substring match; falls back to the first book so
    the mock always has something to stream."""
    query = title.strip().lower()
    matches = [book for book in MOCK_BOOKS if query in book["title"].lower()]
    return matches or [MOCK_BOOKS[0]]


def find_by_isbn13(isbn13: str) -> dict:
    """Exact isbn13 match; falls back to the first book so the mock always
    has something to stream."""
    for book in MOCK_BOOKS:
        if book["isbn13"] == isbn13:
            return book
    return MOCK_BOOKS[0]


def find_by_author(author: str) -> list[dict]:
    """Case-insensitive substring match against the book's author credits;
    falls back to the first book so the mock always has something to
    stream."""
    query = author.strip().lower()
    matches = [book for book in MOCK_BOOKS if query in book["authors"].lower()]
    return matches or [MOCK_BOOKS[0]]


def find_by_coauthors(authors: list[str]) -> list[dict]:
    """Books credited to *every* named author — the co-authorship AND that
    find_by_author's single-name OR can't express. `authors` is a
    semicolon-delimited credit string ("Brian Herbert;Kevin J. Anderson"), so
    each name is matched as a substring of the whole credit.

    No fallback book, unlike the other finders: an empty list is the real
    answer to "did these two ever write together?", and inventing a match
    would make the mock lie about the one thing this node exists to check."""
    queries = [a.strip().lower() for a in authors]
    return [
        book for book in MOCK_BOOKS
        if all(query in book["authors"].lower() for query in queries)
    ]


def find_by_genre(genre: str) -> list[dict]:
    """Case-insensitive genre match; falls back to the first book so the
    mock always has something to stream."""
    query = genre.strip().lower()
    matches = [book for book in MOCK_BOOKS if book["genre"].lower() == query]
    return matches or [MOCK_BOOKS[0]]
