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


async def load_books(ctx: AppContext) -> None:
    """Load books from CSV into PostgreSQL and embed any missing vectors."""

    schema = DatabaseConstants.SCHEMA
    table = BookModel.__tablename__
    csv_path = Path(FilesLocationConstants.DATA_DIR) / FilesLocationConstants.CSV_FILE
    print(f"Running ingestion for schema: {schema} and table: {table}")
    
    await bootstrap_schema(ctx.session_factory)

    ready_report = await is_ready(
        ctx.session_factory,
        schema=schema,
        table=table,
        min_rows=IngestionConstants.APPROXIMATE_LOAD_LIMIT,
    )
    ready_report.print()
    # TODO: check embedding coverage and skip embed when already done
    if not ready_report.ok:
        print("Storing Books into PostgreSQL")
        await store_books(ctx.session_factory, csv_path)

    print("Embedding missing books")
    await embed_missing_books(ctx.session_factory, ctx.openai_client)

async def main() -> None:
    """Entry point for the ingestion pipeline."""
    start = time.perf_counter()
    from config import Settings
    async with AppContext(Settings()) as ctx:
        await load_books(ctx)
        
        
    elapsed = time.perf_counter() - start
    print(f"Ingestion finished in {elapsed:.2f} seconds")


if __name__ == "__main__":
    asyncio.run(main())
