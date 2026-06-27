# tests/test_ingestion_pipeline.py
"""
Unit and integration tests for the Week 1 / P0 Mass Text Ingestion Pipeline.

Coverage:
  - POST /properties/raw-chunk API route (202 Accepted, idempotency)
  - split_into_message_blocks() and chunk_blocks() helpers
  - compute_ingestion_hash() SHA-256 deduplication
  - Property repository: find_by_ingestion_hash
  - Webhook event repository: insert_or_ignore_by_hash
  - Full task loop: multi-listing extraction, deduplication rejection
"""
import pytest
import hashlib
import re
from unittest.mock import patch, MagicMock, AsyncMock


# ============================================================================
# Section 1: Helper Function Unit Tests
# ============================================================================

class TestSplitIntoMessageBlocks:
    """Tests for the apps/worker/tasks/ingestion_tasks.split_into_message_blocks helper."""

    def _import(self):
        from apps.worker.tasks.ingestion_tasks import split_into_message_blocks
        return split_into_message_blocks

    def test_single_block_no_blank_lines(self):
        fn = self._import()
        raw = "2BHK available in Indira Nagar\nRent 12k pm\nCall 9876543210"
        blocks = fn(raw)
        assert len(blocks) == 1
        assert "2BHK" in blocks[0]

    def test_two_blocks_separated_by_blank_line(self):
        fn = self._import()
        raw = "2BHK Indira Nagar 12k\n\n3BHK College Road 22k call 9988776655"
        blocks = fn(raw)
        assert len(blocks) == 2
        assert "2BHK" in blocks[0]
        assert "3BHK" in blocks[1]

    def test_multiple_blank_lines_treated_as_single_separator(self):
        fn = self._import()
        raw = "Block A\n\n\n\nBlock B\n\n\nBlock C"
        blocks = fn(raw)
        assert len(blocks) == 3

    def test_windows_crlf_normalisation(self):
        fn = self._import()
        raw = "Block A\r\n\r\nBlock B"
        blocks = fn(raw)
        assert len(blocks) == 2

    def test_empty_string_returns_empty_list(self):
        fn = self._import()
        assert fn("") == []

    def test_whitespace_only_string_returns_empty_list(self):
        fn = self._import()
        assert fn("   \n   \n   ") == []

    def test_trailing_newlines_do_not_create_extra_block(self):
        fn = self._import()
        raw = "Single block\n\n\n"
        blocks = fn(raw)
        assert len(blocks) == 1

    def test_five_blocks_below_chunk_threshold(self):
        fn = self._import()
        raw = "\n\n".join([f"Message {i}" for i in range(5)])
        blocks = fn(raw)
        assert len(blocks) == 5

    def test_six_blocks_exceeds_chunk_threshold(self):
        fn = self._import()
        raw = "\n\n".join([f"Message {i}" for i in range(6)])
        blocks = fn(raw)
        assert len(blocks) == 6


class TestChunkBlocks:
    """Tests for the chunk_blocks() grouping helper."""

    def _import(self):
        from apps.worker.tasks.ingestion_tasks import chunk_blocks
        return chunk_blocks

    def test_exactly_five_blocks_produces_one_chunk(self):
        fn = self._import()
        blocks = [f"Block {i}" for i in range(5)]
        chunks = fn(blocks, chunk_size=5)
        assert len(chunks) == 1
        assert len(chunks[0]) == 5

    def test_six_blocks_produces_two_chunks(self):
        fn = self._import()
        blocks = [f"Block {i}" for i in range(6)]
        chunks = fn(blocks, chunk_size=5)
        assert len(chunks) == 2
        assert len(chunks[0]) == 5
        assert len(chunks[1]) == 1

    def test_ten_blocks_produces_two_chunks_of_five(self):
        fn = self._import()
        blocks = [f"Block {i}" for i in range(10)]
        chunks = fn(blocks, chunk_size=5)
        assert len(chunks) == 2
        assert all(len(c) == 5 for c in chunks)

    def test_eleven_blocks_produces_three_chunks(self):
        fn = self._import()
        blocks = [f"Block {i}" for i in range(11)]
        chunks = fn(blocks, chunk_size=5)
        assert len(chunks) == 3
        assert len(chunks[2]) == 1

    def test_empty_block_list(self):
        fn = self._import()
        assert fn([], chunk_size=5) == []

    def test_chunk_size_one(self):
        fn = self._import()
        blocks = ["A", "B", "C"]
        chunks = fn(blocks, chunk_size=1)
        assert len(chunks) == 3
        assert all(len(c) == 1 for c in chunks)


# ============================================================================
# Section 2: SHA-256 Ingestion Hash Tests
# ============================================================================

class TestComputeIngestionHash:
    """Tests for compute_ingestion_hash() deduplication logic."""

    def _import(self):
        from apps.worker.tasks.ingestion_tasks import compute_ingestion_hash
        return compute_ingestion_hash

    def test_hash_is_64_char_hex_string(self):
        fn = self._import()
        h = fn(price=12000, area="Indira Nagar", bhk=2, listing_type="rent", broker_phone="9876543210")
        assert isinstance(h, str)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_identical_inputs_produce_identical_hash(self):
        fn = self._import()
        h1 = fn(price=12000, area="Indira Nagar", bhk=2, listing_type="rent", broker_phone="9876543210")
        h2 = fn(price=12000, area="Indira Nagar", bhk=2, listing_type="rent", broker_phone="9876543210")
        assert h1 == h2

    def test_different_price_produces_different_hash(self):
        fn = self._import()
        h1 = fn(price=12000, area="Indira Nagar", bhk=2, listing_type="rent", broker_phone="9876543210")
        h2 = fn(price=15000, area="Indira Nagar", bhk=2, listing_type="rent", broker_phone="9876543210")
        assert h1 != h2

    def test_different_phone_produces_different_hash(self):
        fn = self._import()
        h1 = fn(price=12000, area="Indira Nagar", bhk=2, listing_type="rent", broker_phone="9876543210")
        h2 = fn(price=12000, area="Indira Nagar", bhk=2, listing_type="rent", broker_phone="9999999999")
        assert h1 != h2

    def test_null_phone_handled_gracefully(self):
        fn = self._import()
        h = fn(price=12000, area="Indira Nagar", bhk=2, listing_type="rent", broker_phone=None)
        assert len(h) == 64

    def test_null_phone_and_empty_string_phone_produce_same_hash(self):
        fn = self._import()
        h1 = fn(price=12000, area="Test Area", bhk=2, listing_type="rent", broker_phone=None)
        h2 = fn(price=12000, area="Test Area", bhk=2, listing_type="rent", broker_phone="")
        assert h1 == h2

    def test_punctuation_stripped_from_area(self):
        """'Indira Nagar' and 'Indira-Nagar' should produce the same hash."""
        fn = self._import()
        h1 = fn(price=12000, area="Indira Nagar", bhk=2, listing_type="rent", broker_phone="9876543210")
        h2 = fn(price=12000, area="Indira-Nagar", bhk=2, listing_type="rent", broker_phone="9876543210")
        assert h1 == h2

    def test_price_as_string_coerced_correctly(self):
        fn = self._import()
        h1 = fn(price=12000, area="Test", bhk=2, listing_type="rent", broker_phone="9876543210")
        h2 = fn(price="12000", area="Test", bhk=2, listing_type="rent", broker_phone="9876543210")
        assert h1 == h2

    def test_different_bhk_produces_different_hash(self):
        fn = self._import()
        h1 = fn(price=12000, area="Test", bhk=2, listing_type="rent", broker_phone="9876543210")
        h2 = fn(price=12000, area="Test", bhk=3, listing_type="rent", broker_phone="9876543210")
        assert h1 != h2


# ============================================================================
# Section 3: Property Repository Tests — find_by_ingestion_hash
# ============================================================================

class TestPropertyRepositoryIngestionHash:
    """Tests for property_repo.find_by_ingestion_hash()."""

    @pytest.mark.asyncio
    async def test_find_by_ingestion_hash_returns_none_when_no_match(self, mock_db):
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        result = await repo.find_by_ingestion_hash("nonexistent_hash_abc123")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_ingestion_hash_returns_matching_active_property(self, mock_db):
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        test_hash = "a" * 64  # Synthetic valid-looking SHA-256 hash
        await repo.create({
            "property_id": "prop_hash_test1",
            "title": "2 BHK in Indira Nagar",
            "city": "Nashik",
            "area": "Indira Nagar",
            "price": 12000,
            "bhk": 2,
            "status": "ACTIVE",
            "ingestion_hash": test_hash,
        })
        result = await repo.find_by_ingestion_hash(test_hash)
        assert result is not None
        assert result["ingestion_hash"] == test_hash
        assert result["status"] == "ACTIVE"

    @pytest.mark.asyncio
    async def test_find_by_ingestion_hash_ignores_archived_property(self, mock_db):
        """Archived properties with the same hash should NOT block new insertions."""
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        test_hash = "b" * 64
        await repo.create({
            "property_id": "prop_archived1",
            "title": "Archived Property",
            "city": "Nashik",
            "area": "Test",
            "price": 10000,
            "bhk": 2,
            "status": "ARCHIVED",
            "ingestion_hash": test_hash,
        })
        result = await repo.find_by_ingestion_hash(test_hash)
        # Should return None because the only matching doc is ARCHIVED
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_property_initialises_ingestion_hash_field(self, mock_db):
        """upsert_property() must set ingestion_hash=None when not provided."""
        from apps.api.repositories.property_repository import PropertyRepository
        from datetime import datetime, timezone
        repo = PropertyRepository()
        col = repo.get_collection()
        prop_data = {
            "title": "Test Property",
            "city": "Nashik",
            "area": "Test Area",
            "price": 10000,
            "bhk": 2,
            "listing_type": "rent",
            "broker_phone": "9876543210",
        }
        result = await repo.upsert_property(col, prop_data)
        assert result is not None
        # ingestion_hash must be initialised (to None) when not provided
        assert "ingestion_hash" in result

    @pytest.mark.asyncio
    async def test_upsert_property_preserves_provided_ingestion_hash(self, mock_db):
        """upsert_property() must not overwrite an explicitly provided ingestion_hash."""
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        col = repo.get_collection()
        custom_hash = "c" * 64
        prop_data = {
            "title": "Hashed Property",
            "city": "Nashik",
            "area": "Test Area",
            "price": 12000,
            "bhk": 2,
            "listing_type": "rent",
            "broker_phone": "9876543210",
            "ingestion_hash": custom_hash,
        }
        result = await repo.upsert_property(col, prop_data)
        assert result is not None
        assert result["ingestion_hash"] == custom_hash


# ============================================================================
# Section 4: Webhook Event Repository — insert_or_ignore_by_hash
# ============================================================================

class TestWebhookEventRepositoryIdempotency:
    """Tests for webhook_event_repo.insert_or_ignore_by_hash()."""

    @pytest.mark.asyncio
    async def test_first_insert_returns_new_event_not_duplicate(self, mock_db):
        from apps.api.repositories.webhook_event_repository import WebhookEventRepository
        repo = WebhookEventRepository()
        event = await repo.insert_or_ignore_by_hash(
            event_hash="unique_hash_001",
            source_group="Test Group",
            raw_text_preview="2BHK available"
        )
        assert event["duplicate"] is False
        assert event["event_id"].startswith("evt_raw_")
        assert event["event_hash"] == "unique_hash_001"
        assert event["source_group"] == "Test Group"
        assert event["processing_status"] == "pending"

    @pytest.mark.asyncio
    async def test_second_insert_same_hash_returns_duplicate_flag(self, mock_db):
        from apps.api.repositories.webhook_event_repository import WebhookEventRepository
        repo = WebhookEventRepository()
        # First insert
        first = await repo.insert_or_ignore_by_hash(
            event_hash="duplicate_hash_999",
            source_group="Group A",
            raw_text_preview="Some property text"
        )
        # Second insert with same hash
        second = await repo.insert_or_ignore_by_hash(
            event_hash="duplicate_hash_999",
            source_group="Group A",
            raw_text_preview="Same property text (resent)"
        )
        assert first["duplicate"] is False
        assert second["duplicate"] is True
        assert second["event_id"] == first["event_id"]

    @pytest.mark.asyncio
    async def test_different_hashes_both_inserted_successfully(self, mock_db):
        from apps.api.repositories.webhook_event_repository import WebhookEventRepository
        repo = WebhookEventRepository()
        e1 = await repo.insert_or_ignore_by_hash("hash_aaa", "Group X", "text A")
        e2 = await repo.insert_or_ignore_by_hash("hash_bbb", "Group Y", "text B")
        assert e1["duplicate"] is False
        assert e2["duplicate"] is False
        assert e1["event_id"] != e2["event_id"]


# ============================================================================
# Section 5: API Route Integration Tests — POST /properties/raw-chunk
# ============================================================================

class TestRawChunkRoute:
    """Integration tests for POST /properties/raw-chunk endpoint."""

    def _valid_payload(self, text=None, group=None):
        return {
            "source_group": group or "Nashik Brokers VIP - Group 4",
            "raw_text": text or (
                "2BHK in Indira Nagar available for rent\n"
                "12,000 pm semi furnished\n"
                "Call Rahul: 9876543210\n\n"
                "3BHK College Road\n"
                "25k pm fully furnished parking\n"
                "Contact Suresh 9988776655"
            )
        }

    @patch("apps.api.routers.property.webhook_event_repo")
    def test_raw_chunk_returns_202_accepted(self, mock_repo, api_client):
        """A valid raw chunk payload must always return 202 Accepted immediately."""
        mock_event = {
            "event_id": "evt_raw_abc123",
            "event_hash": "x" * 64,
            "duplicate": False,
            "processing_status": "pending"
        }
        mock_repo.insert_or_ignore_by_hash = AsyncMock(return_value=mock_event)

        with patch("apps.api.routers.property.Celery") as mock_celery_cls:
            mock_celery_instance = MagicMock()
            mock_celery_cls.return_value = mock_celery_instance
            mock_task = MagicMock()
            mock_task.id = "task_id_xyz789"
            mock_celery_instance.send_task.return_value = mock_task

            response = api_client.post("/properties/raw-chunk", json=self._valid_payload())

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["event_id"] == "evt_raw_abc123"
        assert data["task_id"] == "task_id_xyz789"
        assert "accepted" in data["message"].lower()

    @patch("apps.api.routers.property.webhook_event_repo")
    def test_raw_chunk_duplicate_payload_returns_202_with_duplicate_status(
        self, mock_repo, api_client
    ):
        """A duplicate payload (same hash already exists) must return 202 with
        status='duplicate_skipped' — not 400 or 409 — to keep callers happy."""
        mock_event = {
            "event_id": "evt_raw_existing",
            "event_hash": "y" * 64,
            "duplicate": True,
            "processing_status": "pending"
        }
        mock_repo.insert_or_ignore_by_hash = AsyncMock(return_value=mock_event)

        response = api_client.post("/properties/raw-chunk", json=self._valid_payload())

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "duplicate_skipped"
        assert data["event_id"] == "evt_raw_existing"
        assert "duplicate" in data["message"].lower()

    def test_raw_chunk_missing_source_group_returns_422(self, api_client):
        """Omitting source_group must trigger request validation error."""
        response = api_client.post("/properties/raw-chunk", json={
            "raw_text": "Some property text here"
        })
        assert response.status_code == 422

    def test_raw_chunk_missing_raw_text_returns_422(self, api_client):
        """Omitting raw_text must trigger request validation error."""
        response = api_client.post("/properties/raw-chunk", json={
            "source_group": "Some Group"
        })
        assert response.status_code == 422

    def test_raw_chunk_too_short_raw_text_returns_422(self, api_client):
        """raw_text shorter than min_length=10 must be rejected by Pydantic."""
        response = api_client.post("/properties/raw-chunk", json={
            "source_group": "Group Name",
            "raw_text": "short"   # 5 chars, below min_length=10
        })
        assert response.status_code == 422

    def test_raw_chunk_empty_body_returns_422(self, api_client):
        """An empty JSON body must return 422 Unprocessable Entity."""
        response = api_client.post("/properties/raw-chunk", json={})
        assert response.status_code == 422

    @patch("apps.api.routers.property.webhook_event_repo")
    def test_celery_dispatch_failure_still_returns_202(self, mock_repo, api_client):
        """Even if Celery dispatch raises an exception, the API must return 202
        (the event is persisted; it can be replayed later)."""
        mock_event = {
            "event_id": "evt_raw_celery_fail",
            "event_hash": "z" * 64,
            "duplicate": False,
            "processing_status": "pending"
        }
        mock_repo.insert_or_ignore_by_hash = AsyncMock(return_value=mock_event)

        with patch("apps.api.routers.property.Celery") as mock_celery_cls:
            # Simulate a Redis connection failure at dispatch time
            mock_celery_cls.return_value.send_task.side_effect = ConnectionError("Redis unavailable")

            response = api_client.post("/properties/raw-chunk", json=self._valid_payload())

        assert response.status_code == 202
        data = response.json()
        # Task ID falls back to "dispatch_failed" sentinel
        assert data["task_id"] == "dispatch_failed"
        assert data["event_id"] == "evt_raw_celery_fail"


# ============================================================================
# Section 6: Full Task Loop Tests — process_raw_group_dump
# ============================================================================

class TestProcessRawGroupDumpTask:
    """
    Tests for the process_raw_group_dump Celery task execution loop.

    Uses patched Ollama and PyMongo to run the full task logic without
    any external infrastructure. The mock_db fixture is NOT used here
    because the task uses synchronous PyMongo, not async motor.
    """

    def _make_mock_collection(self):
        """Returns a minimal synchronous mock for a PyMongo collection."""
        col = MagicMock()
        col.find_one.return_value = None  # No dedup hits by default
        col.insert_one.return_value = MagicMock(inserted_id="fake_oid")
        col.update_one.return_value = MagicMock(modified_count=1)
        return col

    def _run_task(self, source_group, raw_text, extracted_properties, event_id="evt_test"):
        """
        Helper that patches Ollama and PyMongo then runs the task synchronously.

        Returns the task result dict.
        """
        from apps.worker.tasks.ingestion_tasks import process_raw_group_dump

        mock_properties_col = self._make_mock_collection()
        mock_broker_col = self._make_mock_collection()
        mock_events_col = self._make_mock_collection()

        mock_db_obj = MagicMock()
        mock_db_obj.__getitem__.side_effect = lambda name: {
            "properties": mock_properties_col,
            "broker_profiles": mock_broker_col,
            "webhook_events": mock_events_col,
        }.get(name, MagicMock())

        mock_client = MagicMock()
        mock_client.__getitem__.return_value = mock_db_obj
        mock_client.__enter__ = lambda s: s
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch(
            "apps.worker.tasks.ingestion_tasks.call_ollama_extract",
            return_value=extracted_properties
        ) as mock_ollama, \
        patch(
            "apps.worker.tasks.ingestion_tasks.MongoClient",
            return_value=mock_client
        ):
            # Use celery's .apply() for synchronous in-process execution
            # which bypasses the broker and runs the task body directly
            result = process_raw_group_dump.apply(
                kwargs={
                    "source_group": source_group,
                    "raw_text": raw_text,
                    "event_id": event_id
                }
            ).get()

        return result, mock_properties_col, mock_broker_col, mock_ollama

    def test_single_listing_is_inserted(self):
        """A single valid property extracted by Ollama must be inserted into the collection."""
        extracted = [{
            "title": "2 BHK Indira Nagar",
            "description": "Nice flat",
            "property_type": "apartment",
            "listing_type": "rent",
            "city": "Nashik",
            "area": "Indira Nagar",
            "bhk": 2,
            "price": 12000,
            "broker_phone": "9876543210"
        }]
        result, props_col, broker_col, _ = self._run_task(
            source_group="Nashik Brokers",
            raw_text="2 BHK Indira Nagar\nRent 12k\n9876543210",
            extracted_properties=extracted
        )
        assert result["inserted"] == 1
        assert result["deduplicated"] == 0
        assert result["total_extracted"] == 1
        props_col.insert_one.assert_called_once()

    def test_multi_listing_payload_all_inserted_when_no_duplicates(self):
        """All properties in a multi-listing extraction must be inserted when none are duplicates."""
        extracted = [
            {
                "title": "2 BHK Indira Nagar",
                "property_type": "apartment",
                "listing_type": "rent",
                "city": "Nashik",
                "area": "Indira Nagar",
                "bhk": 2,
                "price": 12000,
                "broker_phone": "9876543210"
            },
            {
                "title": "3 BHK College Road",
                "property_type": "flat",
                "listing_type": "rent",
                "city": "Nashik",
                "area": "College Road",
                "bhk": 3,
                "price": 25000,
                "broker_phone": "9988776655"
            },
            {
                "title": "1 RK Nashik Road",
                "property_type": "apartment",
                "listing_type": "rent",
                "city": "Nashik",
                "area": "Nashik Road",
                "bhk": 1,
                "price": 6000,
                "broker_phone": "9871111111"
            }
        ]
        result, props_col, _, _ = self._run_task(
            source_group="Nashik Premium Group",
            raw_text="\n\n".join([
                "2 BHK Indira Nagar 12k 9876543210",
                "3 BHK College Road 25k 9988776655",
                "1 RK Nashik Road 6k 9871111111"
            ]),
            extracted_properties=extracted
        )
        assert result["total_extracted"] == 3
        assert result["inserted"] == 3
        assert result["deduplicated"] == 0
        assert props_col.insert_one.call_count == 3

    def test_duplicate_hash_gets_caught_and_rejected(self):
        """A property whose ingestion_hash matches an existing ACTIVE property must be skipped."""
        from apps.worker.tasks.ingestion_tasks import compute_ingestion_hash
        extracted = [{
            "title": "2 BHK Indira Nagar",
            "property_type": "apartment",
            "listing_type": "rent",
            "city": "Nashik",
            "area": "Indira Nagar",
            "bhk": 2,
            "price": 12000,
            "broker_phone": "9876543210"
        }]

        # Pre-compute the exact hash that the task will generate for this property
        expected_hash = compute_ingestion_hash(
            price=12000, area="Indira Nagar", bhk=2,
            listing_type="rent", broker_phone="9876543210"
        )

        mock_props_col = self._make_mock_collection()
        mock_broker_col = self._make_mock_collection()
        mock_events_col = self._make_mock_collection()

        # Simulate an existing ACTIVE document with this hash
        mock_props_col.find_one.return_value = {
            "_id": "existing_oid",
            "property_id": "prop_existing",
            "ingestion_hash": expected_hash,
            "status": "ACTIVE"
        }

        mock_db_obj = MagicMock()
        mock_db_obj.__getitem__.side_effect = lambda name: {
            "properties": mock_props_col,
            "broker_profiles": mock_broker_col,
            "webhook_events": mock_events_col,
        }.get(name, MagicMock())
        mock_client = MagicMock()
        mock_client.__getitem__.return_value = mock_db_obj

        from apps.worker.tasks.ingestion_tasks import process_raw_group_dump, compute_ingestion_hash

        # Pre-compute the exact hash that the task will generate for this property
        expected_hash = compute_ingestion_hash(
            price=12000, area="Indira Nagar", bhk=2,
            listing_type="rent", broker_phone="9876543210"
        )

        mock_props_col = self._make_mock_collection()
        mock_broker_col = self._make_mock_collection()
        mock_events_col = self._make_mock_collection()

        # Simulate an existing ACTIVE document with this hash
        mock_props_col.find_one.return_value = {
            "_id": "existing_oid",
            "property_id": "prop_existing",
            "ingestion_hash": expected_hash,
            "status": "ACTIVE"
        }

        mock_db_obj = MagicMock()
        mock_db_obj.__getitem__.side_effect = lambda name: {
            "properties": mock_props_col,
            "broker_profiles": mock_broker_col,
            "webhook_events": mock_events_col,
        }.get(name, MagicMock())
        mock_client = MagicMock()
        mock_client.__getitem__.return_value = mock_db_obj

        with patch(
            "apps.worker.tasks.ingestion_tasks.call_ollama_extract",
            return_value=extracted
        ), patch(
            "apps.worker.tasks.ingestion_tasks.MongoClient",
            return_value=mock_client
        ):
            result = process_raw_group_dump.apply(
                kwargs={
                    "source_group": "Test Group",
                    "raw_text": "2 BHK Indira Nagar 12k 9876543210",
                    "event_id": "evt_dup_test"
                }
            ).get()

        assert result["deduplicated"] == 1
        assert result["inserted"] == 0
        # insert_one must NOT have been called for the duplicate
        mock_props_col.insert_one.assert_not_called()

    def test_partial_dedup_mixed_batch(self):
        """In a batch of 3 properties, if 1 is a dup, only 2 must be inserted."""
        from apps.worker.tasks.ingestion_tasks import compute_ingestion_hash
        extracted = [
            {
                "title": "2 BHK Indira Nagar",
                "property_type": "apartment",
                "listing_type": "rent",
                "city": "Nashik",
                "area": "Indira Nagar",
                "bhk": 2,
                "price": 12000,
                "broker_phone": "9876543210"
            },
            {
                "title": "3 BHK College Road",  # This is the duplicate
                "property_type": "flat",
                "listing_type": "rent",
                "city": "Nashik",
                "area": "College Road",
                "bhk": 3,
                "price": 25000,
                "broker_phone": "9988776655"
            },
            {
                "title": "1 BHK Nashik Road",
                "property_type": "apartment",
                "listing_type": "rent",
                "city": "Nashik",
                "area": "Nashik Road",
                "bhk": 1,
                "price": 6000,
                "broker_phone": "9871111111"
            }
        ]

        dup_hash = compute_ingestion_hash(
            price=25000, area="College Road", bhk=3,
            listing_type="rent", broker_phone="9988776655"
        )

        mock_props_col = self._make_mock_collection()
        mock_broker_col = self._make_mock_collection()
        mock_events_col = self._make_mock_collection()

        def selective_find_one(query):
            """Only return a hit for the duplicate hash."""
            if query.get("ingestion_hash") == dup_hash:
                return {"property_id": "prop_dup", "ingestion_hash": dup_hash, "status": "ACTIVE"}
            return None

        mock_props_col.find_one.side_effect = selective_find_one

        mock_db_obj = MagicMock()
        mock_db_obj.__getitem__.side_effect = lambda name: {
            "properties": mock_props_col,
            "broker_profiles": mock_broker_col,
            "webhook_events": mock_events_col,
        }.get(name, MagicMock())
        mock_client = MagicMock()
        mock_client.__getitem__.return_value = mock_db_obj

        from apps.worker.tasks.ingestion_tasks import process_raw_group_dump

        with patch(
            "apps.worker.tasks.ingestion_tasks.call_ollama_extract",
            return_value=extracted
        ), patch(
            "apps.worker.tasks.ingestion_tasks.MongoClient",
            return_value=mock_client
        ):
            result = process_raw_group_dump.apply(
                kwargs={
                    "source_group": "Mixed Batch Group",
                    "raw_text": "\n\n".join([
                        "2 BHK Indira Nagar 12k 9876543210",
                        "3 BHK College Road 25k 9988776655",
                        "1 BHK Nashik Road 6k 9871111111"
                    ]),
                    "event_id": "evt_mixed"
                }
            ).get()

        assert result["total_extracted"] == 3
        assert result["inserted"] == 2
        assert result["deduplicated"] == 1
        assert mock_props_col.insert_one.call_count == 2

    def test_empty_ollama_response_produces_zero_insertions(self):
        """If Ollama returns an empty array, the task must complete cleanly with 0 insertions."""
        result, props_col, _, _ = self._run_task(
            source_group="Dead Quiet Group",
            raw_text="Need 2BHK flat near college road budget 15k",  # All requests, no offers
            extracted_properties=[]  # Ollama found nothing
        )
        assert result["total_extracted"] == 0
        assert result["inserted"] == 0
        assert result["deduplicated"] == 0
        props_col.insert_one.assert_not_called()

    def test_below_threshold_text_not_chunked(self):
        """Fewer than CHUNK_SIZE_BLOCKS=5 message blocks must result in exactly 1 Ollama call."""
        raw_text = "\n\n".join([f"Block {i}: 2BHK available 9876543{i:03d}" for i in range(3)])
        _, _, _, mock_ollama = self._run_task(
            source_group="Small Group",
            raw_text=raw_text,
            extracted_properties=[]
        )
        # Only 3 blocks → single chunk → one Ollama call
        assert mock_ollama.call_count == 1

    def test_above_threshold_text_is_chunked_correctly(self):
        """More than CHUNK_SIZE_BLOCKS=5 blocks must trigger multiple Ollama calls."""
        raw_text = "\n\n".join([f"Block {i}: 2BHK available 9876543{i:03d}" for i in range(12)])
        _, _, _, mock_ollama = self._run_task(
            source_group="Large Group",
            raw_text=raw_text,
            extracted_properties=[]  # All calls return empty; we only check call count
        )
        # 12 blocks / 5 per chunk = 3 calls (ceil(12/5) = 3)
        assert mock_ollama.call_count == 3

    def test_broker_upsert_called_for_each_unique_new_property(self):
        """For each newly inserted property with a phone number, broker_profiles must be upserted."""
        extracted = [
            {
                "title": "2 BHK A",
                "property_type": "apartment",
                "listing_type": "rent",
                "city": "Nashik",
                "area": "Area A",
                "bhk": 2,
                "price": 10000,
                "broker_phone": "9876543210"
            },
            {
                "title": "3 BHK B",
                "property_type": "flat",
                "listing_type": "rent",
                "city": "Nashik",
                "area": "Area B",
                "bhk": 3,
                "price": 20000,
                "broker_phone": "9911223344"
            }
        ]
        _, props_col, broker_col, _ = self._run_task(
            source_group="Broker Test Group",
            raw_text="2BHK\n\n3BHK",
            extracted_properties=extracted
        )
        # 2 distinct brokers → broker_profiles.update_one called at least twice (upsert + increment)
        assert broker_col.update_one.call_count >= 2

    def test_task_summary_dict_has_expected_keys(self):
        """The return value of the task must include all summary keys."""
        result, _, _, _ = self._run_task(
            source_group="Summary Test Group",
            raw_text="2BHK available 9876543210",
            extracted_properties=[]
        )
        assert "status" in result
        assert "source_group" in result
        assert "total_extracted" in result
        assert "inserted" in result
        assert "deduplicated" in result
