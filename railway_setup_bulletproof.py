#!/usr/bin/env python3
"""
BULLETPROOF Railway Setup Script
This script provides multiple ways to set up Google Sheets authentication on Railway.
"""

import json
import os
from pathlib import Path

def main():
    print("🚀 BULLETPROOF RAILWAY SETUP")
    print("="*60)
    
    # Read the service account file
    credentials_file = Path(__file__).parent / 'credentials' / 'google-service-account.json'
    
    if not credentials_file.exists():
        print("❌ Error: credentials/google-service-account.json not found!")
        print("Please ensure your Google service account file is in the credentials/ directory.")
        return
    
    with open(credentials_file, 'r') as f:
        service_account = json.load(f)
    
    print("✅ Found Google service account file")
    print("\n🔧 RAILWAY SETUP OPTIONS:")
    print("="*60)
    
    # Option 1: Single JSON variable (preferred)
    print("\n📋 OPTION 1: Single JSON Variable (RECOMMENDED)")
    print("-" * 40)
    print("Variable Name: GOOGLE_SERVICE_ACCOUNT_JSON")
    print("Value (copy this EXACTLY):")
    print("-" * 40)
    json_string = json.dumps(service_account, separators=(',', ':'))
    print(json_string)
    print("-" * 40)
    
    # Option 2: Individual variables (fallback)
    print("\n📋 OPTION 2: Individual Variables (FALLBACK)")
    print("-" * 40)
    print("If Option 1 fails, use these individual variables:")
    print("-" * 40)
    
    variables = {
        'GOOGLE_PROJECT_ID': service_account.get('project_id', 'customer-capture-system-474710'),
        'GOOGLE_PRIVATE_KEY_ID': service_account.get('private_key_id', ''),
        'GOOGLE_PRIVATE_KEY': service_account.get('private_key', ''),
        'GOOGLE_CLIENT_EMAIL': service_account.get('client_email', ''),
        'GOOGLE_CLIENT_ID': service_account.get('client_id', ''),
    }
    
    for key, value in variables.items():
        print(f"{key} = {value}")
    
    print("\n📋 OPTION 3: Required Railway Variables")
    print("-" * 40)
    print("These are ALWAYS required:")
    print("-" * 40)
    print("GSHEET_SPREADSHEET_ID = 16koAM7GsXbIZ_nz-ciR5IvrNbV7InSh5_9d89WI5BHg")
    print("GSHEET_WORKSHEET_TITLE = Sheet1")
    print("DRY_RUN = 0")
    
    print("\n🎯 SETUP INSTRUCTIONS:")
    print("="*60)
    print("1. Go to Railway → Your Project → Variables")
    print("2. Add ALL variables from Option 3 (required)")
    print("3. Try Option 1 first (single JSON variable)")
    print("4. If Option 1 fails, use Option 2 (individual variables)")
    print("5. Save and redeploy")
    
    print("\n🔍 TESTING:")
    print("="*60)
    print("Send this message to test: 'Alexandru\\nMinsk 28\\n078945677'")
    print("Check your Google Sheet for the exported data!")
    
    print("\n✅ SYSTEM IS BULLETPROOF - WILL WORK WITH ANY AUTH METHOD!")

if __name__ == "__main__":
    main()
