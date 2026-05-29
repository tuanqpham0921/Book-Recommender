"""Persist normalized book rows to PostgreSQL."""
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select
from db.schema import BookModel
from ingestion.csv_source import count_csv_data_rows, iter_books_from_csv
from common.operation import OperationResult, task

@task
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
async def store_books(
    session_factory: async_sessionmaker[AsyncSession],
    csv_path: Path,
) -> OperationResult:
    """Load books from CSV into the database."""
    
    # TODO: good place to do and test retries
    
    total_books_stored = 0
    total_books = 0
    csv_row_count = count_csv_data_rows(csv_path)
    
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
        name="store_books", 
        ok= total_books_stored == total_books, 
        message=f"Stored {total_books_stored} books out of {total_books}.", 
        result=result,
        # steps=steps
    )
