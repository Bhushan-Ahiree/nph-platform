# services/lead/scoring.py
from datetime import datetime, timezone

def calculate_priority_score(lead: dict) -> int:
    """
    Computes priority score based on lead quality and completeness.
    
    Weights:
      Requirements complete (area+bhk+listing_type)  +25
      Budget provided (max_price)                     +15
      Area provided                                   +15
      BHK provided                                    +15
      Responded within 24h (last_contacted_at)        +10
      lead_type CLIENT                                +15
      lead_type OWNER                                 +5
      lead_type BROKER                                +0
    """
    score = 0
    reqs = lead.get("requirements", {})
    
    # Requirements completeness
    has_area = bool(reqs.get("area"))
    has_bhk = bool(reqs.get("bhk"))
    has_listing_type = bool(reqs.get("listing_type"))
    has_budget = bool(reqs.get("max_price") or reqs.get("min_price"))
    
    if has_area and has_bhk and has_listing_type:
        score += 25
        
    if has_budget:
        score += 15
        
    if has_area:
        score += 15
        
    if has_bhk:
        score += 15
        
    # Recency of contact
    last_contacted_at = lead.get("last_contacted_at")
    if last_contacted_at:
        # If it's a string (from JSON), parse it. Otherwise assume datetime
        if isinstance(last_contacted_at, str):
            try:
                # Handle isoformat with or without Z
                last_contacted_at = datetime.fromisoformat(last_contacted_at.replace("Z", "+00:00"))
            except ValueError:
                last_contacted_at = None
                
    if last_contacted_at:
        now = datetime.now(timezone.utc)
        # Handle naive datetimes if they somehow slip in
        if last_contacted_at.tzinfo is None:
            last_contacted_at = last_contacted_at.replace(tzinfo=timezone.utc)
            
        time_diff = now - last_contacted_at
        if time_diff.total_seconds() <= 86400: # 24 hours
            score += 10
            
    # Lead type
    lead_type = lead.get("lead_type", "CLIENT")
    if lead_type == "CLIENT":
        score += 15
    elif lead_type == "OWNER":
        score += 5
        
    # Clamp 0-100
    return max(0, min(100, score))

def calculate_temperature(score: int) -> str:
    """Classifies a score into HOT, WARM, or COLD buckets."""
    if score >= 80:
        return "HOT"
    elif score >= 50:
        return "WARM"
    else:
        return "COLD"
