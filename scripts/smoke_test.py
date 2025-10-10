#!/usr/bin/env python3
"""
Smoke test script for customer capture system.
Simulates message bursts and prints rows that would be upserted.

Usage:
    python scripts/smoke_test.py
    DRY_RUN=1 python scripts/smoke_test.py  # Don't actually export
"""
import os
import sys
import time
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from customer_capture.integrations.flask_hook import process_customer_message
from customer_capture.state import get_pending_record, InMemoryStore
from customer_capture import state

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def print_separator():
    print("\n" + "=" * 80 + "\n")


def simulate_user_messages(user_id: str, messages: list[str], delays: list[float]):
    """
    Simulate a user sending multiple messages with delays.
    
    Args:
        user_id: Platform user ID
        messages: List of message texts
        delays: List of delays (in seconds) after each message
    """
    print(f"📱 Simulating messages for user: {user_id}")
    print(f"   Total messages: {len(messages)}")
    
    for i, (msg, delay) in enumerate(zip(messages, delays), 1):
        print(f"\n   Message {i}: {msg[:50]}...")
        process_customer_message(platform_user_id=user_id, text=msg)
        
        # Show current state
        record = get_pending_record(user_id)
        if record:
            print(f"   ├─ Name: {record.full_name or '(not set)'}")
            print(f"   ├─ Phone: {record.contact_number or '(not set)'}")
            print(f"   ├─ Address: {record.adress or '(not set)'}")
            print(f"   ├─ Location: {record.location or '(not set)'}")
            print(f"   └─ Postal: {record.postal_code or '(not set)'}")
        
        if i < len(messages):
            print(f"   ⏳ Waiting {delay}s...")
            time.sleep(delay)
    
    # Check final state
    record = get_pending_record(user_id)
    if record:
        customer = record.to_customer_details()
        row = customer.to_sheets_row()
        
        print(f"\n✅ Would upsert row for {user_id}:")
        for col, value in row.items():
            print(f"   {col:20s}: {value}")
    else:
        print(f"\n✅ Record was finalized and exported for {user_id}")


def main():
    """Run smoke tests."""
    print_separator()
    print("🔥 CUSTOMER CAPTURE SMOKE TEST")
    print_separator()
    
    # Force in-memory store for testing
    state._store = InMemoryStore()
    logger.info("Using in-memory store for smoke test")
    
    # Test Scenario 1: Single complete message
    print("\n📋 SCENARIO 1: Single complete message")
    print_separator()
    simulate_user_messages(
        user_id="user_001",
        messages=["Rufa Irina\nSat Giurgiulești\n5318\n068977378"],
        delays=[0]
    )
    
    # Test Scenario 2: Multiple messages building profile
    print_separator()
    print("\n📋 SCENARIO 2: Multiple messages with short delays")
    print_separator()
    simulate_user_messages(
        user_id="user_002",
        messages=[
            "Macaru Veronica",
            "Raionul Hîncești satul Mingir",
            "069682881"
        ],
        delays=[1, 1, 0]
    )
    
    # Test Scenario 3: Address in separate message
    print_separator()
    print("\n📋 SCENARIO 3: Name, address, phone separately")
    print_separator()
    simulate_user_messages(
        user_id="user_003",
        messages=[
            "Pleşciuc Camelia",
            "str. Independenței 48/44, orașul Leova",
            "068370666"
        ],
        delays=[1, 1, 0]
    )
    
    # Test Scenario 4: Phone first
    print_separator()
    print("\n📋 SCENARIO 4: Phone first, then name")
    print_separator()
    simulate_user_messages(
        user_id="user_004",
        messages=[
            "079013356",
            "Ina"
        ],
        delays=[1, 0]
    )
    
    # Test Scenario 5: Russian text with Cyrillic
    print_separator()
    print("\n📋 SCENARIO 5: Russian/Cyrillic content")
    print_separator()
    simulate_user_messages(
        user_id="user_005",
        messages=[
            "Natalia Popa",
            "Codrilor, д. 10",
            "Sauca, Ocnita, 7133",
            "+37369507012"
        ],
        delays=[1, 1, 1, 0]
    )
    
    # Test Scenario 6: Numele pattern
    print_separator()
    print("\n📋 SCENARIO 6: 'Numele' pattern with location")
    print_separator()
    simulate_user_messages(
        user_id="user_006",
        messages=["Numele cobzari Ionela, comuna Burlacu raionul Cahul, 067876429"],
        delays=[0]
    )
    
    # Test Scenario 7: Duplicate detection
    print_separator()
    print("\n📋 SCENARIO 7: Duplicate message (should merge)")
    print_separator()
    msg = "Railean Cristina\n068951991"
    simulate_user_messages(
        user_id="user_007",
        messages=[msg, msg],  # Same message twice
        delays=[0.5, 0]
    )
    
    print_separator()
    print("\n✨ SMOKE TEST COMPLETE")
    print("\nIf DRY_RUN=0 and Google Sheets credentials are configured,")
    print("the rows above would be upserted to the spreadsheet.")
    print_separator()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.exception("Smoke test failed")
        sys.exit(1)

