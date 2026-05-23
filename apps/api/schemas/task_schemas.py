# apps/api/schemas/task_schemas.py
from pydantic import BaseModel, Field

class AnalyticsTaskTrigger(BaseModel):
    locality: str = Field(..., description="Target sub-market area inside Nashik or Pune", examples=["Indira Nagar", "Wakad"])