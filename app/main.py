from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Settle API",
    description="Payment collection infrastructure for Nigerian businesses and developers.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins="*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/v1")


@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "service": "Settle API", "version": "0.1.0"}


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy"}
