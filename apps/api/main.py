# apps/api/main.py
import logging

# Suppress annoying health check logs from Docker container checks
class HealthCheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "GET / " not in record.getMessage()

logging.getLogger("uvicorn.access").addFilter(HealthCheckFilter())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from apps.api.routers.auth import router as auth_router
from apps.api.routers.property import router as property_router
from apps.api.routers.system import router as system_router
from apps.api.routers.lead import router as lead_router
from apps.api.routers.operator_actions import router as operator_actions_router
from apps.api.routers.conversation import router as conversation_router
from apps.api.routers.match import router as match_router
from apps.api.routers.webhooks import router as webhook_router
from apps.api.repositories.lead_repository import LeadRepository
from apps.api.repositories.conversation_repository import ConversationRepository
from apps.api.repositories.match_repository import MatchRepository
from apps.api.routers.analytics import router as analytics_router
from apps.api.repositories.webhook_event_repository import WebhookEventRepository
from shared.utils.database import close_mongo_connection, connect_to_mongo
from apps.api.routers import search
from apps.api.routers.site_visit import router as site_visits_router
from apps.api.repositories.site_visit_repository import site_visit_repo


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup and shutdown events cleanly under a modern single lifecycle workflow."""
    print("[Lifespan Startup] Booting up MongoDB connections...")

    # 1. ACTUALLY CONNECT TO MONGODB FIRST
    await connect_to_mongo()

    print("[Lifespan Startup] Ensuring all MongoDB Atlas cluster collection indexes exist...")
    try:
        # Trigger your repository indexing engines explicitly on container boot
        await LeadRepository().create_indexes()
        await ConversationRepository().create_indexes()
        await MatchRepository().create_indexes()
        await WebhookEventRepository().create_indexes()
        await site_visit_repo.create_indexes()
        from apps.api.repositories.broker_repository import broker_repo
        await broker_repo.create_indexes()

        print("[Lifespan Startup] Index verification complete. Database optimization rules active.")
    except Exception as e:
        print(f"[Lifespan Error] Critical failure during background database setup: {str(e)}")

    yield  # The application serves incoming HTTP traffic here

    print("[Lifespan Shutdown] Cleaning runtime application layer states...")

    # 2. CLOSE THE CONNECTION ON SHUTDOWN
    await close_mongo_connection()

# Pass the modern lifespan handler directly into your core FastAPI instance
app = FastAPI(
    title="NPH Property Intelligence Core",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware for ngrok tunnel and browser dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Route registration mounts
app.include_router(auth_router)
app.include_router(property_router)
app.include_router(system_router)
app.include_router(lead_router)
app.include_router(operator_actions_router)
app.include_router(conversation_router)
app.include_router(match_router)
app.include_router(analytics_router)
app.include_router(webhook_router)
app.include_router(search.router)
app.include_router(site_visits_router)


@app.get("/")
async def root():
    return {"message": "NPH Operating System Backend Platform Running"}
