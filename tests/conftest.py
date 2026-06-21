# tests/conftest.py
"""
Central test configuration for NPH Platform.
Mocks the MongoDB database layer so tests run without external infrastructure.
"""
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set required environment variables before any app code imports
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017/nph_test")
os.environ.setdefault("JWT_SECRET", "test_secret_key_for_testing")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


class AwaitableValue:
    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _async_val():
            return self._value
        return _async_val().__await__()

    def __getattr__(self, name):
        return getattr(self._value, name)

    def __getitem__(self, key):
        if self._value is None:
            raise TypeError("'NoneType' object is not subscriptable")
        return self._value[key]

    def __setitem__(self, key, value):
        if self._value is None:
            raise TypeError("'NoneType' object does not support item assignment")
        self._value[key] = value

    def __contains__(self, item):
        if self._value is None:
            return False
        return item in self._value

    def __bool__(self):
        return bool(self._value)


# ---------------------------------------------------------------------------
# Mock MongoDB collection that behaves like motor's AsyncIOMotorCollection
# ---------------------------------------------------------------------------
class MockCollection:
    """An in-memory mock that mimics motor's async MongoDB collection."""

    def __init__(self):
        self._docs = []
        self._indexes = []

    def insert_one(self, doc):
        from bson import ObjectId
        if "_id" not in doc:
            doc["_id"] = ObjectId()
        self._docs.append(doc.copy())
        return AwaitableValue(MagicMock(inserted_id=doc["_id"]))

    def find_one(self, filter_query=None, projection=None):
        filter_query = filter_query or {}
        for doc in self._docs:
            if self._matches(doc, filter_query):
                result = doc.copy()
                if projection:
                    if isinstance(projection, dict):
                        # Handle projection
                        keys_to_remove = [k for k, v in projection.items() if v == 0]
                        for k in keys_to_remove:
                            result.pop(k, None)
                return AwaitableValue(result)
        return AwaitableValue(None)

    def find_one_and_update(self, filter_query, update, upsert=False, return_document=None):
        from bson import ObjectId
        for i, doc in enumerate(self._docs):
            if self._matches(doc, filter_query):
                self._apply_update(doc, update)
                return AwaitableValue(doc.copy())
        if upsert:
            new_doc = {"_id": ObjectId()}
            # Apply filter fields
            for k, v in filter_query.items():
                if not isinstance(v, dict):
                    new_doc[k] = v
            self._apply_update(new_doc, update)
            self._docs.append(new_doc)
            return AwaitableValue(new_doc.copy())
        return AwaitableValue(None)

    def update_one(self, filter_query, update, upsert=False):
        from bson import ObjectId
        for doc in self._docs:
            if self._matches(doc, filter_query):
                self._apply_update(doc, update)
                return AwaitableValue(MagicMock(modified_count=1))
        if upsert:
            new_doc = {"_id": ObjectId()}
            for k, v in filter_query.items():
                if not isinstance(v, dict):
                    new_doc[k] = v
            self._apply_update(new_doc, update)
            self._docs.append(new_doc)
            return AwaitableValue(MagicMock(modified_count=0, upserted_id=new_doc["_id"]))
        return AwaitableValue(MagicMock(modified_count=0))

    def delete_one(self, filter_query):
        for i, doc in enumerate(self._docs):
            if self._matches(doc, filter_query):
                self._docs.pop(i)
                return AwaitableValue(MagicMock(deleted_count=1))
        return AwaitableValue(MagicMock(deleted_count=0))

    def count_documents(self, filter_query=None):
        filter_query = filter_query or {}
        return AwaitableValue(sum(1 for doc in self._docs if self._matches(doc, filter_query)))

    def create_index(self, *args, **kwargs):
        self._indexes.append(args)
        return AwaitableValue(None)

    def find(self, filter_query=None, projection=None):
        """Returns a MockCursor that supports chaining."""
        filter_query = filter_query or {}
        matched = [doc.copy() for doc in self._docs if self._matches(doc, filter_query)]
        if projection:
            if isinstance(projection, dict):
                keys_to_remove = [k for k, v in projection.items() if v == 0]
                for doc in matched:
                    for k in keys_to_remove:
                        doc.pop(k, None)
        return MockCursor(matched)

    def _matches(self, doc, filter_query):
        """Simple filter matcher supporting basic queries."""
        for key, value in filter_query.items():
            # Handle dot-notation for nested fields
            doc_value = self._get_nested(doc, key)
            if isinstance(value, dict):
                for op, op_val in value.items():
                    if op == "$gte" and (doc_value is None or doc_value < op_val):
                        return False
                    elif op == "$lte" and (doc_value is None or doc_value > op_val):
                        return False
                    elif op == "$lt" and (doc_value is None or doc_value >= op_val):
                        return False
                    elif op == "$gt" and (doc_value is None or doc_value <= op_val):
                        return False
                    elif op == "$regex":
                        import re
                        flags = 0
                        if "$options" in value and "i" in value["$options"]:
                            flags = re.IGNORECASE
                        if doc_value is None or not re.search(op_val, str(doc_value), flags):
                            return False
                    elif op == "$in":
                        if doc_value not in op_val:
                            return False
            else:
                if doc_value != value:
                    return False
        return True

    def _get_nested(self, doc, key):
        """Resolves dot-notation keys like 'source.broker_name'."""
        parts = key.split(".")
        current = doc
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    def _apply_update(self, doc, update):
        """Applies MongoDB-style update operators."""
        if "$set" in update:
            for k, v in update["$set"].items():
                self._set_nested(doc, k, v)
        if "$setOnInsert" in update:
            for k, v in update["$setOnInsert"].items():
                if self._get_nested(doc, k) is None:
                    self._set_nested(doc, k, v)
        if "$inc" in update:
            for k, v in update["$inc"].items():
                current = self._get_nested(doc, k) or 0
                self._set_nested(doc, k, current + v)
        if "$push" in update:
            for k, v in update["$push"].items():
                current = self._get_nested(doc, k)
                if current is None:
                    self._set_nested(doc, k, [v])
                elif isinstance(current, list):
                    current.append(v)

    def _set_nested(self, doc, key, value):
        """Sets a value using dot-notation."""
        parts = key.split(".")
        current = doc
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value


class MockCursor:
    """Mimics an async motor cursor with chaining support."""

    def __init__(self, docs):
        self._docs = docs
        self._skip = 0
        self._limit = None

    def sort(self, key_or_list, direction=None):
        if isinstance(key_or_list, list):
            key, direction = key_or_list[0]
        else:
            key = key_or_list
        reverse = (direction == -1)
        try:
            self._docs.sort(key=lambda x: x.get(key), reverse=reverse)
        except TypeError:
            self._docs.sort(key=lambda x: str(x.get(key)), reverse=reverse)
        return self

    def skip(self, n):
        self._skip = n
        return self

    def limit(self, n):
        self._limit = n
        return self

    def __iter__(self):
        result = self._docs[self._skip:]
        if self._limit:
            result = result[:self._limit]
        return iter(result)

    async def to_list(self, length=None):
        result = self._docs[self._skip:]
        if self._limit:
            result = result[:self._limit]
        if length:
            result = result[:length]
        return result


# ---------------------------------------------------------------------------
# Mock Database Singleton
# ---------------------------------------------------------------------------
class MockDatabase:
    """Mimics the shared.utils.database.Database singleton."""

    def __init__(self):
        self._collections = {
            "nph_core.leads": MockCollection(),
            "nph_core.conversations": MockCollection(),
            "nph_core.matches": MockCollection(),
            "nph_core.webhook_events": MockCollection(),
            "nph_core.site_visits": MockCollection(),
            "nph_core.properties": MockCollection(),
            "nph_core.broker_profiles": MockCollection(),
        }
        self.admin = MagicMock()
        self.admin.command = AsyncMock(return_value={"ok": 1})

    def __getitem__(self, name):
        return self._get_db(name)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._get_db(name)

    def _get_db(self, db_name):
        """Returns a mock database namespace."""
        class MockDB:
            def __init__(self, parent, db_name):
                self._parent = parent
                self._db_name = db_name

            def __getitem__(self, col_name):
                return self._parent._get_collection(f"{self._db_name}.{col_name}")

            def __getattr__(self, col_name):
                if col_name.startswith("_"):
                    raise AttributeError(col_name)
                return self._parent._get_collection(f"{self._db_name}.{col_name}")

        return MockDB(self, db_name)

    def _get_collection(self, full_name):
        if full_name not in self._collections:
            self._collections[full_name] = MockCollection()
        return self._collections[full_name]

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def mock_db():
    """
    Directly swaps the shared database singleton's client so all repository code
    works against in-memory mock collections.
    """
    from shared.utils.database import db

    mock_client = MockDatabase()
    original_client = db.client
    db.client = mock_client
    yield db
    db.client = original_client


@pytest.fixture
def mock_redis():
    """Patches the Redis client used in system router."""
    mock_r = MagicMock()
    mock_r.ping.return_value = True
    with patch("apps.api.routers.system.redis_client", mock_r):
        yield mock_r


@pytest.fixture
def auth_token():
    """Creates a valid JWT token for authenticated endpoints."""
    from shared.utils.security import create_access_token
    return create_access_token(data={
        "sub": "test_user_id_123",
        "email": "test@nph.com",
        "role": "admin"
    })


@pytest.fixture
def api_client():
    """Creates a FastAPI TestClient with the lifespan disabled."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    # Build a test app without lifespan (no real DB connection)
    from apps.api.routes.auth import router as auth_router
    from apps.api.routes.property import router as property_router
    from apps.api.routers.system import router as system_router
    from apps.api.routers.lead import router as lead_router
    from apps.api.routers.conversation import router as conversation_router
    from apps.api.routes.match import router as match_router
    from apps.api.routes.analytics import router as analytics_router
    from apps.api.routes.webhooks import router as webhook_router
    from apps.api.routers import inventory
    from apps.api.routers import search
    from apps.api.routes.site_visit import router as site_visits_router

    test_app = FastAPI(title="NPH Test")
    test_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"])

    test_app.include_router(auth_router)
    test_app.include_router(property_router)
    test_app.include_router(system_router)
    test_app.include_router(lead_router)
    test_app.include_router(conversation_router)
    test_app.include_router(match_router)
    test_app.include_router(analytics_router)
    test_app.include_router(webhook_router)
    test_app.include_router(inventory.router)
    test_app.include_router(search.router)
    test_app.include_router(site_visits_router)

    @test_app.get("/")
    async def root():
        return {"message": "NPH Operating System Backend Platform Running"}

    client = TestClient(test_app)
    return client
