"""Backfill description embeddings for books missing vectors."""
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clients.openai_client import OpenAIClient
from db.stores.book_store import BookStore
from db.schema import BookModel
from common.operation import OperationResult, task
from typing import Any, AsyncIterator
import logging, asyncio
logger = logging.getLogger(__name__)

from ingestion.write_store import store_book_embedding, iter_missing_embeddings

def _get_embedding_text(book: dict) -> str:
    """Canonical text used for book description embeddings."""
    return f"{book['title']}\n\n{book['description']}"

    
@task(log_info=False)
async def _store_batch_embeddings(
    isbn13_bucket: list[str],
    embeddings: list[list[float]],
    session_factory: async_sessionmaker[AsyncSession],
) -> OperationResult:
    if len(isbn13_bucket) != len(embeddings):
        raise ValueError(
            "ISBN13 and embedding batches have different lengths: "
            f"{len(isbn13_bucket)} != {len(embeddings)}"
        )
    
    async with session_factory() as session:
        update_results = []
        for isbn13, embedding in zip(isbn13_bucket, embeddings, strict=True):
            update_result = await store_book_embedding(isbn13, embedding, session)
            update_results.append(update_result)
            if not update_result.ok:
                await session.rollback()
                return OperationResult(
                    ok=False,
                    message=f"Failed to update embedding for book {isbn13}.",
                    result=0,
                    steps=update_results,
                )

        await session.commit()
        
    return OperationResult(
        ok=True,
        message=f"Embedded {len(isbn13_bucket)} books.",
        result=len(isbn13_bucket)
    )
    
async def _get_bucketed_embeddings(
    session_factory: async_sessionmaker[AsyncSession],
    openai_client: OpenAIClient,
) -> dict[int, dict[str, list[str]]]:
    # TODO: blocking operation might be a long operation (not IO bound)
    
    text_bucket: list[str] = []
    isbn13_bucket: list[str] = []
    running_token_count: int = 0
    batch_id: int = 0
    
    async for book in iter_missing_embeddings(session_factory):
        text = _get_embedding_text(book)
        text_tokens = openai_client.token_count(text)
        if text_bucket and running_token_count + text_tokens > openai_client.max_tokens:
            if len(text_bucket) != len(isbn13_bucket):
                raise ValueError(f"Text bucket and ISBN13 bucket have different lengths: {len(text_bucket)} != {len(isbn13_bucket)}")
                
            yield {"batch_id": batch_id, "text_bucket": text_bucket, "isbn13_bucket": isbn13_bucket}
            
            batch_id += 1
            text_bucket = []
            isbn13_bucket = []
            running_token_count = 0
       
        text_bucket.append(text)
        isbn13_bucket.append(book["isbn13"])
        running_token_count += text_tokens
        
    if len(text_bucket):
        if len(text_bucket) != len(isbn13_bucket):
            raise ValueError(f"Text bucket and ISBN13 bucket have different lengths: {len(text_bucket)} != {len(isbn13_bucket)}")
        yield {"batch_id": batch_id, "text_bucket": text_bucket, "isbn13_bucket": isbn13_bucket}

async def _get_batch_embeddings(
    batch_id: int,
    text_bucket: list[str],
    openai_client: OpenAIClient,
) -> dict[str, Any]:
    embeddings = await openai_client.get_embeddings_batch(text_bucket)
    return {"batch_id": batch_id, "embeddings": embeddings}
    
@task
async def embed_missing_books(
    session_factory: async_sessionmaker[AsyncSession],
    openai_client: OpenAIClient,
) -> OperationResult:
    """Backfill embeddings for rows where embedding IS NULL."""
    
    # check if there are any books missing embeddings
    async with session_factory() as session:
        book_store = BookStore(session)
        num_missing = await book_store.get_num_book_missing_embeddings()
        if num_missing == 0:
            return OperationResult(
                               ok=True, 
                               message="No books missing embeddings.")
    
    logger.info(f"📋 Found {num_missing} books with missing embeddings...")
    
    # get the bucketed embeddings
    # get the batch embeddings concurrently
    coroutines = []
    isbn13_batch = {}
    async for bucket in _get_bucketed_embeddings(session_factory, openai_client):
        coroutines.append(_get_batch_embeddings(bucket["batch_id"], bucket["text_bucket"], openai_client))
        
        logger.debug(
            "Prepared embedding bucket %s with %d texts and %d ISBN13s",
            bucket["batch_id"],
            len(bucket["text_bucket"]),
            len(bucket["isbn13_bucket"]),
        )
        
        isbn13_batch[bucket["batch_id"]] = bucket["isbn13_bucket"]
    batch_embedding_results = await asyncio.gather(*coroutines)
    logger.info("📋 Fetched embeddings for %d batches.", len(batch_embedding_results))
    
    # update the book embeddings concurrently
    coroutines = []
    for batch_embedding_result in batch_embedding_results:
        batch_id = batch_embedding_result["batch_id"]
        embeddings = batch_embedding_result["embeddings"]
        isbn13_bucket = isbn13_batch[batch_id]
        
        logger.debug(
            "Prepared update bucket %s with %d ISBN13s and %d embeddings",
            batch_id,
            len(isbn13_bucket),
            len(embeddings),
        )
        
        coroutines.append(_store_batch_embeddings(isbn13_bucket, embeddings, session_factory))
    batch_results = await asyncio.gather(*coroutines)
    logger.info("📋 Updated embeddings for %d batches.", len(batch_results))
    
    # collect the results
    count = 0
    steps = []
    for batch_result in batch_results:
        batch_result.name = f"embed_batch_{count}"
        steps.append(batch_result)
        count += batch_result.result or 0
        
    return OperationResult(
        ok=count == num_missing,
        message= f"Embedded {count} books out of {num_missing}.",
        result=count,
        steps=steps
    )
