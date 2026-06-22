# apps/api/schemas/raw_ingestion_schemas.py
"""
Pydantic schemas that govern the mass text ingestion pipeline.
These types are used by the POST /properties/raw-chunk endpoint and the
Celery task that performs downstream AI extraction.
"""
from pydantic import BaseModel, Field


class RawChunkIngestionRequest(BaseModel):
    """
    Payload accepted by POST /properties/raw-chunk.
    'source_group' identifies the originating WhatsApp broker group name.
    'raw_text' is the full, unformatted copy-pasted chat dump.
    """
    source_group: str = Field(
        ...,
        min_length=2,
        max_length=256,
        description="Human-readable name of the originating WhatsApp broker group.",
        examples=["Nashik Brokers Premium - Group 7"]
    )
    raw_text: str = Field(
        ...,
        min_length=10,
        description="The full, raw unformatted copy-paste dump from a WhatsApp broker group chat.",
        examples=["2BHK available Indira Nagar 12k pm call 9876543210\n3BHK College Road 25k 9988776655"]
    )


class RawChunkIngestionResponse(BaseModel):
    """
    Immediate 202 Accepted response returned to the caller.
    Task processing continues asynchronously in Celery.
    """
    status: str = "accepted"
    event_id: str = Field(..., description="Idempotency key for this delivery, stored in webhook_events.")
    task_id: str = Field(..., description="Celery task ID for status tracking.")
    message: str = "Raw group dump accepted. AI extraction queued."
