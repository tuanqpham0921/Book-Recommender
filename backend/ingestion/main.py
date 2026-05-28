"""CLI entrypoint: load books from CSV and backfill embeddings."""
import asyncio
import time
from pathlib import Path

from clients.openai_client import OpenAIClient
from config import (
    DatabaseConstants,
    FilesLocationConstants,
    IngestionConstants,
    settings,
)
from db import (
    bootstrap_schema,
    close_async_engine,
    get_async_engine,
    get_session_factory,
    is_ready,
)
from db.schema import BookModel
from ingestion.embeddings import embed_missing_books
from ingestion.store import store_books

from common.context import AppContext
from common.operation import OperationResult, task

@task
async def load_books(ctx: AppContext) -> OperationResult:
    """Load books from CSV into PostgreSQL and embed any missing vectors."""

    schema = DatabaseConstants.SCHEMA
    table = BookModel.__tablename__
    csv_path = Path(FilesLocationConstants.DATA_DIR) / FilesLocationConstants.CSV_FILE
    print(f"Running ingestion for schema: {schema} and table: {table}")
    
    checks = []
    checks.append(await is_ready(
        ctx.session_factory, schema=schema, 
        table=table, 
    min_rows=IngestionConstants.APPROXIMATE_LOAD_LIMIT))
    # if not checks[-1].ok:
    #     checks.append(await bootstrap_schema(ctx.session_factory))
        
    # checks.append(await store_books(ctx.session_factory, csv_path))
    # checks.append(await embed_missing_books(ctx.session_factory, ctx.openai_client))
    
    return OperationResult(name="load_books", ok=all(check.ok for check in checks), message="Books loaded successfully.", steps=checks)

async def main() -> None:
    """Entry point for the ingestion pipeline."""
    from config import Settings
    async with AppContext(Settings()) as ctx:
        result = await load_books(ctx)
        
        print("-----------FINAL RESULT-----------------")
        result.print()
        print("--------------------------------")

if __name__ == "__main__":
    asyncio.run(main())
