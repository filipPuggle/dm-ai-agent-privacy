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
    r'(?:\+?373|0)?\s*[6-7]\d{7,8}(?=\s|$|\n)',
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


def parse_customer_message(text: str, location_context: Optional[str] = None) -> ParsedMessage:
    """
    Parse a customer message and extract entities.
    
    Args:
        text: Message text to parse
        location_context: Optional location context from webhook (e.g., "CHISINAU", "BALTI", "OTHER_MD")
    
    Returns ParsedMessage with extracted fields and confidence score.
    """
    if not text or not text.strip():
        return ParsedMessage(raw_message=text or "", confidence=0.0)
    
    # Extract entities (order matters: phone/postal first, then address, then location, then name)
    phone = extract_phone(text)
    postal_code = extract_postal_code(text)
    street_address = extract_street_address(text)  # Extract address before name
    location = extract_location(text, location_context=location_context)  # Extract location before name
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
    
    # Also try to find phone numbers that might not match the strict pattern
    # Look for 8-9 digit numbers starting with 06 or 07
    phone_candidates = re.findall(r'\b0[67]\d{6,7}\b', text)
    for candidate in phone_candidates:
        normalized = normalize_phone_md(candidate)
        if normalized:
            logger.debug(f"Found phone (fallback): {candidate} -> {normalized}")
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
    - Prioritize lines that look like actual names (short, capitalized)
    - Avoid conversation text and long phrases
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
    
    # First pass: Look for lines that look like actual names (short, simple)
    name_candidates = []
    
    for line in lines:
        # Skip lines with clear address/location keywords
        if has_address_keywords(line) or has_location_keywords(line):
            continue
        
        # Skip lines that look like locations (comma-separated capitalized words)
        if ',' in line and len([t for t in line.split(',') if t.strip() and t.strip()[0].isupper()]) >= 2:
            logger.debug(f"Skipping location-like line: {line}")
            continue
        
        # Skip lines that are too long (likely conversation text)
        if len(line.strip()) > 30:
            logger.debug(f"Skipping long line (likely conversation): {line}")
            continue
        
        # Skip lines with common conversation words
        conversation_words = ['vreau', 'vrea', 'poate', 'poți', 'pot', 'să', 'să', 'și', 'cu', 'la', 'în', 'pe', 'de', 'pentru', 'că', 'când', 'cum', 'unde', 'ce', 'care']
        if any(word in line.lower() for word in conversation_words):
            logger.debug(f"Skipping conversation line: {line}")
            continue
        
        # Extract word sequences
        tokens = extract_tokens(line)
        name_tokens = [t for t in tokens if t.isalpha()]  # Only alphabetic words
        
        # Filter out exclusions
        clean_tokens = [t for t in name_tokens if t.lower() not in NAME_EXCLUSIONS]
        
        if not clean_tokens:
            continue
        
        # Prioritize short, simple names
        if len(clean_tokens) == 1 and len(clean_tokens[0]) >= 3:
            # Single word name - high priority
            name_candidates.append((clean_tokens[0], 1))
        elif len(clean_tokens) == 2 and all(len(t) >= 3 for t in clean_tokens):
            # Two word name - medium priority
            name_candidates.append((' '.join(clean_tokens), 2))
        elif len(clean_tokens) >= 3 and all(len(t) >= 3 for t in clean_tokens):
            # Multi-word name - lower priority
            name_candidates.append((' '.join(clean_tokens), 3))
    
    # Return the best candidate (shortest priority number)
    if name_candidates:
        name_candidates.sort(key=lambda x: x[1])  # Sort by priority
        best_name = name_candidates[0][0]
        logger.debug(f"Found name: {best_name}")
        return best_name
    
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


def extract_location(text: str, location_context: Optional[str] = None) -> Optional[str]:
    """
    Extract location (settlement/district).
    Keywords: sat, comună, oraș, raion (RO) / село, коммуна, город, район (RU)
    Fallback: line with comma-separated places + postal code
    Skip lines that are already identified as street addresses.
    
    Args:
        text: Message text to parse
        location_context: Optional location context from webhook (e.g., "CHISINAU", "BALTI", "OTHER_MD")
    """
    # If we have location context from webhook, use it as the primary location
    if location_context:
        # Convert location context to proper location name
        if location_context == "CHISINAU":
            context_location = "Chișinău"
            logger.debug(f"Using location context: {context_location}")
            return context_location
        elif location_context == "BALTI":
            context_location = "Bălți"
            logger.debug(f"Using location context: {context_location}")
            return context_location
        elif location_context == "OTHER_MD":
            # For other locations, we still need to extract from text
            # but we'll be more careful about what we consider a location
            # and prioritize location extraction over name extraction
            logger.debug("Location context is OTHER_MD, will extract from text with higher priority")
        else:
            # Unknown location context, use as-is
            logger.debug(f"Using location context: {location_context}")
            return location_context
    
    all_keywords = LOCATION_KEYWORDS_RO + LOCATION_KEYWORDS_RU
    pattern = '|'.join(all_keywords)
    
    lines = text.split('\n')
    fallback_candidate = None
    
    # If we have OTHER_MD context, we know user mentioned a location earlier
    # So we should be more aggressive about finding location-like patterns
    has_location_context = (location_context == "OTHER_MD")
    
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
        
        # Skip lines that are too short (likely names)
        if len(line.strip()) < 5:
            continue
            
        # Skip lines that look like names (single word, short)
        tokens = extract_tokens(line)
        capitalized = [t for t in tokens if is_capitalized_token(t)]
        
        # Skip if it looks like a person's name (single word, 3-8 characters)
        if len(capitalized) == 1 and 3 <= len(capitalized[0]) <= 8:
            # Check if it's a common name pattern
            name_patterns = ['Alexandru', 'Alexandru', 'Maria', 'Ion', 'Ana', 'Cristina', 'Mihai', 'Andrei', 'Elena', 'Vlad', 'Diana', 'Radu', 'Ioana', 'Bogdan', 'Alina', 'Catalin', 'Roxana', 'Florin', 'Gabriela', 'Adrian', 'Filip', 'Vasile', 'Nicolae', 'Gheorghe', 'Constantin', 'Petru', 'Alexandru', 'Viorel', 'Iurie', 'Ion', 'Dumitru', 'Valeriu', 'Sergei', 'Vladimir', 'Igor', 'Oleg', 'Andrei', 'Dmitri', 'Mikhail']
            if capitalized[0] in name_patterns:
                logger.debug(f"Skipping likely name: {capitalized[0]}")
                continue
        
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
    
    # If we have location context but couldn't extract specific location from this message,
    # we should return a generic indication that location was mentioned earlier
    if has_location_context:
        logger.debug("Location context indicates user mentioned location earlier, but couldn't extract specific location from current message")
        return "Moldova (other location)"
    
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

