# Technology Stack

---

## Technology Matrix & Architectural Rationale

The NPH Property Intelligence Platform is constructed from a curated stack of robust, enterprise-grade technologies. Each component has been selected to ensure optimal system performance, clean architectural boundaries, and high operational resiliency.

| Technology | Purpose | Reason for Choosing It | Alternatives Considered | Examples in Codebase |
|---|---|---|---|---|
| **FastAPI** | Primary HTTP API Framework | Provides top-tier ASGI performance, native asynchronous request handling (`async/await`), automatic OpenAPI documentation generation, and strict type safety via Pydantic. | **Django DRF:** Rejected due to heavy synchronous overhead and lack of native async support.<br>**Flask:** Rejected due to lack of built-in validation and manual API documentation overhead. | `apps/api/main.py`<br>`apps/api/routers/property.py`<br>`apps/api/routers/match.py` |
| **Celery** | Asynchronous Task Queue & Scheduled Beat Engine | Decouples heavy AI extraction, webhook processing, and periodic maintenance sweeps from the API event loop. Features advanced fault-tolerant execution (`task_acks_late`). | **RQ (Redis Queue):** Rejected due to lack of built-in advanced scheduling (`Celery Beat`) and limited sub-task workflow capabilities.<br>**ARQ:** Rejected due to strict requirement for async worker loops. | `apps/worker/main.py`<br>`apps/worker/tasks/ingestion_tasks.py`<br>`apps/worker/tasks/maintenance_tasks.py` |
| **Redis** | In-Memory Message Broker & Result Backend | Provides high-throughput, sub-millisecond task queuing and transient result storage for Celery workers. Easily containerized and horizontally scalable. | **RabbitMQ:** Rejected as unnecessary architectural overhead; Redis perfectly handles the required task throughput while doubling as a potential caching tier.<br>**Amazon SQS:** Rejected to maintain localized cloud-independent execution. | `apps/worker/main.py`<br>`docker-compose.yml` (`redis` service) |
| **MongoDB Atlas** | Primary Document Database & Transaction Engine | Flexible document schema perfectly maps to highly irregular, polymorphic real estate data. Supports strict multi-document ACID transactions across dedicated replica sets. | **PostgreSQL:** Rejected due to severe relational friction when modeling highly variable, dynamic property attributes and nested Knowledge Graph entities.<br>**DynamoDB:** Rejected due to lack of flexible aggregation pipelines. | `shared/utils/database.py`<br>`apps/api/repositories/property_repository.py` |
| **Motor** | Asynchronous MongoDB Driver (API Tier) | Integrates flawlessly with FastAPI's `asyncio` event loop. Ensures that long-running database aggregations and complex matching queries never block the HTTP thread pool. | **PyMongo (in API):** Rejected because synchronous database drivers would block FastAPI's asynchronous event loop, destroying concurrent API throughput. | `shared/utils/database.py`<br>`apps/api/main.py` (`connect_to_mongo`) |
| **PyMongo** | Synchronous MongoDB Driver (Worker Tier) | Provides direct, predictable, thread-safe database communication within Celery's synchronous pre-fork execution pool. | **Motor (in Worker):** Rejected because spinning up one-off `asyncio` event loops inside synchronous Celery worker threads introduces severe execution overhead and brittleness. | `apps/worker/tasks/ingestion_tasks.py`<br>`apps/worker/tasks/maintenance_tasks.py` |
| **Docker & Compose** | Container Orchestration & Service Isolation | Ensures clean environmental isolation across API, worker, scraper, and caching tiers. Standardizes internal networking and enables repeatable production deployments. | **Podman:** Rejected due to lower industry standardization for local developer orchestration.<br>**Bare Metal / Virtualenv:** Rejected due to extreme vulnerability to environmental drift and dependency conflicts. | `docker-compose.yml`<br>`infrastructure/Dockerfile` |
| **Ollama** | Localized LLM Inference Server | Container-adjacent AI serving engine. Secures proprietary broker data by keeping all inference local and entirely eliminates recurring per-token cloud AI expenses. | **vLLM / TensorRT-LLM:** Rejected due to heavier infrastructure requirements and higher complexity when serving smaller models on host hardware. | `apps/worker/tasks/ingestion_tasks.py` (`OLLAMA_BASE_URL`) |
| **Llama 3.2** | Core Extraction Large Language Model | Provides state-of-the-art natural language understanding and structured JSON calling capabilities within a highly compact, GPU-efficient parameter footprint. | **GPT-4o / Claude 3.5 Sonnet:** Rejected due to absolute operational requirement to keep confidential broker supply data private and avoid recurring token costs.<br>**Mistral 7B:** Rejected in favor of Llama 3.2's superior structured JSON adherence. | `apps/worker/tasks/ingestion_tasks.py` (`OLLAMA_MODEL`) |
| **Pydantic** | Data Serialization & Runtime Validation | Enforces rigid runtime validation guardrails, complex type transformations, and clear serializations across all network ingress and egress boundaries. | **Marshmallow / Cerberus:** Rejected due to slower runtime validation speeds and lack of native integration with FastAPI. | `apps/api/schemas/property_schema_v2.py`<br>`shared/schemas/user.py`<br>`apps/api/schemas/knowledge_graph_schemas.py` |
| **pytest** | Automated Testing Harness | Industry-standard test execution framework. Paired with `pytest-asyncio` to execute complex asynchronous contract and integration tests across core pipelines. | **Unittest:** Rejected due to verbose boilerplate requirements and lack of advanced fixture dependency injection capabilities. | `tests/test_knowledge_graph.py`<br>`tests/test_sprint_g_extraction.py`<br>`tests/test_deterministic_ingestion.py` |
| **GitHub Actions** | Continuous Integration & Automation (Planned) | Automates test suite execution, container image builds, and structural validation checks upon every code commit. | **Jenkins / GitLab CI:** Rejected in favor of GitHub Actions' seamless integration with public repository infrastructure and zero-maintenance runners. | Planned for future production infrastructure tier |

---

## Architectural Dependency Wiring

```
+-----------------------------------------------------------------------------------+
|                                  FASTAPI API TIER                                 |
|                                                                                   |
|    +------------------------+                          +---------------------+    |
|    |      Pydantic 2.6      | <--- Validation -------- |    FastAPI 0.110    |    |
|    +------------------------+                          +----------+----------+    |
|                                                                   |               |
|    +------------------------+                                     |               |
|    |      Motor 3.3.2       | <--- Async I/O (asyncio) -----------+               |
|    +-----------+------------+                                                     |
+----------------|------------------------------------------------------------------+
                 |
                 v
+----------------+------------------------------------------------------------------+
|                                MONGODB ATLAS CLUSTER                              |
|    (Dedicated Document Store | Multi-Document ACID Transactions | Replica Set)    |
+----------------+------------------------------------------------------------------+
                 ^
                 |
+----------------|------------------------------------------------------------------+
|    +-----------+------------+                                                     |
|    |      PyMongo 3.11      | <--- Sync I/O (Thread Pool) --------+               |
|    +------------------------+                                     |               |
|                                                                   |               |
|    +------------------------+                          +----------+----------+    |
|    |       Ollama LLM       | <--- Local HTTP POST --- |    Celery 5.3.6     |    |
|    |      (Llama 3.2)       |                          +----------+----------+    |
|    +------------------------+                                     |               |
|                                                                   |               |
|    +------------------------+                                     |               |
|    |       Redis 7.0        | <--- Message Queue & Backend -------+               |
|    +------------------------+                                                     |
|                                                                                   |
|                                CELERY WORKER TIER                                 |
+-----------------------------------------------------------------------------------+
```

---

## Key Framework Optimizations

### 1. Pydantic Validator Enforcement
The platform heavily utilizes Pydantic `model_validator` constructs across `PropertyPublicResponse` and `PropertyInternalResponse`. Rather than scattering validation logic across controllers, Pydantic acts as an impenetrable serialization shield. It ensures that missing fields are systematically normalized and strict ID alignment contracts are maintained before data ever exits the API boundary.

### 2. Pytest Asynchronous Integration (`asyncio_mode=auto`)
Because the API layer operates entirely on an `asyncio` event loop with asynchronous Motor repository calls, the automated test harness configures `pytest.ini` with `asyncio_mode=auto`. This permits test suites (`test_knowledge_graph.py`, `test_deterministic_ingestion.py`) to execute complex asynchronous setup fixtures, database calls, and route invocations natively without manual event loop management.

### 3. Celery Late Acknowledgments & Prefetch Limits
The background worker framework is explicitly tuned for the intense resource demands of local AI engineering:
* `task_acks_late = True`: Guarantees zero data loss by withholding task acknowledgment until full MongoDB persistence completes.
* `worker_prefetch_multiplier = 1`: Prevents memory starvation and GPU VRAM exhaustion by forcing sequential, single-task execution across worker threads.
