"""
Google Sheets exporter with upsert capability.
Exports customer data to Google Sheets via service account.
"""
import logging
from typing import Optional
from .models import CustomerDetails
from .settings import settings

logger = logging.getLogger(__name__)


# Exact column order as specified
SHEET_COLUMNS = [
    "Full_Name",
    "Adress",  # Keep spelling
    "Location",
    "Contact Number",
    "Postal Code",
    "Raw_Message",
    "Created_At",
]


class GoogleSheetsExporter:
    """Export customer records to Google Sheets."""
    
    def __init__(self):
        self.worksheet = None
        self._initialized = False
    
    def _initialize(self) -> None:
        """Initialize Google Sheets connection."""
        if self._initialized:
            return
        
        if settings.DRY_RUN:
            logger.info("DRY_RUN mode: skipping Google Sheets initialization")
            self._initialized = True
            return
        
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            
            # Validate settings
            settings.validate()
            
            # Setup credentials
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            
            # Try environment variable first, then file
            import os
            import json
            
            # Try multiple authentication methods in order of preference
            auth_success = False
            
            # Method 1: Try NEW environment variable JSON first
            json_env = os.getenv('GSHEET_CREDENTIALS_JSON') or os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
            if json_env and not auth_success:
                try:
                    # Clean and parse JSON from environment variable
                    cleaned_json = json_env.strip()
                    service_account_info = json.loads(cleaned_json)
                    
                    # Validate required fields
                    required_fields = ['type', 'project_id', 'private_key', 'client_email']
                    for field in required_fields:
                        if field not in service_account_info:
                            raise ValueError(f"Missing required field: {field}")
                    
                    creds = Credentials.from_service_account_info(
                        service_account_info,
                        scopes=scopes
                    )
                    logger.info("✅ Using Google Sheets authentication from environment variable")
                    auth_success = True
                except Exception as e:
                    logger.warning(f"❌ Environment variable JSON failed: {e}")
            
            # Method 2: Try file authentication
            if not auth_success and settings.GOOGLE_APPLICATION_CREDENTIALS and os.path.exists(settings.GOOGLE_APPLICATION_CREDENTIALS):
                try:
                    creds = Credentials.from_service_account_file(
                        settings.GOOGLE_APPLICATION_CREDENTIALS,
                        scopes=scopes
                    )
                    logger.info("✅ Using Google Sheets authentication from file")
                    auth_success = True
                except Exception as e:
                    logger.warning(f"❌ File authentication failed: {e}")
            
            # Method 3: Try individual environment variables (NEW names first, then fallback to old)
            if not auth_success:
                try:
                    # Try NEW variable names first, fallback to old names
                    private_key = (os.getenv('GCLOUD_PRIVATE_KEY') or 
                                   os.getenv('GOOGLE_PRIVATE_KEY') or '')
                    client_email = (os.getenv('GCLOUD_EMAIL') or 
                                    os.getenv('GOOGLE_CLIENT_EMAIL') or 
                                    'customer-capture-bot@customer-capture-system-474710.iam.gserviceaccount.com')
                    project_id = (os.getenv('GCLOUD_PROJECT') or 
                                  os.getenv('GOOGLE_PROJECT_ID') or 
                                  'customer-capture-system-474710')
                    key_id = (os.getenv('GCLOUD_KEY_ID') or 
                              os.getenv('GOOGLE_PRIVATE_KEY_ID') or 
                              '13251ed782f68320e5d880830af4c676d59484d9')
                    client_id = (os.getenv('GCLOUD_CLIENT_ID') or 
                                 os.getenv('GOOGLE_CLIENT_ID') or 
                                 '111153201774146294036')
                    
                    # Try to construct credentials from individual env vars
                    service_account_info = {
                        "type": "service_account",
                        "project_id": project_id,
                        "private_key_id": key_id,
                        "private_key": private_key,
                        "client_email": client_email,
                        "client_id": client_id,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                        "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{client_email.replace('@', '%40')}",
                        "universe_domain": "googleapis.com"
                    }
                    
                    if service_account_info['private_key']:
                        creds = Credentials.from_service_account_info(
                            service_account_info,
                            scopes=scopes
                        )
                        logger.info("✅ Using Google Sheets authentication from individual environment variables")
                        auth_success = True
                except Exception as e:
                    logger.warning(f"❌ Individual environment variables failed: {e}")
            
            if not auth_success:
                raise ValueError("No valid Google service account credentials found in any method")
            
            gc = gspread.authorize(creds)
            
            # Open spreadsheet and worksheet
            spreadsheet = gc.open_by_key(settings.GSHEET_SPREADSHEET_ID)
            
            try:
                self.worksheet = spreadsheet.worksheet(settings.GSHEET_WORKSHEET_TITLE)
            except gspread.WorksheetNotFound:
                # Create worksheet if it doesn't exist
                self.worksheet = spreadsheet.add_worksheet(
                    title=settings.GSHEET_WORKSHEET_TITLE,
                    rows=1000,
                    cols=len(SHEET_COLUMNS)
                )
            
            # Ensure header row exists
            self._ensure_headers()
            
            self._initialized = True
            logger.info(f"Google Sheets initialized: {settings.GSHEET_SPREADSHEET_ID}/{settings.GSHEET_WORKSHEET_TITLE}")
            
        except FileNotFoundError as e:
            logger.error(f"Google service account file not found: {e}")
            logger.error("Please ensure GOOGLE_APPLICATION_CREDENTIALS points to a valid file, or set GOOGLE_SERVICE_ACCOUNT_JSON environment variable")
            if settings.DRY_RUN:
                logger.warning("DRY_RUN mode: Continuing without Google Sheets")
                self._initialized = True
                return
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets: {e}")
            if settings.DRY_RUN:
                logger.warning("DRY_RUN mode: Continuing without Google Sheets")
                self._initialized = True
                return
            raise
    
    def _ensure_headers(self) -> None:
        """Ensure the first row has correct headers."""
        if not self.worksheet:
            return
        
        try:
            first_row = self.worksheet.row_values(1)
            
            # If empty or incorrect, set headers
            if not first_row or first_row != SHEET_COLUMNS:
                self.worksheet.update('A1:G1', [SHEET_COLUMNS])
                logger.info("Set header row in Google Sheets")
        except Exception as e:
            logger.warning(f"Could not check/set headers: {e}")
    
    def upsert(self, customer: CustomerDetails) -> bool:
        """
        Append customer record to Google Sheets.
        
        Always appends new row since Record_Id is removed.
        Returns True on success.
        """
        try:
            self._initialize()
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets: {e}")
            if settings.DRY_RUN:
                logger.warning("DRY_RUN mode: Logging data instead of exporting")
                row_data = customer.to_sheets_row()
                row_values = [row_data.get(col, "") for col in SHEET_COLUMNS]
                logger.info(f"DRY_RUN: Would append row: {dict(zip(SHEET_COLUMNS, row_values))}")
                return True
            return False
        
        row_data = customer.to_sheets_row()
        
        # Format row in correct column order
        row_values = [row_data.get(col, "") for col in SHEET_COLUMNS]
        
        if settings.DRY_RUN:
            logger.info(f"DRY_RUN: Would append row: {dict(zip(SHEET_COLUMNS, row_values))}")
            return True
        
        try:
            # Always append new row
            logger.info(f"Appending new row for customer: {customer.full_name}")
            self.worksheet.append_row(row_values, value_input_option='RAW')
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to append to Google Sheets: {e}")
            return False


# Global exporter instance
_exporter: Optional[GoogleSheetsExporter] = None


def get_exporter() -> GoogleSheetsExporter:
    """Get or create global exporter instance."""
    global _exporter
    if _exporter is None:
        _exporter = GoogleSheetsExporter()
    return _exporter


def export_customer(customer: CustomerDetails) -> bool:
    """Export customer record to Google Sheets."""
    exporter = get_exporter()
    return exporter.upsert(customer)

