import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.async_engine import check_connection
from db.schema.extensions import REQUIRED_EXTENSIONS

logger = logging.getLogger(__name__)
from common.operation import OperationResult, task

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
async def has_minimum_books(
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
        result=row_count,
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
        result=result,
    )
    

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

    async with session_factory() as session:
        # simple test connection (must be first and pass)
        if not await check_connection(session):
            raise ValueError("Database connection failed")

        # check if table exists and schema is correct
        table_check = await _check_table(session, schema=schema, table=table)
        checks.append(table_check)
        
    async with session_factory() as session:
        # check if table has rows
        rows = await has_minimum_books(
            session,
            schema=schema,
            table=table,
            min_rows=min_rows,
        )
        checks.append(rows)
    
    async with session_factory() as session:
        # check if required extensions are installed
        extensions = await _check_table_extensions(session)
        checks.append(extensions)
        

    return OperationResult(
        name="is_ready", 
        ok=all(check.ok for check in checks), 
        message="Database is ready.", 
        steps=checks
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
