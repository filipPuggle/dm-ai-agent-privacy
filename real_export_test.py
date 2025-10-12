#!/usr/bin/env python3
"""
Real Google Sheets export test - exports actual data to your Google Sheet
"""
import sys
import os
import logging
from datetime import datetime, timezone

# Add the project root to Python path
sys.path.insert(0, '/Users/filipas/Desktop/dm-ai-agent-privacy')

from customer_capture.integrations.flask_hook import process_customer_message, force_finalize_user
from customer_capture.settings import settings

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def setup_environment():
    """Set up environment variables for Google Sheets export."""
    
    print("🚀 REAL GOOGLE SHEETS EXPORT TEST")
    print("=" * 50)
    
    # Check current environment
    spreadsheet_id = os.getenv('GSHEET_SPREADSHEET_ID')
    worksheet_title = os.getenv('GSHEET_WORKSHEET_TITLE') or 'Sheet1'
    
    if not spreadsheet_id:
        print("❌ Google Sheets not configured!")
        print("\n📋 SETUP REQUIRED:")
        print("Please set these environment variables:")
        print("\nexport GSHEET_SPREADSHEET_ID='your-spreadsheet-id-here'")
        print("export GSHEET_WORKSHEET_TITLE='Sheet1'")
        print("\n🔍 To find your spreadsheet ID:")
        print("1. Open your Google Sheet")
        print("2. Look at the URL: https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit")
        print("3. Copy the SPREADSHEET_ID part")
        print("\n💡 Example:")
        print("export GSHEET_SPREADSHEET_ID='1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms'")
        print("export GSHEET_WORKSHEET_TITLE='Sheet1'")
        print("\n🔄 After setting the variables, run this script again.")
        return False
    
    # Configure environment for real export
    os.environ['DRY_RUN'] = '0'  # Disable DRY_RUN mode
    os.environ['GSHEET_SPREADSHEET_ID'] = spreadsheet_id
    os.environ['GSHEET_WORKSHEET_TITLE'] = worksheet_title
    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '/Users/filipas/Desktop/dm-ai-agent-privacy/credentials/google-service-account.json'
    
    print(f"✅ Google Sheets configured!")
    print(f"📊 Spreadsheet ID: {spreadsheet_id}")
    print(f"📋 Worksheet: {worksheet_title}")
    print(f"🔐 Credentials: {os.environ['GOOGLE_APPLICATION_CREDENTIALS']}")
    
    # Check if credentials file exists
    if not os.path.exists(os.environ['GOOGLE_APPLICATION_CREDENTIALS']):
        print(f"❌ Credentials file not found: {os.environ['GOOGLE_APPLICATION_CREDENTIALS']}")
        return False
    
    print("✅ Credentials file found!")
    return True

def run_real_export_test():
    """Run a real export test with actual customer data."""
    
    if not setup_environment():
        return
    
    print("\n" + "=" * 50)
    print("🧪 TESTING REAL GOOGLE SHEETS EXPORT")
    print("=" * 50)
    
    # Test scenarios with real customer data
    test_scenarios = [
        {
            "name": "Real Export Test 1: Chișinău Customer",
            "user_id": "REAL_TEST_CHISINAU_001",
            "messages": [
                {"text": "Doresc livrare în Chișinău", "location_context": "CHISINAU"},
                {"text": "Prin curier", "location_context": "CHISINAU"},
                {"text": "Maria Popescu\nStr. Ștefan cel Mare 45\nAp. 12\n068123456", "location_context": "CHISINAU"}
            ]
        },
        {
            "name": "Real Export Test 2: Bălți Customer", 
            "user_id": "REAL_TEST_BALTI_002",
            "messages": [
                {"text": "Vreau să comand în Bălți", "location_context": "BALTI"},
                {"text": "Cu livrare", "location_context": "BALTI"},
                {"text": "Ion Țurcanu\nBd. Independenței 78\n3700\n079456789", "location_context": "BALTI"}
            ]
        },
        {
            "name": "Real Export Test 3: Other City Customer",
            "user_id": "REAL_TEST_OTHER_003", 
            "messages": [
                {"text": "Am nevoie la Telenești", "location_context": "OTHER_MD", "specific_location": "Telenești"},
                {"text": "Prin poștă", "location_context": "OTHER_MD", "specific_location": "Telenești"},
                {"text": "Elena Rusu\ns. Copăceni, r-nul Hîncești\n3400\n069123456", "location_context": "OTHER_MD", "specific_location": "Telenești"}
            ]
        }
    ]
    
    results = []
    
    for i, scenario in enumerate(test_scenarios, 1):
        print(f"\n🧪 {scenario['name']}")
        print("-" * 60)
        
        try:
            # Process all messages for this scenario
            for j, message in enumerate(scenario['messages']):
                print(f"   📝 Message {j+1}: {message['text'][:50]}{'...' if len(message['text']) > 50 else ''}")
                process_customer_message(
                    platform_user_id=scenario['user_id'],
                    text=message['text'],
                    timestamp=datetime.now(timezone.utc),
                    location_context=message.get('location_context'),
                    specific_location=message.get('specific_location')
                )
            
            # Force finalize to export
            print(f"   🔄 Finalizing and exporting to Google Sheets...")
            success = force_finalize_user(scenario['user_id'])
            
            if success:
                print(f"   ✅ SUCCESS: Data exported to Google Sheets!")
                results.append({"scenario": scenario['name'], "status": "SUCCESS"})
            else:
                print(f"   ❌ FAILED: Could not export data")
                results.append({"scenario": scenario['name'], "status": "FAILED"})
                
        except Exception as e:
            print(f"   ❌ ERROR: {str(e)}")
            results.append({"scenario": scenario['name'], "status": "ERROR", "error": str(e)})
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 EXPORT RESULTS SUMMARY")
    print("=" * 60)
    
    successful = sum(1 for r in results if r['status'] == 'SUCCESS')
    failed = sum(1 for r in results if r['status'] == 'FAILED')
    errors = sum(1 for r in results if r['status'] == 'ERROR')
    
    print(f"✅ Successful exports: {successful}/3")
    print(f"❌ Failed exports: {failed}/3") 
    print(f"💥 Errors: {errors}/3")
    
    if successful == 3:
        print("\n🎉 ALL EXPORTS SUCCESSFUL!")
        print("📊 Check your Google Sheet to see the exported data!")
        print("\nExpected data:")
        print("Row 1: Maria Popescu, Chișinău, +37368123456")
        print("Row 2: Ion Țurcanu, Bălți, +37379456789") 
        print("Row 3: Elena Rusu, Telenești, +37369123456")
    else:
        print(f"\n⚠️  {3 - successful} exports need attention")
        for result in results:
            status_emoji = "✅" if result['status'] == 'SUCCESS' else "❌" if result['status'] == 'FAILED' else "💥"
            print(f"   {status_emoji} {result['scenario']}: {result['status']}")
            if 'error' in result:
                print(f"      Error: {result['error']}")
    
    return results

if __name__ == '__main__':
    run_real_export_test()
