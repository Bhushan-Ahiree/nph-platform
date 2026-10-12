# System Architecture

---

## Table of Contents
1. [Architectural Overview](#architectural-overview)
2. [End-to-End Pipeline Architecture](#end-to-end-pipeline-architecture)
3. [Stage-by-Stage Deep Dive](#stage-by-stage-deep-dive)
4. [Cross-Cutting Architectural Subsystems](#cross-cutting-architectural-subsystems)

---

## Architectural Overview

The NPH Property Intelligence Platform is designed around a decoupled, event-driven, containerized monorepo architecture. It separates fast, non-blocking HTTP request processing from heavy, asynchronous data processing and local AI inference.

```
+---------------------------------------------------------------------------------------+
|                                  DOCKER NETWORK                                       |
|                                                                                       |
|   +--------------------------+     +--------------------------+     +-------------+   |
|   |         nph_api          |     |        nph_worker        |     | nph_scraper |   |
|   |    FastAPI HTTP Server   |     |    Celery + Celery Beat  |     |   Scraper   |   |
|   |     (Async Motor I/O)    |     |    (Sync PyMongo I/O)    |     |   Daemon    |   |
|   +------------+-------------+     +------------+-------------+     +------+------+   |
|                |                                |                          |          |
|                |       +----------------+       |                          |          |
|                +-----> |   Redis 7.0    | <-----+--------------------------+          |
|                        | Task & Message |                                             |
|                        +-------+--------+                                             |
+--------------------------------|------------------------------------------------------+
                                 |                                                       
            +--------------------+--------------------+                                  
            |                                         |                                  
            v                                         v                                  
+-----------------------+                 +-----------------------+                      
|     MongoDB Atlas     |                 |     Ollama (Host)     |                      
|  Dedicated Database   |                 |     Llama 3.2 LLM     |                      
+-----------------------+                 +-----------------------+                      
```

### Separation of Concurrency Models
A core architectural tenet of the platform is the complete separation of concurrency models across its container tiers:
* **API Layer (`nph_api`):** Operates on an asynchronous event loop (`asyncio`) managed by Uvicorn and FastAPI. It communicates with MongoDB Atlas via the asynchronous `Motor` driver, ensuring that heavy I/O operations (such as multi-document queries and matching aggregations) never block the HTTP thread pool.
* **Worker Layer (`nph_worker`):** Operates in a synchronous pre-fork thread pool managed by Celery. Because Celery tasks do not natively execute within an `asyncio` event loop, the worker tier utilizes the synchronous `PyMongo` driver. This avoids the severe overhead of spinning up one-off event loops per task and guarantees predictable execution during heavy local LLM inference.

---

## End-to-End Pipeline Architecture

The platform functions as an advanced ingestion and normalization engine. The flow of data from decentralized, unstructured messaging networks to structured business intelligence projections follows an explicit 11-stage pipeline.

```
       +------------------------------------+
       |              WhatsApp              |  (Decentralized Broker Broadcasts)
       +-----------------+------------------+
                         |
                         v
       +------------------------------------+
       |              Raw Dump              |  (POST /properties/raw-chunk)
       +-----------------+------------------+
                         |
                         v
       +------------------------------------+
       |            Preprocessor            |  (Tokenization & Noise Sanitization)
       +-----------------+------------------+
                         |
                         v
       +------------------------------------+
       |      Deterministic Extraction      |  (Ground-Truth Category A Guards)
       +-----------------+------------------+
                         |
                         v
       +------------------------------------+
       |           LLM Enrichment           |  (Llama 3.2 Micro-Batch Entity Mining)
       +-----------------+------------------+
                         |
                         v
       +------------------------------------+
       |           Normalization            |  (Knowledge Graph & Unit Alignment)
       +-----------------+------------------+
                         |
                         v
       +------------------------------------+
       |              Routing               |  (Review Queues & Spam Isolation)
       +-----------------+------------------+
                         |
                         v
       +------------------------------------+
       |              MongoDB               |  (Idempotent Ingestion Hash Upserts)
       +-----------------+------------------+
                         |
                         v
       +------------------------------------+
       |           Matching Engine          |  (Composite Scoring & Zero-Clamping)
       +-----------------+------------------+
                         |
                         v
       +------------------------------------+
       |           Recommendations          |  (Funnel Tracking & Commission Shield)
       +-----------------+------------------+
                         |
                         v
       +------------------------------------+
       |             Analytics              |  (Supplier Reputation & LTV BI)
       +------------------------------------+
```

---

## Stage-by-Stage Deep Dive

### 1. WhatsApp
The ingestion lifecycle begins in external, decentralized real estate broker WhatsApp groups. Brokers broadcast real estate inventory, buyer requirements, and conversational chatter in informal, unstructured multiline messages. This data represents the raw top-of-funnel supply.

### 2. Raw Dump
Operators or automated scraper daemons bundle raw chat histories into payloads and transmit them to the platform via `POST /properties/raw-chunk`. 
* **Idempotency Guard:** The API layer intercepts the payload, computes an immediate SHA-256 hash over the raw content, and performs an atomic `insert_or_ignore` operation against the `webhook_events` collection. If a duplicate payload is detected, the API returns `202 Accepted` with a `duplicate_skipped` notice, completely protecting the background worker tier from redundant processing.
* **Task Dispatch:** If the event is unique, the API registers the event as `PENDING` and dispatches the job asynchronously to the Celery task broker via `celery_client.send_task("tasks.ingestion_tasks.process_raw_group_dump")`.

### 3. Preprocessor
Upon receiving the task, the `nph_worker` container executes the `WhatsAppTokenizer` service. The preprocessor performs structural sanitization prior to analysis:
* **Noise Removal:** Strips intrusive WhatsApp application artifacts including chat timestamps, `[Forwarded]` labels, `View Channel` links, emoji sequences, and repetitive phone chain signatures.
* **Structural Chunking:** Splits the contiguous chat text into distinct property blocks separated by empty lines, and batches them into micro-groups of five (`CHUNK_SIZE_BLOCKS = 5`). This micro-batching is critical to preventing context window overflow and VRAM exhaustion during downstream LLM evaluation.

### 4. Deterministic Extraction
To prevent AI hallucinations in highly sensitive financial and contact fields, the pipeline routes each sanitized chunk through a specialized `CategoryAExtractor` before invoking the LLM.
* **Pattern Guards:** Utilizes robust regular expression boundaries and strict parsing logic to achieve 100% deterministic extraction of primary parameters: `broker_phone`, `price`, `bhk`, `area`, and `intent` (separating active property offers from buyer inquiries).
* **Pre-Validation:** Any property block failing basic deterministic feasibility (e.g., missing phone numbers or containing obvious non-real-estate text) is immediately tagged or discarded, preserving AI compute resources.

### 5. LLM Enrichment
The partially structured property block, alongside ground-truth deterministic hints, is submitted via `POST` to the local Ollama LLM service (`http://host.docker.internal:11434/api/generate`) running Llama 3.2.
* **Prompt Engineering:** A strictly typed system prompt instructs the model to bypass conversational filler and extract secondary qualitative entities: `builder_name`, `project_name`, `landmarks`, `amenities`, `possession_status`, `furnishing_status`, and `poster_type` (Broker, Builder, Owner, Channel Partner, Investor).
* **JSON Enforcement:** The LLM returns a clean JSON array. If the model produces malformed output or network latency exceeds thresholds, the worker enforces an automated 3-attempt retry sequence before logging a structured warning.

### 6. Normalization
The extracted JSON object is passed to `normalise_extracted_property` to enforce strict canonical schema boundaries and establish referential integrity.
* **Unit Alignment:** Highly variable regional metrics are converted into uniform numerical standards. `Guntha`, `Vaar`, `Sqm`, and `Acre` are mathematically converted to standard `normalized_area_sqft`. Financial descriptions such as `Lakh`, `Crore`, `15k`, or `Per Person` are parsed into exact integer values representing total INR (`normalized_price_inr`).
* **Knowledge Graph Resolution:** The pipeline performs multikey index lookups against dedicated MongoDB collections (`builders`, `projects`, `localities`, `amenity_dictionary`) matching entity strings against `aliases` arrays. Known entities are assigned stable foreign keys (`builder_id`, `project_id`, `locality_id`). If an unknown entity string is discovered, the worker dynamically generates and inserts a new canonical Knowledge Graph node, allowing the system's intelligence to expand organically.

### 7. Routing
Before persistence, the normalized data passes through a `PropertyValidator` guardrail layer that enforces rigid pre-insertion validation rules.
* **Spam & Category Isolation:** Validates `is_real_estate_listing`. Detects and purges vehicle ads, loan promotions, event notices, and government announcements.
* **Specialized Routing:** Identifies Paying Guest (PG) and roommate posts, routing them directly to a dedicated `pg_listings` collection so they never pollute the primary residential/commercial database. Discards out-of-network properties outside the primary operational geo-fences (Nashik, Pune, Mumbai).
* **Validation Queue:** Any listing exhibiting conflicting data (e.g., a deterministic price of 40 Lakh vs an LLM hallucination of 4 Crore) is redirected to a dedicated `properties_review_queue` for manual operator validation.

### 8. MongoDB
Fully validated property objects reach the data access layer for persistence in the `properties` collection.
* **Cryptographic Fingerprinting:** The repository computes an invariant structural hash: `compute_ingestion_hash(price, area, bhk, listing_type, broker_phone)`. 
* **Idempotent Upsert:** The repository executes `upsert_property()`. If the `ingestion_hash` does not exist, a new property document is inserted with `status = ACTIVE` and `availability_status = NEW`. If a hash collision occurs (indicating the same broker has re-broadcast the exact same asset), the database bypasses document creation and atomically appends a `SourceEntry` to the existing document's `sources[]` array while incrementing `intelligence.duplicate_count`.

### 9. Matching Engine
When a buyer inquires about inventory (`GET /matches/lead/{lead_id}`), the API invokes an advanced MongoDB aggregation pipeline that unifies structural fit with statistical confidence.
* **Composite Scoring Formula:** `Composite Score = Structural Score + Clamped Confidence + Broker Reliability`
* **Execution Dynamics:** The aggregation pipeline filters for active, verified properties matching the lead's strict parameter bounds (BHK, budget, geography). It executes a `$lookup` against `broker_profiles` to pull historical reliability metrics. It evaluates inventory age, penalizing unverified listings while enforcing a strict `zero-clamping` rule (`clamped_confidence = max(computed_confidence, 0)`) to ensure mathematical stability. Properties receive dynamic point bonuses for preferred supply channels (e.g., direct owner listings receive a +30 point boost).

### 10. Recommendations
Matched properties are prepared for egress to the client. This stage enforces enterprise governance and constructs comprehensive audit trails.
* **Funnel Audit Logging:** For every property surfaced to a lead, the system asynchronously records an immutable tracking document in the `recommendation_events` collection with an initial state of `SENT` and the calculated composite score.
* **Commission Shield Governance:** The `shield_property(data, role)` service inspects the requesting user's JWT authorization claim. If the user possesses a `PUBLIC` role, the Commission Shield dynamically purges and blinds sensitive disintermediation vectors: `broker_phone`, `owner_phone`, `building_name`, `exact_address`, `google_pin`, and `ingestion_hash`. The sanitized object is strictly serialized through `PropertyPublicResponse`, ensuring flawless data governance before network transmission.

### 11. Analytics
The persistent exhaust generated by the ingestion pipelines, matching engines, and site visit lifecycles feeds directly into executive business intelligence projections.
* **Broker Reputation Modeling:** The `broker_profiles` collection continuously recalculates supplier reliability scores based on the mathematical ratio of verified inventory to total properties posted (`(verified / posted) * 100`).
* **Funnel & Monetization BI:** Subsystems analyze `site_visits` and `recommendation_events` to project customer conversion ratios, calculate multi-channel marketing attribution, track collected site visit fees, and aggregate total Customer Lifetime Value (LTV) across closed deals.

---

## Cross-Cutting Architectural Subsystems

### The Commission Shield Subsystem
The Commission Shield is a dedicated governance boundary located in `services/property/commission_shield.py`. It establishes a definitive separation between raw database storage and client API presentation.

```
+-----------------------------------------------------------------------+
|                        RAW MONGODB PROPERTY DOCUMENT                  |
|  (Contains exact_address, broker_phone, building_name, google_pin)    |
+-----------------------------------+-----------------------------------+
                                    |
                                    v
+-----------------------------------+-----------------------------------+
|               COMMISSION SHIELD GOVERNANCE BOUNDARY                   |
|                   `shield_property(data, role)`                       |
+-----------------------------------+-----------------------------------+
                                    |
         +--------------------------+--------------------------+
         | (role == PUBLIC)                                    | (role == INTERNAL / ADMIN)
         v                                                     v
+--------+-----------------------+                    +--------+-----------------------+
|  PropertyPublicResponse Schema |                    | PropertyInternalResponse Schema|
|  - STRIPPED: broker_phone      |                    |  - FULL ACCESS: broker_phone   |
|  - STRIPPED: owner_phone       |                    |  - FULL ACCESS: owner_phone    |
|  - STRIPPED: exact_address     |                    |  - FULL ACCESS: exact_address  |
|  - STRIPPED: building_name     |                    |  - FULL ACCESS: building_name  |
|  - STRIPPED: google_pin        |                    |  - FULL ACCESS: google_pin     |
+--------------------------------+                    +--------------------------------+
```

By decoupling field blinding from transport models and embedding it directly within the pure-Python domain service tier, the shield achieves total framework independence. It can be fully unit-tested without instantiating complex ASGI request objects or Pydantic serialization lifecycles.

### Atomic Deal Closure Cascade
In high-stakes real estate CRM architectures, managing state across independent customer, visit, and inventory tables is highly prone to partial failure anomalies. If a network drop occurs mid-update, a property might appear archived while its associated sales opportunity remains actively matched to new buyers.

```
       +----------------------------------------------------+
       |          PATCH /site-visits/{id}                   |
       |  Payload: {status: "COMPLETED", deal_closed: true} |
       +-------------------------+--------------------------+
                                 |
                                 v
       +-------------------------+--------------------------+
       |             db.client.start_session()              |
       |            session.start_transaction()             |
       +-------------------------+--------------------------+
                                 |
         +-----------------------+-----------------------+
         |                       |                       |
         v                       v                       v
+--------+------------+ +--------+------------+ +--------+------------+
|     site_visits     | |        leads        | |     properties      |
|  status: COMPLETED  | |    status: CLOSED   | |   status: ARCHIVED  |
|   deal_closed: true | |                     | | availability:       |
|                     | |                     | |            ARCHIVED |
+--------+------------+ +--------+------------+ +--------+------------+
         |                       |                       |
         +-----------------------+-----------------------+
                                 |
                                 v
       +-------------------------+--------------------------+
       |                session.commit_transaction()        |
       |       (Flawless ACID Consistency Across 3 Tables)  |
       +----------------------------------------------------+
```

To achieve total state synchronization, `PATCH /site-visits/{id}` leverages MongoDB Atlas multi-document ACID transactions. When a site visit successfully closes a commercial deal, the service initiates a transactional session. It atomically updates the visit record, transitions the buyer's lead profile to `CLOSED`, and purges the property from active search vectors by setting `status = ARCHIVED` and `availability_status = ARCHIVED`. If any single update throws an exception, the entire transaction rolls back instantly, maintaining pristine referential integrity across the monorepo.
