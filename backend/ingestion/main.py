"""CLI entrypoint: load books from CSV and backfill embeddings."""
import asyncio
import logging
from pathlib import Path

from config import (
    DatabaseConstants,
    FilesLocationConstants,
    IngestionConstants,
    Settings,
)
from common.utils import save_file, setup_logging
from db import bootstrap_schema, is_ready

from db.schema import BookModel
from ingestion.embeddings import embed_missing_books
from ingestion.store import store_books

from common.context import AppContext
from common.operation import OperationResult, task

logger = logging.getLogger(__name__)

@task
async def load_books(ctx: AppContext) -> OperationResult:
    """Load books from CSV into PostgreSQL and embed any missing vectors."""

    schema = DatabaseConstants.SCHEMA
    table = BookModel.__tablename__
    csv_path = Path(FilesLocationConstants.DATA_DIR) / FilesLocationConstants.CSV_FILE
    logger.info(f"Running ingestion for schema: {schema} and table: {table}")
    
    checks = []
    readiness = await is_ready(
        ctx.session_factory, 
        schema=schema, 
        table=table, 
        min_rows=IngestionConstants.APPROXIMATE_LOAD_LIMIT
    )
    checks.append(readiness)
    
    checks.append(await bootstrap_schema(ctx.session_factory, readiness.result))
    checks.append(await store_books(
        ctx.session_factory, csv_path, readiness.result))
    checks.append(await embed_missing_books(
        ctx.session_factory, ctx.openai_client))
    
    return OperationResult(
        ok=all(check.ok for check in checks), 
        message="Books loaded successfully.", 
        steps=checks
    )

async def main() -> None:
    """Entry point for the ingestion pipeline."""
    settings = Settings()
    setup_logging(
        environment=settings.app.ENVIRONMENT, 
        log_file=FilesLocationConstants.EXPORT_DIR / "ingestion_log.log"
    )
    async with AppContext(settings) as ctx:
        result = await load_books(ctx)
        
        # print("-----------FINAL RESULT-----------------")
        # result.print()
        # print("--------------------------------")
        if result.ok:
            logger.info("✅ Books loaded successfully.")
        else:
            logger.error("❌ Books loading failed.")

        save_file(result, file_name="operation_result")

if __name__ == "__main__":
    asyncio.run(main())
