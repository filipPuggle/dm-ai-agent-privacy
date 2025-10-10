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
        # Support both old and new variable names
        return os.getenv("SPREADSHEET_ID") or os.getenv("GSHEET_SPREADSHEET_ID")
    
    @classmethod
    def _get_gsheet_worksheet_title(cls) -> str:
        # Support both old and new variable names
        return os.getenv("WORKSHEET_NAME") or os.getenv("GSHEET_WORKSHEET_TITLE", "Leads")
    
    @classmethod
    def _get_google_application_credentials(cls) -> Optional[str]:
        return os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    
    @classmethod
    def _get_dry_run(cls) -> bool:
        # Support both old and new variable names
        enable_dry_run = os.getenv("ENABLE_DRY_RUN", "").lower()
        if enable_dry_run in ("true", "1", "yes"):
            return True
        if enable_dry_run in ("false", "0", "no"):
            return False
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
                raise ValueError("SPREADSHEET_ID or GSHEET_SPREADSHEET_ID is required when DRY_RUN=false")
            # Check for any of the authentication methods
            import os
            has_json_creds = bool(os.getenv('GSHEET_CREDENTIALS_JSON') or os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON'))
            has_file_creds = bool(self.GOOGLE_APPLICATION_CREDENTIALS)
            has_individual_creds = bool(os.getenv('GCLOUD_PRIVATE_KEY') or os.getenv('GOOGLE_PRIVATE_KEY'))
            
            if not (has_json_creds or has_file_creds or has_individual_creds):
                raise ValueError("Google credentials required: Set GSHEET_CREDENTIALS_JSON, or GCLOUD_PRIVATE_KEY + GCLOUD_EMAIL, or provide credentials file")


settings = Settings()

