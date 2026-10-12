# Major Engineering Decisions

---

## Table of Contents
1. [AI & Data Ingestion Decisions](#ai--data-ingestion-decisions)
   * [Local LLM over Cloud](#1-local-llm-over-cloud)
   * [Deterministic-First Extraction](#2-deterministic-first-extraction)
   * [SHA-256 Ingestion Hashing](#3-sha-256-ingestion-hashing)
2. [Data Access & Database Architecture](#data-access--database-architecture)
   * [The Repository Pattern](#4-clean-repository-pattern)
   * [Atomic MongoDB Updates](#5-atomic-mongodb-updates)
   * [Single Source of Truth](#6-single-source-of-truth)
3. [Concurrency & Background Execution](#concurrency--background-execution)
   * [Background Workers](#7-background-workers)
   * [Inventory Freshness Sweeper](#8-inventory-freshness-sweeper)
4. [Data Governance & Normalization](#data-governance--normalization)
   * [Canonical Normalization](#9-canonical-normalization)
   * [The Commission Shield](#10-commission-shield)
   * [Raw Data Immutability](#11-raw-data-immutability)

---

## AI & Data Ingestion Decisions

### 1. Local LLM over Cloud

#### The Decision
Serve Llama 3.2 locally within a container-adjacent Ollama server (`http://host.docker.internal:11434`) rather than integrating with commercial cloud AI APIs (e.g., OpenAI GPT-4o, Anthropic Claude 3.5).

#### Why This Decision Exists
In PropTech and high-velocity real estate brokering, supply inventory data is highly proprietary. Broadcasts originating in closed broker WhatsApp groups represent confidential market supply before it reaches the public sphere. Transmitting these raw chat logs to third-party cloud AI vendors introduces severe data privacy risks and violates supplier confidentiality.

Furthermore, cloud AI APIs operate on variable per-token pricing models. Processing continuous, high-volume chat dumps containing heavy conversational noise would incur massive, unbounded operational expenses. Serving Llama 3.2 locally entirely eliminates recurring inference costs, guarantees complete data privacy, and ensures the platform remains completely immune to third-party API rate limits and external network outages.

```
+-----------------------------------------------------------------------------------+
|                           LOCAL OLLAMA INFERENCE BOUNDARY                         |
|                                                                                   |
|     +--------------------+   HTTP POST (Localhost)   +----------------------+     |
|     | nph_worker Daemon  | ------------------------> | Ollama (Llama 3.2)   |     |
|     | (Celery Task Pool) | <------------------------ | Container-Adjacent   |     |
|     +--------------------+     Extracted JSON Array  +----------------------+     |
|                                                                                   |
|     [Absolute Supply Privacy | Zero Variable Token Costs | Zero Rate Limits]      |
+-----------------------------------------------------------------------------------+
```

---

### 2. Deterministic-First Extraction

#### The Decision
Force all incoming chat chunks through a strict regular expression and tokenization parsing layer (`CategoryAExtractor`) to firmly establish ground-truth financial, structural, and contact data prior to LLM evaluation.

#### Why This Decision Exists
While Large Language Models possess exceptional natural language understanding for unstructured text, they are fundamentally probabilistic engines prone to severe numerical and unit hallucinations. In real estate transactions, a minor hallucination—such as misinterpreting a regional price of `40 Lakh` as `4 Crore`, or truncating a digit in a broker's phone number—corrupts the database and destroys platform credibility.

```
+-----------------------------------------------------------------------------------+
|                        DETERMINISTIC-FIRST EXTRACTION PIPELINE                    |
|                                                                                   |
|     +----------------------------------+                                          |
|     |  Unstructured Raw Messaging Dump |                                          |
|     +----------------+-----------------+                                          |
|                      |                                                            |
|                      v                                                            |
|     +----------------+-----------------+                                          |
|     | Category A Deterministic Parser  |  (Extracts EXACT Phone, Price, BHK, Area)|
|     +----------------+-----------------+                                          |
|                      |                                                            |
|                      v                                                            |
|     +----------------+-----------------+                                          |
|     |   Local Ollama LLM Enrichment    |  (Extracts Nuanced Amenities, Landmarks) |
|     +----------------------------------+                                          |
+-----------------------------------------------------------------------------------+
```

By decoupling extraction into a deterministic-first architecture, the platform enforces absolute mathematical and structural guardrails. The deterministic parser establishes immutable values for `broker_phone`, `price`, `bhk`, and `area`. The LLM is strictly restricted to extracting qualitative secondary entities (e.g., landmarks, amenities, furnishing status, poster type). If the LLM generates output that violates the deterministic ground truth, the validation tier catches the discrepancy and redirects the record to a review queue, achieving absolute data correctness.

---

### 3. SHA-256 Ingestion Hashing

#### The Decision
Implement a deterministic SHA-256 cryptographic fingerprinting algorithm over five unalterable structural parameters (`price + area + bhk + listing_type + broker_phone`) to manage property deduplication and idempotency.

#### Why This Decision Exists
In decentralized real estate aggregation, relying on textual matching, promotional descriptions, or titles for deduplication is structurally flawed. Brokers copy, paste, modify, and forward the exact same physical property across dozens of messaging groups daily. Descriptions are altered, emojis are added, and formatting is changed. A traditional database relying on text matching would create dozens of redundant rows for a single physical asset.

The five chosen parameters represent the immutable physical and economic fingerprint of a listing. If a broker posts the identical flat in fifteen different groups, the cryptographic hash evaluates to the exact same SHA-256 string every time. 

```
+-----------------------------------------------------------------------------------+
|                           SHA-256 DEDUPLICATION ENGINE                            |
|                                                                                   |
|    Incoming Listing -> SHA-256(Price + Area + BHK + Listing Type + Phone)         |
|                                     |                                             |
|              +----------------------+----------------------+                      |
|              | (Hash Does NOT Exist)                       | (Hash Collision)     |
|              v                                             v                      |
|    +---------+---------+                         +---------+---------+            |
|    | Insert New Record |                         | Append SourceEntry|            |
|    |  (status: ACTIVE) |                         | (Inc Duplicate Ct)|            |
|    +-------------------+                         +-------------------+            |
+-----------------------------------------------------------------------------------+
```

When a hash collision occurs during insertion (`upsert_property()`), the repository overrides new document creation and instead appends a `SourceEntry` to the existing document's `sources[]` array while incrementing `intelligence.duplicate_count`. This decision elegantly converts repetitive spam into highly valuable market intelligence, tracking exactly how widely and across which networks a specific asset is being broadcast.

---

## Data Access & Database Architecture

### 4. Clean Repository Pattern

#### The Decision
Enforce a rigid Repository Pattern across all 13 MongoDB collections, completely decoupling database queries from FastAPI routers, Pydantic transport schemas, and business service logic.

#### Why This Decision Exists
In complex Python backends, tightly coupling database drivers directly within route controllers or transport models introduces severe maintainability and lifecycle defects:
* **Import-Time Race Conditions:** Early instantiations of database connections during module import time frequently trigger fatal configuration exceptions if underlying network bridges or DNS SRV records are experiencing transient initialization delays.
* **Complex Testing Mocks:** Testing routing logic requires setting up heavy, complex database mocks across every unit test.
* **Leaky Abstractions:** Controllers become cluttered with raw MongoDB aggregation syntax, making future schema migrations highly error-prone.

The clean repository pattern guarantees that routers and services remain entirely agnostic of the underlying database engine. Repositories (`PropertyRepository`, `LeadRepository`, `SiteVisitRepository`) encapsulate all complex aggregation pipelines, return clean Python dictionaries, and utilize lazy database proxy initialization (`DatabaseProxy`) to completely eliminate import-time DNS timeouts.

---

### 5. Atomic MongoDB Updates

#### The Decision
Execute all multi-collection state transitions—specifically deal closure cascades across `site_visits`, `leads`, and `properties`—using strict MongoDB Atlas multi-document ACID transactions.

#### Why This Decision Exists
In an enterprise PropTech CRM, data consistency across independent operational tables is paramount. When a site visit successfully converts into a won commercial deal, the platform must execute three distinct state updates:
1. Mark the `site_visits` document as `status = COMPLETED` and `deal_closed = True`.
2. Update the parent `leads` profile to `status = CLOSED`.
3. Purge the matching asset from active search vectors by updating `properties` to `status = ARCHIVED` and `availability_status = ARCHIVED`.

If these updates were executed sequentially without an enclosing transaction, any transient network drop, database failover, or worker crash occurring mid-execution would leave the system in a severely corrupted partial state. A property might appear archived while its corresponding sales lead remains actively matched to new inventory. Utilizing MongoDB Atlas ACID transactional sessions guarantees that all three updates commit atomically or roll back entirely, ensuring pristine referential integrity across the monorepo.

---

### 6. Single Source of Truth

#### The Decision
Designate `apps/api/schemas/property_schema_v2.py` as the single canonical source of truth for property data structures, retiring legacy duplicated models (`shared/schemas/property.py`) and standardizing strict Pydantic Literal enforcement.

#### Why This Decision Exists
As systems evolve, maintaining duplicate schema files for a single underlying database table creates massive technical debt (`TD-002`). The platform historically maintained a legacy shared schema for manual CRUD operations alongside a V2 schema designed for advanced AI ingestion and matching aggregations. Over time, these files diverged in field type definitions (e.g., `carpet_area_sqft` drifting between `float` and `int`), resulting in runtime validation failures and high cognitive overhead for engineers.

Collapsing the architecture into a single source of truth eliminates the risk of silent serialization bugs. `property_schema_v2.py` establishes strict validation contracts, enforcing rigid Pydantic Literals for critical domain fields (`city`, `listing_type`, `status`, `availability_status`) across all network ingress, storage, and egress boundaries.

---

## Concurrency & Background Execution

### 7. Background Workers

#### The Decision
Offload all high-latency operations—including raw group dump chunking, deterministic parsing, LLM inference, webhook events, and scheduled inventory sweeps—to asynchronous Celery worker containers running over a Redis message broker.

#### Why This Decision Exists
FastAPI operates on an asynchronous event loop (`asyncio`). If heavy, CPU-intensive parsing or long-running local LLM HTTP POST calls (which take 30-90 seconds per chat dump) were executed directly within the API request lifecycle, the underlying ASGI thread pool would instantly stall. Incoming customer search queries and lead capture webhooks would experience severe queuing delays and network timeouts.

```
+-----------------------------------------------------------------------------------+
|                        FASTAPI / CELERY DECOUPLED CONCURRENCY                     |
|                                                                                   |
|    +----------------------+   202 Accepted (Instant)   +---------------------+    |
|    | Client / Scraper Hook| <------------------------- | FastAPI HTTP Server |    |
|    +----------+-----------+                            +----------+----------+    |
|               |                                                   |               |
|               | POST /properties/raw-chunk                        | Async Task    |
|               v                                                   v Dispatch      |
|    +----------+-----------+                            +----------+----------+    |
|    | webhook_events Table |                            |  Redis Message Queue|    |
|    +----------------------+                            +----------+----------+    |
|                                                                   |               |
|                                                                   v               |
|                                                        +----------+----------+    |
|                                                        | nph_worker Daemon   |    |
|                                                        | (Celery / PyMongo)  |    |
|                                                        +---------------------+    |
+-----------------------------------------------------------------------------------+
```

By decoupling heavy compute into a dedicated worker tier (`nph_worker`), the API layer executes an immediate idempotency check against `webhook_events`, returns a `202 Accepted` response in sub-millisecond time, and delegates the heavy processing to Celery. Furthermore, the worker tier is explicitly configured with `worker_prefetch_multiplier = 1` and `task_acks_late = True`, establishing an impenetrable safeguard against GPU VRAM exhaustion and worker crash data loss.

---

### 8. Inventory Freshness Sweeper

#### The Decision
Implement a highly specialized, scheduled Celery Beat engine (`sweep_inventory_freshness`) executing every five minutes to calculate asymmetric inventory decay and degrade property confidence scores with strict `zero-clamping`.

#### Why This Decision Exists
A fundamental failure in legacy PropTech architectures is treating all property inventory as possessing an identical operational lifespan. In active real estate markets, inventory displays an asymmetric velocity: high-demand rental apartments are leased within days, whereas commercial properties and outright sales remain active for months. A traditional blanket expiration cron job would either prematurely purge valid sales inventory or leave deeply stale rental inventory active, destroying user trust in the matching engine.

The platform establishes an advanced 5-state lifecycle (`NEW` -> `VERIFIED` -> `STALE` -> `UNVERIFIED` -> `ARCHIVED`) driven continuously by the asymmetric sweeper.

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

As properties age into `UNVERIFIED`, the sweeper deducts 10 points from their `confidence_score` per calculation pass. To maintain absolute mathematical stability within the matching engine's sorting algorithms, the update query enforces a rigid `zero-clamping` rule (`$set: {confidence_score: max(0, current_score - 10)}`), ensuring scores never decay into negative values.

---

## Data Governance & Normalization

### 9. Canonical Normalization

#### The Decision
Compute clean, normalized entities and resolve Knowledge Graph foreign keys (`builder_id`, `project_id`, `locality_id`) within the background Celery worker during ingestion, persisting them as flat fields on the property document rather than computing them dynamically at query time.

#### Why This Decision Exists
Real estate entities in raw messaging broadcasts exhibit extreme variation, frequent misspellings, and informal local shorthand (e.g., broadcasting `GangapurRd` instead of `Gangapur Road`, or `meadows by ashoka` instead of `Ashoka Meadows`). Performing string cleaning, alias dictionary lookups, and entity resolution dynamically during API search and matching aggregations would introduce massive CPU overhead, severely spiking read latency across every customer request.

```
+-----------------------------------------------------------------------------------+
|                        KNOWLEDGE GRAPH MULTIKEY RESOLUTION                        |
|                                                                                   |
|    Raw Alias String ("meadows by ashoka")                                         |
|                     |                                                             |
|                     v                                                             |
|    +----------------+------------------+                                          |
|    | Multikey Index Lookup (aliases[]) |                                          |
|    +----------------+------------------+                                          |
|                     |                                                             |
|       +-------------+-------------+                                               |
|       | (Alias Match Found)       | (Unknown Entity String)                       |
|       v                           v                                               |
|    +--+---------------+        +--+---------------+        +-------------------+  |
|    | Assign Canonical |        | Dynamically Create| ----> | Assign New Stable |  |
|    |   project_id     |        |  New KG Node     |        |    project_id     |  |
|    +------------------+        +------------------+        +-------------------+  |
+-----------------------------------------------------------------------------------+
```

By executing canonical normalization exactly once in the background worker during `normalise_extracted_property`, the platform achieves **zero read latency**. API search and matching routes query pre-computed, indexed flat foreign keys directly in MongoDB. Furthermore, if an unknown entity string is encountered during ingestion, the worker dynamically creates and inserts a new canonical Knowledge Graph node, allowing the platform's entity awareness to expand organically without requiring developer intervention or schema migrations.

---

### 10. Commission Shield

#### The Decision
Centralize all role-based field blinding within a standalone, pure-Python domain governance service (`services/property/commission_shield.py`) to systematically mask supplier contact identities and exact physical markers from unauthorized users.

#### Why This Decision Exists
In an advisory business model where monetization depends on collecting site visit fees and deal closure commissions, prematurely exposing a broker's phone number, building name, exact address, or Google Pin allows clients to bypass the platform and transact directly. Protecting these disintermediation vectors is an existential business requirement.

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

While basic field masking could be scattered across API controllers or Pydantic model validators, centralizing the logic within `shield_property(data, role)` achieves absolute separation of concerns. The shield acts as an impenetrable governance boundary that dynamically inspects the user's authorization tier (`PUBLIC`, `INTERNAL`, `ADMIN`). It can be exhaustively unit-tested in isolation without instantiating complex ASGI request lifecycles, ensuring flawless data governance before network transmission.

---

### 11. Raw Data Immutability

#### The Decision
Preserve the exact raw messaging text (`raw_text`), original uncleaned entity strings (`raw_locality`), and direct relational pointers (`raw_message_id`) alongside normalized canonical data within every property document.

#### Why This Decision Exists
In automated ingestion pipelines powered by regular expressions and LLMs, data extraction algorithms evolve over time. If the platform overwrote raw input strings with normalized outputs during database persistence, any historical bug in the parsing logic or AI enrichment layer would permanently corrupt the underlying data, making recovery impossible.

Preserving raw data immutability establishes a perfect operational audit trail. Maintaining `raw_locality` alongside `canonical_locality`, and embedding `raw_message_id` linking directly to the `raw_message_logs` collection, ensures absolute system transparency. If an extraction rule is updated or a new canonical entity matching model is deployed in the future, the platform can seamlessly replay historical raw message logs through the updated pipeline, regenerating perfectly clean databases without zero data loss.
