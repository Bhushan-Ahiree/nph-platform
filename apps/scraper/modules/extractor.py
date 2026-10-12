# apps/scraper/modules/extractor.py
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any

class PropertyExtractor:
    """Handles network connections and fallback HTML document parsing operations."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.selectors = config["selectors"]

    def fetch_raw_listings(self) -> List[Dict[str, Any]]:
        """Downloads HTML or injects local real estate mock metrics for validation."""
        raw_results = []
        html_content = ""

        # Define an internal production-grade sandbox data set for Nashik/Pune listings
        mock_html = """
        <div class="property-card">
            <h2 class="listing-title">Modern 2 BHK Apartment in Indira Nagar</h2>
            <span class="locality-text">Indira Nagar</span>
            <span class="price-amount">₹ 45 Lakhs</span>
            <span class="bhk-config">2 BHK</span>
            <div class="area-sqft">1050 sqft</div>
        </div>
        <div class="property-card">
            <h2 class="listing-title">Luxury 3 BHK Villa near Gangapur Road</h2>
            <span class="locality-text">Gangapur Road</span>
            <span class="price-amount">₹ 1.2 Crores</span>
            <span class="bhk-config">3 BHK</span>
            <div class="area-sqft">2400 sqft</div>
        </div>
        <div class="property-card">
            <h2 class="listing-title">Cozy 1 BHK Flat in Wakad Pune</h2>
            <span class="locality-text">Wakad</span>
            <span class="price-amount">₹ 32 Lakhs</span>
            <span class="bhk-config">1 BHK</span>
            <div class="area-sqft">650 sqft</div>
        </div>
        """

        base_url = self.config.get("base_url")
        if not base_url:
            print("[Extractor Notice] No base_url configured. Using the built-in sample dataset.")
            html_content = mock_html
        else:
            try:
                # Attempt to reach external target first
                response = requests.get(base_url, timeout=5)
                if response.status_code == 200:
                    html_content = response.text
                else:
                    print(f"[Extractor Notice] Remote URL hit {response.status_code}. Activating local sandbox dataset.")
                    html_content = mock_html
            except Exception:
                print("[Extractor Notice] Server unreachable. Activating local sandbox dataset.")
                html_content = mock_html
                
        soup = BeautifulSoup(html_content, "html.parser")
        cards = soup.select(self.selectors["card_container"])
        
        print(f"[Extractor] Isolated {len(cards)} raw target elements inside source document.")
        
        for card in cards:
            try:
                title = card.select_one(self.selectors["title"]).get_text(strip=True)
                locality = card.select_one(self.selectors["locality"]).get_text(strip=True)
                price = card.select_one(self.selectors["price"]).get_text(strip=True)
                bhk = card.select_one(self.selectors["bhk"]).get_text(strip=True)
                area = card.select_one(self.selectors["area"]).get_text(strip=True) if card.select_one(self.selectors["area"]) else ""
                
                raw_results.append({
                    "title": title,
                    "locality": locality,
                    "price_str": price,
                    "bhk_str": bhk,
                    "area_str": area
                })
            except AttributeError:
                continue
                
        return raw_results
