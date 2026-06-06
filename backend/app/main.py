import os
from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from common.utils import setup_logging
from config import FilesLocationConstants

import logging
setup_logging(
    environment=settings.app.ENVIRONMENT, 
    log_file=FilesLocationConstants.LOG_DIR / "dev_log.log"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI): 
    from common.context import AppContext
    from app.orchestration.orchestrator import Orchestrator
    
    logger.info("Starting App lifespan")
    async with AppContext(settings) as ctx:
        
        app.state.openai_client = ctx.openai_client
        logger.info("OpenAI client set")
        
        app.state.sqlalchemy_engine = ctx.engine
        logger.info("SQLAlchemy engine set")
        
        app.state.sqlalchemy_session_factory = ctx.session_factory
        logger.info("SQLAlchemy session factory set")
        
        app.state.orchestrator = Orchestrator()
        logger.info("Orchestrator set")
        
        yield
    
    logger.info("Ending App lifespan")


app = FastAPI(
    title="Book Recommender API",
    description="AI-powered book recommendation system",
    version="3.0.0",
    lifespan=lifespan
)

# CORS configuration for Cloud Run
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app.ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"], # TODO: need to update this
    allow_headers=["*"],
)

# Include routers
from app.api.routes.health import router as health_router
from app.api.routes.chat_message import router as chat_router  
from app.api.routes.session import router as session_router

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(session_router)

# Cloud Run entry point
if __name__ == "__main__":
    import uvicorn
    
    # Cloud Run provides PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    
    logger.info(f"🌐 Starting server on {host}:{port}")
    
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=False,  # Never use reload in production
        access_log=True,
        log_level="info"
    )