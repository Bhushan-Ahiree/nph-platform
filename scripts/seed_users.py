# scripts/seed_users.py — creates the local admin and scraper bot accounts (idempotent)
# Usage: docker compose exec api python scripts/seed_users.py
import os
import sys
from datetime import datetime, timezone

from pymongo import MongoClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.utils.security import hash_password

USERS = [
    ("ADMIN_EMAIL", "ADMIN_PASSWORD", "Local Admin", "admin"),
    ("SCRAPER_BOT_EMAIL", "SCRAPER_BOT_PASSWORD", "NPH Ingestion Bot", "broker"),
]


def main():
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        sys.exit("MONGO_URI is not set.")

    users = MongoClient(mongo_uri)["nph_core"]["users"]
    users.create_index("email", unique=True, sparse=True)

    for email_var, password_var, full_name, role in USERS:
        email, password = os.getenv(email_var), os.getenv(password_var)
        if not email or not password:
            print(f"[SKIP] {email_var} / {password_var} not set.")
            continue

        result = users.update_one(
            {"email": email},
            {"$setOnInsert": {
                "email": email,
                "hashed_password": hash_password(password),
                "full_name": full_name,
                "role": role,
                "created_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        print(f"[{'CREATED' if result.upserted_id else 'EXISTS'}] {email} ({role})")


if __name__ == "__main__":
    main()
