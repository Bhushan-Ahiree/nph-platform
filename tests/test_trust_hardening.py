# tests/test_trust_hardening.py
"""
Sprint A — Inventory Quality & Trust Hardening Test Suite
==========================================================

Coverage:
  1. Source array appends on duplicate listing hash collisions
  2. RawMessageRepository: insert_raw_log, mark_processed, get_by_log_id
  3. Asymmetric freshness sweeper (maintenance_tasks.sweep_inventory_freshness):
       - Rental velocity thresholds (0-3d VERIFIED, 4-7d STALE, 8-14d UNVERIFIED, 15+d ARCHIVED)
       - Sale/commercial velocity thresholds (0-45d, 46-60d, 61-90d, 91+d)
       - confidence_score clamping to 0 (never goes negative)
       - Broker expiry side-effect on ARCHIVED transitions
  4. PATCH /properties/{id}/verify endpoint (Sprint A: returns VerifyResponse shape)
  5. PATCH /properties/{id}/inactive endpoint (immediately archives)
  6. PropertySchemaV2 and shared schema Sprint A field defaults
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timedelta, timezone


# ============================================================================
# Helpers
# ============================================================================

def _make_property(
    property_id: str = "prop_test001",
    listing_type: str = "rent",
    status: str = "ACTIVE",
    availability_status: str = "NEW",
    confidence_score: int = 100,
    age_days: int = 0,
    broker_phone: str = "9876543210",
) -> dict:
    """Builds a minimal property document for sweeper tests."""
    now = datetime.now(timezone.utc)
    updated_at = now - timedelta(days=age_days)
    return {
        "_id": f"oid_{property_id}",
        "property_id": property_id,
        "title": f"Test Property {property_id}",
        "listing_type": listing_type,
        "property_type": "apartment",
        "status": status,
        "availability_status": availability_status,
        "confidence_score": confidence_score,
        "updated_at": updated_at,
        "last_verified_at": updated_at,
        "broker_phone": broker_phone,
        "sources": [],
        "ingestion_hash": f"hash_{property_id}",
    }


def _run_sweeper(mock_properties: list, mock_brokers: dict = None) -> dict:
    """
    Runs sweep_inventory_freshness in-process with patched PyMongo.

    Args:
        mock_properties: List of property documents the sweeper will process.
        mock_brokers: Optional dict of {phone: broker_doc} for broker lookups.

    Returns:
        The task's return dict containing status and counters.
    """
    from apps.worker.tasks.maintenance_tasks import sweep_inventory_freshness

    captured_updates = {}  # property_id → last $set payload

    def mock_update_one(query, update, *args, **kwargs):
        if "$set" in update:
            oid = query.get("_id")
            if oid:
                captured_updates[oid] = update["$set"]
        result = MagicMock()
        result.modified_count = 1
        return result

    mock_props_col = MagicMock()
    mock_props_col.find.return_value = iter(mock_properties)
    mock_props_col.update_one.side_effect = mock_update_one

    mock_broker_col = MagicMock()
    mock_broker_col.update_one.return_value = MagicMock(modified_count=1)
    if mock_brokers:
        mock_broker_col.find_one.side_effect = lambda q: mock_brokers.get(q.get("_id"))
    else:
        mock_broker_col.find_one.return_value = None

    mock_db = MagicMock()
    mock_db.__getitem__.side_effect = lambda name: {
        "properties": mock_props_col,
        "broker_profiles": mock_broker_col,
    }.get(name, MagicMock())

    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db

    with patch("apps.worker.tasks.maintenance_tasks.MongoClient", return_value=mock_client):
        result = sweep_inventory_freshness.apply().get()

    return result, captured_updates, mock_props_col, mock_broker_col


# ============================================================================
# Section 1: Sprint A Schema Field Defaults
# ============================================================================

class TestSprintASchemaDefaults:
    """Validates that Sprint A fields are initialised with correct defaults."""

    def test_source_entry_has_seen_at_default(self):
        from apps.api.schemas.property_schema_v2 import SourceEntry
        entry = SourceEntry(broker_phone="9876543210", group_name="Test Group")
        assert entry.seen_at is not None
        assert entry.seen_at.tzinfo is not None  # timezone-aware

    def test_property_schema_v2_sources_defaults_to_empty_list(self):
        from apps.api.schemas.property_schema_v2 import PropertySchemaV2
        prop = PropertySchemaV2(
            title="Test Flat",
            area="Indira Nagar",
            price=12000,
        )
        assert prop.sources == []

    def test_property_schema_v2_availability_status_defaults_to_new(self):
        from apps.api.schemas.property_schema_v2 import PropertySchemaV2
        prop = PropertySchemaV2(
            title="Test Flat",
            area="College Road",
            price=15000,
        )
        assert prop.availability_status == "NEW"

    def test_property_schema_v2_raw_message_id_defaults_to_none(self):
        from apps.api.schemas.property_schema_v2 import PropertySchemaV2
        prop = PropertySchemaV2(
            title="Test Flat",
            area="Nashik Road",
            price=8000,
        )
        assert prop.raw_message_id is None

    def test_property_schema_v2_extraction_confidence_defaults_to_100(self):
        from apps.api.schemas.property_schema_v2 import PropertySchemaV2
        prop = PropertySchemaV2(
            title="Test Flat",
            area="Gangapur Road",
            price=22000,
        )
        assert prop.extraction_confidence == 100

    def test_source_entry_all_fields(self):
        from apps.api.schemas.property_schema_v2 import SourceEntry
        now = datetime.now(timezone.utc)
        entry = SourceEntry(
            broker_phone="9876543210",
            group_name="Nashik Brokers VIP",
            seen_at=now
        )
        assert entry.broker_phone == "9876543210"
        assert entry.group_name == "Nashik Brokers VIP"
        assert entry.seen_at == now

    def test_shared_schema_normalises_legacy_verified_to_uppercase(self):
        from apps.api.schemas.property_schema_v2 import PropertySchemaV2
        prop = PropertySchemaV2(
            title="Legacy Property",
            city="Nashik",
            area="Test Area",
            price=12000,
            availability_status="verified",
        )
        assert prop.availability_status == "VERIFIED"

    def test_shared_schema_normalises_legacy_stale_to_uppercase(self):
        from apps.api.schemas.property_schema_v2 import PropertySchemaV2
        prop = PropertySchemaV2(
            title="Stale Property",
            city="Nashik",
            area="Test Area",
            price=12000,
            availability_status="stale",
        )
        assert prop.availability_status == "STALE"

    def test_shared_schema_preserves_canonical_verified(self):
        from apps.api.schemas.property_schema_v2 import PropertySchemaV2
        prop = PropertySchemaV2(
            title="Canonical Property",
            city="Nashik",
            area="Test Area",
            price=12000,
            availability_status="VERIFIED",
        )
        assert prop.availability_status == "VERIFIED"

    def test_shared_schema_empty_availability_defaults_to_new(self):
        from apps.api.schemas.property_schema_v2 import PropertySchemaV2
        prop = PropertySchemaV2(
            title="Empty Avail Property",
            city="Nashik",
            area="Test Area",
            price=12000,
        )
        assert prop.availability_status == "NEW"

    def test_shared_schema_sources_initialised_as_empty_list(self):
        from apps.api.schemas.property_schema_v2 import PropertySchemaV2
        prop = PropertySchemaV2(
            title="No Sources Property",
            city="Nashik",
            area="Test Area",
            price=12000,
        )
        assert prop.sources == []

    def test_shared_schema_extraction_confidence_initialised(self):
        from apps.api.schemas.property_schema_v2 import PropertySchemaV2
        prop = PropertySchemaV2(
            title="Extraction Test",
            city="Nashik",
            area="Test Area",
            price=12000,
        )
        assert prop.extraction_confidence == 100


# ============================================================================
# Section 2: RawMessageRepository Tests
# ============================================================================

class TestRawMessageRepository:
    """Tests for raw_message_logs persistence operations."""

    @pytest.mark.asyncio
    async def test_insert_raw_log_returns_log_id(self, mock_db):
        from apps.api.repositories.raw_message_repository import RawMessageRepository
        repo = RawMessageRepository()
        log_id = await repo.insert_raw_log(
            raw_text="2BHK in Indira Nagar 12k 9876543210",
            ingestion_hash="a" * 64,
            source_group="Nashik Brokers Group",
        )
        assert log_id.startswith("rawlog_")
        assert len(log_id) > 10

    @pytest.mark.asyncio
    async def test_insert_raw_log_persists_correct_fields(self, mock_db):
        from apps.api.repositories.raw_message_repository import RawMessageRepository
        repo = RawMessageRepository()
        log_id = await repo.insert_raw_log(
            raw_text="3BHK College Road 25k",
            ingestion_hash="b" * 64,
            source_group="College Road Group",
        )
        retrieved = await repo.get_by_log_id(log_id)
        assert retrieved is not None
        assert retrieved["raw_text"] == "3BHK College Road 25k"
        assert retrieved["ingestion_hash"] == "b" * 64
        assert retrieved["source_group"] == "College Road Group"
        assert retrieved["processed"] is False
        assert "received_at" in retrieved

    @pytest.mark.asyncio
    async def test_mark_processed_sets_processed_flag(self, mock_db):
        from apps.api.repositories.raw_message_repository import RawMessageRepository
        repo = RawMessageRepository()
        log_id = await repo.insert_raw_log(
            raw_text="2BHK Nashik Road",
            ingestion_hash="c" * 64,
        )
        success = await repo.mark_processed(log_id)
        assert success is True
        doc = await repo.get_by_log_id(log_id)
        assert doc["processed"] is True

    @pytest.mark.asyncio
    async def test_mark_processed_nonexistent_returns_false(self, mock_db):
        from apps.api.repositories.raw_message_repository import RawMessageRepository
        repo = RawMessageRepository()
        result = await repo.mark_processed("rawlog_nonexistent_id")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_by_log_id_returns_none_for_missing(self, mock_db):
        from apps.api.repositories.raw_message_repository import RawMessageRepository
        repo = RawMessageRepository()
        result = await repo.get_by_log_id("rawlog_does_not_exist")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_unprocessed_returns_only_unprocessed(self, mock_db):
        from apps.api.repositories.raw_message_repository import RawMessageRepository
        repo = RawMessageRepository()
        # Insert two logs; process the first
        id1 = await repo.insert_raw_log("Text A", "d" * 64, "Group A")
        id2 = await repo.insert_raw_log("Text B", "e" * 64, "Group B")
        await repo.mark_processed(id1)
        unprocessed = await repo.get_unprocessed(limit=10)
        log_ids = [doc["log_id"] for doc in unprocessed]
        assert id2 in log_ids
        assert id1 not in log_ids

    @pytest.mark.asyncio
    async def test_multiple_logs_have_distinct_ids(self, mock_db):
        from apps.api.repositories.raw_message_repository import RawMessageRepository
        repo = RawMessageRepository()
        ids = [
            await repo.insert_raw_log(f"Text {i}", f"hash_{i:064d}", f"Group {i}")
            for i in range(5)
        ]
        assert len(set(ids)) == 5, "All log IDs must be unique"


# ============================================================================
# Section 3: Source Array Append on Dedup Collision (Property Repository)
# ============================================================================

class TestSourceArrayAppend:
    """Tests for PropertyRepository.append_source_entry."""

    @pytest.mark.asyncio
    async def test_append_source_entry_pushes_new_source(self, mock_db):
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        col = repo.get_collection()

        # Insert an initial property with an ingestion_hash
        initial_hash = "f" * 64
        await col.insert_one({
            "property_id": "prop_source_test_1",
            "title": "2 BHK Indira Nagar",
            "ingestion_hash": initial_hash,
            "status": "ACTIVE",
            "sources": [],
            "intelligence": {"duplicate_count": 0},
            "updated_at": datetime.now(timezone.utc),
        })

        # Now append a new source via a second broker observation
        result = await repo.append_source_entry(
            ingestion_hash=initial_hash,
            broker_phone="9988776655",
            group_name="Nashik Brokers Group 2",
        )

        assert result is not None
        assert len(result["sources"]) == 1
        new_source = result["sources"][0]
        assert new_source["broker_phone"] == "9988776655"
        assert new_source["group_name"] == "Nashik Brokers Group 2"
        assert "seen_at" in new_source

    @pytest.mark.asyncio
    async def test_append_source_entry_increments_duplicate_count(self, mock_db):
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        col = repo.get_collection()

        initial_hash = "a1b2" * 16  # 64-char hash
        await col.insert_one({
            "property_id": "prop_dup_count_test",
            "ingestion_hash": initial_hash,
            "status": "ACTIVE",
            "sources": [],
            "intelligence": {"duplicate_count": 3},
            "updated_at": datetime.now(timezone.utc),
        })

        result = await repo.append_source_entry(
            ingestion_hash=initial_hash,
            broker_phone="9871234567",
            group_name="Indira Nagar Brokers",
        )

        assert result is not None
        assert result["intelligence"]["duplicate_count"] == 4

    @pytest.mark.asyncio
    async def test_append_source_entry_accumulates_multiple_sources(self, mock_db):
        """Three consecutive append_source_entry calls grow the sources array to 3."""
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        col = repo.get_collection()

        initial_hash = "cc" * 32
        await col.insert_one({
            "property_id": "prop_multi_source",
            "ingestion_hash": initial_hash,
            "status": "ACTIVE",
            "sources": [],
            "intelligence": {"duplicate_count": 0},
            "updated_at": datetime.now(timezone.utc),
        })

        for i in range(3):
            await repo.append_source_entry(
                ingestion_hash=initial_hash,
                broker_phone=f"987654321{i}",
                group_name=f"Broker Group {i}",
            )

        # Retrieve the document and verify 3 sources were accumulated
        from shared.utils.database import db
        doc = await db.client.nph_core.properties.find_one({"ingestion_hash": initial_hash})
        assert doc is not None
        assert len(doc["sources"]) == 3

    @pytest.mark.asyncio
    async def test_append_source_entry_returns_none_for_unknown_hash(self, mock_db):
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        result = await repo.append_source_entry(
            ingestion_hash="0" * 64,  # No property has this hash
            broker_phone="9876543210",
            group_name="Ghost Group",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_append_source_entry_ignores_archived_properties(self, mock_db):
        """append_source_entry should NOT match ARCHIVED properties (they're out of search)."""
        from apps.api.repositories.property_repository import PropertyRepository
        repo = PropertyRepository()
        col = repo.get_collection()

        archived_hash = "dd" * 32
        await col.insert_one({
            "property_id": "prop_archived_no_append",
            "ingestion_hash": archived_hash,
            "status": "ARCHIVED",   # ← ARCHIVED, not ACTIVE
            "sources": [],
            "intelligence": {"duplicate_count": 0},
            "updated_at": datetime.now(timezone.utc),
        })

        result = await repo.append_source_entry(
            ingestion_hash=archived_hash,
            broker_phone="9876543210",
            group_name="Any Group",
        )
        assert result is None  # ARCHIVED docs must not be matched


# ============================================================================
# Section 4: Asymmetric Freshness Sweeper Tests
# ============================================================================

class TestSweepInventoryFreshness:
    """Tests for the Sprint A sweep_inventory_freshness Celery task."""

    # ── Rental thresholds ────────────────────────────────────────────────────

    def test_rental_0_days_sets_verified(self):
        """A brand-new rental (0 days old) must transition to VERIFIED."""
        prop = _make_property(listing_type="rent", age_days=0)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "VERIFIED"
        assert updates["oid_prop_test001"]["status"] == "ACTIVE"

    def test_rental_3_days_sets_verified(self):
        """A 3-day-old rental is still within the VERIFIED window."""
        prop = _make_property(listing_type="rent", age_days=3)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "VERIFIED"

    def test_rental_4_days_sets_stale(self):
        """A 4-day-old rental must transition to STALE."""
        prop = _make_property(listing_type="rent", age_days=4)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "STALE"
        assert updates["oid_prop_test001"]["status"] == "ACTIVE"

    def test_rental_7_days_sets_stale(self):
        """A 7-day-old rental is at the STALE boundary — should be STALE."""
        prop = _make_property(listing_type="rent", age_days=7)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "STALE"

    def test_rental_8_days_sets_unverified_with_score_penalty(self):
        """An 8-day-old rental must become UNVERIFIED and lose 10 confidence points."""
        prop = _make_property(listing_type="rent", age_days=8, confidence_score=80)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "UNVERIFIED"
        assert updates["oid_prop_test001"]["confidence_score"] == 70  # 80 - 10

    def test_rental_14_days_sets_unverified(self):
        """A 14-day-old rental is at the UNVERIFIED boundary."""
        prop = _make_property(listing_type="rent", age_days=14, confidence_score=60)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "UNVERIFIED"
        assert updates["oid_prop_test001"]["confidence_score"] == 50

    def test_rental_15_days_sets_archived(self):
        """A 15-day-old rental must be ARCHIVED and the core status set to ARCHIVED."""
        prop = _make_property(listing_type="rent", age_days=15)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "ARCHIVED"
        assert updates["oid_prop_test001"]["status"] == "ARCHIVED"

    def test_rental_30_days_sets_archived(self):
        """A very old rental (30 days) must also be ARCHIVED."""
        prop = _make_property(listing_type="rent", age_days=30)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "ARCHIVED"
        assert updates["oid_prop_test001"]["status"] == "ARCHIVED"

    # ── Sale thresholds ──────────────────────────────────────────────────────

    def test_sale_45_days_sets_verified(self):
        """A 45-day-old sale listing is still within the VERIFIED window."""
        prop = _make_property(listing_type="sale", age_days=45)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "VERIFIED"
        assert updates["oid_prop_test001"]["status"] == "ACTIVE"

    def test_sale_46_days_sets_stale(self):
        """A 46-day-old sale listing transitions to STALE."""
        prop = _make_property(listing_type="sale", age_days=46)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "STALE"

    def test_sale_60_days_sets_stale(self):
        """A 60-day-old sale listing is at the STALE boundary."""
        prop = _make_property(listing_type="sale", age_days=60)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "STALE"

    def test_sale_61_days_sets_unverified_with_penalty(self):
        """A 61-day-old sale listing transitions to UNVERIFIED with score penalty."""
        prop = _make_property(listing_type="sale", age_days=61, confidence_score=90)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "UNVERIFIED"
        assert updates["oid_prop_test001"]["confidence_score"] == 80  # 90 - 10

    def test_sale_90_days_sets_unverified(self):
        """A 90-day-old sale is at the UNVERIFIED boundary."""
        prop = _make_property(listing_type="sale", age_days=90, confidence_score=50)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "UNVERIFIED"
        assert updates["oid_prop_test001"]["confidence_score"] == 40

    def test_sale_91_days_sets_archived(self):
        """A 91-day-old sale listing must be ARCHIVED."""
        prop = _make_property(listing_type="sale", age_days=91)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "ARCHIVED"
        assert updates["oid_prop_test001"]["status"] == "ARCHIVED"

    def test_buy_listing_uses_sale_thresholds(self):
        """listing_type='buy' must use the same wide (sale) thresholds."""
        prop = _make_property(listing_type="buy", age_days=44)
        result, updates, _, _ = _run_sweeper([prop])
        # 44 days ≤ 45 verified_max → VERIFIED under sale thresholds
        assert updates["oid_prop_test001"]["availability_status"] == "VERIFIED"

    # ── Confidence score clamping ─────────────────────────────────────────────

    def test_score_does_not_go_below_zero_rental_unverified(self):
        """Clamping guardrail: confidence_score stays at 0, not -10."""
        prop = _make_property(listing_type="rent", age_days=10, confidence_score=5)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "UNVERIFIED"
        assert updates["oid_prop_test001"]["confidence_score"] == 0  # max(0, 5 - 10)

    def test_score_already_zero_stays_zero_rental(self):
        """A property at exactly 0 confidence doesn't go negative."""
        prop = _make_property(listing_type="rent", age_days=10, confidence_score=0)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["confidence_score"] == 0

    def test_score_already_zero_stays_zero_sale(self):
        """Score clamping works equally for sale/commercial UNVERIFIED transitions."""
        prop = _make_property(listing_type="sale", age_days=75, confidence_score=3)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "UNVERIFIED"
        assert updates["oid_prop_test001"]["confidence_score"] == 0  # max(0, 3 - 10)

    def test_score_not_decremented_on_stale_transition(self):
        """STALE transitions must NOT decrement the confidence_score."""
        prop = _make_property(listing_type="rent", age_days=5, confidence_score=80)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "STALE"
        assert "confidence_score" not in updates.get("oid_prop_test001", {})

    def test_score_not_decremented_on_archived_transition(self):
        """ARCHIVED transitions (15+ days rental) must NOT decrement the score."""
        prop = _make_property(listing_type="rent", age_days=20, confidence_score=70)
        result, updates, _, _ = _run_sweeper([prop])
        assert updates["oid_prop_test001"]["availability_status"] == "ARCHIVED"
        # confidence_score should NOT be in the update payload for ARCHIVED
        assert "confidence_score" not in updates.get("oid_prop_test001", {})

    # ── Skip logic ───────────────────────────────────────────────────────────

    def test_already_correct_state_is_skipped(self):
        """A property already in the correct state for its age is skipped (no DB write)."""
        prop = _make_property(listing_type="rent", age_days=5, availability_status="STALE")
        prop["status"] = "ACTIVE"  # already correct core status
        result, updates, props_col, _ = _run_sweeper([prop])
        # No update was written for this property
        assert "oid_prop_test001" not in updates

    def test_property_without_updated_at_is_skipped(self):
        """A property missing 'updated_at' must be skipped gracefully without error."""
        prop = _make_property(listing_type="rent", age_days=5)
        del prop["updated_at"]  # Remove the required field
        del prop["last_verified_at"]
        result, updates, _, _ = _run_sweeper([prop])
        assert "oid_prop_test001" not in updates

    # ── Broker side-effects ─────────────────────────────────────────────────

    def test_broker_expired_properties_incremented_on_archive(self):
        """When a property is ARCHIVED by the sweeper, the broker's expired_properties goes up."""
        prop = _make_property(listing_type="rent", age_days=20, broker_phone="9876543210")
        mock_broker = {
            "_id": "9876543210",
            "phone": "9876543210",
            "verified_properties": 5,
            "properties_posted": 10,
            "expired_properties": 2,
            "reliability_score": 50,
        }
        _, _, _, broker_col = _run_sweeper(
            [prop], mock_brokers={"9876543210": mock_broker}
        )
        # The sweeper should have called broker update_one at least once
        assert broker_col.update_one.call_count >= 1

    def test_broker_reliability_score_recalculated_on_archive(self):
        """After archival, the broker's reliability_score is recalculated."""
        prop = _make_property(listing_type="rent", age_days=20, broker_phone="9999888877")
        mock_broker = {
            "_id": "9999888877",
            "verified_properties": 4,
            "properties_posted": 10,
            "expired_properties": 1,
            "reliability_score": 40,
        }
        _, _, _, broker_col = _run_sweeper(
            [prop], mock_brokers={"9999888877": mock_broker}
        )
        # Reliability score update call is part of the sequence
        assert broker_col.update_one.called

    # ── Multi-property batch ─────────────────────────────────────────────────

    def test_mixed_batch_applies_correct_transitions_per_property(self):
        """A batch with multiple ages/types applies independent transitions correctly."""
        props = [
            _make_property("p1", "rent", age_days=1),    # → VERIFIED
            _make_property("p2", "rent", age_days=5),    # → STALE
            _make_property("p3", "rent", age_days=10),   # → UNVERIFIED
            _make_property("p4", "rent", age_days=20),   # → ARCHIVED
            _make_property("p5", "sale", age_days=30),   # → VERIFIED (sale window)
            _make_property("p6", "sale", age_days=91),   # → ARCHIVED
        ]
        _, updates, _, _ = _run_sweeper(props)

        assert updates["oid_p1"]["availability_status"] == "VERIFIED"
        assert updates["oid_p2"]["availability_status"] == "STALE"
        assert updates["oid_p3"]["availability_status"] == "UNVERIFIED"
        assert updates["oid_p4"]["availability_status"] == "ARCHIVED"
        assert updates["oid_p5"]["availability_status"] == "VERIFIED"
        assert updates["oid_p6"]["availability_status"] == "ARCHIVED"

    def test_sweeper_returns_structured_counter_dict(self):
        """Task return value must include 'status' and 'counters' keys."""
        props = [
            _make_property("q1", "rent", age_days=2),
            _make_property("q2", "rent", age_days=6),
        ]
        result, _, _, _ = _run_sweeper(props)
        assert result["status"] == "completed"
        assert "counters" in result
        assert "swept_at" in result
        assert isinstance(result["counters"], dict)

    def test_sweeper_empty_inventory_completes_cleanly(self):
        """Sweeper must handle an empty properties collection without error."""
        result, updates, _, _ = _run_sweeper([])
        assert result["status"] == "completed"
        assert updates == {}


# ============================================================================
# Section 5: API Route Tests — /verify and /inactive
# ============================================================================

class TestVerifyAndInactiveRoutes:
    """Integration tests for Sprint A verification endpoints."""

    @pytest.fixture(autouse=True)
    def setup_auth_override(self, api_client):
        from shared.utils.auth_guard import get_current_user
        from fastapi import Request, HTTPException

        async def mock_get_current_user(request: Request):
            auth = request.headers.get("Authorization")
            if not auth or not auth.startswith("Bearer "):
                raise HTTPException(status_code=401, detail="Could not validate credentials. Please log in.")
            return {"id": "user1", "role": "admin"}

        api_client.app.dependency_overrides[get_current_user] = mock_get_current_user
        yield
        api_client.app.dependency_overrides.clear()

    def _make_prop_doc(self, prop_id: str = "prop_api_test01"):
        return {
            "_id": "some_oid",
            "property_id": prop_id,
            "title": "Test Property",
            "city": "Nashik",
            "area": "Indira Nagar",
            "price": 12000,
            "bhk": 2,
            "listing_type": "rent",
            "status": "ACTIVE",
            "availability_status": "STALE",
            "confidence_score": 60,
            "verification_count": 3,
            "last_verified_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "broker_phone": "9876543210",
            "sources": [],
        }

    def test_verify_endpoint_returns_200_with_verify_response_shape(
        self, api_client, auth_token
    ):
        """PATCH /verify must return 200 with the Sprint A VerifyResponse shape."""
        prop_doc = self._make_prop_doc("prop_verify_001")
        updated_doc = {
            **prop_doc,
            "availability_status": "VERIFIED",
            "confidence_score": 100,
            "verification_count": 4,
            "last_verified_at": datetime.now(timezone.utc),
        }

        with patch("apps.api.routers.property.property_repo") as mock_repo:
            mock_col = AsyncMock()
            mock_col.find_one = AsyncMock(return_value=prop_doc)
            mock_repo.get_collection.return_value = mock_col
            mock_repo.update = AsyncMock(return_value=updated_doc)

            response = api_client.patch(
                "/properties/prop_verify_001/verify",
                headers={"Authorization": f"Bearer {auth_token}"}
            )

        assert response.status_code == 200
        data = response.json()
        # VerifyResponse fields
        assert "property_id" in data
        assert "availability_status" in data
        assert "confidence_score" in data
        assert "verification_count" in data
        assert "last_verified_at" in data
        assert "message" in data

    def test_verify_endpoint_sets_verified_and_resets_confidence(
        self, api_client, auth_token
    ):
        """PATCH /verify must set availability_status=VERIFIED and confidence_score=100."""
        prop_doc = self._make_prop_doc("prop_verify_002")
        updated_doc = {
            **prop_doc,
            "availability_status": "VERIFIED",
            "confidence_score": 100,
            "verification_count": 4,
            "status": "ACTIVE",
            "last_verified_at": datetime.now(timezone.utc),
        }

        with patch("apps.api.routers.property.property_repo") as mock_repo:
            mock_col = AsyncMock()
            mock_col.find_one = AsyncMock(return_value=prop_doc)
            mock_repo.get_collection.return_value = mock_col
            mock_repo.update = AsyncMock(return_value=updated_doc)

            response = api_client.patch(
                "/properties/prop_verify_002/verify",
                headers={"Authorization": f"Bearer {auth_token}"}
            )

        data = response.json()
        assert data["availability_status"] == "VERIFIED"
        assert data["confidence_score"] == 100
        assert "verified" in data["message"].lower()

    def test_verify_increments_verification_count(self, api_client, auth_token):
        """PATCH /verify must increment verification_count by 1."""
        prop_doc = self._make_prop_doc("prop_verify_003")
        prop_doc["verification_count"] = 7  # Set to 7 so we expect 8 back
        updated_doc = {**prop_doc, "verification_count": 8, "availability_status": "VERIFIED",
                       "confidence_score": 100, "last_verified_at": datetime.now(timezone.utc)}

        with patch("apps.api.routers.property.property_repo") as mock_repo:
            mock_col = AsyncMock()
            mock_col.find_one = AsyncMock(return_value=prop_doc)
            mock_repo.get_collection.return_value = mock_col
            mock_repo.update = AsyncMock(return_value=updated_doc)

            response = api_client.patch(
                "/properties/prop_verify_003/verify",
                headers={"Authorization": f"Bearer {auth_token}"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["verification_count"] == 8

    def test_verify_nonexistent_property_returns_404(self, api_client, auth_token):
        """PATCH /verify on a non-existent property must return 404."""
        with patch("apps.api.routers.property.property_repo") as mock_repo:
            mock_col = AsyncMock()
            mock_col.find_one = AsyncMock(return_value=None)
            mock_repo.get_collection.return_value = mock_col

            response = api_client.patch(
                "/properties/prop_does_not_exist/verify",
                headers={"Authorization": f"Bearer {auth_token}"}
            )

        assert response.status_code == 404

    def test_inactive_endpoint_sets_both_statuses_to_archived(
        self, api_client, auth_token
    ):
        """PATCH /inactive must set BOTH status=ARCHIVED and availability_status=ARCHIVED."""
        prop_doc = self._make_prop_doc("prop_inactive_001")
        updated_doc = {
            **prop_doc,
            "status": "ARCHIVED",
            "availability_status": "ARCHIVED",
        }

        with patch("apps.api.routers.property.property_repo") as mock_repo:
            mock_col = AsyncMock()
            mock_col.find_one = AsyncMock(return_value=prop_doc)
            mock_repo.get_collection.return_value = mock_col
            mock_repo.update = AsyncMock(return_value=updated_doc)

            response = api_client.patch(
                "/properties/prop_inactive_001/inactive",
                headers={"Authorization": f"Bearer {auth_token}"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ARCHIVED"
        assert data["availability_status"] == "ARCHIVED"
        assert "property_id" in data
        assert "message" in data
        assert "archived" in data["message"].lower()

    def test_inactive_returns_inactive_response_shape(self, api_client, auth_token):
        """PATCH /inactive must return the Sprint A InactiveResponse envelope."""
        prop_doc = self._make_prop_doc("prop_inactive_002")
        updated_doc = {**prop_doc, "status": "ARCHIVED", "availability_status": "ARCHIVED"}

        with patch("apps.api.routers.property.property_repo") as mock_repo:
            mock_col = AsyncMock()
            mock_col.find_one = AsyncMock(return_value=prop_doc)
            mock_repo.get_collection.return_value = mock_col
            mock_repo.update = AsyncMock(return_value=updated_doc)

            response = api_client.patch(
                "/properties/prop_inactive_002/inactive",
                headers={"Authorization": f"Bearer {auth_token}"}
            )

        data = response.json()
        # InactiveResponse required fields
        required_keys = {"property_id", "status", "availability_status", "message"}
        assert required_keys.issubset(set(data.keys()))

    def test_inactive_nonexistent_property_returns_404(self, api_client, auth_token):
        """PATCH /inactive on a non-existent property must return 404."""
        with patch("apps.api.routers.property.property_repo") as mock_repo:
            mock_col = AsyncMock()
            mock_col.find_one = AsyncMock(return_value=None)
            mock_repo.get_collection.return_value = mock_col

            response = api_client.patch(
                "/properties/prop_no_exist_inactive/inactive",
                headers={"Authorization": f"Bearer {auth_token}"}
            )

        assert response.status_code == 404

    def test_both_endpoints_require_authentication(self, api_client):
        """Both /verify and /inactive endpoints must reject unauthenticated requests."""
        verify_resp = api_client.patch("/properties/prop_abc/verify")
        inactive_resp = api_client.patch("/properties/prop_abc/inactive")
        # FastAPI returns 401 (Unauthorized) when no Bearer token is provided
        assert verify_resp.status_code == 401
        assert inactive_resp.status_code == 401


# ============================================================================
# Section 6: Helper Function Tests (Sweeper internal functions)
# ============================================================================

class TestSweeperHelpers:
    """Unit tests for _resolve_age_state and _get_thresholds."""

    def test_get_thresholds_rent_returns_rental_params(self):
        from apps.worker.tasks.maintenance_tasks import _get_thresholds, RENTAL_THRESHOLDS
        assert _get_thresholds("rent") == RENTAL_THRESHOLDS

    def test_get_thresholds_sale_returns_sale_params(self):
        from apps.worker.tasks.maintenance_tasks import _get_thresholds, SALE_THRESHOLDS
        assert _get_thresholds("sale") == SALE_THRESHOLDS

    def test_get_thresholds_buy_returns_sale_params(self):
        from apps.worker.tasks.maintenance_tasks import _get_thresholds, SALE_THRESHOLDS
        assert _get_thresholds("buy") == SALE_THRESHOLDS

    def test_resolve_age_state_rental_day_0_verified(self):
        from apps.worker.tasks.maintenance_tasks import _resolve_age_state, RENTAL_THRESHOLDS
        avail, core, penalise = _resolve_age_state(0, RENTAL_THRESHOLDS)
        assert avail == "VERIFIED"
        assert core == "ACTIVE"
        assert penalise is False

    def test_resolve_age_state_rental_day_4_stale(self):
        from apps.worker.tasks.maintenance_tasks import _resolve_age_state, RENTAL_THRESHOLDS
        avail, core, penalise = _resolve_age_state(4, RENTAL_THRESHOLDS)
        assert avail == "STALE"
        assert penalise is False

    def test_resolve_age_state_rental_day_8_unverified_with_penalty(self):
        from apps.worker.tasks.maintenance_tasks import _resolve_age_state, RENTAL_THRESHOLDS
        avail, core, penalise = _resolve_age_state(8, RENTAL_THRESHOLDS)
        assert avail == "UNVERIFIED"
        assert penalise is True

    def test_resolve_age_state_rental_day_15_archived(self):
        from apps.worker.tasks.maintenance_tasks import _resolve_age_state, RENTAL_THRESHOLDS
        avail, core, penalise = _resolve_age_state(15, RENTAL_THRESHOLDS)
        assert avail == "ARCHIVED"
        assert core == "ARCHIVED"
        assert penalise is False

    def test_resolve_age_state_sale_day_45_verified(self):
        from apps.worker.tasks.maintenance_tasks import _resolve_age_state, SALE_THRESHOLDS
        avail, core, penalise = _resolve_age_state(45, SALE_THRESHOLDS)
        assert avail == "VERIFIED"

    def test_resolve_age_state_sale_day_91_archived(self):
        from apps.worker.tasks.maintenance_tasks import _resolve_age_state, SALE_THRESHOLDS
        avail, core, penalise = _resolve_age_state(91, SALE_THRESHOLDS)
        assert avail == "ARCHIVED"
        assert core == "ARCHIVED"
