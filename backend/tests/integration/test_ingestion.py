import pytest
from sqlalchemy import text, select
import pandas as pd
from ingestion.utils import row_to_book
import numpy as np

def book_without_embedding(book):
    """ return a book without the embedding for comparison purposes """
    return {
        column.name: getattr(book, column.name)
        for column in book.__table__.columns
        if column.name != "embedding"
    }

@pytest.mark.asyncio
async def test_ingestion_loads_books(sample_books: pd.DataFrame):
    from config import Settings
    from common.context import AppContext
    from db.bootstrap import bootstrap_schema
    from db.schema import BookModel
    from ingestion.main import load_books
    
    settings = Settings()
    
    # NOTE: maybe this should be a fixture later
    async with AppContext(settings) as ctx:
        await bootstrap_schema(ctx.session_factory)
        
        # clear book table
        async with ctx.session_factory() as session:
            await session.execute(text("TRUNCATE TABLE books"))
            await session.commit()

        # run ingestion process
        result = await load_books(ctx)
        
        # get one book from the database
        async with ctx.session_factory() as session:
            row_count = await session.scalar(text("SELECT count(*) FROM books"))
            test_book = await session.execute(
                select(BookModel).where(BookModel.isbn13 == "9780141439518")
            )
            test_book = test_book.scalar_one_or_none()
            
            
    assert result.ok
    assert row_count == 6
    
    # check if the embedding is valid shape and exists
    assert test_book is not None
    assert test_book.embedding is not None
    assert isinstance(test_book.embedding, np.ndarray)
    assert test_book.embedding.shape == (1024,)
    assert test_book.embedding.dtype == np.float32    
    
    # check if the book is the same as the reference book
    reference_book = sample_books[sample_books["isbn13"].astype(str) == "9780141439518"]
    reference_book = row_to_book(reference_book.iloc[0])
    assert book_without_embedding(test_book) == book_without_embedding(reference_book)
    
    