"""
Flask integration hook - minimal glue to call from existing webhook.

Usage in webhook.py:
    from customer_capture.integrations.flask_hook import process_customer_message
    
    # Inside your message handler:
    process_customer_message(
        platform_user_id=sender_id,
        text=message_text,
        timestamp=msg_timestamp  # optional
    )
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from ..parser import parse_customer_message
from ..state import (
    get_pending_record, 
    save_pending_record, 
    delete_pending_record,
    AggregationRecord,
    cleanup_stale_records
)
from ..exporter import export_customer

logger = logging.getLogger(__name__)


def process_customer_message(
    platform_user_id: str,
    text: str,
    timestamp: Optional[datetime] = None
) -> None:
    """
    Process incoming customer message for data capture.
    
    This function:
    1. Parses the message for customer entities
    2. Aggregates data with cooldown logic
    3. Exports to Google Sheets when ready
    
    Args:
        platform_user_id: Unique user ID from platform (e.g., Instagram sender_id)
        text: Message text content
        timestamp: Optional message timestamp (defaults to now)
    """
    if not platform_user_id or not text:
        logger.debug("Skipping: empty platform_user_id or text")
        return
    
    # Cleanup old records periodically
    cleanup_stale_records()
    
    # Parse message
    parsed = parse_customer_message(text)
    logger.info(f"[{platform_user_id}] Parsed: name={parsed.full_name}, phone={parsed.contact_number}, confidence={parsed.confidence:.2f}")
    
    # Skip if nothing useful extracted
    if parsed.confidence < 0.1:
        logger.debug(f"[{platform_user_id}] Low confidence ({parsed.confidence:.2f}), skipping")
        return
    
    # Get or create pending record
    record = get_pending_record(platform_user_id)
    
    if record is None:
        record = AggregationRecord(platform_user_id)
        if timestamp:
            record.created_at = timestamp
        logger.info(f"[{platform_user_id}] Created new aggregation record")
    
    # Merge parsed data
    had_changes = record.merge(parsed)
    
    # Save updated record
    save_pending_record(record)
    
    # Check if should finalize
    if record.should_finalize():
        logger.info(f"[{platform_user_id}] Finalizing record")
        _finalize_and_export(record)
    elif record.has_minimum_data() and parsed.confidence >= 0.8:
        # Immediate finalization for high-confidence complete data
        logger.info(f"[{platform_user_id}] High confidence complete data, finalizing immediately")
        _finalize_and_export(record)
    else:
        logger.debug(f"[{platform_user_id}] Saved, waiting for more data or cooldown")


def _finalize_and_export(record: AggregationRecord) -> None:
    """Finalize record and export to Google Sheets."""
    try:
        # Convert to CustomerDetails
        customer = record.to_customer_details()
        
        logger.info(f"[{record.platform_user_id}] Exporting: {customer.record_id}")
        
        # Export to Google Sheets
        success = export_customer(customer)
        
        if success:
            logger.info(f"[{record.platform_user_id}] Successfully exported")
            # Delete pending record
            delete_pending_record(record.platform_user_id)
        else:
            logger.error(f"[{record.platform_user_id}] Export failed, keeping record for retry")
    
    except Exception as e:
        logger.exception(f"[{record.platform_user_id}] Error during finalization: {e}")


def force_finalize_user(platform_user_id: str) -> bool:
    """
    Force finalize and export pending record for a user.
    
    Useful for manual triggers or testing.
    Returns True if record was found and exported.
    """
    record = get_pending_record(platform_user_id)
    
    if record:
        logger.info(f"[{platform_user_id}] Force finalizing")
        _finalize_and_export(record)
        return True
    else:
        logger.warning(f"[{platform_user_id}] No pending record found")
        return False

