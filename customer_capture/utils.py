"""
Utility functions for phone normalization, hashing, and logging.
"""
import re
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


def normalize_phone_md(raw: str) -> Optional[str]:
    """
    Normalize Moldovan phone numbers to E.164 format (+373).
    
    Accepts:
    - 068977378
    - 079013356
    - +37369507012
    - 069 682 881
    - (0)689 51991
    
    Returns: +3736xxxxxxx or +3737xxxxxxx, or None if invalid.
    """
    # Remove all non-digits
    digits = re.sub(r'\D', '', raw)
    
    if not digits:
        return None
    
    # Handle various formats
    # Format: 0XXXXXXXX (9 digits starting with 0) or 0XXXXXXX (8 digits starting with 0)
    if len(digits) in (8, 9) and digits[0] == '0':
        # Extract last 7 or 8 digits and check if starts with 6 or 7
        last_digits = digits[1:]
        if last_digits[0] in ('6', '7'):
            return f"+373{last_digits}"
    
    # Format: 373XXXXXXXX (11 digits starting with 373)
    if len(digits) == 11 and digits.startswith('373'):
        last8 = digits[3:]
        if last8[0] in ('6', '7'):
            return f"+{digits}"
    
    # Format: XXXXXXXX (8 digits starting with 6 or 7)
    if len(digits) == 8 and digits[0] in ('6', '7'):
        return f"+373{digits}"
    
    # Format: 37XXXXXXXX (10 digits - might be missing leading 3)
    if len(digits) == 10 and digits.startswith('37') and digits[2] in ('6', '7'):
        return f"+3{digits}"
    
    logger.warning(f"Could not normalize phone: {raw} (digits: {digits})")
    return None


def generate_record_id(platform_user_id: str, normalized_phone: Optional[str]) -> str:
    """
    Generate idempotent record ID: SHA256(platform_user_id | normalized_phone | date(UTC)).
    """
    date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    phone_part = normalized_phone or "NO_PHONE"
    payload = f"{platform_user_id}|{phone_part}|{date_str}"
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def is_cyrillic(text: str) -> bool:
    """Check if text contains Cyrillic characters."""
    return bool(re.search(r'[\u0400-\u04FF]', text))


def extract_tokens(text: str) -> list[str]:
    """Extract word tokens from text, preserving case."""
    # Split on whitespace and common separators, but keep words intact
    # Include Romanian special characters: ăâîșț and Cyrillic
    # Unicode ranges: Latin, Cyrillic, Romanian diacritics
    return re.findall(r'[\w\u0102\u0103\u00C2\u00E2\u00CE\u00EE\u0218\u0219\u021A\u021B]+', text, re.UNICODE)


def is_capitalized_token(token: str) -> bool:
    """Check if token is capitalized (first letter uppercase)."""
    return len(token) > 0 and token[0].isupper()

