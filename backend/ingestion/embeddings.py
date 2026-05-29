"""Backfill description embeddings for books missing vectors."""
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from clients.openai_client import OpenAIClient
from db.stores.book_store import BookStore
from db.schema import BookModel
from common.operation import OperationResult, task

import logging
logger = logging.getLogger(__name__)

def embedding_text(book: dict) -> str:
    """Canonical text used for book description embeddings."""
    # TODO: might be blocking
    return f"{book['title']}\n\n{book['description']}"

@task
async def update_book_embedding(
    isbn13: str,
    embedding: list[float],
    session: AsyncSession,
) -> OperationResult:
    stmt = (
        update(BookModel)
        .where(BookModel.isbn13 == isbn13)
        .values(embedding=embedding)
    )
    await session.execute(stmt)
    return OperationResult(
        ok=True,
        message=f"Updated embedding for book {isbn13}.",
        result=isbn13
    )

from typing import AsyncIterator, Any
from sqlalchemy import select
async def _iter_missing_embeddings(
        session_factory: async_sessionmaker[AsyncSession],
        *,
        batch_size: int = 500,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream books missing embeddings."""
        stmt = (
            select(
                BookModel.isbn13,
                BookModel.title,
                BookModel.description,
            )
            .where(BookModel.embedding.is_(None))
            .where(BookModel.description.is_not(None))
            .execution_options(yield_per=batch_size)
            # .limit(1000)
        )
        async with session_factory() as session:
            result = await session.stream(stmt)
            async for row in result.mappings():
                yield dict(row)
    
@task
async def _embed_batch(
    batch_isbn13: list[str],
    embeddings: list[list[float]],
    session_factory: async_sessionmaker[AsyncSession],
) -> OperationResult:
    async with session_factory() as session:
        for i, embedding in enumerate(embeddings):
            await update_book_embedding(batch_isbn13[i], embedding, session)
                
        await session.commit()
        
    return OperationResult(
        ok=True,
        message=f"Embedded {len(batch_isbn13)} books.",
        result=len(batch_isbn13)
    )
    
@task
async def embed_missing_books(
    session_factory: async_sessionmaker[AsyncSession],
    openai_client: OpenAIClient,
) -> OperationResult:
    """Backfill embeddings for rows where embedding IS NULL."""

    async with session_factory() as session:
        book_store = BookStore(session)
        num_missing = await book_store.get_num_book_missing_embeddings()
        if num_missing == 0:
            return OperationResult(
                               ok=True, 
                               message="No books missing embeddings.")
    
    batch_isbn13 = []
    batch_text = []
    
    
    logger.info(f"📋 Embedding {num_missing} books missing embeddings...")
    count = 0
    token_count = 0
    steps = []
    batch_count = 0
    async for book in _iter_missing_embeddings(session_factory):
        text = embedding_text(book)
        
        if openai_client.over_max_tokens(token_count + openai_client.token_count(text)):
            embeddings = await openai_client.get_embeddings_batch(batch_text)
            
            batch_result = await _embed_batch(batch_isbn13, embeddings, session_factory)
            logger.info(f"📋 Embedded {len(batch_isbn13)} books...")
            
            batch_result.name = f"embed_batch_{count}"
            steps.append(batch_result)
            
            count += len(batch_isbn13)
            batch_isbn13 = []
            batch_text = []
            token_count = 0
            batch_count += 1
            
        batch_isbn13.append(book["isbn13"])
        batch_text.append(text)
        token_count += openai_client.token_count(text)
        
    if len(batch_isbn13) > 0:
        embeddings = await openai_client.get_embeddings_batch(batch_text)
        batch_result = await _embed_batch(batch_isbn13, embeddings, session_factory)
        logger.info(f"📋 Embedded {len(batch_isbn13)} books...")
        
        batch_result.name = f"embed_batch_{batch_count}"
        steps.append(batch_result)
        batch_count += 1
        count += len(batch_isbn13)
        
    return OperationResult(
        ok=count == num_missing,
        message= f"Embedded {count} books out of {num_missing}.",
        result=count,
        steps=steps
    )
