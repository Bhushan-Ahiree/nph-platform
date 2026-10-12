# tests/test_database.py
"""
Tests for shared/utils/database.py — MongoDB connection lifecycle.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestDatabaseConnection:
    """Validates MongoDB connection and disconnection logic."""

    @pytest.mark.asyncio
    async def test_connect_to_mongo_success(self):
        from shared.utils.database import connect_to_mongo, db
        with patch.dict("os.environ", {"MONGO_URI": "mongodb://localhost:27017/test"}):
            with patch("shared.utils.database.AsyncIOMotorClient") as MockClient:
                mock_instance = MagicMock()
                MockClient.return_value = mock_instance
                await connect_to_mongo()
                assert db.client == mock_instance

    @pytest.mark.asyncio
    async def test_connect_to_mongo_missing_uri(self):
        from shared.utils.database import connect_to_mongo
        with patch.dict("os.environ", {}, clear=True):
            # Remove MONGO_URI
            import os
            old_val = os.environ.pop("MONGO_URI", None)
            try:
                await connect_to_mongo()
                # Should not set client when URI is missing
            finally:
                if old_val:
                    os.environ["MONGO_URI"] = old_val

    @pytest.mark.asyncio
    async def test_close_mongo_connection(self):
        from shared.utils.database import close_mongo_connection, db
        mock_client = MagicMock()
        db.client = mock_client
        await close_mongo_connection()
        mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_mongo_connection_no_client(self):
        from shared.utils.database import close_mongo_connection, db
        db.client = None
        # Should not raise
        await close_mongo_connection()
