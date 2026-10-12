# System Design & Scalability

---

## Table of Contents
1. [System Goals & Architectural Principles](#system-goals--architectural-principles)
2. [Scalability & Worker Architecture](#scalability--worker-architecture)
3. [Background Jobs & Event Processing](#background-jobs--event-processing)
4. [Deduplication & Indexing Strategy](#deduplication--indexing-strategy)
5. [Caching & Data Lifecycle](#caching--data-lifecycle)
6. [Failure Recovery & Concurrency Strategy](#failure-recovery--concurrency-strategy)
7. [Architectural Tradeoffs](#architectural-tradeoffs)
8. [Future Scaling Strategy](#future-scaling-strategy)

---

## System Goals & Architectural Principles

The NPH Property Intelligence Platform operates in a highly dynamic, unstructured data ecosystem. To achieve enterprise-grade reliability and performance, the system design is governed by five core architectural principles:

* **High Availability & Sub-Second API Latency:** The customer-facing API layer must remain completely decoupled from heavy background compute, ensuring that search queries, matching aggregations, and lead capture operations respond with sub-second latency.
* **Deterministic Correctness:** While AI enrichment is utilized for qualitative entity extraction, core financial, structural, and contact data must be extracted and validated through rigid, deterministic parsing guardrails to eliminate data corruption.
* **Strict Data Isolation:** Supplier contact identities and precise physical markers must be systematically isolated via centralized governance layers (`Commission Shield`) to eliminate the risk of disintermediation prior to commercial commitment.
* **Zero-Spam Tolerance:** Ingested messaging streams are highly contaminated with conversational chatter, spam, and non-target listings (e.g., vehicles, loans, daily rentals). The pipeline must enforce absolute pre-insertion isolation so that invalid records never reach the core databases.
* **Observable Execution:** Every stage of the ingestion, matching, and site visit lifecycles must generate explicit, structured audit trails to guarantee full operational transparency and replayability.

---

## Scalability & Worker Architecture

The platform achieves horizontal scalability through a clean decoupling of the HTTP ingress boundary from the background execution tier.

```
+-----------------------------------------------------------------------------------+
|                                API INGRESS TIER                                   |
|                                                                                   |
|         +-------------------+       +-------------------+                         |
|         |  nph_api (Inst 1) |       |  nph_api (Inst 2) |  (Horizontal Scaling)   |
|         +---------+---------+       +---------+---------+                         |
+-------------------|---------------------------|-----------------------------------+
                    |                           |                                    
                    +-------------+-------------+                                    
                                  |                                                  
                                  v                                                  
+---------------------------------+-------------------------------------------------+
|                               REDIS BROKER TIER                                   |
|                                                                                   |
|                           +-----+-----+                                           |
|                           | Redis 7.0 |  (In-Memory Task Queue)                   |
|                           +-----+-----+                                           |
+---------------------------------+-------------------------------------------------+
                                  |                                                  
            +---------------------+---------------------+                            
            |                     |                     |                            
            v                     v                     v                            
+-----------+-------+   +---------+---------+   +-------+-----------+                
| nph_worker (GPU1) |   | nph_worker (GPU2) |   | nph_worker (CPU1) |                
|  Celery Daemon    |   |  Celery Daemon    |   |   Celery Daemon   |                
+-------------------+   +-------------------+   +-------------------+                
```

### Worker Concurrency & VRAM Management
A critical challenge in modern AI engineering is managing the severe resource constraints of localized Large Language Models (LLMs). Serving Llama 3.2 on host hardware creates a highly contested VRAM boundary. If Celery workers were permitted to prefetch arbitrary batches of ingestion tasks, concurrent LLM invocations would instantly exhaust GPU memory, resulting in cascading out-of-memory crashes.

To guarantee system stability under massive ingestion spikes, the Celery worker tier is architected with highly defensive concurrency configurations:
* `worker_prefetch_multiplier = 1`: Forces each worker process to request exactly one message from Redis at a time. This establishes a highly predictable, sequential memory allocation footprint across the inference hardware.
* `task_acks_late = True`: Instructs the worker to withhold message acknowledgment from Redis until the entire extraction, normalization, and persistence pipeline successfully completes. If a worker container crashes mid-execution due to an underlying hardware fault, the unacknowledged task is safely retained in Redis and re-delivered to a healthy worker node.

---

## Background Jobs & Event Processing

The platform divides background processing into two distinct operational paradigms: on-demand event processing and scheduled asynchronous sweeping.

```
+-----------------------------------------------------------------------------------+
|                           CELERY BACKGROUND EXECUTION                             |
|                                                                                   |
|         +-----------------------+           +-----------------------+             |
|         |   On-Demand Events    |           |    Scheduled Beat     |             |
|         |  (Celery Task Queue)  |           |     (Celery Beat)     |             |
|         +-----------+-----------+           +-----------+-----------+             |
|                     |                                   |                         |
|         +-----------+-----------+           +-----------+-----------+             |
|         | - process_raw_dump    |           | - sweep_freshness     |             |
|         | - webhook_tasks       |           |   (Every 5 Minutes)   |             |
|         | - whatsapp_dispatch   |           | - sweep_stale_nightly |             |
|         +-----------------------+           +-----------------------+             |
+-----------------------------------------------------------------------------------+
```

### On-Demand Task Execution
* `tasks.ingestion_tasks.process_raw_group_dump`: Triggered asynchronously by incoming webhook events. Handles text chunking, tokenization, deterministic parsing, LLM entity extraction, and database upserts.
* `tasks.webhook_tasks`: Processes structured webhook payloads originating from third-party application integrations (e.g., WhatsApp Cloud API, Instagram DMs).
* `tasks.whatsapp_tasks`: Manages asynchronous outbound messaging dispatch, isolating the API layer from external network latency during client communication.

### Scheduled Maintenance (Celery Beat)
* `tasks.maintenance_tasks.sweep_inventory_freshness`: Executes every five minutes to calculate dynamic inventory aging and degrade confidence scores across active databases.
* `tasks.maintenance_tasks.sweep_stale_properties`: Executes nightly at 02:00 IST to perform deep database cleanups and archive deeply inactive legacy records.

---

## Deduplication & Indexing Strategy

### Structural Idempotency & Cryptographic Fingerprinting
In decentralized real estate aggregation, relying on textual matching or titles for deduplication is structurally flawed. Brokers frequently modify descriptions, alter formatting, and introduce typos when re-broadcasting inventory across messaging networks.

To achieve absolute database idempotency, the data access layer computes an invariant cryptographic fingerprint over the unalterable physical facts of a listing:

```python
def compute_ingestion_hash(price, area, bhk, listing_type, broker_phone) -> str:
    def alphanumeric_only(value: str) -> str:
        return re.sub(r"[^a-zA-Z0-9]", "", str(value)).lower()

    composite = (
        alphanumeric_only(str(int(float(price)))) +
        alphanumeric_only(area) +
        alphanumeric_only(str(bhk)) +
        alphanumeric_only(listing_type) +
        alphanumeric_only(broker_phone or "")
    )
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()
```

* **The Invariance Principle:** The same physical property, listed by the same broker, at the same price, will always evaluate to the identical SHA-256 string, regardless of severe permutations in the accompanying promotional text.
* **Source Appending:** When a hash collision occurs during database insertion, the repository overrides document creation. Instead, it atomically appends a `SourceEntry` object to the existing document's `sources[]` array and increments `intelligence.duplicate_count`. This successfully transforms duplicate spam into high-value market intelligence, tracking exactly how widely a specific asset is being forwarded across broker networks.

### Comprehensive Indexing Architecture
To guarantee highly performant query execution across large datasets, the platform enforces a rigorous compound indexing architecture across MongoDB Atlas:

* **`properties` Collection:**
  * `{ingestion_hash: 1, status: 1}`: High-performance unique compound index powering sub-second deduplication lookups during heavy worker ingestion.
  * `{status: 1, availability_status: 1, listing_type: 1, area: 1, bhk: 1}`: Dedicated compound index optimized specifically for the matching engine's multi-stage aggregation pipeline.
  * `{property_id: 1}`: Unique index supporting atomic single-document updates, manual verification overrides, and site visit cascade modifications.
  * `{status: 1, last_verified_at: 1}`: Compound index designed to provide instant read access for the 5-minute inventory freshness sweeper.
* **Knowledge Graph Collections (`builders`, `projects`, `localities`, `amenity_dictionary`):**
  * `{aliases: 1}`: Multikey index on array fields allowing sub-second resolution of highly irregular entity strings (e.g., resolving "ashoka meadows" and "meadows by ashoka" to a single canonical `project_id`).
* **`broker_profiles` Collection:**
  * Uses the cleaned 10-digit phone number directly as the MongoDB primary key (`_id`). This guarantees primary key uniqueness at the storage engine level and achieves `O(1)` direct lookup performance during aggregation joins.

---

## Caching & Data Lifecycle

### Redis Tier
Redis 7.0 is utilized as a unified message broker and high-speed task result backend. It maintains transient Celery task states, queues incoming webhook events, and buffers asynchronous task payloads, successfully decoupling high-throughput network receivers from database write operations.

### The Asymmetric Data Lifecycle
A major structural defect in standard PropTech architectures is treating all property inventory as possessing an equal lifespan. In active real estate markets, inventory displays an asymmetric velocity: high-demand rental apartments are leased within days, whereas commercial properties and outright sales remain active for months.

```
+-----------------------------------------------------------------------------------+
|                        5-STATE AVAILABILITY LIFECYCLE                             |
|                                                                                   |
|      +-----+     +----------+     +-------+     +------------+     +----------+   |
|      | NEW | --> | VERIFIED | --> | STALE | --> | UNVERIFIED | --> | ARCHIVED |   |
|      +-----+     +----------+     +-------+     +------------+     +----------+   |
+-----------------------------------------------------------------------------------+
```

The platform establishes an advanced 5-state lifecycle (`NEW` -> `VERIFIED` -> `STALE` -> `UNVERIFIED` -> `ARCHIVED`) driven continuously by the `sweep_inventory_freshness` background task.

```
+-----------------------------------------------------------------------------------+
|                         ASYMMETRIC DECAY THRESHOLDS                               |
|                                                                                   |
|   +----------------------+------------+------------+--------------+-----------+   |
|   | Listing Type         | VERIFIED   | STALE      | UNVERIFIED   | ARCHIVED  |   |
|   +----------------------+------------+------------+--------------+-----------+   |
|   | Rental (rent)        | 0-3 Days   | 4-7 Days   | 8-14 Days    | 15+ Days  |   |
|   | Sale (buy/sale)      | 0-45 Days  | 46-60 Days | 61-90 Days   | 91+ Days  |   |
|   +----------------------+------------+------------+--------------+-----------+   |
+-----------------------------------------------------------------------------------+
```

* **Dynamic Confidence Decay & Zero-Clamping:** As inventory ages into the `UNVERIFIED` state, the sweeper deducts 10 points from the property's `confidence_score` per calculation pass. To maintain absolute mathematical stability within the matching engine's sorting algorithms, the update query enforces a rigid `zero-clamping` rule (`$set: {confidence_score: max(0, current_score - 10)}`), ensuring scores never decay into negative values.
* **The `NEW` State Principle:** Freshly ingested WhatsApp dumps default strictly to `NEW` rather than `VERIFIED`. Because raw messaging dumps may contain historical or forwarded chatter, starting at `NEW` prevents unverified assets from immediately polluting high-trust client recommendation feeds.

---

## Failure Recovery & Concurrency Strategy

### Resilient Initialization & DNS Decoupling
In multi-container cloud environments, services frequently restart or initialize out of order. Early initializations of MongoDB async drivers historically triggered fatal `pymongo.errors.ConfigurationError` exceptions when attempting DNS SRV lookups before Docker network bridges fully resolved.
* **Lazy Database Proxy:** The platform implements a robust `DatabaseProxy` singleton pattern across all repository files. Database connection pools are strictly withheld during Python module import time. The connection is established exclusively upon the first runtime query execution. This completely eliminates startup race conditions, allowing the API and worker containers to boot cleanly even if underlying database clusters are experiencing transient networking delays.

### ACID Transactional Boundaries
During critical commercial milestones—such as registering a completed site visit that resulted in a successful property sale—the platform must update three independent collections (`site_visits`, `leads`, `properties`).
* **Multi-Document Transactions:** To eliminate the risk of partial update anomalies (e.g., marking a deal as closed but failing to archive the property due to a transient network blip), the `SiteVisitRepository` initiates a strict MongoDB Atlas multi-document ACID transaction. If any individual collection update fails, the entire transaction rolls back instantly, ensuring pristine data integrity across the platform.

---

## Architectural Tradeoffs

| Decision | Primary Benefit | Primary Tradeoff | Architectural Rationale |
|---|---|---|---|
| **Local LLM (Ollama) vs. Cloud API (OpenAI/Anthropic)** | Total data privacy; zero recurring per-token inference costs; complete immunity to third-party API rate limits and external outages. | Constrained by host hardware GPU VRAM; slower per-property inference latency (30-90s per chunk). | Real estate broker data is highly proprietary. The absolute protection of supply inventory and elimination of unbounded token costs heavily outweigh the increased asynchronous ingestion latency. |
| **Two Property Schemas (`shared` vs. `V2`)** | Preserves backward compatibility for legacy manual CRUD routes and extensive test suites while enabling advanced ingestion validation in V2. | Introduces schema maintenance overhead; requires parallel updates across two files when modifying core database fields. | Acknowledged as explicit technical debt (`TD-002`). Allows immediate operational agility and deployment stability, with `property_schema_v2.py` designated as the eventual single source of truth. |
| **Worker Synchronous PyMongo vs. API Async Motor** | Flawless compatibility with Celery's synchronous pre-fork execution pool; eliminates the overhead of spinning up one-off event loops per task. | Requires maintaining two separate database connection patterns across the monorepo. | Motor requires an active `asyncio` event loop. Attempting to force async drivers into Celery's synchronous worker threads introduces severe complexity and runtime brittleness. |
| **Broker Phone as Primary Key (`_id`)** | Enforces absolute primary key uniqueness at the database engine level; guarantees `O(1)` direct lookup performance during aggregation joins. | Sacrifices globally unique `ObjectId` standards; creates potential migration overhead if phone number formats require universal modification. | Within a regional, single-business PropTech platform, broker profiles are accessed exclusively via phone numbers. The massive performance and deduplication benefits make this an optimal domain optimization. |
| **Pre-Computed Canonical Fields vs. Query-Time Logic** | Achieves zero read latency during complex matching and search API requests by querying pre-computed flat database fields directly. | Increases background write latency and storage footprint during worker ingestion. | Search and recommendation endpoints are invoked continuously by clients and operators, whereas ingestion occurs asynchronously in the background. Optimizing for zero read latency is the correct architectural choice. |

---

## Future Scaling Strategy

As platform throughput scales and operational boundaries expand across new geographic territories, the system architecture is designed to evolve across four primary axes:

```
+-----------------------------------------------------------------------------------+
|                           FUTURE SCALING ARCHITECTURE                             |
|                                                                                   |
|   +----------------------+    +----------------------+    +-------------------+   |
|   |  Atlas Search Tier   |    |    V2 CRM Identity   |    | Omni-Channel Hook |   |
|   | (Full-Text & Hybrid) |    |  (Master Contacts)   |    | (Meta / Web / IG) |   |
|   +----------+-----------+    +----------+-----------+    +---------+---------+   |
+--------------|---------------------------|--------------------------|-------------+
               |                           |                          |              
               +-------------+-------------+--------------------------+              
                             |                                                       
                             v                                                       
+----------------------------+------------------------------------------------------+
|                         KNOWLEDGE GRAPH AI SEARCH ENGINE                          |
|    (Matching via stable entity IDs rather than brittle textual query strings)     |
+-----------------------------------------------------------------------------------+
```

1. **Full-Text & Vector Search Integration:** Transitioning from regex-based area matching to dedicated full-text search clusters (`MongoDB Atlas Search` / `Elasticsearch`), laying the groundwork for hybrid semantic vector search over property descriptions.
2. **Architecture V2 CRM Normalization:** Executing the planned refactoring of the `leads` collection into decoupled `Contact` (master real-world identity) and `Lead` (transactional requirement opportunity) entities, unlocking advanced omni-channel marketing attribution and Customer Lifetime Value (LTV) analytics.
3. **Omni-Channel Ingestion Receivers:** Expanding the `webhooks.py` receiver boundaries to establish automated, real-time lead capture pipelines across Instagram DMs, Meta Lead Forms, and direct WhatsApp client interactions.
4. **Deep Knowledge Graph Exploitation:** Transitioning the matching engine from textual parameter matching to querying stable Knowledge Graph foreign keys (`builder_id`, `project_id`, `locality_id`), enabling highly advanced AI recommendation engines.
