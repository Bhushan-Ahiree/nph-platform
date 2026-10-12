import re
from typing import List, Tuple

class MessageSplitter:
    """
    Strategy-based chunker for raw unstructured real estate data.
    Automatically detects the best strategy to split a raw dump into individual property listings.
    """
    
    CONTINUATION_PATTERNS = [
        r"^price\s*[:\-]",
        r"^rent\s*[:\-]",
        r"^contact\s*[:\-]",
        r"^call\s*[:\-]",
        r"^mob\s*[:\-]",
        r"^📍",
        r"^📞",
        r"^💰",
        r"^area\s*[:\-]",
        r"^bhk\s*[:\-]",
        r"^floor\s*[:\-]",
    ]

    @classmethod
    def is_continuation(cls, block_text: str) -> bool:
        """Returns True if the block appears to be a continuation of a previous property listing."""
        text = block_text.strip().lower()
        for pat in cls.CONTINUATION_PATTERNS:
            if re.search(pat, text):
                return True
        return False

    @classmethod
    def apply_continuation_merge(cls, blocks: List[str]) -> List[str]:
        """Merges blocks that start with continuation patterns into the previous block."""
        if not blocks:
            return []
            
        merged = [blocks[0]]
        for i in range(1, len(blocks)):
            current = blocks[i]
            if cls.is_continuation(current):
                # Merge into the last block
                merged[-1] = merged[-1] + "\n\n" + current
            else:
                merged.append(current)
        return merged

    @classmethod
    def split(cls, raw_text: str) -> Tuple[str, List[str]]:
        """
        Main entrypoint to split text.
        Returns a tuple: (strategy_name, list_of_message_blocks)
        """
        if not raw_text or not raw_text.strip():
            return "empty", []

        # Normalise line endings
        normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")

        # 1. WhatsApp Timestamp Splitter
        # Looks for [DD/MM/YYYY, HH:MM] or DD/MM/YY, HH:MM - format
        wa_ts_pattern = r"(?:^|\n)(?:\[?\d{1,2}/\d{1,2}/\d{2,4}[,.]?\s*\d{1,2}:\d{2}(?:\s*[APap][Mm])?\]?\s*[-:]?\s*)"
        if re.search(wa_ts_pattern, normalized):
            # Split and keep the timestamp in the split if possible, or just split.
            # re.split keeps the delimiter if wrapped in capturing groups, but we can just split.
            parts = re.split(r"(?:^|\n)(?=\[?\d{1,2}/\d{1,2}/\d{2,4}[,.]?\s*\d{1,2}:\d{2}(?:\s*[APap][Mm])?\]?\s*[-:]?\s*)", normalized)
            blocks = [p.strip() for p in parts if p.strip()]
            if len(blocks) > 1:
                return "whatsapp_export", cls.apply_continuation_merge(blocks)

        # 2. Explicit MSG_BOUNDARY
        if "---MSG_BOUNDARY---" in normalized:
            blocks = [b.strip() for b in normalized.split("---MSG_BOUNDARY---") if b.strip()]
            return "explicit_boundary", cls.apply_continuation_merge(blocks)

        # 3. Double Blank Line Splitter (Paragraph Splitter)
        if re.search(r"\n\s*\n\s*\n", normalized):
            blocks = [b.strip() for b in re.split(r"\n\s*\n\s*\n+", normalized) if b.strip()]
            return "double_blank_line", cls.apply_continuation_merge(blocks)

        # 4. Smart Single Blank Line Splitter (with continuation logic)
        if re.search(r"\n\s*\n", normalized):
            blocks = [b.strip() for b in re.split(r"\n\s*\n+", normalized) if b.strip()]
            merged_blocks = cls.apply_continuation_merge(blocks)
            # Only use this if it actually resulted in multiple blocks
            if len(merged_blocks) > 1:
                return "smart_single_blank", merged_blocks

        # 5. Single Document Fallback
        return "single_document", [normalized.strip()]
