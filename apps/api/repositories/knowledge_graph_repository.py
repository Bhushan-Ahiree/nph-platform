# apps/api/repositories/knowledge_graph_repository.py
from typing import Optional, Dict, Any


class KnowledgeGraphRepository:
    """
    Isolates all structural database execution logic for the Knowledge Graph entities:
    builders, projects, localities, and amenity_dictionary.
    """

    def _get_db(self):
        from shared.utils.database import db
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core

    def get_builders_collection(self):
        return self._get_db().builders

    def get_projects_collection(self):
        return self._get_db().projects

    def get_localities_collection(self):
        return self._get_db().localities

    def get_amenity_dictionary_collection(self):
        return self._get_db().amenity_dictionary

    async def create_indexes(self):
        """
        Builds background indexing models for Knowledge Graph entities to enable
        high-performance multikey alias lookups and ensure zero duplicate entities.
        """
        b_col = self.get_builders_collection()
        await b_col.create_index([("city", 1), ("canonical_name", 1)], unique=True)
        await b_col.create_index([("builder_id", 1)], unique=True)
        await b_col.create_index([("aliases", 1)])

        p_col = self.get_projects_collection()
        await p_col.create_index([("city", 1), ("canonical_name", 1)], unique=True)
        await p_col.create_index([("project_id", 1)], unique=True)
        await p_col.create_index([("builder_id", 1)])
        await p_col.create_index([("aliases", 1)])

        l_col = self.get_localities_collection()
        await l_col.create_index([("locality_id", 1)], unique=True)
        await l_col.create_index([("city", 1), ("canonical_name", 1)], unique=True)
        await l_col.create_index([("city", 1), ("aliases", 1)])

        a_col = self.get_amenity_dictionary_collection()
        await a_col.create_index([("amenity_id", 1)], unique=True)
        await a_col.create_index([("aliases", 1)])

    async def find_builder_by_alias(self, city: str, alias: str) -> Optional[Dict[str, Any]]:
        col = self.get_builders_collection()
        return await col.find_one({"city": city, "aliases": alias.lower().strip()})

    async def find_project_by_alias(self, city: str, alias: str) -> Optional[Dict[str, Any]]:
        col = self.get_projects_collection()
        return await col.find_one({"city": city, "aliases": alias.lower().strip()})

    async def find_locality_by_alias(self, city: str, alias: str) -> Optional[Dict[str, Any]]:
        col = self.get_localities_collection()
        return await col.find_one({"city": city, "aliases": alias.lower().strip()})

    async def find_amenity_by_alias(self, alias: str) -> Optional[Dict[str, Any]]:
        col = self.get_amenity_dictionary_collection()
        return await col.find_one({"aliases": alias.lower().strip()})


knowledge_graph_repo = KnowledgeGraphRepository()
