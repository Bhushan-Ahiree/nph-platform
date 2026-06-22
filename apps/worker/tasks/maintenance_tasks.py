# apps/worker/tasks/maintenance_tasks.py
"""
Sprint A — Asymmetric Freshness Verification Engine
====================================================
Celery Beat scheduled tasks for automated inventory quality maintenance.

Tasks:
  sweep_stale_properties   — Legacy broad-sweep archiver (preserved).
  sweep_inventory_freshness — Sprint A asymmetric 5-state lifecycle engine.
"""
import os
import logging
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from celery import shared_task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Asymmetric Velocity Parameters
# ---------------------------------------------------------------------------
#
# RENTAL thresholds (all listing_type="rent", regardless of property_type):
#   0–3 days  → VERIFIED
#   4–7 days  → STALE
#   8–14 days → UNVERIFIED  (confidence_score - 10)
#   15+ days  → ARCHIVED    (status = ARCHIVED, drops from search vectors)
#
# SALE / COMMERCIAL thresholds (listing_type in "buy"/"sale"):
#   0–45 days  → VERIFIED
#   46–60 days → STALE
#   61–90 days → UNVERIFIED (confidence_score - 10)
#   91+ days   → ARCHIVED   (status = ARCHIVED)
#

RENTAL_THRESHOLDS = {
    "verified_max_days": 3,
    "stale_max_days": 7,
    "unverified_max_days": 14,
    # anything beyond unverified_max_days → ARCHIVED
}

SALE_THRESHOLDS = {
    "verified_max_days": 45,
    "stale_max_days": 60,
    "unverified_max_days": 90,
}


def _get_thresholds(listing_type: str) -> dict:
    """Return the correct velocity parameters for a given listing_type."""
    if listing_type.lower() == "rent":
        return RENTAL_THRESHOLDS
    return SALE_THRESHOLDS  # covers "buy", "sale", land, commercial


def _resolve_age_state(age_days: int, thresholds: dict) -> tuple:
    """
    Maps an age (in days) to a (new_availability_status, new_core_status, penalise_score) tuple.

    Returns:
        new_availability_status : str  — One of NEW / VERIFIED / STALE / UNVERIFIED / ARCHIVED
        new_core_status         : str  — Either "ACTIVE" or "ARCHIVED"
        penalise_score          : bool — True if confidence_score should be decremented by 10
    """
    v = thresholds["verified_max_days"]
    s = thresholds["stale_max_days"]
    u = thresholds["unverified_max_days"]

    if age_days <= v:
        return "VERIFIED", "ACTIVE", False
    elif age_days <= s:
        return "STALE", "ACTIVE", False
    elif age_days <= u:
        return "UNVERIFIED", "ACTIVE", True
    else:
        return "ARCHIVED", "ARCHIVED", False  # Score is irrelevant when archived


# ---------------------------------------------------------------------------
# Task 1 — Legacy Broad-Sweep Archiver (preserved, not modified)
# ---------------------------------------------------------------------------

@shared_task(name="tasks.maintenance_tasks.sweep_stale_properties")
def sweep_stale_properties(days_old: int = 10):
    """
    Scans the database for active properties older than 'days_old'.
    Automatically marks them as expired to prevent dead leads.
    """
    mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
    client = MongoClient(mongo_url)
    db = client["nph_core"]

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)

    try:
        result = db["properties"].update_many(
            {
                "availability.status": "active",
                "updated_at": {"$lt": cutoff_date}
            },
            {
                "$set": {
                    "availability.status": "expired",
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )

        log_msg = (
            f"[Midnight Sweeper] Success: Scanned inventory. "
            f"Expired {result.modified_count} stale properties."
        )
        logger.info(log_msg)
        return log_msg

    except Exception as e:
        error_msg = f"[Midnight Sweeper] Error during execution: {str(e)}"
        logger.error(error_msg)
        return error_msg
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Task 2 — Sprint A Asymmetric Freshness Engine
# ---------------------------------------------------------------------------

@shared_task(name="tasks.maintenance_tasks.sweep_inventory_freshness")
def sweep_inventory_freshness():
    """
    Sprint A Asymmetric Verification Engine.

    Scans all non-ARCHIVED properties and applies asymmetric velocity rules
    based on listing_type to transition each property through the 5-state
    availability_status lifecycle:

        NEW → VERIFIED → STALE → UNVERIFIED → ARCHIVED

    Rental Thresholds (listing_type = "rent"):
        0–3 days:  VERIFIED   (no penalty)
        4–7 days:  STALE      (no penalty)
        8–14 days: UNVERIFIED (−10 confidence_score, clamped to ≥ 0)
        15+ days:  ARCHIVED   (core status = ARCHIVED, removed from search)

    Sale/Commercial Thresholds (listing_type = "buy" | "sale"):
        0–45 days:  VERIFIED   (no penalty)
        46–60 days: STALE      (no penalty)
        61–90 days: UNVERIFIED (−10 confidence_score, clamped to ≥ 0)
        91+ days:   ARCHIVED   (core status = ARCHIVED)

    Age is calculated from the later of 'updated_at' and 'last_verified_at'.
    This means a manual verification resets the clock.

    Clamping Guardrail:
        All confidence_score decrements are wrapped in max(0, updated_score)
        to prevent scores from falling below zero.

    Broker Side-Effects:
        When a property transitions to ARCHIVED, the broker's 'expired_properties'
        counter is incremented and their reliability_score is recalculated.
    """
    mongo_url = os.getenv("MONGO_URL") or os.getenv("MONGO_URI")
    client = MongoClient(mongo_url)
    db = client["nph_core"]

    now = datetime.now(timezone.utc)
    counters = {
        "verified": 0,
        "stale": 0,
        "unverified": 0,
        "archived": 0,
        "skipped": 0,
    }

    try:
        # Scan all non-archived properties (we process every status except ARCHIVED
        # so that STALE and UNVERIFIED docs can be re-evaluated and potentially recovered
        # if last_verified_at was manually refreshed).
        cursor = db["properties"].find({"status": {"$ne": "ARCHIVED"}})

        for prop in cursor:
            # ── Determine effective age ──────────────────────────────────────
            # Use the most recent of updated_at and last_verified_at as the
            # "freshness anchor" — a manual verification PATCH resets the clock.
            updated_at = prop.get("updated_at")
            last_verified_at = prop.get("last_verified_at")

            if not updated_at:
                counters["skipped"] += 1
                continue

            # Make timezone-aware if naive (legacy documents)
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if last_verified_at and last_verified_at.tzinfo is None:
                last_verified_at = last_verified_at.replace(tzinfo=timezone.utc)

            # Freshness anchor = most recent timestamp
            freshness_anchor = updated_at
            if last_verified_at and last_verified_at > freshness_anchor:
                freshness_anchor = last_verified_at

            age_days = (now - freshness_anchor).days

            # ── Resolve target state ─────────────────────────────────────────
            listing_type = prop.get("listing_type", "rent").lower()
            thresholds = _get_thresholds(listing_type)
            new_avail_status, new_core_status, penalise = _resolve_age_state(
                age_days, thresholds
            )

            # Skip if no change needed (already in the correct state and core status)
            current_avail = prop.get("availability_status", "NEW")
            current_core = prop.get("status", "ACTIVE")
            if current_avail == new_avail_status and current_core == new_core_status:
                counters["skipped"] += 1
                continue

            # ── Build update payload ─────────────────────────────────────────
            update_fields = {
                "availability_status": new_avail_status,
                "status": new_core_status,
                "updated_at": now,
            }

            if penalise:
                current_score = prop.get("confidence_score", 100)
                # Clamping guardrail: score never goes below 0
                new_score = max(0, current_score - 10)
                update_fields["confidence_score"] = new_score

            db["properties"].update_one(
                {"_id": prop["_id"]},
                {"$set": update_fields}
            )

            # ── Track counters ───────────────────────────────────────────────
            counters[new_avail_status.lower()] += 1

            # ── Broker side-effects on ARCHIVED transition ───────────────────
            if new_avail_status == "ARCHIVED":
                _handle_broker_expiry(db, prop, now)

        log_msg = (
            f"[Freshness Sweeper] Completed sweep. "
            f"verified={counters['verified']}, stale={counters['stale']}, "
            f"unverified={counters['unverified']}, archived={counters['archived']}, "
            f"skipped={counters['skipped']}"
        )
        logger.info(log_msg)
        return {
            "status": "completed",
            "counters": counters,
            "swept_at": now.isoformat(),
        }

    except Exception as err:
        error_msg = f"[Freshness Sweeper] Fatal error: {str(err)}"
        logger.error(error_msg, exc_info=True)
        return {"status": "error", "message": error_msg}

    finally:
        client.close()


def _handle_broker_expiry(db, prop: dict, now: datetime):
    """
    Increments the broker's expired_properties counter and recalculates
    their reliability_score when a property transitions to ARCHIVED.

    This is extracted as a helper to keep sweep_inventory_freshness readable.
    """
    broker_phone = prop.get("broker_phone")
    if not broker_phone:
        broker_phone = prop.get("source", {}).get("broker_phone")
    if not broker_phone:
        return

    # Ensure broker profile exists before incrementing
    db["broker_profiles"].update_one(
        {"_id": broker_phone},
        {
            "$set": {
                "phone": broker_phone,
                "last_seen_at": now,
            },
            "$setOnInsert": {
                "name": f"Broker {broker_phone}",
                "properties_posted": 0,
                "verified_properties": 0,
                "expired_properties": 0,
                "reliability_score": 100,
            },
        },
        upsert=True,
    )

    # Increment expired_properties
    db["broker_profiles"].update_one(
        {"_id": broker_phone},
        {
            "$inc": {"expired_properties": 1},
            "$set": {"last_seen_at": now},
        },
    )

    # Recalculate reliability_score
    broker = db["broker_profiles"].find_one({"_id": broker_phone})
    if broker:
        verified = broker.get("verified_properties", 0)
        posted = broker.get("properties_posted", 0)
        divisor = posted if posted > 0 else 1
        reliability_score = max(0, int((verified / divisor) * 100))
        db["broker_profiles"].update_one(
            {"_id": broker_phone},
            {"$set": {"reliability_score": reliability_score}},
        )