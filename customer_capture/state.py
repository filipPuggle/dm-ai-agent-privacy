"""
Aggregation store for customer data per platform_user_id.
Supports Redis (if REDIS_URL set) with in-memory fallback.
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict
from .models import CustomerDetails, ParsedMessage
from .settings import settings
from .utils import generate_record_id

logger = logging.getLogger(__name__)


class AggregationRecord:
    """Pending customer record being aggregated."""
    
    def __init__(self, platform_user_id: str):
        self.platform_user_id = platform_user_id
        self.full_name: Optional[str] = None
        self.contact_number: Optional[str] = None
        self.adress: Optional[str] = None
        self.location: Optional[str] = None
        self.postal_code: Optional[str] = None
        self.raw_messages: list[str] = []
        self.created_at: datetime = datetime.now(timezone.utc)
        self.last_update: float = time.time()
        self.last_field_update: float = time.time()  # When last new field was added
    
    def merge(self, parsed: ParsedMessage) -> bool:
        """
        Merge parsed message into this record.
        Returns True if new fields were added.
        Enhanced to handle multiple messages and prioritize name + phone.
        """
        now = time.time()
        self.last_update = now
        had_changes = False
        
        # Add raw message
        if parsed.raw_message and parsed.raw_message not in self.raw_messages:
            self.raw_messages.append(parsed.raw_message)
        
        # Merge name: prioritize longer/more complete names
        if parsed.full_name:
            if not self.full_name:
                self.full_name = parsed.full_name
                had_changes = True
                logger.debug(f"[{self.platform_user_id}] Set name: {parsed.full_name}")
            else:
                # Compare names: prefer longer or more complete names
                current_words = len(self.full_name.split())
                new_words = len(parsed.full_name.split())
                
                # Replace if new name is longer or has higher confidence
                if (new_words > current_words or 
                    (new_words == current_words and parsed.confidence > 0.8)):
                    logger.debug(f"[{self.platform_user_id}] Upgrading name: {self.full_name} -> {parsed.full_name}")
                    self.full_name = parsed.full_name
                    had_changes = True
        
        # Merge phone: accept any valid phone number (prioritize phone number)
        if parsed.contact_number:
            if not self.contact_number:
                self.contact_number = parsed.contact_number
                had_changes = True
                logger.debug(f"[{self.platform_user_id}] Set phone: {parsed.contact_number}")
            else:
                # Only replace if new phone has higher confidence or is more complete
                if parsed.confidence > 0.8:
                    logger.debug(f"[{self.platform_user_id}] Upgrading phone: {self.contact_number} -> {parsed.contact_number}")
                    self.contact_number = parsed.contact_number
                    had_changes = True
        
        # Merge address fields: accept any new valid data
        if parsed.address_block.street_address:
            if not self.adress:
                self.adress = parsed.address_block.street_address
                had_changes = True
                logger.debug(f"[{self.platform_user_id}] Set address: {parsed.address_block.street_address}")
            else:
                # Replace if new address is longer/more complete
                if len(parsed.address_block.street_address) > len(self.adress):
                    logger.debug(f"[{self.platform_user_id}] Upgrading address: {self.adress} -> {parsed.address_block.street_address}")
                    self.adress = parsed.address_block.street_address
                    had_changes = True
        
        if parsed.address_block.location:
            if not self.location:
                self.location = parsed.address_block.location
                had_changes = True
                logger.debug(f"[{self.platform_user_id}] Set location: {parsed.address_block.location}")
            else:
                # Replace if new location is longer/more complete
                if len(parsed.address_block.location) > len(self.location):
                    logger.debug(f"[{self.platform_user_id}] Upgrading location: {self.location} -> {parsed.address_block.location}")
                    self.location = parsed.address_block.location
                    had_changes = True
        
        if parsed.address_block.postal_code:
            if not self.postal_code:
                self.postal_code = parsed.address_block.postal_code
                had_changes = True
                logger.debug(f"[{self.platform_user_id}] Set postal: {parsed.address_block.postal_code}")
            else:
                # Replace if new postal code is different (rare case)
                if parsed.address_block.postal_code != self.postal_code:
                    logger.debug(f"[{self.platform_user_id}] Upgrading postal: {self.postal_code} -> {parsed.address_block.postal_code}")
                    self.postal_code = parsed.address_block.postal_code
                    had_changes = True
        
        if had_changes:
            self.last_field_update = now
        
        return had_changes
    
    def has_minimum_data(self) -> bool:
        """Check if we have the minimum required data (name + phone)."""
        return bool(self.full_name and self.contact_number)
    
    def should_finalize(self) -> bool:
        """
        Check if record should be finalized and exported.
        Enhanced to handle multiple messages and prioritize name + phone.
        
        Rules:
        1. 90s inactivity (COOLDOWN_SECONDS) - export whatever we have
        2. Have name + phone AND 20s passed since last field update (FINALIZE_AFTER_BOTH_SECONDS)
        3. Have name + phone AND 30s passed since last message (shorter wait for complete data)
        """
        now = time.time()
        idle_time = now - self.last_update
        
        # Rule 1: 90s cooldown - export whatever we have
        if idle_time >= settings.COOLDOWN_SECONDS:
            logger.debug(f"[{self.platform_user_id}] Finalizing: {idle_time:.1f}s idle (cooldown)")
            return True
        
        # Rule 2: Have both name and phone + 20s since last field
        if self.has_minimum_data():
            time_since_field = now - self.last_field_update
            if time_since_field >= settings.FINALIZE_AFTER_BOTH_SECONDS:
                logger.debug(f"[{self.platform_user_id}] Finalizing: have name+phone, {time_since_field:.1f}s since last field")
                return True
            
            # Rule 3: Have name + phone + 30s since last message (shorter wait for complete data)
            if idle_time >= 30:  # 30 seconds since last message
                logger.debug(f"[{self.platform_user_id}] Finalizing: have name+phone, {idle_time:.1f}s since last message")
                return True
        
        return False
    
    def to_customer_details(self) -> CustomerDetails:
        """Convert to final CustomerDetails for export."""
        raw_combined = "\n".join(self.raw_messages)
        record_id = generate_record_id(self.platform_user_id, self.contact_number)
        
        return CustomerDetails(
            platform_user_id=self.platform_user_id,
            full_name=self.full_name,
            contact_number=self.contact_number,
            adress=self.adress,
            location=self.location,
            postal_code=self.postal_code,
            raw_message=raw_combined,
            created_at=self.created_at,
            record_id=record_id
        )
    
    def to_dict(self) -> dict:
        """Serialize to dict for storage."""
        return {
            'platform_user_id': self.platform_user_id,
            'full_name': self.full_name,
            'contact_number': self.contact_number,
            'adress': self.adress,
            'location': self.location,
            'postal_code': self.postal_code,
            'raw_messages': self.raw_messages,
            'created_at': self.created_at.isoformat(),
            'last_update': self.last_update,
            'last_field_update': self.last_field_update,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'AggregationRecord':
        """Deserialize from dict."""
        rec = cls(data['platform_user_id'])
        rec.full_name = data.get('full_name')
        rec.contact_number = data.get('contact_number')
        rec.adress = data.get('adress')
        rec.location = data.get('location')
        rec.postal_code = data.get('postal_code')
        rec.raw_messages = data.get('raw_messages', [])
        rec.created_at = datetime.fromisoformat(data['created_at'])
        rec.last_update = data['last_update']
        rec.last_field_update = data['last_field_update']
        return rec


class InMemoryStore:
    """In-memory storage with TTL cleanup."""
    
    def __init__(self):
        self.store: Dict[str, AggregationRecord] = {}
    
    def get(self, user_id: str) -> Optional[AggregationRecord]:
        return self.store.get(user_id)
    
    def set(self, user_id: str, record: AggregationRecord) -> None:
        self.store[user_id] = record
    
    def delete(self, user_id: str) -> None:
        self.store.pop(user_id, None)
    
    def cleanup_stale(self) -> None:
        """Remove records older than 2x COOLDOWN_SECONDS."""
        max_age = settings.COOLDOWN_SECONDS * 2
        now = time.time()
        stale = [
            uid for uid, rec in self.store.items()
            if (now - rec.last_update) > max_age
        ]
        for uid in stale:
            logger.debug(f"Cleaning up stale record: {uid}")
            del self.store[uid]


class RedisStore:
    """Redis-backed storage."""
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self.ttl = settings.COOLDOWN_SECONDS * 2  # Auto-expire
    
    def get(self, user_id: str) -> Optional[AggregationRecord]:
        key = f"customer_capture:{user_id}"
        data = self.redis.get(key)
        if data:
            return AggregationRecord.from_dict(json.loads(data))
        return None
    
    def set(self, user_id: str, record: AggregationRecord) -> None:
        key = f"customer_capture:{user_id}"
        data = json.dumps(record.to_dict())
        self.redis.setex(key, self.ttl, data)
    
    def delete(self, user_id: str) -> None:
        key = f"customer_capture:{user_id}"
        self.redis.delete(key)
    
    def cleanup_stale(self) -> None:
        """Redis handles TTL automatically."""
        pass


# === Global Store Instance ===
_store: Optional[InMemoryStore | RedisStore] = None


def get_store() -> InMemoryStore | RedisStore:
    """Get or initialize the global store instance."""
    global _store
    
    if _store is not None:
        return _store
    
    # Try Redis first
    if settings.REDIS_URL:
        try:
            import redis
            client = redis.from_url(settings.REDIS_URL, decode_responses=True)
            client.ping()  # Test connection
            _store = RedisStore(client)
            logger.info(f"Using Redis store: {settings.REDIS_URL}")
            return _store
        except Exception as e:
            logger.warning(f"Redis connection failed, falling back to in-memory: {e}")
    
    # Fallback to in-memory
    _store = InMemoryStore()
    logger.info("Using in-memory store")
    return _store


def get_pending_record(user_id: str) -> Optional[AggregationRecord]:
    """Get pending record for user."""
    store = get_store()
    return store.get(user_id)


def save_pending_record(record: AggregationRecord) -> None:
    """Save pending record."""
    store = get_store()
    store.set(record.platform_user_id, record)


def delete_pending_record(user_id: str) -> None:
    """Delete pending record."""
    store = get_store()
    store.delete(user_id)


def cleanup_stale_records() -> None:
    """Cleanup old records."""
    store = get_store()
    store.cleanup_stale()

