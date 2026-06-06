import os
from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware

import logging

from config import settings
from common.utils import setup_logging
from config.constants import FilesLocationConstants

setup_logging(
    environment=settings.app.ENVIRONMENT, 
    log_file=FilesLocationConstants.LOG_DIR / "dev_log.log"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    ...
    
    
app = FastAPI(
    title="Book Recommender API",
    description="AI-powered book recommendation system",
    version="0.1.0",
    # lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app.ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
from app.routes.session import router as session_router

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