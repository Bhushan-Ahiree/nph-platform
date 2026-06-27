# apps/api/routes/analytics.py
from fastapi import APIRouter, HTTPException, status
from apps.api.schemas.analytics_schemas import PipelineSummaryResponse, LeadSummaryResponse
from apps.api.schemas.lead_schemas import LeadResponse
from apps.api.repositories.analytics_repository import AnalyticsRepository
from apps.api.repositories.lead_repository import LeadRepository
from datetime import datetime, timezone

router = APIRouter(prefix="/analytics", tags=["CRM Operational Insights"])
analytics_repo = AnalyticsRepository()
lead_repo = LeadRepository()

@router.post("/followup/{lead_id}", response_model=LeadResponse)
async def log_followup_attempt(lead_id: str):
    """Increments a lead's follow-up interactions counter and recalculates priority metrics."""
    lead = await lead_repo.get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead '{lead_id}' not found.")

    current_count = lead.get("follow_up_count", 0) + 1
    
    # Update baseline metrics
    await analytics_repo.leads_col.update_one(
        {"lead_id": lead_id},
        {
            "$set": {
                "follow_up_count": current_count,
                "last_contacted_at": datetime.now(timezone.utc)
            }
        }
    )

    # Re-evaluate the hotness calculation matrix immediately
    await analytics_repo.calculate_and_update_hotness(lead_id)
    return await lead_repo.get_lead_by_id(lead_id)

@router.get("/pipeline", response_model=PipelineSummaryResponse)
async def get_system_pipeline_dashboard_metrics():
    """Fetches high-level operational funnel metrics from the cloud cluster instance."""
    try:
        return await analytics_repo.get_pipeline_metrics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Metrics compilation failed: {str(e)}")

@router.get("/lead-summary", response_model=LeadSummaryResponse)
async def get_lead_summary_metrics():
    """Generates counts for the CRM operations summary."""
    leads_col = analytics_repo.leads_col
    
    total = await leads_col.count_documents({})
    hot = await leads_col.count_documents({"lead_temperature": "HOT"})
    warm = await leads_col.count_documents({"lead_temperature": "WARM"})
    cold = await leads_col.count_documents({"lead_temperature": "COLD"})
    
    clients = await leads_col.count_documents({"lead_type": "CLIENT"})
    brokers = await leads_col.count_documents({"lead_type": "BROKER"})
    owners = await leads_col.count_documents({"lead_type": "OWNER"})
    
    instagram = await leads_col.count_documents({"source": "instagram"})
    whatsapp = await leads_col.count_documents({"source": "whatsapp"})
    website = await leads_col.count_documents({"source": "website"})
    
    return {
        "total_leads": total,
        "hot_leads": hot,
        "warm_leads": warm,
        "cold_leads": cold,
        "clients": clients,
        "brokers": brokers,
        "owners": owners,
        "instagram": instagram,
        "whatsapp": whatsapp,
        "website": website
    }