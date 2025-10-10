"""
Pydantic v2 models for customer data validation.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import pytz


class AddressBlock(BaseModel):
    """Structured address information."""
    street_address: Optional[str] = None  # str., bd., etc.
    location: Optional[str] = None  # sat, oraș, raion
    postal_code: Optional[str] = None  # 4-digit MD code


class ParsedMessage(BaseModel):
    """Single message parsing result."""
    full_name: Optional[str] = None
    contact_number: Optional[str] = None  # E.164 format
    address_block: AddressBlock = Field(default_factory=AddressBlock)
    raw_message: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)  # parsing confidence


class CustomerDetails(BaseModel):
    """Aggregated customer record ready for export."""
    platform_user_id: str
    full_name: Optional[str] = None
    contact_number: Optional[str] = None  # E.164 +373...
    adress: Optional[str] = None  # Keep original spelling from requirements
    location: Optional[str] = None
    postal_code: Optional[str] = None
    raw_message: str  # Concatenated original messages
    created_at: datetime
    record_id: str  # SHA256 hash for idempotency
    
    def to_sheets_row(self) -> dict:
        """Convert to Google Sheets row format (exact column order)."""
        # Convert to Chișinău time and format as MM/DD/YY HH:MM:SS
        chisinau_tz = pytz.timezone('Europe/Chisinau')
        chisinau_time = self.created_at.astimezone(chisinau_tz)
        formatted_datetime = chisinau_time.strftime('%m/%d/%y %H:%M:%S')
        
        return {
            "Full_Name": self.full_name or "",
            "Adress": self.adress or "",  # Keep spelling
            "Location": self.location or "",
            "Contact Number": self.contact_number or "",
            "Postal Code": self.postal_code or "",
            "Raw_Message": self.raw_message,
            "Created_At": formatted_datetime,
        }

