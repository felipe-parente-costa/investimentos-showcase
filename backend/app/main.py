from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.health import router as health_router
from app.api.imports import router as imports_router
from app.api.market import router as market_router
from app.api.portfolio import router as portfolio_router
from app.api.reports import router as reports_router
from app.api.transactions import router as transactions_router
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = None
    if settings.scheduler_enabled:
        from app.jobs.scheduler import create_scheduler

        scheduler = create_scheduler()
        scheduler.start()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Investimentos", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(imports_router)
app.include_router(portfolio_router)
app.include_router(transactions_router)
app.include_router(reports_router)
app.include_router(admin_router)
app.include_router(market_router)
