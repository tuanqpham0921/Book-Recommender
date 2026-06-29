import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.async_engine import check_connection
from db.schema.extensions import REQUIRED_EXTENSIONS

logger = logging.getLogger(__name__)
from common.operation import OperationResult, task
from pydantic import BaseModel, Field
from db.stores.book_store import BookStore

@task
async def _check_table(
    session: AsyncSession,
    *,
    schema: str,
    table: str,
) -> OperationResult:
    """Check if the table exists and the schema is correct.

    Args:
        session: An async session.
        schema: The schema to check.
        table: The table to check.
    """

    fqtn = f"{schema}.{table}"
    result = await session.execute(
        text("SELECT to_regclass(:fqtn) IS NOT NULL"),
        {"fqtn": fqtn},
    )
    exists = bool(result.scalar())
    
    return OperationResult(
        name="table",
        ok=exists,
        message=f"Table {fqtn} exists." if exists else f"Table {fqtn} not found.",
        details={"schema": schema, "table": table},
    )

@task
async def _check_table_rows(
    session: AsyncSession,
    *,
    schema: str,
    table: str,
    min_rows: int,
) -> OperationResult:
    """Check if the table has at least the minimum number of rows.

    Args:
        session: An async session.
        schema: The schema to check.
        table: The table to check.
        min_rows: The minimum number of rows the table should have.
    """
    fqtn = f"{schema}.{table}"
    
    result = await session.execute(text(f"SELECT COUNT(*) FROM {schema}.{table}"))
    row_count = int(result.scalar() or 0)
    ok = row_count >= min_rows
    return OperationResult(
        name="rows",
        ok=ok,
        message=(f"Table {fqtn} has {row_count} rows (need at least {min_rows})."),
        details={"row_count": row_count, "min_rows": min_rows},
        output=row_count,
    )
    

@task
async def _check_table_extensions(session: AsyncSession) -> OperationResult:
    """Check if the required PostgreSQL extensions are installed.

    Args:
        session: An async session.
    """
    required_extensions = list(REQUIRED_EXTENSIONS)
    result = await session.execute(
        text(
            "SELECT extname FROM pg_extension WHERE extname = ANY(:extensions)"
            ),
        {"extensions": required_extensions},
    )
    found = {row[0] for row in result.fetchall()}
    missing = [ext for ext in required_extensions if ext not in found]
    ok = not missing
    result = {
        "required": required_extensions,
        "installed": sorted(found),
        "missing": missing,
    }
    return OperationResult(
        name="extensions",
        ok=ok,
        message=(
            "Required PostgreSQL extensions are installed."
            if ok
            else f"Missing PostgreSQL extensions: {', '.join(missing)}."
        ),
        output=result,
    )
    


class ReadinessResult(BaseModel):
    database_connected: bool = False
    need_db_bootstrap: bool = False
    enough_rows: bool = False
    need_extensions: bool = False
    num_missing_embeddings: int = 0

    missing_extensions: list[str] = Field(default_factory=list)
    
@task
async def is_ready(
    session_factory: async_sessionmaker[AsyncSession],
    schema: str,
    table: str,
    *,
    min_rows: int,
) -> OperationResult:
    """Run database readiness checks and return a structured report.

    Args:
        session_factory: A factory for creating async sessions.
        schema: The schema to check.
        table: The table to check.
        min_rows: The minimum number of rows the table should have.
    """
    checks: list[OperationResult] = []
    result = ReadinessResult()
    
    if not await check_connection(session_factory):
        raise ValueError("Database connection failed")
    result.database_connected = True

    async with session_factory() as session:
        # check if table exists and schema is correct
        table_check = await _check_table(session, schema=schema, table=table)
        checks.append(table_check)
        
        result.need_db_bootstrap = not table_check.ok
        
    async with session_factory() as session:
        # check if table has rows
        rows = await _check_table_rows(
            session,
            schema=schema,
            table=table,
            min_rows=min_rows,
        )
        checks.append(rows)
        result.enough_rows = rows.ok
    
    async with session_factory() as session:
        # check if required extensions are installed
        extensions = await _check_table_extensions(session)
        checks.append(extensions)
        result.need_extensions = not extensions.ok
        result.missing_extensions = extensions.output["missing"]
        
    
    async with session_factory() as session:
        # check if embeddings are present
        book_store = BookStore(session)
        # TODO: we can change this when book store implement @task decorator
        num_missing = await book_store.get_num_book_missing_embeddings()
        checks.append(OperationResult(
            name="num_missing_embeddings",
            ok=num_missing == 0,
            message="No books missing embeddings." if num_missing == 0 else f"Found {num_missing} books missing embeddings.",
            output=num_missing,
        ))
        result.num_missing_embeddings = num_missing
        
    ok = all(check.ok for check in checks)
    return OperationResult(
        ok=ok, 
        message="Database is ready." if ok else "Database is not ready.", 
        steps=checks,
        output=result,
    )


# -----------------------------------------------------------------------------
# For testing purposes
# poetry run python db/readiness.py
# -----------------------------------------------------------------------------
async def main() -> None:
    from config import DatabaseConstants, IngestionConstants
    from db.async_engine import (
        close_async_engine,
        get_async_engine,
        get_session_factory,
    )
    from db.schema import BookModel
    from config import settings

    engine = None
    try:
        engine = get_async_engine(settings.sqlalchemy)
        schema = DatabaseConstants.SCHEMA
        table = BookModel.__tablename__
        min_rows = IngestionConstants.APPROXIMATE_LOAD_LIMIT

        session_factory = get_session_factory(engine)
        report = await is_ready(
            session_factory, schema=schema, table=table, min_rows=min_rows
        )
        report.log()
    finally:
        if engine:
            await close_async_engine(engine)


if __name__ == "__main__":
    asyncio.run(main())
