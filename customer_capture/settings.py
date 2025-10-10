"""
Environment-driven configuration for customer capture system.
"""
import os
from typing import Optional


class Settings:
    """Configuration loaded from environment variables."""
    
    @classmethod
    def _get_redis_url(cls) -> Optional[str]:
        return os.getenv("REDIS_URL")
    
    @classmethod
    def _get_cooldown_seconds(cls) -> int:
        return int(os.getenv("COOLDOWN_SECONDS", "90"))
    
    @classmethod
    def _get_finalize_after_both_seconds(cls) -> int:
        return int(os.getenv("FINALIZE_AFTER_BOTH_SECONDS", "20"))
    
    @classmethod
    def _get_gsheet_spreadsheet_id(cls) -> Optional[str]:
        return os.getenv("GSHEET_SPREADSHEET_ID")
    
    @classmethod
    def _get_gsheet_worksheet_title(cls) -> str:
        return os.getenv("GSHEET_WORKSHEET_TITLE", "Leads")
    
    @classmethod
    def _get_google_application_credentials(cls) -> Optional[str]:
        return os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    @classmethod
    def _get_dry_run(cls) -> bool:
        return os.getenv("DRY_RUN", "0") == "1"
    
    # Properties that read from environment each time
    @property
    def REDIS_URL(self) -> Optional[str]:
        return self._get_redis_url()
    
    @property
    def COOLDOWN_SECONDS(self) -> int:
        return self._get_cooldown_seconds()
    
    @property
    def FINALIZE_AFTER_BOTH_SECONDS(self) -> int:
        return self._get_finalize_after_both_seconds()
    
    @property
    def GSHEET_SPREADSHEET_ID(self) -> Optional[str]:
        return self._get_gsheet_spreadsheet_id()
    
    @property
    def GSHEET_WORKSHEET_TITLE(self) -> str:
        return self._get_gsheet_worksheet_title()
    
    @property
    def GOOGLE_APPLICATION_CREDENTIALS(self) -> Optional[str]:
        return self._get_google_application_credentials()
    
    @property
    def DRY_RUN(self) -> bool:
        return self._get_dry_run()
    
    def validate(self) -> None:
        """Validate required settings for production use."""
        if not self.DRY_RUN:
            if not self.GSHEET_SPREADSHEET_ID:
                raise ValueError("GSHEET_SPREADSHEET_ID is required when DRY_RUN=0")
            # Check for either file path or JSON environment variable
            import os
            if not self.GOOGLE_APPLICATION_CREDENTIALS and not os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON'):
                raise ValueError("Either GOOGLE_APPLICATION_CREDENTIALS file path or GOOGLE_SERVICE_ACCOUNT_JSON environment variable is required when DRY_RUN=0")


settings = Settings()

