# apps/scraper/modules/normalizer.py
import re

class PropertyNormalizer:
    """Cleans, parses, and converts raw web-scraped strings into strict data types."""

    @staticmethod
    def normalize_price(raw_price: str) -> float:
        """Converts currency text strings (Lakhs/Crores) into clean numeric floats in INR."""
        if not raw_price:
            return 0.0
        
        # Clean out currency symbols and spaces, remove commas entirely
        cleaned = raw_price.lower().replace("₹", "").replace(",", "").strip()
        
        # Extract the first matching decimal or integer number string
        match = re.search(r"[-+]?\d*\.\d+|\d+", cleaned)
        if not match:
            return 0.0
        
        try:
            value = float(match.group())
            
            # Apply standard Indian Real Estate multiplier tracking rules
            if "cr" in cleaned or "crore" in cleaned:
                return value * 10_000_000
            elif "lakh" in cleaned or "lc" in cleaned or "l" in cleaned:
                return value * 100_000
            return value
        except ValueError:
            return 0.0

    @staticmethod
    def normalize_bhk(raw_bhk: str) -> int:
        if not raw_bhk:
            return 1
        match = re.search(r"\d+", raw_bhk)
        return int(match.group()) if match else 1

    @staticmethod
    def normalize_area(raw_area: str) -> float:
        if not raw_area:
            return 0.0
        match = re.search(r"\d+", raw_area.replace(",", ""))
        return float(match.group()) if match else 0.0