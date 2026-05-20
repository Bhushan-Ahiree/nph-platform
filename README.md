# NPH Property Intelligence Core

## Overview
The foundational data infrastructure for the NPH PropTech ecosystem. This monorepo houses the centralized property database, FastAPI backend, scraping pipeline, and internal admin operations. 

Built for high-performance data ingestion, automated normalization, and AI-module extensibility.

## Monorepo Architecture
- `apps/api/` - Core backend (FastAPI)
- `apps/scraper/` - Data acquisition engine (Scrapy/Playwright) *[Pending]*
- `apps/worker/` - Async task processing (Celery) *[Pending]*
- `apps/dashboard/` - Internal operational UI (Next.js) *[Pending]*
- `shared/` - Unified Pydantic schemas, database connections, and types
- `infrastructure/` - Docker configurations and deployment pipelines

## Tech Stack
- **Backend:** Python 3.11, FastAPI
- **Database:** MongoDB Atlas (Motor Async Driver)
- **Cache / Queue:** Redis
- **Validation:** Pydantic V2
- **Infrastructure:** Docker & Docker Compose

## Quick Start (Local Development)
1. Ensure Docker Desktop is running.
2. Create a `.env` file in the root directory with your `MONGO_URI`.
3. Boot the ecosystem:
   ```bash
   docker compose up --build