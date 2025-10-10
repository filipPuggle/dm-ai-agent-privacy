#!/usr/bin/env python3
"""
Generate properly formatted JSON for Railway environment variable.
This script reads the local credentials file and outputs a clean JSON string.
"""

import json
import sys
import os

def generate_railway_json():
    """Generate clean JSON for Railway GOOGLE_SERVICE_ACCOUNT_JSON variable."""
    
    # Read the local credentials file
    creds_file = 'credentials/google-service-account.json'
    
    if not os.path.exists(creds_file):
        print(f"❌ Error: {creds_file} not found")
        print("Make sure you have the Google service account JSON file in the credentials/ directory")
        return False
    
    try:
        with open(creds_file, 'r') as f:
            data = json.load(f)
        
        # Clean and validate the JSON
        required_fields = ['type', 'project_id', 'private_key', 'client_email']
        for field in required_fields:
            if field not in data:
                print(f"❌ Error: Missing required field '{field}' in credentials file")
                return False
        
        # Generate clean JSON string
        clean_json = json.dumps(data, separators=(',', ':'))
        
        print("✅ Generated clean JSON for Railway:")
        print("="*60)
        print("Copy this EXACT value to Railway GOOGLE_SERVICE_ACCOUNT_JSON variable:")
        print("="*60)
        print(clean_json)
        print("="*60)
        print("\n📋 Instructions:")
        print("1. Go to Railway → Your project → Variables")
        print("2. Add new variable: GOOGLE_SERVICE_ACCOUNT_JSON")
        print("3. Paste the JSON above as the value")
        print("4. Save and redeploy")
        
        return True
        
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON in credentials file: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    generate_railway_json()
