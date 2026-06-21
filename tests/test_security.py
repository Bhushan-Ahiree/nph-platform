# tests/test_security.py
"""
Tests for shared/utils/security.py — password hashing, verification, and JWT operations.
"""
import pytest
from datetime import timedelta


class TestPasswordHashing:
    """Validates bcrypt password hashing and verification."""

    def test_hash_password_returns_hash(self):
        from shared.utils.security import hash_password
        hashed = hash_password("mysecretpassword")
        assert hashed != "mysecretpassword"
        assert hashed.startswith("$2b$")

    def test_verify_correct_password(self):
        from shared.utils.security import hash_password, verify_password
        hashed = hash_password("correctpassword")
        assert verify_password("correctpassword", hashed) is True

    def test_verify_wrong_password(self):
        from shared.utils.security import hash_password, verify_password
        hashed = hash_password("correctpassword")
        assert verify_password("wrongpassword", hashed) is False

    def test_hash_uniqueness(self):
        from shared.utils.security import hash_password
        hash1 = hash_password("samepassword")
        hash2 = hash_password("samepassword")
        # bcrypt produces different salts each time
        assert hash1 != hash2


class TestJWTTokens:
    """Validates JWT token creation and decoding."""

    def test_create_access_token(self):
        from shared.utils.security import create_access_token
        token = create_access_token(data={"sub": "user123", "email": "test@nph.com"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_contains_claims(self):
        import jwt
        from shared.utils.security import create_access_token, JWT_SECRET, JWT_ALGORITHM
        token = create_access_token(data={"sub": "user123", "email": "test@nph.com", "role": "admin"})
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["sub"] == "user123"
        assert payload["email"] == "test@nph.com"
        assert payload["role"] == "admin"
        assert "exp" in payload

    def test_token_with_custom_expiry(self):
        import jwt
        from shared.utils.security import create_access_token, JWT_SECRET, JWT_ALGORITHM
        token = create_access_token(
            data={"sub": "user123"},
            expires_delta=timedelta(minutes=5)
        )
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["sub"] == "user123"
        assert "exp" in payload

    def test_expired_token_raises(self):
        import jwt
        from shared.utils.security import create_access_token, JWT_SECRET, JWT_ALGORITHM
        token = create_access_token(
            data={"sub": "user123"},
            expires_delta=timedelta(seconds=-1)
        )
        with pytest.raises(jwt.ExpiredSignatureError):
            jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])

    def test_token_invalid_secret_raises(self):
        import jwt
        from shared.utils.security import create_access_token
        token = create_access_token(data={"sub": "user123"})
        with pytest.raises(jwt.InvalidSignatureError):
            jwt.decode(token, "wrong_secret", algorithms=["HS256"])
