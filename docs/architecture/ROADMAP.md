# Engineering Roadmap

---

## Table of Contents
1. [Roadmap Overview](#roadmap-overview)
2. [Phase 1: Completed Architectural Milestones](#phase-1-completed-architectural-milestones)
3. [Phase 2: Current Execution & Stabilization](#phase-2-current-execution--stabilization)
4. [Phase 3: Future Strategic Vision](#phase-3-future-strategic-vision)

---

## Roadmap Overview

The engineering roadmap for the NPH Property Intelligence Platform follows a rigorous, phased execution strategy. It prioritizes core platform stability, data normalization, and deterministic correctness before scaling out multi-channel ingestion receivers or executing complex CRM architectural redesigns.

```
+-----------------------------------------------------------------------------------+
|                           PHASED ROADMAP EXECUTION                                |
|                                                                                   |
|    +-----------------------+     +-----------------------+     +-------------+    |
|    |       COMPLETED       | --> |        CURRENT        | --> |   FUTURE    |    |
|    |  Core Platform & AI   |     |  Extraction Accuracy  |     | Observability|    |
|    |   Normalization       |     |  Production Hardening |     | Advanced AI |    |
|    +-----------------------+     +-----------------------+     +-------------+    |
+-----------------------------------------------------------------------------------+
```

---

## Phase 1: Completed Architectural Milestones

### Core Platform Foundation
* **Asynchronous API Core:** Architected the primary HTTP REST API utilizing FastAPI and Uvicorn, integrating the asynchronous `Motor` MongoDB driver to achieve non-blocking I/O across all search and lead endpoints.
* **Decoupled Worker Tier:** Established a dedicated Celery worker and beat scheduling container utilizing synchronous `PyMongo` to execute heavy background tasks without stalling the API event loop.
* **Idempotency & Deduplication:** Designed and verified the structural SHA-256 cryptographic fingerprinting engine (`price + area + bhk + listing_type + broker_phone`), successfully handling asset collisions via atomic `SourceEntry` appending.
* **Commission Shield Governance:** Built the centralized `shield_property(data, role)` service, successfully establishing robust role-based field blinding (`PUBLIC`, `INTERNAL`, `ADMIN`) across Pydantic serialization boundaries.
* **Site Visit Monetization Engine:** Deployed the physical visit tracking lifecycle featuring multi-document ACID transactions to handle atomic deal closure cascades across `site_visits`, `leads`, and `properties`.

### Repository Normalization
* **Clean Data Access Layer:** Enforced a rigid Repository Pattern across all collections, completely decoupling database queries from routing logic and transport models.
* **Lazy Database Proxy:** Invented the lazy-loading `DatabaseProxy` singleton pattern across the worker and shared tiers, successfully eliminating import-time DNS SRV resolution timeouts during multi-container startup.
* **Comprehensive Indexing:** Executed startup index declarations across `PropertyRepository`, `LeadRepository`, `MatchRepository`, `SiteVisitRepository`, and `WebhookEventRepository` to guarantee performant query execution.
* **Schema Consolidation:** Eliminated dual-schema technical debt (`TD-002`) by designating `property_schema_v2.py` as the single source of truth and standardizing strict Pydantic Literal enforcement across the monorepo.

### Raw Dump Intelligence & Entity Extraction
* **Deterministic-First Ingestion:** Redesigned the WhatsApp ingestion pipeline to execute strict regex tokenization (`WhatsAppTokenizer` / `CategoryAExtractor`) for exact ground-truth parsing of phone numbers, prices, BHK, area, and intent prior to AI processing.
* **LLM Micro-Batching:** Configured incoming multiline group dumps to automatically batch into micro-chunks of five messages (`CHUNK_SIZE_BLOCKS = 5`), completely preventing local Ollama GPU VRAM exhaustion.
* **Canonical Entity Mining:** Expanded `normalise_extracted_property` to extract builder names, project names, landmarks, structured amenities, possession status, furnishing status, and granular poster types (Broker, Builder, Owner, Channel Partner, Investor, Developer).
* **Quality & Diagnostic Tracking:** Implemented deterministic `listing_quality_score` (0-100) calculations based on explicit missing field deductions, alongside top-level diagnostic tracking arrays (`missing_fields[]`, `warnings[]`, `confidence_breakdown{}`).

### Matching Engine & Knowledge Graph
* **Composite Scoring Formula:** Built the composite matching engine unifying structural fit, dynamic confidence scores, and historical broker reliability metrics (`(verified / posted) * 100`).
* **Zero-Clamping Enforcement:** Incorporated rigid `zero-clamping` rules (`max(computed_confidence, 0)`) within the 5-minute asymmetric freshness sweeper to maintain absolute mathematical stability in matching vectors.
* **Knowledge Graph Foundation:** Created dedicated canonical entity collections (`builders`, `projects`, `localities`, `amenity_dictionary`) featuring multikey alias indexing and dynamic node creation for unknown entity strings.
* **Test Suite Verification:** Exhaustively verified all normalization, extraction, matching, and Knowledge Graph pipelines with a robust automated test harness achieving a flawless 300-test passing rate.

---

## Phase 2: Current Execution & Stabilization

```
+-----------------------------------------------------------------------------------+
|                        CURRENT SPRINT / STABILIZATION FOCUS                       |
|                                                                                   |
|   +------------------------------------+     +--------------------------------+   |
|   |        EXTRACTION ACCURACY         |     |      PRODUCTION HARDENING      |   |
|   | - Rigid Pre-Insertion Guardrails   |     | - Lazy DNS Proxy Verification  |   |
|   | - Review Queue Routing             |     | - CORS & Auth Guard Enforcement|   |
|   | - Unit & Currency Normalization    |     | - Uvicorn Reload Optimization  |   |
|   +------------------------------------+     +--------------------------------+   |
+-----------------------------------------------------------------------------------+
```

### Extraction Accuracy
* **Pre-Insertion Guardrails:** Hardening the `PropertyValidator` layer to enforce absolute pre-insertion isolation, systematically blocking LLM price/unit hallucinations (e.g., misinterpreting 40 Lakh as 4 Crore), buyer requirement posts, and empty properties from reaching MongoDB.
* **Review Queue Routing:** Establishing automated redirection of records failing validation guardrails to a dedicated `properties_review_queue` for manual operator inspection.
* **Unit & Currency Alignment:** Standardizing mathematical conversion logic for regional metrics (`Guntha`, `Vaar`, `Lakh`, `Crore`, `Per Person`, `15k`) into uniform `normalized_area_sqft` and `normalized_price_inr` integers.

### Production Hardening
* **Container Resiliency:** Verifying lazy `DatabaseProxy` initializations across all worker task modules to guarantee flawless multi-container deployment resilience under transient network delays.
* **Security & Governance:** Restricting wildcard CORS configurations (`allow_origins=["*"]`) to explicit ngrok subdomains and localhost, while enforcing strict JWT authentication guards across all sensitive CRM and lead endpoints.
* **Health Check & Reload Tuning:** Increasing API container healthcheck start periods to 180 seconds and restricting Uvicorn reload directories (`--reload-dir apps/api --reload-dir shared --reload-dir services`) to prevent internal rust watcher crashes during host file changes.

---

## Phase 3: Future Strategic Vision

```
+-----------------------------------------------------------------------------------+
|                              FUTURE STRATEGIC VISION                              |
|                                                                                   |
|   +----------------------+    +----------------------+    +-------------------+   |
|   |     Observability    |    |   CI/CD & Cloud      |    |    Advanced AI    |   |
|   | - Prometheus / Grafana|   | - GitHub Actions     |    | - Hybrid Vector   |   |
|   | - Structured Logging |    | - Multi-Node Clusters|    | - V2 CRM Contacts |   |
|   +----------+-----------+    +----------+-----------+    +---------+---------+   |
+--------------|---------------------------|--------------------------|-------------+
               +---------------------------+--------------------------+
                                           |
                                           v
+-----------------------------------------------------------------------------------+
|                         ENTERPRISE PROPTECH ECOSYSTEM                             |
|    [Fully Observable | Horizontally Scalable | Deep Knowledge Graph Matching]     |
+-----------------------------------------------------------------------------------+
```

### Monitoring & Observability
* **Prometheus & Grafana Integration:** Instrumenting FastAPI and Celery worker containers with dedicated metrics exporters to track API request latencies, task queue depths, database query execution times, and LLM inference durations.
* **Centralized Structured Logging:** Unifying JSON structured logging across `nph_api`, `nph_worker`, and `nph_scraper` while verifying that custom log filters (`HealthCheckFilter`) successfully suppress routine health pings (`GET /`) to maintain pristine log clarity.
* **Uptime & Endpoint Alerting:** Deploying automated uptime monitoring and alerting infrastructure for public webhook receivers and active ngrok tunnel endpoints.

### CI/CD & Cloud Deployment
* **Automated CI/CD Pipelines:** Architecting comprehensive GitHub Actions workflows to automatically execute the full 300-test pytest suite, verify Pydantic serialization contracts, and build production container images upon every code commit.
* **Cloud Container Orchestration:** Preparing infrastructure blueprints to transition from localized Docker Compose deployments to managed multi-node container orchestration clusters (e.g., AWS ECS / EKS, GCP Cloud Run).
* **Automated Database Snapshots:** Configuring automated daily backup schedules and documenting point-in-time recovery procedures for core MongoDB Atlas collections (`properties`, `leads`, `site_visits`).

### Advanced AI Extraction & Search
* **Hybrid Vector Search:** Integrating dedicated full-text search clusters (`MongoDB Atlas Search` / `Elasticsearch`) to transition from regex-based area matching to advanced hybrid semantic vector search over property descriptions.
* **Omni-Channel Webhook Receivers:** Expanding `webhooks.py` ingress boundaries to establish automated, real-time lead capture pipelines across Instagram DMs, Meta Lead Forms, and direct WhatsApp client interactions.
* **Architecture V2 CRM Redesign:** Executing the planned structural refactoring of the `leads` collection into decoupled `Contact` (master real-world identity) and `Lead` (transactional requirement opportunity) entities, unlocking enterprise-grade omni-channel marketing attribution and Customer Lifetime Value (LTV) analytics.
