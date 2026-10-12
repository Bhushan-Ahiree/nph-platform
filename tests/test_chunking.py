import pytest
from shared.utils.chunking import MessageSplitter

def test_whatsapp_export_strategy():
    text = (
        "[12/05/26, 14:30] Sender A: 2 BHK Flat for sale\n"
        "Price: 30 Lakh\n\n"
        "Contact: 9999999999\n"
        "[12/05/26, 14:32] Sender B: 3 BHK Villa\n"
        "Price: 1 Cr\n"
    )
    strategy, blocks = MessageSplitter.split(text)
    assert strategy == "whatsapp_export"
    assert len(blocks) == 2
    assert "2 BHK Flat" in blocks[0]
    assert "3 BHK Villa" in blocks[1]

def test_explicit_boundary_strategy():
    text = (
        "Property 1: 1 BHK\n"
        "---MSG_BOUNDARY---\n"
        "Property 2: 2 BHK\n"
    )
    strategy, blocks = MessageSplitter.split(text)
    assert strategy == "explicit_boundary"
    assert len(blocks) == 2
    assert "Property 1" in blocks[0]
    assert "Property 2" in blocks[1]

def test_double_blank_line_strategy():
    text = (
        "🏡 1 BHK Flat\n\n"
        "Rent: 15k\n\n\n"
        "🏡 2 BHK Flat\n"
        "Rent: 20k\n"
    )
    strategy, blocks = MessageSplitter.split(text)
    assert strategy == "double_blank_line"
    assert len(blocks) == 2
    assert "1 BHK Flat" in blocks[0]
    assert "2 BHK Flat" in blocks[1]

def test_continuation_merge_on_smart_single_blank():
    text = (
        "Property 1 details\n\n"
        "Price: 50 Lakh\n\n"
        "Contact: 9876543210\n\n"
        "Property 2 details\n\n"
        "Rent: 25k\n"
    )
    strategy, blocks = MessageSplitter.split(text)
    assert strategy == "smart_single_blank"
    assert len(blocks) == 2
    assert "Price: 50 Lakh" in blocks[0]
    assert "Contact: 9876543210" in blocks[0]
    assert "Rent: 25k" in blocks[1]

def test_single_document_fallback():
    text = (
        "Only one property listing here.\n"
        "It doesn't have multiple blocks.\n"
    )
    strategy, blocks = MessageSplitter.split(text)
    assert strategy == "single_document"
    assert len(blocks) == 1

def test_emoji_heavy_and_marathi_posts():
    text = (
        "🔥 [ Big Offer ]🔥\n"
        "🏠 3Bhk Flat – full furnished\n"
        "🛑 Rent: ₹20k\n\n\n"
        "🙏(ओमभाऊ प्रॉपर्टी)🙏\n"
        "स्वस्तात मस्त प्लॉट\n"
        "📞 9000000009\n"
    )
    strategy, blocks = MessageSplitter.split(text)
    assert strategy == "double_blank_line"
    assert len(blocks) == 2
    assert "Big Offer" in blocks[0]
    assert "स्वस्तात मस्त" in blocks[1]
    
def test_continuation_patterns():
    # Test that continuation words at the beginning of a block are detected
    assert MessageSplitter.is_continuation("Price: 50 Lakh") == True
    assert MessageSplitter.is_continuation("Rent: 25k") == True
    assert MessageSplitter.is_continuation("Contact: 9876543210") == True
    assert MessageSplitter.is_continuation("Mob - 9999") == True
    assert MessageSplitter.is_continuation("📞 Call now") == True
    assert MessageSplitter.is_continuation("📍 Location details") == True
    assert MessageSplitter.is_continuation("Not a continuation") == False
