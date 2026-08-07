"""CLI entrypoint: load books from CSV and backfill embeddings."""

import asyncio
import logging
from pathlib import Path

from common import setup_logging, task, OperationResult
from common.context import AppContext
from common.utils import save_file

from config import (
    DatabaseConstants,
    FilesLocationConstants,
    Settings,
)
from db.bootstrap import bootstrap_schema
from db.readiness import is_ready
from db.schema import BookModel
from db.ingestion.embeddings import embed_missing_books
from db.ingestion.store import store_books_from_csv
from db.ingestion.utils import count_csv_data_rows
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from clients.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


@task
async def load_books(
    session_factory: async_sessionmaker[AsyncSession],
    openai_client: OpenAIClient,
) -> OperationResult:
    """Load books from CSV into PostgreSQL and embed any missing vectors."""

    schema = DatabaseConstants.SCHEMA
    table = BookModel.__tablename__
    csv_path = Path(FilesLocationConstants.DATA_DIR) / FilesLocationConstants.CSV_FILE

    logger.info(f"Running ingestion for schema: {schema} and table: {table}")

    csv_rows = count_csv_data_rows(csv_path)

    checks = []
    readiness = await is_ready(
        session_factory, schema=schema, table=table, min_rows=csv_rows
    )
    checks.append(readiness)

    checks.append(await bootstrap_schema(session_factory, readiness.response.output))

    checks.append(
        await store_books_from_csv(session_factory, csv_path, readiness.response.output)
    )

    checks.append(
        await embed_missing_books(session_factory, openai_client)
    )

    if not readiness.ok:
        logger.info("Readiness check failed first time, retrying after ingestion...")
        readiness = await is_ready(
            session_factory, schema=schema, table=table, min_rows=csv_rows
        )
        readiness.name += "---retry"
        readiness.details = {"retry_reason": "Readiness check failed first time."}
        checks.append(readiness)

    ok = all(check.ok for check in checks) or readiness.ok
    return OperationResult(
        ok=ok,
        message="Books loaded successfully." if ok else "Books loading failed.",
        steps=checks,
    )


async def main() -> None:
    """Entry point for the ingestion pipeline."""
    settings = Settings()
    setup_logging(
        environment=settings.app.ENVIRONMENT,
        log_file=FilesLocationConstants.LOG_DIR / "ingestion_log.log",
    )
    async with AppContext(settings) as ctx:
        result = await load_books(
            session_factory=ctx.session_factory,
            openai_client=OpenAIClient(settings.openai)
        )

        # print("-----------FINAL RESULT-----------------")
        # result.print()
        # print("--------------------------------")
        if result.ok:
            logger.info("✅ Books loaded successfully.")
        else:
            logger.error("❌ Books loading failed.")

        # TODO: add a config option for this
        # no need to save the file in test environment
        if ctx.app_env != "test":
            save_file(result, file_name="operation_result")

    return result


if __name__ == "__main__":
    asyncio.run(main())
