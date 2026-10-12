# tests/test_knowledge_graph.py
import pytest
from apps.api.schemas.knowledge_graph_schemas import BuilderNode, ProjectNode, LocalityNode, AmenityNode
from apps.api.repositories.knowledge_graph_repository import knowledge_graph_repo
from shared.utils.normalization import normalise_extracted_property


def test_knowledge_graph_schemas_default_population():
    b = BuilderNode(_id="bldr_123", canonical_name="Ashoka Builders", city="Nashik")
    assert b.id == "bldr_123"
    assert b.builder_id == "bldr_123"
    assert b.reputation_score == 100
    assert b.aliases == []

    p = ProjectNode(_id="proj_123", canonical_name="Ashoka Meadows", city="Nashik")
    assert p.id == "proj_123"
    assert p.project_id == "proj_123"
    assert p.master_amenities == []

    loc = LocalityNode(_id="loc_nas_123", canonical_name="Gangapur Road", city="Nashik")
    assert loc.id == "loc_nas_123"
    assert loc.locality_id == "loc_nas_123"
    assert loc.pin_codes == []

    a = AmenityNode(_id="amen_lift", canonical_name="lift", display_name="Lift")
    assert a.id == "amen_lift"
    assert a.amenity_id == "amen_lift"
    assert a.weight == 10


@pytest.mark.asyncio
async def test_knowledge_graph_repository_methods(monkeypatch):
    # Mock database collections
    class MockCollection:
        def __init__(self, name):
            self.name = name
            self.indexes = []
            self.queries = []
        async def create_index(self, keys, **kwargs):
            self.indexes.append(keys)
        async def find_one(self, query):
            self.queries.append(query)
            if query.get("aliases") == "ashoka":
                return {"_id": "bldr_ashoka", "builder_id": "bldr_ashoka", "canonical_name": "Ashoka Builders"}
            if query.get("aliases") == "ashoka meadows":
                return {"_id": "proj_meadows", "project_id": "proj_meadows", "canonical_name": "Ashoka Meadows"}
            if query.get("aliases") == "gangapur road":
                return {"_id": "loc_gangapur", "locality_id": "loc_gangapur", "canonical_name": "Gangapur Road"}
            if query.get("aliases") == "lift":
                return {"_id": "amen_lift", "amenity_id": "amen_lift", "canonical_name": "lift"}
            return None

    class MockDB:
        def __init__(self):
            self.builders = MockCollection("builders")
            self.projects = MockCollection("projects")
            self.localities = MockCollection("localities")
            self.amenity_dictionary = MockCollection("amenity_dictionary")

    mock_db_instance = MockDB()
    monkeypatch.setattr(knowledge_graph_repo, "_get_db", lambda: mock_db_instance)

    # Test index creation
    await knowledge_graph_repo.create_indexes()
    assert len(mock_db_instance.builders.indexes) > 0
    assert len(mock_db_instance.projects.indexes) > 0
    assert len(mock_db_instance.localities.indexes) > 0
    assert len(mock_db_instance.amenity_dictionary.indexes) > 0

    # Test alias finders
    b_res = await knowledge_graph_repo.find_builder_by_alias("Nashik", "ashoka")
    assert b_res["builder_id"] == "bldr_ashoka"

    p_res = await knowledge_graph_repo.find_project_by_alias("Nashik", "ashoka meadows")
    assert p_res["project_id"] == "proj_meadows"

    l_res = await knowledge_graph_repo.find_locality_by_alias("Nashik", "gangapur road")
    assert l_res["locality_id"] == "loc_gangapur"

    a_res = await knowledge_graph_repo.find_amenity_by_alias("lift")
    assert a_res["amenity_id"] == "amen_lift"


def test_normalise_extracted_property_with_knowledge_graph():
    class SyncMockCollection:
        def __init__(self, name):
            self.name = name
            self.docs = {}
        def find_one(self, query):
            alias = query.get("aliases")
            if alias == "gangapur road":
                return {"_id": "loc_gangapur", "locality_id": "loc_gangapur", "canonical_name": "Gangapur Road"}
            if alias == "ashoka":
                return {"_id": "bldr_ashoka", "builder_id": "bldr_ashoka", "canonical_name": "Ashoka Builders"}
            if alias == "ashoka meadows":
                return {"_id": "proj_meadows", "project_id": "proj_meadows", "canonical_name": "Ashoka Meadows", "builder_id": "bldr_ashoka"}
            if alias == "lift":
                return {"_id": "amen_lift", "amenity_id": "amen_lift"}
            return None
        def insert_one(self, doc):
            self.docs[doc["_id"]] = doc

    class SyncMockDB:
        def __init__(self):
            self.cols = {
                "localities": SyncMockCollection("localities"),
                "builders": SyncMockCollection("builders"),
                "projects": SyncMockCollection("projects"),
                "amenity_dictionary": SyncMockCollection("amenity_dictionary"),
            }
        def __getitem__(self, item):
            return self.cols[item]

    db = SyncMockDB()

    # 1. Test with existing entities
    raw1 = {
        "title": "2 BHK in Ashoka Meadows",
        "city": "Nashik",
        "area": "Gangapur Road",
        "builder_name": "Ashoka",
        "project_name": "Ashoka Meadows",
        "amenities": ["Lift"],
        "price": 4500000,
        "broker_phone": "9876543210",
        "property_type": "apartment",
        "listing_type": "sale"
    }

    doc1 = normalise_extracted_property(raw1, "WhatsApp Group A", "hash123", db=db)
    assert doc1["locality_id"] == "loc_gangapur"
    assert doc1["builder_id"] == "bldr_ashoka"
    assert doc1["project_id"] == "proj_meadows"
    assert doc1["amenity_ids"] == ["amen_lift"]

    # 2. Test with new/unknown entities that trigger automatic node creation
    raw2 = {
        "title": "3 BHK in New Horizon",
        "city": "Nashik",
        "area": "Indira Nagar",
        "builder_name": "Suyojit",
        "project_name": "Suyojit Viridian",
        "amenities": ["Club House"],
        "price": 6500000,
        "broker_phone": "9876543210",
        "property_type": "apartment",
        "listing_type": "sale"
    }

    doc2 = normalise_extracted_property(raw2, "WhatsApp Group B", "hash456", db=db)
    assert doc2["locality_id"].startswith("loc_nas_")
    assert doc2["builder_id"].startswith("bldr_")
    assert doc2["project_id"].startswith("proj_")
    assert len(doc2["amenity_ids"]) == 1
    assert doc2["amenity_ids"][0].startswith("amen_club_house")
