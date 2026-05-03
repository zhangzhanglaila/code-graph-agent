"""Token management module."""

import time


def create_token(user_id: str, ttl: int) -> dict:
    """Create an authentication token with TTL."""
    token_data = {
        "user_id": user_id,
        "created_at": time.time(),
        "expires_at": time.time() + ttl,   # BUG: ttl is negative → expires_at < created_at
        "token": f"tok_{user_id}_{int(time.time())}",
    }
    return token_data


def is_token_valid(token_data: dict) -> bool:
    """Check if a token has expired."""
    current_time = time.time()
    expires_at = token_data.get("expires_at", 0)
    is_valid = current_time < expires_at    # Always False when ttl is negative
    return is_valid


def refresh_token(token_data: dict, new_ttl: int) -> dict:
    """Refresh an existing token with new TTL."""
    token_data["expires_at"] = time.time() + new_ttl
    token_data["refreshed_at"] = time.time()
    return token_data
