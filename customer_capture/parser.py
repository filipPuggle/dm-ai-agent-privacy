"""
Multilingual entity extractor for Romanian/Russian customer data.
Extracts: Full Name, Phone, Address, Location, Postal Code.
"""
import re
import logging
from typing import Optional
from .models import ParsedMessage, AddressBlock
from .utils import normalize_phone_md, is_capitalized_token, extract_tokens

logger = logging.getLogger(__name__)


# === Phone Pattern (Moldova +373) ===
PHONE_PATTERN = re.compile(
    r'(?:\+?373|0)?\s*[6-7]\s*[\d\.\s]{7,9}(?=\s|$|\n)',
    re.IGNORECASE
)

# === Postal Code Pattern (MD) ===
POSTAL_CODE_PATTERN = re.compile(
    r'\b(?:MD-?)?(\d{4})\b',
    re.IGNORECASE
)

# === Location Keywords (RO + RU) ===
LOCATION_KEYWORDS_RO = [
    r'\bsat(?:ul)?\b', r'\bcomun[aă]\b', r'\bora[șs](?:ul)?\b', 
    r'\braion(?:ul)?\b', r'\brnul\b', r'\br-nul\b', r'\bmun\.\b', r'\bmunicipi(?:ul)?\b'
]

LOCATION_KEYWORDS_RU = [
    r'\bсело\b', r'\bкоммуна\b', r'\bгород\b', 
    r'\bрайон\b', r'\bмун\.\b'
]

# === Address (Street) Keywords (RO + RU) ===
ADDRESS_KEYWORDS_RO = [
    r'\bstr\.', r'\bstrada\b', r'\bbd\.', r'\bbulevardul\b',
    r'\bbloc\b', r'\bap\.', r'\bapartament\b', r'\bsc\.', r'\bscara\b',
    r'\bnr\.', r'\bnumărul\b', r'\bnr\b'
]

ADDRESS_KEYWORDS_RU = [
    r'\bул\.', r'\bулица\b', r'\bдом\b', r'\bд\.',
    r'\bкв\.', r'\bквартира\b', r'\bподъезд\b'
]

# === Anti-keywords (words that should NOT be part of a name) ===
NAME_EXCLUSIONS_RO = {
    'sat', 'satul', 'comuna', 'oraș', 'orașul', 'raion', 'raionul', 
    'str', 'strada', 'bd', 'bulevardul', 'bloc', 'ap', 'sc', 'nr',
    'numarul', 'numele', 'mun'
}

NAME_EXCLUSIONS_RU = {
    'село', 'коммуна', 'город', 'район', 'ул', 'улица', 'дом', 
    'кв', 'квартира', 'подъезд', 'мун'
}

# Common English words to exclude
NAME_EXCLUSIONS_EN = {
    'hello', 'hi', 'hey', 'thanks', 'thank', 'please', 'yes', 'no',
    'ok', 'okay', 'good', 'bad', 'how', 'are', 'you', 'what', 'when',
    'where', 'who', 'why'
}

# Combine all exclusions (lowercase for comparison)
NAME_EXCLUSIONS = NAME_EXCLUSIONS_RO | NAME_EXCLUSIONS_RU | NAME_EXCLUSIONS_EN


def parse_customer_message(text: str) -> ParsedMessage:
    """
    Parse a customer message and extract entities.
    
    Returns ParsedMessage with extracted fields and confidence score.
    """
    if not text or not text.strip():
        return ParsedMessage(raw_message=text or "", confidence=0.0)
    
    # Extract entities (order matters: phone/postal first, then address, then location, then name)
    phone = extract_phone(text)
    postal_code = extract_postal_code(text)
    street_address = extract_street_address(text)  # Extract address before name
    location = extract_location(text)  # Extract location before name
    name = extract_name(text)  # Extract name last to avoid conflicts
    
    # Calculate confidence
    confidence = calculate_confidence(
        has_name=name is not None,
        has_phone=phone is not None,
        has_location=location is not None,
        has_postal=postal_code is not None,
        has_address=street_address is not None
    )
    
    address_block = AddressBlock(
        street_address=street_address,
        location=location,
        postal_code=postal_code
    )
    
    return ParsedMessage(
        full_name=name,
        contact_number=phone,
        address_block=address_block,
        raw_message=text,
        confidence=confidence
    )


def extract_phone(text: str) -> Optional[str]:
    """Extract and normalize phone number from text."""
    matches = PHONE_PATTERN.findall(text)
    
    for match in matches:
        normalized = normalize_phone_md(match)
        if normalized:
            logger.debug(f"Found phone: {match} -> {normalized}")
            return normalized
    
    return None


def extract_postal_code(text: str) -> Optional[str]:
    """Extract postal code (4 digits, optional MD- prefix)."""
    match = POSTAL_CODE_PATTERN.search(text)
    if match:
        code = match.group(1)  # Extract just the digits
        logger.debug(f"Found postal code: {code}")
        return code
    return None


def extract_name(text: str) -> Optional[str]:
    """
    Extract full name from text.
    
    Logic:
    - Favor capitalized tokens (Latin/Cyrillic)
    - Accept single token ("Ina") or 2+ tokens ("Rufa Irina")
    - Exclude location/address keywords
    - Handle "Numele <name>" pattern
    """
    # Handle "Numele meu este <name>" pattern (RO)
    numele_match = re.search(r'\bnumele\s+meu\s+este\s+([\w\u0102\u0103\u00C2\u00E2\u00CE\u00EE\u0218\u0219\u021A\u021B]+(?:\s+[\w\u0102\u0103\u00C2\u00E2\u00CE\u00EE\u0218\u0219\u021A\u021B]+)*)',
                            text, re.IGNORECASE | re.UNICODE)
    if numele_match:
        candidate = numele_match.group(1).strip()
        tokens = candidate.split()
        # Filter out exclusions
        clean_tokens = [t for t in tokens if t.lower() not in NAME_EXCLUSIONS]
        if clean_tokens:
            name = ' '.join(clean_tokens)
            logger.debug(f"Found name via 'Numele meu este' pattern: {name}")
            return name
    
    # Handle "Numele <name>" pattern (RO)
    numele_match = re.search(r'\bnumele\s+([\w\u0102\u0103\u00C2\u00E2\u00CE\u00EE\u0218\u0219\u021A\u021B]+(?:\s+[\w\u0102\u0103\u00C2\u00E2\u00CE\u00EE\u0218\u0219\u021A\u021B]+)*)',
                            text, re.IGNORECASE | re.UNICODE)
    if numele_match:
        candidate = numele_match.group(1).strip()
        tokens = candidate.split()
        # Filter out exclusions
        clean_tokens = [t for t in tokens if t.lower() not in NAME_EXCLUSIONS]
        if clean_tokens:
            name = ' '.join(clean_tokens)
            logger.debug(f"Found name via 'Numele' pattern: {name}")
            return name
    
    # Split text into lines for better segmentation
    lines = text.split('\n')
    
    # Try to find name in each line
    for line in lines:
        # Skip lines with clear address/location keywords
        if has_address_keywords(line) or has_location_keywords(line):
            continue
        
        # Skip lines that look like locations (comma-separated capitalized words)
        if ',' in line and len([t for t in line.split(',') if t.strip() and t.strip()[0].isupper()]) >= 2:
            logger.debug(f"Skipping location-like line: {line}")
            continue
        
        # Extract capitalized word sequences
        tokens = extract_tokens(line)
        capitalized = [t for t in tokens if is_capitalized_token(t)]
        
        # Filter out exclusions
        clean_tokens = [t for t in capitalized if t.lower() not in NAME_EXCLUSIONS]
        
        if not clean_tokens:
            continue
        
        # Single capitalized word (e.g., "Ina")
        if len(clean_tokens) == 1:
            # Check if it looks like a name (not a city or keyword)
            if len(clean_tokens[0]) >= 3:  # At least 3 chars
                logger.debug(f"Found single-token name: {clean_tokens[0]}")
                return clean_tokens[0]
        
        # Two or more capitalized words
        elif len(clean_tokens) >= 2:
            name = ' '.join(clean_tokens)  # Take all capitalized words
            logger.debug(f"Found multi-token name: {name}")
            return name
    
    return None


def extract_street_address(text: str) -> Optional[str]:
    """
    Extract street address.
    Keywords: str., bd., ул., дом, etc.
    Fallback: Lines that look like street addresses (word + number pattern).
    Priority: If a line has both address and location keywords, prioritize address.
    """
    all_keywords = ADDRESS_KEYWORDS_RO + ADDRESS_KEYWORDS_RU
    pattern = '|'.join(all_keywords)
    
    lines = text.split('\n')
    
    for line in lines:
        # Check if line contains street/address keywords
        if re.search(pattern, line, re.IGNORECASE):
            # Clean up: remove phone and postal code
            clean = re.sub(PHONE_PATTERN, '', line)
            clean = re.sub(POSTAL_CODE_PATTERN, '', clean)
            clean = clean.strip(' ,.\n')
            
            # Remove common prefixes
            clean = re.sub(r'^(adresa|adress|адрес):\s*', '', clean, flags=re.IGNORECASE)
            clean = clean.strip()
            
            if clean:
                logger.debug(f"Found street address (with keywords): {clean}")
                return clean
    
    # Fallback: Look for lines that look like street addresses (word + number)
    for line in lines:
        # Skip lines that are phone numbers or postal codes
        if PHONE_PATTERN.search(line) or POSTAL_CODE_PATTERN.search(line):
            continue
            
        # Look for pattern: word(s) + number (e.g., "Lenin 14", "Strada Mihai Viteazu 25")
        if re.search(r'\b\w+\s+\d+\b', line):
            clean = line.strip()
            # Remove common prefixes
            clean = re.sub(r'^(adresa|adress|адрес):\s*', '', clean, flags=re.IGNORECASE)
            clean = clean.strip()
            if clean and len(clean) > 3:  # At least 3 characters
                logger.debug(f"Found street address (fallback): {clean}")
                return clean
    
    return None


def extract_location(text: str) -> Optional[str]:
    """
    Extract location (settlement/district).
    Keywords: sat, comună, oraș, raion (RO) / село, коммуна, город, район (RU)
    Fallback: line with comma-separated places + postal code
    Skip lines that are already identified as street addresses.
    """
    all_keywords = LOCATION_KEYWORDS_RO + LOCATION_KEYWORDS_RU
    pattern = '|'.join(all_keywords)
    
    lines = text.split('\n')
    fallback_candidate = None
    
    for line in lines:
        # Skip if this line has street/address keywords (prioritize street address)
        if has_address_keywords(line):
            continue
        
        # Check if line contains location keywords
        if re.search(pattern, line, re.IGNORECASE):
            # Clean up the line: remove phone and postal code
            clean = re.sub(PHONE_PATTERN, '', line)
            clean = re.sub(POSTAL_CODE_PATTERN, '', clean)
            clean = clean.strip(' ,.\n')
            
            # Remove location keywords from the result
            clean = re.sub(r'\b(?:sat(?:ul)?|comun[aă]|ora[șs](?:ul)?|raion(?:ul)?|rnul|r-nul|mun\.|municipi(?:ul)?)\b', '', clean, flags=re.IGNORECASE)
            clean = clean.strip(' ,.\n')
            
            if clean:
                logger.debug(f"Found location: {clean}")
                return clean
        
        # Fallback heuristic: line with postal code + comma-separated capitalized words
        # Example: "Sauca, Ocnita, 7133"
        if not fallback_candidate and POSTAL_CODE_PATTERN.search(line):
            # Check if it has comma and capitalized words
            if ',' in line:
                # Remove postal code and check
                clean = re.sub(POSTAL_CODE_PATTERN, '', line)
                clean = re.sub(PHONE_PATTERN, '', clean)
                clean = clean.strip(' ,.\n')
                
                # If it has capitalized words and commas, likely a location
                tokens = extract_tokens(clean)
                capitalized = [t for t in tokens if is_capitalized_token(t)]
                
                if len(capitalized) >= 2 and ',' in clean:
                    fallback_candidate = clean
    
    if fallback_candidate:
        logger.debug(f"Found location (fallback): {fallback_candidate}")
        return fallback_candidate
    
    # Final fallback: Look for capitalized words that might be location names
    # But be very conservative - only single capitalized words that look like place names
    for line in lines:
        # Skip lines that are phone numbers, postal codes, or have address keywords
        if (PHONE_PATTERN.search(line) or POSTAL_CODE_PATTERN.search(line) or 
            has_address_keywords(line)):
            continue
            
        # Skip lines that look like names (multiple capitalized words)
        tokens = extract_tokens(line)
        capitalized = [t for t in tokens if is_capitalized_token(t)]
        
        # Consider single capitalized words that are longer than 3 characters
        # This helps avoid picking up short names like "Ion", "Ana", etc.
        if len(capitalized) == 1 and len(capitalized[0]) > 3:
            clean = line.strip()
            # Remove common prefixes
            clean = re.sub(r'^(localitatea|localitate|место|город):\s*', '', clean, flags=re.IGNORECASE)
            clean = clean.strip()
            if clean and len(clean) > 3:
                logger.debug(f"Found location (final fallback): {clean}")
                return clean
    
    return None


def has_location_keywords(text: str) -> bool:
    """Check if text contains location keywords."""
    all_keywords = LOCATION_KEYWORDS_RO + LOCATION_KEYWORDS_RU
    pattern = '|'.join(all_keywords)
    return bool(re.search(pattern, text, re.IGNORECASE))


def has_address_keywords(text: str) -> bool:
    """Check if text contains address/street keywords."""
    all_keywords = ADDRESS_KEYWORDS_RO + ADDRESS_KEYWORDS_RU
    pattern = '|'.join(all_keywords)
    return bool(re.search(pattern, text, re.IGNORECASE))


def calculate_confidence(has_name: bool, has_phone: bool, 
                        has_location: bool, has_postal: bool,
                        has_address: bool = False) -> float:
    """
    Calculate parsing confidence score.
    
    Priority: Name + Phone are most important, then address/location details.
    """
    score = 0.0
    
    if has_name:
        score += 0.4
    if has_phone:
        score += 0.4
    if has_address:
        score += 0.1
    if has_location:
        score += 0.05
    if has_postal:
        score += 0.05
    
    return min(score, 1.0)

