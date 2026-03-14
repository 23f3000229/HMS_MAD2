"""
Redis caching utilities for the hospital management system.
Provides helper functions to cache and retrieve data from Redis.
"""

import redis
import json
from datetime import timedelta

# Initialize Redis client
# Connect to Redis server (default: localhost:6379)
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    # Test connection
    redis_client.ping()
    print("✓ Redis connection established")
except redis.ConnectionError:
    print("⚠ Warning: Redis server not running on localhost:6379")
    redis_client = None
except Exception as e:
    print(f"⚠ Warning: Redis connection failed - {str(e)}")
    redis_client = None


def cache_get(key):
    """
    Retrieve a value from Redis cache.
    
    Args:
        key: Cache key to retrieve
        
    Returns:
        Parsed JSON value if exists, None otherwise
    """
    if not redis_client:
        return None
    
    try:
        value = redis_client.get(key)
        if value:
            return json.loads(value)
        return None
    except Exception as e:
        print(f"Cache get error for key {key}: {str(e)}")
        return None


def cache_set(key, value, expire_seconds=3600):
    """
    Store a value in Redis cache with expiration.
    
    Args:
        key: Cache key
        value: Value to cache (will be JSON serialized)
        expire_seconds: TTL in seconds (default 1 hour)
        
    Returns:
        True if successful, False otherwise
    """
    if not redis_client:
        return False
    
    try:
        redis_client.setex(
            key, 
            expire_seconds, 
            json.dumps(value)
        )
        return True
    except Exception as e:
        print(f"Cache set error for key {key}: {str(e)}")
        return False


def cache_delete(key):
    """
    Delete a key from Redis cache.
    
    Args:
        key: Cache key to delete
        
    Returns:
        True if key was deleted, False otherwise
    """
    if not redis_client:
        return False
    
    try:
        redis_client.delete(key)
        return True
    except Exception as e:
        print(f"Cache delete error for key {key}: {str(e)}")
        return False


def cache_delete_pattern(pattern):
    """
    Delete all keys matching a pattern from Redis cache.
    
    Args:
        pattern: Pattern to match (e.g., "doctor_avail:*")
        
    Returns:
        Number of keys deleted
    """
    if not redis_client:
        return 0
    
    try:
        keys = redis_client.keys(pattern)
        if keys:
            return redis_client.delete(*keys)
        return 0
    except Exception as e:
        print(f"Cache delete pattern error for pattern {pattern}: {str(e)}")
        return 0


def cache_flush_all():
    """
    Flush all data from Redis cache (use with caution).
    
    Returns:
        True if successful, False otherwise
    """
    if not redis_client:
        return False
    
    try:
        redis_client.flushdb()
        return True
    except Exception as e:
        print(f"Cache flush error: {str(e)}")
        return False


# Cache key generators for consistency
def get_doctor_availability_key(doctor_id):
    """Generate cache key for doctor availabilities."""
    return f"doctor_avail:{doctor_id}"


def get_all_doctors_key():
    """Generate cache key for all doctors."""
    return "doctors:all"


def get_doctor_search_key(specialization=None, department_name=None, doctor_name=None):
    """Generate cache key for doctor search results."""
    parts = ["doctors:search"]
    if specialization:
        parts.append(f"spec:{specialization}")
    if department_name:
        parts.append(f"dept:{department_name}")
    if doctor_name:
        parts.append(f"name:{doctor_name}")
    return ":".join(parts)


def get_patient_search_key(name=None):
    """Generate cache key for patient search results."""
    if name:
        return f"patients:search:name:{name}"
    return "patients:all"


def get_booked_slots_key(doctor_id):
    """Generate cache key for booked slots."""
    return f"booked_slots:{doctor_id}"
