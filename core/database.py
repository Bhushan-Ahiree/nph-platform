# core/database.py
from shared.utils.database import db

def get_db_client():
    """
    Dependency helper that returns the active database namespace.
    """
    if db.client is None:
        raise RuntimeError("Database client is not initialized yet.")
    return db.client["nph_core"]
