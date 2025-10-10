"""
Tests for multilingual parser.
Covers all 7 required test cases plus edge cases.
"""
import pytest
from customer_capture.parser import parse_customer_message
from customer_capture.utils import normalize_phone_md


class TestPhoneNormalization:
    """Test phone number normalization."""
    
    def test_simple_8_digit(self):
        assert normalize_phone_md("68977378") == "+37368977378"
        assert normalize_phone_md("79013356") == "+37379013356"
    
    def test_with_leading_zero(self):
        assert normalize_phone_md("068977378") == "+37368977378"
        assert normalize_phone_md("079013356") == "+37379013356"
        assert normalize_phone_md("069682881") == "+37369682881"
    
    def test_with_spaces(self):
        assert normalize_phone_md("069 682 881") == "+37369682881"
        assert normalize_phone_md("068 977 378") == "+37368977378"
    
    def test_with_parentheses(self):
        assert normalize_phone_md("(0)689 51991") == "+37368951991"
    
    def test_with_country_code(self):
        assert normalize_phone_md("+37369507012") == "+37369507012"
        assert normalize_phone_md("37369507012") == "+37369507012"
    
    def test_invalid_numbers(self):
        assert normalize_phone_md("123456") is None
        assert normalize_phone_md("999999999") is None  # Wrong prefix
        assert normalize_phone_md("") is None


class TestParserCase1:
    """Test Case 1: Rufa Irina, Sat Giurgiulești, postal, phone"""
    
    def test_case_1(self):
        text = "Rufa Irina\nSat Giurgiulești\n5318\n068977378"
        parsed = parse_customer_message(text)
        
        assert parsed.full_name == "Rufa Irina"
        assert parsed.contact_number == "+37368977378"
        assert parsed.address_block.location == "Sat Giurgiulești"
        assert parsed.address_block.postal_code == "5318"
        assert parsed.confidence >= 0.8


class TestParserCase2:
    """Test Case 2: Location first, then name and phone"""
    
    def test_case_2(self):
        text = "Raionul Hîncești satul Mingir\nMacaru Veronica\n069682881"
        parsed = parse_customer_message(text)
        
        assert parsed.full_name == "Macaru Veronica"
        assert parsed.contact_number == "+37369682881"
        assert parsed.address_block.location == "Raionul Hîncești satul Mingir"
        assert parsed.confidence >= 0.8


class TestParserCase3:
    """Test Case 3: Name, street address, phone"""
    
    def test_case_3(self):
        text = "Pleşciuc Camelia\nstr. Independenței 48/44, orașul Leova\n068370666"
        parsed = parse_customer_message(text)
        
        assert parsed.full_name == "Pleşciuc Camelia"
        assert parsed.contact_number == "+37368370666"
        # Street address might capture the whole line
        assert parsed.address_block.street_address is not None
        assert "str. Independenței" in parsed.address_block.street_address
        assert parsed.confidence >= 0.8


class TestParserCase4:
    """Test Case 4: Phone first, then single-token name"""
    
    def test_case_4(self):
        text = "079013356\nIna"
        parsed = parse_customer_message(text)
        
        assert parsed.full_name == "Ina"
        assert parsed.contact_number == "+37379013356"
        assert parsed.confidence >= 0.8


class TestParserCase5:
    """Test Case 5: Simple name and phone"""
    
    def test_case_5(self):
        text = "Railean Cristina\n068951991"
        parsed = parse_customer_message(text)
        
        assert parsed.full_name == "Railean Cristina"
        assert parsed.contact_number == "+37368951991"
        assert parsed.confidence >= 0.8


class TestParserCase6:
    """Test Case 6: Cyrillic address, full data"""
    
    def test_case_6(self):
        text = "Natalia Popa\nCodrilor, д. 10\nSauca, Ocnita, 7133\n+37369507012"
        parsed = parse_customer_message(text)
        
        assert parsed.full_name == "Natalia Popa"
        assert parsed.contact_number == "+37369507012"
        assert parsed.address_block.street_address is not None
        assert "д. 10" in parsed.address_block.street_address  # Russian "дом"
        assert parsed.address_block.location is not None
        assert parsed.address_block.postal_code == "7133"
        assert parsed.confidence >= 0.8


class TestParserCase7:
    """Test Case 7: "Numele" pattern, location, phone"""
    
    def test_case_7(self):
        text = "Numele cobzari Ionela, comuna Burlacu raionul Cahul, 067876429"
        parsed = parse_customer_message(text)
        
        assert parsed.full_name is not None
        assert "Ionela" in parsed.full_name or "cobzari" in parsed.full_name.lower()
        assert parsed.contact_number == "+37367876429"
        assert parsed.address_block.location is not None
        assert "comuna" in parsed.address_block.location
        assert parsed.confidence >= 0.8


class TestParserEdgeCases:
    """Edge cases and additional scenarios."""
    
    def test_only_phone(self):
        text = "068977378"
        parsed = parse_customer_message(text)
        
        assert parsed.contact_number == "+37368977378"
        assert parsed.full_name is None
    
    def test_only_name(self):
        text = "Maria Popescu"
        parsed = parse_customer_message(text)
        
        assert parsed.full_name == "Maria Popescu"
        assert parsed.contact_number is None
    
    def test_empty_message(self):
        text = ""
        parsed = parse_customer_message(text)
        
        assert parsed.confidence == 0.0
    
    def test_cyrillic_name(self):
        text = "Наталья Попова\n068977378"
        parsed = parse_customer_message(text)
        
        assert parsed.full_name == "Наталья Попова"
        assert parsed.contact_number == "+37368977378"
    
    def test_mixed_latin_cyrillic(self):
        text = "Ana Иванова\n069682881"
        parsed = parse_customer_message(text)
        
        # Should extract at least one name token
        assert parsed.full_name is not None
        assert parsed.contact_number == "+37369682881"
    
    def test_postal_with_md_prefix(self):
        text = "John Doe\nMD-2001\n068977378"
        parsed = parse_customer_message(text)
        
        assert parsed.address_block.postal_code == "2001"
    
    def test_no_useful_data(self):
        text = "Hello, how are you?"
        parsed = parse_customer_message(text)
        
        assert parsed.confidence < 0.3  # Low confidence

