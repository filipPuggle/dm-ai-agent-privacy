#!/usr/bin/env python3
"""
Create Google Service Account credentials file from environment variables.
This bypasses all JSON parsing issues.
"""

import os
import json
from pathlib import Path

def create_credentials_file():
    """Create credentials file from environment variables."""
    
    # Get credentials from environment
    project_id = os.getenv('GCLOUD_PROJECT', 'customer-capture-system-474710')
    key_id = os.getenv('GCLOUD_KEY_ID', '13251ed782f68320e5d880830af4c676d59484d9')
    private_key = os.getenv('GCLOUD_PRIVATE_KEY', '')
    client_email = os.getenv('GCLOUD_EMAIL', 'customer-capture-bot@customer-capture-system-474710.iam.gserviceaccount.com')
    client_id = os.getenv('GCLOUD_CLIENT_ID', '111153201774146294036')
    
    if not private_key:
        print("❌ GCLOUD_PRIVATE_KEY not found in environment")
        return False
    
    # Create credentials directory
    creds_dir = Path('/tmp/credentials')
    creds_dir.mkdir(exist_ok=True)
    
    # Create service account info
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
    
    # Write to file
    creds_file = creds_dir / 'google-service-account.json'
    with open(creds_file, 'w') as f:
        json.dump(service_account_info, f, indent=2)
    
    print(f"✅ Created credentials file: {creds_file}")
    return str(creds_file)

if __name__ == "__main__":
    create_credentials_file()
