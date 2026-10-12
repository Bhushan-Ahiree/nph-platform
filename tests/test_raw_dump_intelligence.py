from unittest.mock import patch
from apps.worker.tasks.ingestion_tasks import (
    preprocess_whatsapp_text,
    is_real_estate_listing,
    process_raw_group_dump
)
from shared.utils.normalization import normalise_extracted_property, compute_ingestion_hash

# Sample raw dump from production WhatsApp group
SAMPLE_RAW_DUMP = """
https://chat.whatsapp.com/EXAMPLEINVITE01
🏡 Want to generate more real estate leads using just your mobile phone?

📱 Join the Real Estate Mobile Video Marketing Workshop and learn how to create professional property reels that help attract more buyers, sellers, and business opportunities.

📍 Dadar West, Mumbai
🗓️ Sunday, 28 June 2026
⏰ 9:30 AM onwards

👇 Click the button below for more information & registration.
🔗 https://wa.me/919000000007?text=IAM_Ready_to_Join_workshop

https://chat.whatsapp.com/EXAMPLEINVITE02
खरोली दापुरे आदिवासी ३. ५ एकर वैतारना बॅक. वॉटर
३५ लाख एकरी
https://maps.google.com/maps?q=19.8555439%2C73.5119391&z=17&hl=en

Join fastest-growing WhatsApp business network— where real deals happen everyday!🚀

☑️ 200+⚡Exclusive Business Groups 
☑️ 800+ Other More Niche WhatsApp Groups 
☑️ 50k+ Active Members — your target audience is already here
☑️ Promote • Collaborate • Generate Leads • Grow Sales

Perfect for: 
Entrepreneurs, Startups, Freelancers, Real Estates, Investors, Funding, Jobs seekers, Buyers & Sellers, Marketing & Promotions !
-----
One-Time Investment = Lifetime Growth! 💰📈

🔰Special Offer: ₹399 only —Limited Time ⏰
📩https://wa.me/+919000000003?text=Wp-10x
DM if you're interested⏳

Follow the PRELEASED PROPERTY PAN INDIA channel on WhatsApp: https://whatsapp.com/channel/0029VbCHRpfF1YlZBouTi92F

New Member Can Follow This Channel for updated All Prelesed Property in This Group..

Looking for a high-potential real estate investment?

✨ Presenting – Mountain view’s Farmhouse Plots
📍 Just 8km from Trimbakeshwar
🌿 Surrounded by the serene Sahyadri Hills
🕉️ Strategically located near the site of Mahakumbh 2027 – Huge tourism & rental potential!

✅ Starting at just ₹735/sqft
✅ 3+Acres | Nature-focused & vastu-aligned
✅ Ideal for a premium weekend home or retreat villa
✅ Perfect long-term asset for future growth & lifestyle
✅ Tree Plantation 
✅water Line
✅Security Cabin
✅Electricity 
✅Authentic Gate
✅ WBM Road
✅Plate Compound 
✅street Light 

🧘 Live the peaceful life you deserve. Or earn from the tourism boom ahead!

Team,
shree land developers

♦️serious buyers Msg only 
☎️9000000004

55" inch 
Sony Bravia 
model no:KD55A8F 

OLED 4K ULTRA UHD SMART ANDROID ALEXA BLUETOOTH GOOGLE TV
 MRP168900
 Rs63000 

Samsung led tv 

43inch samsung model no:QA-43QN70F

QLED 4K ULTRA UHD SMART ANDROID ALEXA BLUETOOTH TAIZAN TV
MRP54900
Rs33000

Vinod Sonawane 
Mo 86 68 96 96 98 

OGENERAL AC 5star
 compressor 4 year
 guarantee warranty
⚙️ 1 YEAR OTHER part guarantee
1 ton 5star Ogeneral model no:ASGA12FTTA-AB 25
Mrp58900
Rs30000

[11:04 am, 27/06/2026] +91 90000 00001: 👉 नाशिक येथे जत्रा हॉटेल जवळ पार्क साईड च्या पाठी मागे 1 BHK लक्झरीयस फ्लॅट विकणे आहे 🙏
👉 650 SQFT फ्लॅट
👉 100 SQFT पार्किंग
👉 मास्टर बेड रूम
👉 पहिला मजला ( लिफ्ट, पार्किंग आहे )

💥ऑफर = 28 लाख💥

💥 संपर्क = यश खरवंटे = 9000000001

[2:16 pm, 25/06/2026] +91 93456 78012: 🏠 ROOM PARTNERS WANTED – 2 BOYS
👨🦱 Vacancy for 2 Boys
🏡 Flat: 1 BHK
💰 Rent: ₹1900rs per Person
🔐 Deposit: ₹6,000
❌ No Brokerage
📍 Location:
Mahajan Nagar , Uttam Nagar, Nashik 
📞 Contact:
9000000006
"""

def test_preprocess_whatsapp_text():
    cleaned = preprocess_whatsapp_text(SAMPLE_RAW_DUMP)
    # Timestamps should be stripped
    assert "[11:04 am, 27/06/2026]" not in cleaned
    assert "[2:16 pm, 25/06/2026]" not in cleaned
    # Channel links should be stripped
    assert "https://whatsapp.com/channel/0029VbCHRpfF1YlZBouTi92F" not in cleaned

def test_is_real_estate_listing_spam_filtering():
    # Test absolute spam rejection
    assert not is_real_estate_listing("55 inch Sony Bravia model no:KD55A8F OLED 4K ULTRA UHD SMART ANDROID")
    assert not is_real_estate_listing("Samsung led tv 43inch samsung model no:QA-43QN70F QLED 4K")
    assert not is_real_estate_listing("OGENERAL AC 5star compressor 4 year guarantee warranty")
    assert not is_real_estate_listing("Join Real Estate Mobile Video Marketing Workshop and learn how to create property reels")
    assert not is_real_estate_listing("Join fastest-growing WhatsApp business network— where real deals happen everyday! Promote • Collaborate")

    # Test true positive acceptance
    assert is_real_estate_listing("नाशिक येथे जत्रा हॉटेल जवळ 1 BHK लक्झरीयस फ्लॅट विकणे आहे 650 SQFT फ्लॅट 28 लाख")
    assert is_real_estate_listing("ROOM PARTNERS WANTED – 2 BOYS Flat: 1 BHK Rent: 1900rs per Person")
    assert is_real_estate_listing("खरोली दापुरे आदिवासी ३. ५ एकर वैतारना बॅक. वॉटर ३५ लाख एकरी")

def test_normalise_extracted_property_intelligence():
    # 1. Test Marathi price and area parsing
    raw_marathi = {
        "title": "1 BHK Flat near Jatra Hotel",
        "description": "Luxurious flat on first floor",
        "property_type": "apartment",
        "listing_type": "sale",
        "city": "Nashik",
        "area": "Jatra Hotel",
        "bhk": 1,
        "price": "28 लाख",
        "carpet_area_sqft": "650 sqft",
        "broker_phone": "+919000000001",
        "ownership_type": "broker"
    }
    hash_val = compute_ingestion_hash("2800000", "Jatra Hotel", 1, "sale", "9000000001")
    normalised = normalise_extracted_property(raw_marathi, "Nashik Group 1", hash_val)
    assert normalised["price"] == 2800000
    assert normalised["normalized_price_inr"] == 2800000
    assert normalised["carpet_area_sqft"] == 650
    assert normalised["normalized_area_sqft"] == 650

    # 2. Test Agricultural Marathi area (एकर)
    raw_agri = {
        "title": "Tribal Land Vaitarna Backwater",
        "property_type": "agricultural",
        "listing_type": "sale",
        "city": "Nashik",
        "area": "Kharoli",
        "price": "35 लाख",
        "carpet_area_sqft": "3.5 एकर",
        "broker_phone": "9876543210"
    }
    normalised_agri = normalise_extracted_property(raw_agri, "Nashik Group 1", "hash2")
    assert normalised_agri["price"] == 3500000
    assert normalised_agri["carpet_area_sqft"] == int(3.5 * 43560)  # 152460 sqft
    assert normalised_agri["property_type"] == "agricultural"

    # 3. Test PG / Roommate terms
    raw_pg = {
        "title": "ROOM PARTNERS WANTED – 2 BOYS",
        "property_type": "roommate",
        "listing_type": "pg",
        "city": "Nashik",
        "area": "Mahajan Nagar",
        "price": "1900rs per Person",
        "broker_phone": "9000000006"
    }
    normalised_pg = normalise_extracted_property(raw_pg, "Nashik Group 1", "hash3")
    assert normalised_pg["price"] == 1900
    assert normalised_pg["property_type"] == "roommate"
    assert normalised_pg["listing_type"] == "pg"

@patch("apps.worker.tasks.ingestion_tasks.get_db")
@patch("apps.worker.tasks.ingestion_tasks.call_ollama_extract")
def test_process_raw_group_dump_integration(mock_call_ollama, mock_get_db, mock_db):
    mock_get_db.return_value = mock_db.client.nph_core
    # Mock Ollama output to simulate extracted properties covering all routing cases
    mock_call_ollama.side_effect = [[
        # 1. Standard Property (goes to properties collection)
        {
            "title": "1 BHK Apartment near Jatra Hotel",
            "description": "First floor, parking available",
            "property_type": "apartment",
            "listing_type": "sale",
            "city": "Nashik",
            "area": "Jatra Hotel",
            "bhk": 1,
            "price": 2800000,
            "carpet_area_sqft": 650,
            "broker_phone": "9000000001",
            "ownership_type": "broker",
            "raw_text": "Sample raw text"
        },
        # 2. PG / Roommate Property (goes to pg_listings collection)
        {
            "title": "ROOM PARTNERS WANTED  2 BOYS",
            "description": "Mahajan Nagar, Uttam Nagar",
            "property_type": "roommate",
            "listing_type": "pg",
            "city": "Nashik",
            "area": "Mahajan Nagar",
            "bhk": 1,
            "price": 1900,
            "broker_phone": "9000000006",
            "ownership_type": "owner",
            "raw_text": "PG for boys on rent"
        },
        # 3. Agricultural Land (goes to agricultural_jv_listings collection)
        {
            "title": "115 acres tribal land Shahapur",
            "description": "Table land near highway",
            "property_type": "agricultural",
            "listing_type": "sale",
            "city": "Nashik",
            "area": "Shahapur",
            "bhk": 0,
            "price": 1000000, # per acre
            "broker_phone": "9000000005",
            "ownership_type": "broker",
            "raw_text": "agricultural land for sale"
        },
        # 4. Out of network property (goes to out_of_network_properties collection)
        {
            "title": "2 BHK Flat in Thane West",
            "description": "Near station, prime area",
            "property_type": "apartment",
            "listing_type": "sale",
            "city": "Thane",
            "area": "Thane West",
            "bhk": 2,
            "price": 12000000,
            "broker_phone": "9999999999",
            "ownership_type": "broker",
            "raw_text": "2 bhk flat for sale"
        }
    ]] + [[]] * 20

    summary = process_raw_group_dump(
        source_group="Production Raw Dump Group",
        raw_text=SAMPLE_RAW_DUMP,
        event_id="evt_raw_123"
    )

    assert summary["status"] == "completed"
    assert summary["inserted"] == 1  # Only the standard property goes to properties
    assert summary["pg_routed"] == 1  # PG property goes to pg_listings
    assert summary["agri_discarded"] == 1  # Agricultural property goes to agricultural_jv_listings
    assert summary["out_of_geo"] == 1  # Thane property goes to out_of_network_properties
    assert summary["spam_filtered"] > 0  # Sony/Samsung/OGeneral ads get filtered out

    # Verify documents in MongoDB collections
    db = mock_db.client.nph_core
    assert db.properties.count_documents({"title": "1 BHK Apartment near Jatra Hotel"})._value == 1
    assert db.pg_listings.count_documents({"title": "ROOM PARTNERS WANTED  2 BOYS"})._value == 1
    assert db.agricultural_jv_listings.count_documents({"title": "115 acres tribal land Shahapur"})._value == 1
    assert db.out_of_network_properties.count_documents({"title": "2 BHK Flat in Thane West"})._value == 1
