import pandas as pd

from db.schema.models import BookModel
from ingestion.utils import row_to_book


def test_row_to_book(sample_books: pd.DataFrame):
    one_row = sample_books.iloc[0]
    book: BookModel = row_to_book(one_row)

    assert book.isbn13 == str(one_row["isbn13"])
    assert book.isbn10 == str(one_row["isbn10"])
    assert book.title == one_row["title"]
    assert book.authors == str(one_row["authors"])
    assert book.categories == str(one_row["categories"])
    assert book.thumbnail == str(one_row["thumbnail"])

    assert book.description == one_row["tagged_description"]

    assert book.published_year == 1995
    assert book.average_rating == 4.43
    assert book.num_pages == 128
    assert book.ratings_count == 3860
