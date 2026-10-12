import re
from typing import Dict, Any, Optional, List, Tuple

class WhatsAppTokenizer:
    """
    Deterministic tokenizer and cleanser for raw WhatsApp group text dumps.
    Strips timestamps, forwarded headers, view channel links, emoji spam,
    and normalizes multiline text blocks for downstream extraction.
    """
    @staticmethod
    def clean_text(text: str) -> str:
        if not text:
            return ""
        s = str(text)
        # Strip WhatsApp timestamps e.g. [12/05/2026, 14:30] or [12/05/26, 2:30 PM] or 12/05/2026, 14:30 - 
        s = re.sub(r"\[?\d{1,2}/\d{1,2}/\d{2,4}[,.]?\s*\d{1,2}:\d{2}(?:\s*[APap][Mm])?\]?\s*[-:]?\s*", "", s)
        # Strip Forwarded headers
        s = re.sub(r"<This message was edited>", "", s, flags=re.IGNORECASE)
        s = re.sub(r"Forwarded\s*(?:message)?", "", s, flags=re.IGNORECASE)
        # Strip View Channel / WhatsApp invite links
        s = re.sub(r"View\s*Channel", "", s, flags=re.IGNORECASE)
        s = re.sub(r"https?://\S+|wa\.me/\S+|maps\.app\.goo\.gl/\S+", "", s)
        # Strip decorative stars and bullets used in WhatsApp formatting
        s = re.sub(r"[*~`#+💥👉🙏👇🎉✅🔴🟢🟡💥]+", " ", s)
        # Collapse excessive whitespace
        s = re.sub(r"\s+", " ", s).strip()
        return s

    @staticmethod
    def extract_urls_and_links(text: str) -> Dict[str, List[str]]:
        if not text:
            return {"urls": [], "whatsapp_links": []}
        s = str(text)
        urls = re.findall(r"https?://[^\s]+|maps\.app\.goo\.gl/[^\s]+", s)
        wa_links = re.findall(r"wa\.me/[^\s]+|whatsapp\.com/[^\s]+", s)
        return {"urls": list(set(urls)), "whatsapp_links": list(set(wa_links))}


class CategoryAExtractor:
    """
    Deterministic Entity Extractor for Category A fields.
    These fields must NEVER be calculated or extracted purely by the LLM.
    """
    @staticmethod
    def extract_phone(text: str) -> Optional[str]:
        if not text:
            return None
        # Look for typical 10-digit phone number patterns or +91 patterns
        digits = re.findall(r"(?:\+?91[\s\-]*)?[789]\d{9}|(?:\+?91[\s\-]*)?[789]\d{2}\s*\d{3}\s*\d{4}|(?:\+?91[\s\-]*)?[789]\d{4}\s*\d{5}", str(text))
        if not digits:
            # Fallback scan for any 10 consecutive digits
            all_digits = re.sub(r"\D", "", str(text))
            if len(all_digits) >= 10:
                # Find valid Indian mobile starting with 6,7,8,9
                match = re.search(r"([6789]\d{9})", all_digits)
                if match:
                    return match.group(1)
            return None
        clean = re.sub(r"\D", "", digits[0])
        if len(clean) == 12 and clean.startswith("91"):
            return clean[2:]
        if len(clean) == 10:
            return clean
        return None

    @staticmethod
    def extract_price(text: str) -> Dict[str, Any]:
        """
        Rigorous deterministic parser for Indian pricing tokens (Lakh, Crore, Thousand, etc.)
        as well as Marathi/Hindi terms (लाख, कोटी, हजार).
        """
        if not text:
            return {"price": 0, "price_raw": None}
        s = str(text).lower()

        # Check explicit rent/price/offer keywords first to avoid matching deposit (e.g. डिपॉझिट = 30हजार vs भाडे = 13000)
        match_kw_unit = re.search(r"(?:भाडे|rent|price|offer)\s*[-=:]?\s*([0-9]+(?:\.[0-9]+)?)\s*(cr|crore|crores|कोटी|lakh|lakhs|lac|lacs|लाख|k|thousand|हजार)", s)
        if match_kw_unit:
            val = float(match_kw_unit.group(1))
            unit = match_kw_unit.group(2)
            mult = 10000000 if any(u in unit for u in ("cr", "crore", "crores", "कोटी")) else (100000 if any(u in unit for u in ("lakh", "lakhs", "lac", "lacs", "लाख")) else 1000)
            return {"price": int(val * mult), "price_raw": match_kw_unit.group(0).strip()}

        match_kw = re.search(r"(?:भाडे|rent|price|offer|rs\.?|₹)\s*[-=:]?\s*([0-9]{3,8})", s)
        if match_kw:
            val = int(match_kw.group(1))
            return {"price": val, "price_raw": match_kw.group(0).strip()}

        # Match explicit price mentions with units: e.g. 40 lakh, 12.50 cr, 25 lakh, 40 लाख, 1.21 cr
        # Strip out deposit mentions before scanning for general units
        s_no_dep = re.sub(r"(?:deposit|डिपॉझिट|adv|advance)\s*[-=:]?\s*[0-9]+(?:\.[0-9]+)?\s*(?:k|thousand|हजार|lakh|lakhs|lac|lacs|लाख)?", "", s)

        patterns = [
            (r"([0-9]+(?:\.[0-9]+)?)\s*(cr|crore|crores|कोटी)", 10000000),
            (r"([0-9]+(?:\.[0-9]+)?)\s*(lakh|lakhs|lac|lacs|लाख)", 100000),
            (r"([0-9]+(?:\.[0-9]+)?)\s*(k|thousand|हजार)", 1000)
        ]
        
        for pat, mult in patterns:
            match = re.search(pat, s_no_dep)
            if match:
                val = float(match.group(1))
                price = int(val * mult)
                return {"price": price, "price_raw": match.group(0).strip()}

        # Look for standalone large numbers (e.g. 10000, 13000, 1150000, 4500000)
        match_num = re.findall(r"\b([1-9]\d{3,7})\b", s_no_dep)
        for num_str in match_num:
            # Exclude typical phone numbers or pin codes if any slip through
            val = int(num_str)
            if val != 40000000 and val != 48000000 and val != 58000000: # Exclude known LLM hallucination values if passed back
                return {"price": val, "price_raw": num_str}

        return {"price": 0, "price_raw": None}

    @staticmethod
    def extract_area(text: str) -> Dict[str, Any]:
        """
        Rigorous deterministic parser for area units (sqft, sqm, guntha, acre, vaar)
        including Marathi textual numbers (दोन गुंठे, 400 ते 500 वाराचा).
        """
        if not text:
            return {"carpet_area_sqft": None, "area_raw": None}
        s = str(text).lower()

        # Translate Marathi number words for common land sizes
        marathi_nums = {"एक": 1, "दोन": 2, "तीन": 3, "चार": 4, "पाच": 5, "दहा": 10, "वीस": 20, "पन्नास": 50, "शंभर": 100}
        for m_word, m_val in marathi_nums.items():
            s = re.sub(rf"\b{m_word}\s+(गुंठे|गुंठा|acre|acres|एकर|war|vaar|वार|वारा)\b", rf"{m_val} \g<1>", s)

        # Range patterns like 400 ते 500 वाराचा (take the average or upper bound; let's take average 450)
        match_range = re.search(r"(\d+)\s*(?:ते|to|-)\s*(\d+)\s*(vaar|war|वार|वारा|sqft|guntha|गुंठा|गुंठे)", s)
        if match_range:
            avg_val = (float(match_range.group(1)) + float(match_range.group(2))) / 2.0
            unit = match_range.group(3)
            mult = 9 if any(u in unit for u in ("vaar", "war", "वार", "वारा")) else (1089 if any(u in unit for u in ("guntha", "गुंठा", "गुंठे")) else 1)
            return {"carpet_area_sqft": int(avg_val * mult), "area_raw": match_range.group(0).strip()}

        patterns = [
            (r"([0-9]+(?:\.[0-9]+)?)\s*(acre|acres|एकर)", 43560),
            (r"([0-9]+(?:\.[0-9]+)?)\s*(guntha|gunthas|gunthe|gunta|guntas|गुंठे|गुंठा)", 1089),
            (r"([0-9]+(?:\.[0-9]+)?)\s*(vaar|vaars|war|wars|sqyd|sqyds|sqyard|sqyards|वार|वारा)", 9),
            (r"([0-9]+(?:\.[0-9]+)?)\s*(sqmeter|sqmeters|sqm)", 10.7639),
            (r"([0-9]+(?:\.[0-9]+)?)\s*(sqft|sqfts|sq\.ft|sq\s*ft)", 1)
        ]

        for pat, mult in patterns:
            match = re.search(pat, s)
            if match:
                val = float(match.group(1))
                return {"carpet_area_sqft": int(val * mult), "area_raw": match.group(0).strip()}

        # Standalone numbers before specific keywords like 'plot' or 'land'
        match_plot = re.search(r"(\d{3,5})\s*(?:var|varach|sqft)?\s*plot", s)
        if match_plot:
            val = float(match_plot.group(1))
            # If < 4000, likely vaar in Nashik context if 'var' is present, but let's check original text
            if "var" in match_plot.group(0):
                return {"carpet_area_sqft": int(val * 9), "area_raw": match_plot.group(0).strip()}
            return {"carpet_area_sqft": int(val), "area_raw": match_plot.group(0).strip()}

        return {"carpet_area_sqft": None, "area_raw": None}

    @staticmethod
    def extract_bhk(text: str) -> Dict[str, Any]:
        if not text:
            return {"bhk": 0, "bhk_raw": None}
        s = str(text).lower()
        match = re.search(r"(\d)\s*(bhk|rk|bedroom)", s)
        if match:
            return {"bhk": int(match.group(1)), "bhk_raw": match.group(0).strip()}
        return {"bhk": 0, "bhk_raw": None}

    @staticmethod
    def detect_intent(text: str) -> Dict[str, Any]:
        """
        Deterministic classifier for Requirement/Inquiry vs Offer/Sale/Rent.
        Also infers listing_type and property_type from ground-truth keywords.
        """
        if not text:
            return {"is_requirement": False, "listing_type": "rent", "property_type": "apartment"}
        s = str(text).lower()

        # Requirement / Inquiry keywords
        req_keywords = ["पाहिजे", "रिक्वायरमेंट", "wanted", "requirement", "required", "need", "looking for", "buyer", "पाहिजेत"]
        is_req = any(kw in s for kw in req_keywords)

        # Transaction / Listing type
        listing_type = "rent"
        if any(kw in s for kw in ["विकणे", "विकायचा", "outrate", "sale", "for sale", "buy", "विकत", "sell"]):
            listing_type = "sale"
        elif any(kw in s for kw in ["lease", "long lease"]):
            listing_type = "lease"
        elif any(kw in s for kw in ["pg", "paying guest"]):
            listing_type = "pg"
        elif any(kw in s for kw in ["roommate"]):
            listing_type = "roommate"
        elif any(kw in s for kw in ["jv", "joint venture"]):
            listing_type = "jv"
        elif any(kw in s for kw in ["भाड्याने", "भाडे", "rent", "for rent"]):
            listing_type = "rent"

        # Asset / Property type
        property_type = "apartment"
        if any(kw in s for kw in ["plot", "प्लॉट"]):
            property_type = "plot"
        elif any(kw in s for kw in ["land", "jgh", "जमीन", "acre", "acres", "guntha", "gunthe", "adivasi", "shivar"]):
            property_type = "land"
        elif any(kw in s for kw in ["commercial", "shop", "office", "warehouse", "hotel", "industrial"]):
            property_type = "commercial"
        elif any(kw in s for kw in ["villa", "row house", "रो हाऊस", "bungalow", "house"]):
            property_type = "villa"
        elif any(kw in s for kw in ["flat", "apartment", "bhk", "फ्लॅट", "rk"]):
            property_type = "apartment"

        return {
            "is_requirement": is_req,
            "listing_type": listing_type,
            "property_type": property_type
        }


class CategoryBExtractor:
    """
    LLM-Assisted Entity Extractor. Pre-matches structured values using
    deterministic rules to provide hints/ground-truth to the LLM.
    """
    @staticmethod
    def extract_entities(text: str) -> Dict[str, Any]:
        if not text:
            return {}
        s = str(text).lower()
        
        # Furnishing status
        furnishing = None
        if any(k in s for k in ("fully furnished", "full furnish", "fully")):
            furnishing = "Fully Furnished"
        elif any(k in s for k in ("semi furnished", "semi furnish", "सेमी फर्निश", "semi")):
            furnishing = "Semi Furnished"
        elif any(k in s for k in ("unfurnished", "no furnish")):
            furnishing = "Unfurnished"

        # Possession status
        possession = None
        if any(k in s for k in ("ready possession", "ready move", "ready to move", "ready")):
            possession = "Ready Possession"
        elif any(k in s for k in ("under construction", "uc", "construction")):
            possession = "Under Construction"
        elif any(k in s for k in ("immediate",)):
            possession = "Immediate Possession"

        # Poster type
        poster = "Broker"
        if any(k in s for k in ("owner", "malik", "malak", "direct owner")):
            poster = "Owner"
        elif any(k in s for k in ("builder", "developer")):
            poster = "Builder"
        elif any(k in s for k in ("channel partner", "cp")):
            poster = "Channel Partner"

        # Common amenities scan
        amenities = []
        for a in ["lift", "parking", "terrace", "garden", "security", "club house", "power backup", "swimming pool"]:
            if a in s:
                amenities.append(a.title())

        return {
            "furnishing_status": furnishing,
            "possession_status": possession,
            "poster_type": poster,
            "amenities": amenities
        }
