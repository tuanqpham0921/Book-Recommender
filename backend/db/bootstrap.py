import asyncio
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.schema.extensions import REQUIRED_EXTENSIONS

from config.constants import FilesLocationConstants
from db.readiness import ReadinessResult

logger = logging.getLogger(__name__)
from common.operation import OperationResult, task

def _sql_statements(sql: str) -> list[str]:
    """Split the SQL file into individual statements."""
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


async def _execute_sql_file(session: AsyncSession, path: Path) -> OperationResult:
    """Execute the SQL file."""
    for statement in _sql_statements(path.read_text(encoding="utf-8")):
        await session.execute(text(statement))
    return OperationResult(name="execute_sql_file", ok=True, message="SQL file executed successfully.", steps=[])

async def enable_extensions(session_factory: async_sessionmaker[AsyncSession]) -> OperationResult:
    """Install required PostgreSQL extensions."""
    async with session_factory() as session:
        await _execute_sql_file(
            session, FilesLocationConstants.SCHEMA_EXTENSIONS_FILE
        )
        await session.commit()
    logger.info("Installed PostgreSQL extensions: %s", ", ".join(REQUIRED_EXTENSIONS))
    return OperationResult(name="enable_extensions", ok=True, message="PostgreSQL extensions installed successfully.", steps=[])

async def init_tables(session_factory: async_sessionmaker[AsyncSession]) -> OperationResult:
    """Create application tables from schema SQL."""
    async with session_factory() as session:
        await _execute_sql_file(session, FilesLocationConstants.SCHEMA_TABLES_FILE)
        await session.commit()
    logger.info("Ensured books table exists.")
    return OperationResult(name="init_tables", ok=True, message="Tables created successfully.", steps=[])

async def create_indexes(session_factory: async_sessionmaker[AsyncSession]) -> OperationResult:
    """Create database indexes from schema SQL."""
    async with session_factory() as session:
        await _execute_sql_file(session, FilesLocationConstants.SCHEMA_INDEXES_FILE)
        await session.commit()
    logger.info("Ensured books indexes exist.")
    return OperationResult(name="create_indexes", ok=True, message="Indexes created successfully.", steps=[])


async def bootstrap_schema(session_factory: async_sessionmaker[AsyncSession], readiness: ReadinessResult | None = None) -> OperationResult:
    """Apply extensions, tables, and indexes in order."""
    checks: list[OperationResult] = []
    
    if not readiness.table_exists:
        await init_tables(session_factory)
        checks.append(await init_tables(session_factory))
        
        await create_indexes(session_factory)
        checks.append(await create_indexes(session_factory))
    
    if readiness.extensions_missing:
        checks.append(await enable_extensions(session_factory))
    
    if not checks:
        return OperationResult(
            name="bootstrap_schema", 
            ok=True, 
            message="No actions required.", 
            steps=checks
        )

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
    from config.bootstrap import setup_logging
    from db.async_engine import close_async_engine, get_async_engine, get_session_factory
    from config import settings
    setup_logging()
    engine = get_async_engine(settings.sqlalchemy)
    try:
        session_factory = get_session_factory(engine)
        await bootstrap_schema(session_factory)
    finally:
        await close_async_engine(engine)


if __name__ == "__main__":
    asyncio.run(main())
