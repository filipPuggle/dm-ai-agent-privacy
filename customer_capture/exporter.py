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
            
            json_env = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
            if json_env:
                try:
                    # Use JSON from environment variable
                    service_account_info = json.loads(json_env)
                    creds = Credentials.from_service_account_info(
                        service_account_info,
                        scopes=scopes
                    )
                    logger.info("Using Google Sheets authentication from environment variable")
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON in GOOGLE_SERVICE_ACCOUNT_JSON: {e}")
                    logger.error("Falling back to file authentication")
                    # Fall back to file authentication
                    if settings.GOOGLE_APPLICATION_CREDENTIALS and os.path.exists(settings.GOOGLE_APPLICATION_CREDENTIALS):
                        creds = Credentials.from_service_account_file(
                            settings.GOOGLE_APPLICATION_CREDENTIALS,
                            scopes=scopes
                        )
                        logger.info("Using Google Sheets authentication from file")
                    else:
                        raise ValueError("No valid Google service account credentials found")
            else:
                # Use file path
                if settings.GOOGLE_APPLICATION_CREDENTIALS and os.path.exists(settings.GOOGLE_APPLICATION_CREDENTIALS):
                    creds = Credentials.from_service_account_file(
                        settings.GOOGLE_APPLICATION_CREDENTIALS,
                        scopes=scopes
                    )
                    logger.info("Using Google Sheets authentication from file")
                else:
                    raise ValueError("No Google service account credentials found")
            
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
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets: {e}")
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
        self._initialize()
        
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

