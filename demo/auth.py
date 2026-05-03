"""Authentication module — login validation logic."""

import os
import yaml
from demo.token import create_token, is_token_valid


def load_config() -> dict:
    """Load configuration from config.yaml."""
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def authenticate(username: str, password: str) -> dict:
    """Authenticate user and return token.

    This function will always fail because config.token_ttl is negative,
    causing is_token_valid to return False immediately after token creation.
    """
    config = load_config()
    ttl = config["auth"]["token_ttl"]       # reads negative TTL from config

    # Simulate credential check
    if not username or not password:
        raise ValueError("Username and password are required")

    # Simulate password verification (simplified)
    if password != "correct_password":
        raise PermissionError("Invalid credentials")

    # Create token — expires_at will be in the past due to negative TTL
    token = create_token(username, ttl)

    # This check always fails when TTL is negative
    if not is_token_valid(token):
        raise RuntimeError(f"Token expired immediately! TTL={ttl}s is invalid")

    return token


def verify_access(token_data: dict) -> bool:
    """Verify that a token grants access."""
    if not is_token_valid(token_data):
        return False
    return True


if __name__ == "__main__":
    try:
        result = authenticate("alice", "correct_password")
        print(f"Login successful: {result}")
    except Exception as e:
        print(f"Login failed: {e}")
