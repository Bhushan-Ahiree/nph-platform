# apps/api/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager
from apps.api.routes.auth import router as auth_router
from apps.api.routes.property import router as property_router
from apps.api.routers.system import router as system_router
from apps.api.routers.lead import router as lead_router
from apps.api.routers.conversation import router as conversation_router

# Import the repositories to handle initialization centrally
from apps.api.repositories.lead_repository import LeadRepository
from apps.api.repositories.conversation_repository import ConversationRepository

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup and shutdown events cleanly under a modern single lifecycle workflow."""
    print("[Lifespan Startup] Ensuring all MongoDB Atlas cluster collection indexes exist...")
    try:
        # Trigger your repository indexing engines explicitly on container boot
        await LeadRepository().create_indexes()
        await ConversationRepository().create_indexes()
        print("[Lifespan Startup] Index verification complete. Database optimization rules active.")
    except Exception as e:
        print(f"[Lifespan Error] Critical failure during background database setup: {str(e)}")
        
    yield  # The application serves incoming HTTP traffic here
    
    print("[Lifespan Shutdown] Cleaning runtime application layer states...")

# Pass the modern lifespan handler directly into your core FastAPI instance
app = FastAPI(
    title="NPH Property Intelligence Core",
    version="1.0.0",
    lifespan=lifespan
)

# Route registration mounts
app.include_router(auth_router)
app.include_router(property_router)
app.include_router(system_router)
app.include_router(lead_router)
app.include_router(conversation_router)

@app.get("/")
async def root():
    return {"message": "NPH Operating System Backend Platform Running"}