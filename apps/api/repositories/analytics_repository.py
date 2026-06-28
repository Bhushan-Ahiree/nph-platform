# apps/api/repositories/analytics_repository.py
from datetime import datetime, timezone


class AnalyticsRepository:
    """Computes and persists CRM operational analytics and scoring metrics."""

    @property
    def leads_col(self):
        """Dynamically fetches the leads collection via shared database singleton."""
        from shared.utils.database import db
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.leads

    @property
    def matches_col(self):
        """Dynamically fetches the matches collection via shared database singleton."""
        from shared.utils.database import db
        if db.client is None:
            raise RuntimeError("Database client is not initialized yet.")
        return db.client.nph_core.matches

    async def calculate_and_update_hotness(self, lead_id: str) -> int:
        """Computes the core operational business priority rating for a target user profile."""
        lead = await self.leads_col.find_one({"id": lead_id})
        if not lead:
            return 0

        score = 0

        # 1. Match Density Calculation (Max 40)
        match_count = await self.matches_col.count_documents({"lead_id": lead_id, "score": {"$gte": 70}})
        score += min(match_count * 10, 40)

        # 2. Engagement Intent Tracking (Max 40)
        if lead.get("site_visit_booked"):
            score += 20
        if lead.get("site_visit_paid"):
            score += 20

        # 3. Time Friction Decay (Negative Weight)
        follow_ups = lead.get("follow_up_count", 0)
        score -= (follow_ups * 10)

        # Enforce strict boundary limits [0, 100]
        final_score = max(0, min(score, 100))

        # Commit score directly back into your cloud document base
        await self.leads_col.update_one(
            {"id": lead_id},
            {"$set": {"hotness_score": final_score}}
        )
        return final_score

    async def get_pipeline_metrics(self) -> dict:
        """Aggregates all system statuses instantly to deliver performance metrics summaries."""
        total_leads = await self.leads_col.count_documents({})
        hot = await self.leads_col.count_documents({"hotness_score": {"$gte": 70}})
        warm = await self.leads_col.count_documents({"hotness_score": {"$gte": 40, "$lt": 70}})
        cold = await self.leads_col.count_documents({"hotness_score": {"$lt": 40}})

        visits_booked = await self.leads_col.count_documents({"site_visit_booked": True})
        visits_paid = await self.leads_col.count_documents({"site_visit_paid": True})
        closed_deals = await self.leads_col.count_documents({"deal_closed": True})

        # Calculate dynamic monetary indicators
        cursor = self.leads_col.find({"deal_closed": True}, {"deal_value": 1})
        deals = await cursor.to_list(length=1000)
        total_rev = sum(float(d.get("deal_value", 0)) for d in deals)

        conversion_rate = (closed_deals / total_leads * 100) if total_leads > 0 else 0.0

        return {
            "total_active_leads": total_leads,
            "hot_leads_count": hot,
            "warm_leads_count": warm,
            "cold_leads_count": cold,
            "site_visits_booked": visits_booked,
            "site_visits_paid": visits_paid,
            "conversion_rate_percentage": round(conversion_rate, 2),
            "total_deal_revenue": total_rev
        }