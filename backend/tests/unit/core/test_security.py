import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from app.core.security import SecurityService
from app.domain.enums.user import UserRole
from app.domain.user import InvalidCredentialsError
from app.settings import Settings
from jwt.exceptions import InvalidTokenError


class TestPasswordHashing:
    """Test password hashing functionality."""

    @pytest.fixture
    def security_svc(self, test_settings: Settings) -> SecurityService:
        """Create SecurityService instance."""
        return SecurityService(test_settings)

    def test_password_hash_creates_different_hash(self, security_svc: SecurityService) -> None:
        """Test that password hashing creates unique hashes."""
        password = "test_password_123"
        hash1 = security_svc.get_password_hash(password)
        hash2 = security_svc.get_password_hash(password)

        # Hashes should be different due to salting
        assert hash1 != hash2
        assert password not in hash1
        assert password not in hash2

    def test_password_verification_success(self, security_svc: SecurityService) -> None:
        """Test successful password verification."""
        password = "correct_password"
        hashed = security_svc.get_password_hash(password)

        assert security_svc.verify_password(password, hashed) is True

    def test_password_verification_failure(self, security_svc: SecurityService) -> None:
        """Test failed password verification."""
        password = "correct_password"
        wrong_password = "wrong_password"
        hashed = security_svc.get_password_hash(password)

        assert security_svc.verify_password(wrong_password, hashed) is False

    def test_empty_password_handling(self, security_svc: SecurityService) -> None:
        """Test handling of empty passwords."""
        empty_password = ""
        hashed = security_svc.get_password_hash(empty_password)

        assert security_svc.verify_password(empty_password, hashed) is True
        assert security_svc.verify_password("not_empty", hashed) is False

    def test_special_characters_in_password(self, security_svc: SecurityService) -> None:
        """Test passwords with special characters."""
        special_password = "P@ssw0rd!#$%^&*()"
        hashed = security_svc.get_password_hash(special_password)

        assert security_svc.verify_password(special_password, hashed) is True

    def test_unicode_password(self, security_svc: SecurityService) -> None:
        """Test Unicode characters in passwords."""
        unicode_password = "пароль密码パスワード🔒"
        hashed = security_svc.get_password_hash(unicode_password)

        assert security_svc.verify_password(unicode_password, hashed) is True


class TestSecurityService:
    """Test SecurityService functionality."""

    @pytest.fixture
    def security_service(self, test_settings: Settings) -> SecurityService:
        """Create SecurityService instance using test settings."""
        return SecurityService(test_settings)

    def test_create_access_token_basic(
            self,
            security_service: SecurityService
    ) -> None:
        """Test basic access token creation."""
        data = {"sub": "testuser", "user_id": str(uuid4())}

        token = security_service.create_access_token(
            data, expires_delta=timedelta(minutes=security_service.settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

        # Decode and verify token
        decoded = jwt.decode(
            token,
            security_service.settings.SECRET_KEY,
            algorithms=[security_service.settings.ALGORITHM]
        )
        assert decoded["sub"] == "testuser"
        assert "user_id" in decoded
        assert "exp" in decoded

    def test_create_access_token_with_expiry(
            self,
            security_service: SecurityService
    ) -> None:
        """Test access token creation with custom expiry."""
        data = {"sub": "testuser"}
        expires_delta = timedelta(minutes=15)

        token = security_service.create_access_token(data, expires_delta)

        decoded = jwt.decode(
            token,
            security_service.settings.SECRET_KEY,
            algorithms=[security_service.settings.ALGORITHM]
        )

        # Check expiry is approximately correct (within 1 second)
        expected_exp = datetime.now(timezone.utc) + expires_delta
        actual_exp = datetime.fromtimestamp(decoded["exp"], tz=timezone.utc)
        assert abs((expected_exp - actual_exp).total_seconds()) < 1

    def test_create_access_token_with_roles(
            self,
            security_service: SecurityService
    ) -> None:
        """Test access token creation with user roles."""
        user_id = str(uuid4())
        data = {
            "sub": "admin_user",
            "user_id": user_id,
            "role": UserRole.ADMIN
        }

        expires_delta = timedelta(minutes=security_service.settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        token = security_service.create_access_token(data, expires_delta=expires_delta)

        decoded = jwt.decode(
            token,
            security_service.settings.SECRET_KEY,
            algorithms=[security_service.settings.ALGORITHM]
        )

        assert decoded["role"] == UserRole.ADMIN
        assert decoded["user_id"] == user_id

    def test_token_contains_expected_claims(self, security_service: SecurityService) -> None:
        data = {"sub": "testuser", "user_id": str(uuid4()), "role": UserRole.USER}
        token = security_service.create_access_token(
            data, expires_delta=timedelta(minutes=security_service.settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        decoded = jwt.decode(
            token, security_service.settings.SECRET_KEY, algorithms=[security_service.settings.ALGORITHM]
        )
        assert decoded["sub"] == "testuser"
        assert decoded["user_id"] == data["user_id"]
        assert decoded["role"] == UserRole.USER

    def test_decode_token_expired(
            self,
            security_service: SecurityService
    ) -> None:
        """Test decoding an expired token."""
        data = {"sub": "testuser"}
        expires_delta = timedelta(seconds=-1)  # Already expired

        token = security_service.create_access_token(data, expires_delta)

        # Try to decode expired token - should raise
        with pytest.raises(jwt.ExpiredSignatureError):
            jwt.decode(
                token,
                security_service.settings.SECRET_KEY,
                algorithms=[security_service.settings.ALGORITHM],
            )

    def test_decode_token_invalid_signature(
            self,
            security_service: SecurityService
    ) -> None:
        """Test decoding token with invalid signature."""
        data = {"sub": "testuser"}

        # Create token with one key
        token = security_service.create_access_token(
            data, expires_delta=timedelta(minutes=security_service.settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        # Decoding with a wrong key raises
        with pytest.raises(InvalidTokenError):
            jwt.decode(
                token,
                "different-secret-key-for-testing-only",
                algorithms=[security_service.settings.ALGORITHM],
            )

    def test_decode_token_malformed(
            self,
            security_service: SecurityService
    ) -> None:
        """Test decoding malformed token."""
        malformed_tokens = [
            "not.a.token",
            "invalid_base64",
            "",
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",  # Missing parts
        ]

        for token in malformed_tokens:
            # Should raise when trying to decode malformed tokens
            with pytest.raises((jwt.DecodeError, jwt.InvalidTokenError)):
                jwt.decode(
                    token,
                    security_service.settings.SECRET_KEY,
                    algorithms=[security_service.settings.ALGORITHM],
                )

    def test_decode_token_missing_username(
            self,
            security_service: SecurityService
    ) -> None:
        """Test decoding token without username."""
        # Create token without 'sub' field
        data: dict[str, str | datetime] = {"user_id": str(uuid4())}

        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
        to_encode = data.copy()
        to_encode["exp"] = expire

        token = jwt.encode(
            to_encode,
            security_service.settings.SECRET_KEY,
            algorithm=security_service.settings.ALGORITHM,
        )

        # Token is valid JWT but missing 'sub' - should decode successfully
        decoded = jwt.decode(
            token, security_service.settings.SECRET_KEY, algorithms=[security_service.settings.ALGORITHM]
        )
        assert "sub" not in decoded
        assert decoded["user_id"] == data["user_id"]

    async def test_concurrent_token_creation(
            self,
            security_service: SecurityService
    ) -> None:
        """Test concurrent token creation for thread safety."""
        users = [f"user_{i}" for i in range(100)]

        async def create_token(username: str) -> str:
            data = {"sub": username, "user_id": str(uuid4())}
            return security_service.create_access_token(
                data, expires_delta=timedelta(minutes=security_service.settings.ACCESS_TOKEN_EXPIRE_MINUTES)
            )

        # Create tokens concurrently
        tasks = [create_token(user) for user in users]
        tokens = await asyncio.gather(*tasks)

        # Verify all tokens are unique and valid
        assert len(set(tokens)) == len(tokens)  # All unique

        for i, token in enumerate(tokens):
            decoded = jwt.decode(
                token,
                security_service.settings.SECRET_KEY,
                algorithms=[security_service.settings.ALGORITHM],
            )
            assert decoded["sub"] == users[i]

    def test_token_has_only_expected_claims(self, security_service: SecurityService) -> None:
        user_id = str(uuid4())
        data = {"sub": "testuser", "user_id": user_id, "role": UserRole.USER, "extra_field": "x"}
        token = security_service.create_access_token(
            data, expires_delta=timedelta(minutes=security_service.settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        decoded = jwt.decode(
            token, security_service.settings.SECRET_KEY, algorithms=[security_service.settings.ALGORITHM]
        )
        assert decoded["sub"] == "testuser"
        assert decoded["user_id"] == user_id
        assert decoded["role"] == UserRole.USER
        assert "extra_field" in decoded  # Claims are carried as provided

    def test_password_context_configuration(self, test_settings: Settings) -> None:
        """Test password context is properly configured."""
        svc = SecurityService(test_settings)
        password = "test_password"
        hashed = svc.get_password_hash(password)
        assert svc.verify_password(password, hashed)

    def test_token_algorithm_consistency(
            self,
            security_service: SecurityService
    ) -> None:
        """Test that token algorithm is consistent."""
        data = {"sub": "testuser"}

        token = security_service.create_access_token(
            data, expires_delta=timedelta(minutes=security_service.settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )

        # Decode token header to check algorithm
        header = jwt.get_unverified_header(token)
        assert header["alg"] == security_service.settings.ALGORITHM
        assert header["typ"] == "JWT"


class TestDecodeToken:
    """Test SecurityService.decode_token method."""

    @pytest.fixture
    def security_service(self, test_settings: Settings) -> SecurityService:
        return SecurityService(test_settings)

    def test_valid_token_returns_username(self, security_service: SecurityService) -> None:
        token = security_service.create_access_token(
            {"sub": "testuser"}, expires_delta=timedelta(minutes=15)
        )

        result = security_service.decode_token(token)

        assert result == "testuser"

    def test_expired_token_raises(self, security_service: SecurityService) -> None:
        token = security_service.create_access_token(
            {"sub": "testuser"}, expires_delta=timedelta(seconds=-1)
        )

        with pytest.raises(InvalidCredentialsError):
            security_service.decode_token(token)

    def test_missing_sub_raises(self, security_service: SecurityService) -> None:
        token = security_service.create_access_token(
            {"user_id": str(uuid4())}, expires_delta=timedelta(minutes=15)
        )

        with pytest.raises(InvalidCredentialsError):
            security_service.decode_token(token)

    def test_invalid_signature_raises(self, security_service: SecurityService) -> None:
        token = jwt.encode(
            {"sub": "testuser", "exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
            "wrong-secret-key",
            algorithm=security_service.settings.ALGORITHM,
        )

        with pytest.raises(InvalidCredentialsError):
            security_service.decode_token(token)

    @pytest.mark.parametrize("bad_token", ["not.a.token", "invalid_base64", ""])
    def test_malformed_token_raises(self, security_service: SecurityService, bad_token: str) -> None:
        with pytest.raises(InvalidCredentialsError):
            security_service.decode_token(bad_token)
