import asyncio
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from common.operation import OperationResult, task
from config.constants import FilesLocationConstants
from db.readiness import ReadinessResult

logger = logging.getLogger(__name__)

def _sql_statements(sql: str) -> list[str]:
    """Split the SQL file into individual statements."""
    # TODO: this might be blocking
    statements: list[str] = []
    for chunk in sql.split(";"):
        lines = [
            line for line in chunk.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        if not lines:
            continue
        statements.append("\n".join(lines))
    return statements

async def _execute_sql_file(session: AsyncSession, path: Path) -> None:
    """Execute the SQL file."""
    for statement in _sql_statements(path.read_text(encoding="utf-8")):
        await session.execute(text(statement))

@task
async def enable_extensions(session_factory: async_sessionmaker[AsyncSession]) -> OperationResult:
    """Install required PostgreSQL extensions."""
    async with session_factory() as session:
        await _execute_sql_file(
            session, FilesLocationConstants.SCHEMA_EXTENSIONS_FILE
        )
        await session.commit()

    return OperationResult(
        ok=True, 
        message="PostgreSQL extensions installed successfully."
    )

@task
async def init_tables(session_factory: async_sessionmaker[AsyncSession]) -> OperationResult:
    """Create application tables from schema SQL."""
    async with session_factory() as session:
        await _execute_sql_file(session, FilesLocationConstants.SCHEMA_TABLES_FILE)
        await session.commit()

    return OperationResult(
        ok=True, 
        message="Tables created successfully."
    )

@task
async def create_indexes(session_factory: async_sessionmaker[AsyncSession]) -> OperationResult:
    """Create database indexes from schema SQL."""
    async with session_factory() as session:
        await _execute_sql_file(session, FilesLocationConstants.SCHEMA_INDEXES_FILE)
        await session.commit()

    return OperationResult(
        ok=True, 
        message="Indexes created successfully."
    )

@task
async def bootstrap_schema(session_factory: async_sessionmaker[AsyncSession], readiness: ReadinessResult | None = None) -> OperationResult:
    """Apply extensions, tables, and indexes in order (idempotent and safe to call multiple times)."""
    if readiness and not readiness.need_db_bootstrap:
        return OperationResult(
            ok=True, 
            message="No actions required.", 
            steps=[]
        )
    
    checks: list[OperationResult] = []
    
    checks.append(await enable_extensions(session_factory))
    checks.append(await init_tables(session_factory))
    checks.append(await create_indexes(session_factory))
    
    return OperationResult(
        name="bootstrap_schema", 
        ok=all(check.ok for check in checks), 
        message="Bootstrap schema completed.", 
        steps=checks
    )

# -----------------------------------------------------------------------------
# For testing purposes
# poetry run python db/bootstrap.py
# -----------------------------------------------------------------------------
async def main() -> None:
    from config import settings
    from db.async_engine import (
        close_async_engine,
        get_async_engine,
        get_session_factory,
    )

    engine = get_async_engine(settings.sqlalchemy)
    try:
        session_factory = get_session_factory(engine)
        await bootstrap_schema(session_factory)
    finally:
        await close_async_engine(engine)


if __name__ == "__main__":
    asyncio.run(main())
