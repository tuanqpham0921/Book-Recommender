"""Persist normalized book rows to PostgreSQL."""
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import update
from db.schema import BookModel
from ingestion.utils import count_csv_data_rows, iter_books_from_csv
from common.operation import OperationResult, task
from db.readiness import ReadinessResult
import logging
from typing import Any, AsyncIterator
from sqlalchemy import select

logger = logging.getLogger(__name__)

@task(log_info=False)
async def insert_batch(
    batch: list[dict],
    session_factory: async_sessionmaker[AsyncSession],
) -> OperationResult:
    """Upsert a batch of books (metadata only; embedding column excluded on conflict)."""
    if not batch:
        return OperationResult(ok=False, message="No books to insert.", details={"batch_length": len(batch)})

    table = BookModel.__table__
    stmt = insert(table).values(batch)
    update_columns = {
        column.name: stmt.excluded[column.name]
        for column in table.columns
        if column.name not in ("isbn13", "embedding")
    }
    stmt = stmt.on_conflict_do_update(
        index_elements=["isbn13"],
        set_=update_columns,
    )
    
    async with session_factory() as session:
        result = await session.execute(stmt)
        await session.commit()
    rowcount = result.rowcount or 0
    return OperationResult(
        ok=rowcount, 
        message=f"Stored {rowcount} books out.", 
        result=rowcount,
        details={"batch_length": len(batch)}
    )

@task
async def store_books_from_csv(
    session_factory: async_sessionmaker[AsyncSession],
    csv_path: Path,
    readiness: ReadinessResult | None = None,
) -> OperationResult:
    """Load books from CSV into the database."""
    if readiness and readiness.enough_rows:
        return OperationResult(
            ok=True, 
            message="Already have enough rows to start applications.", 
            steps=[]
        )
    
    # TODO: good place to do and test retries
    
    total_books_stored = 0
    total_books = 0
    csv_row_count = count_csv_data_rows(csv_path)
    logger.info(f"📋 Found {csv_row_count} rows in CSV.")
    
    steps = []
    i = 0
    for batch in iter_books_from_csv(csv_path):
        total_books += len(batch)        
        batch_result = await insert_batch(batch, session_factory)
        total_books_stored += batch_result.result
        batch_result.name += f"--batch-{i}"
        
        steps.append(batch_result)
        i += 1
    
    result = {
        "total_books_stored": total_books_stored,
        "total_books": total_books,
        "csv_row_count": csv_row_count,
    }
    return OperationResult(
        ok= total_books_stored == total_books, 
        message=f"Stored {total_books_stored} books out of {total_books}.", 
        result=result,
        steps=steps
    )
    
# ------------------------------------------------------------
# ---------------- EMBEDDINGS WRITE --------------------------
# ------------------------------------------------------------

@task(log_info=False)
async def store_book_embedding(
    isbn13: str,
    embedding: list[float],
    session: AsyncSession,
) -> OperationResult:
    stmt = (
        update(BookModel)
        .where(BookModel.isbn13 == isbn13)
        .values(embedding=embedding)
    )
    await session.execute(stmt)
    return OperationResult(
        ok=True,
        message=f"Updated embedding for book {isbn13}.",
        result=isbn13
    )
    
async def iter_missing_embeddings(
        session_factory: async_sessionmaker[AsyncSession],
        *,
        batch_size: int = 500,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream books missing embeddings."""
        stmt = (
            select(
                BookModel.isbn13,
                BookModel.title,
                BookModel.description,
            )
            .where(BookModel.embedding.is_(None))
            .where(BookModel.description.is_not(None))
            .execution_options(yield_per=batch_size)
            # .limit(1000)
        )
        async with session_factory() as session:
            result = await session.stream(stmt)
            async for row in result.mappings():
                yield dict(row)