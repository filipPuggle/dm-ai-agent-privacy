"""
Environment-driven configuration for customer capture system.
"""
import os
from typing import Optional


class Settings:
    """Configuration loaded from environment variables."""
    
    # Redis connection (optional, fallback to in-memory)
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL")
    
    # Aggregation timing
    COOLDOWN_SECONDS: int = int(os.getenv("COOLDOWN_SECONDS", "90"))
    FINALIZE_AFTER_BOTH_SECONDS: int = int(os.getenv("FINALIZE_AFTER_BOTH_SECONDS", "20"))
    
    # Google Sheets configuration
    GSHEET_SPREADSHEET_ID: Optional[str] = os.getenv("GSHEET_SPREADSHEET_ID")
    GSHEET_WORKSHEET_TITLE: str = os.getenv("GSHEET_WORKSHEET_TITLE", "Leads")
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    # Dry run mode (skip actual exports)
    DRY_RUN: bool = os.getenv("DRY_RUN", "0") == "1"
    
    @classmethod
    def validate(cls) -> None:
        """Validate required settings for production use."""
        if not cls.DRY_RUN:
            if not cls.GSHEET_SPREADSHEET_ID:
                raise ValueError("GSHEET_SPREADSHEET_ID is required when DRY_RUN=0")
            if not cls.GOOGLE_APPLICATION_CREDENTIALS:
                raise ValueError("GOOGLE_APPLICATION_CREDENTIALS is required when DRY_RUN=0")


settings = Settings()

