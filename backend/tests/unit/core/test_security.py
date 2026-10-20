import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr

from app.core.security import SecurityService
from app.domain.enums import UserRole
from app.domain.user import InvalidCredentialsError
from app.settings import Settings


class TestPasswordHashing:
    """Test password hashing functionality."""

    @pytest.fixture
    def security_svc(self, test_settings: Settings, tracer: trace.Tracer) -> SecurityService:
        """Create SecurityService instance."""
        return SecurityService(test_settings, tracer)

    def test_password_hash_creates_different_hash(self, security_svc: SecurityService) -> None:
        """Test that password hashing creates unique hashes."""
        password = SecretStr("test_password_123")
        hash1 = security_svc.get_password_hash(password)
        hash2 = security_svc.get_password_hash(password)

        # Hashes should be different due to salting
        assert hash1 != hash2
        assert password.get_secret_value() not in hash1.get_secret_value()
        assert password.get_secret_value() not in hash2.get_secret_value()

    def test_password_verification_success(self, security_svc: SecurityService) -> None:
        """Test successful password verification."""
        password = SecretStr("correct_password")
        hashed = security_svc.get_password_hash(password)

        assert security_svc.verify_password(password, hashed) is True

    def test_password_verification_failure(self, security_svc: SecurityService) -> None:
        """Test failed password verification."""
        password = SecretStr("correct_password")
        wrong_password = SecretStr("wrong_password")
        hashed = security_svc.get_password_hash(password)

        assert security_svc.verify_password(wrong_password, hashed) is False

    def test_empty_password_handling(self, security_svc: SecurityService) -> None:
        """Test handling of empty passwords."""
        empty_password = SecretStr("")
        hashed = security_svc.get_password_hash(empty_password)

        assert security_svc.verify_password(empty_password, hashed) is True
        assert security_svc.verify_password(SecretStr("not_empty"), hashed) is False

    def test_special_characters_in_password(self, security_svc: SecurityService) -> None:
        """Test passwords with special characters."""
        special_password = SecretStr("P@ssw0rd!#$%^&*()")
        hashed = security_svc.get_password_hash(special_password)

        assert security_svc.verify_password(special_password, hashed) is True

    def test_unicode_password(self, security_svc: SecurityService) -> None:
        """Test Unicode characters in passwords."""
        unicode_password = SecretStr("пароль密码パスワード🔒")
        hashed = security_svc.get_password_hash(unicode_password)

        assert security_svc.verify_password(unicode_password, hashed) is True


class TestSecurityService:
    """Test SecurityService functionality."""

    @pytest.fixture
    def security_service(self, test_settings: Settings, tracer: trace.Tracer) -> SecurityService:
        """Create SecurityService instance using test settings."""
        return SecurityService(test_settings, tracer)

    def test_create_access_token_basic(self, security_service: SecurityService) -> None:
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
            security_service.settings.SECRET_KEY.get_secret_value(),
            algorithms=[security_service.settings.ALGORITHM],
        )
        assert decoded["sub"] == "testuser"
        assert "user_id" in decoded
        assert "exp" in decoded

    def test_create_access_token_with_expiry(self, security_service: SecurityService) -> None:
        """Test access token creation with custom expiry."""
        data = {"sub": "testuser"}
        expires_delta = timedelta(minutes=15)

        before = int(time.time())
        token = security_service.create_access_token(data, expires_delta)
        after = int(time.time())

        decoded = jwt.decode(
            token,
            security_service.settings.SECRET_KEY.get_secret_value(),
            algorithms=[security_service.settings.ALGORITHM],
        )
        lifetime = int(expires_delta.total_seconds())
        assert before + lifetime <= decoded["exp"] <= after + lifetime

    def test_create_access_token_with_roles(self, security_service: SecurityService) -> None:
        """Test access token creation with user roles."""
        user_id = str(uuid4())
        data = {"sub": "admin_user", "user_id": user_id, "role": UserRole.ADMIN}

        expires_delta = timedelta(minutes=security_service.settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        token = security_service.create_access_token(data, expires_delta=expires_delta)

        decoded = jwt.decode(
            token,
            security_service.settings.SECRET_KEY.get_secret_value(),
            algorithms=[security_service.settings.ALGORITHM],
        )

        assert decoded["role"] == UserRole.ADMIN
        assert decoded["user_id"] == user_id

    def test_token_contains_expected_claims(self, security_service: SecurityService) -> None:
        data = {"sub": "testuser", "user_id": str(uuid4()), "role": UserRole.USER}
        token = security_service.create_access_token(
            data, expires_delta=timedelta(minutes=security_service.settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        decoded = jwt.decode(
            token,
            security_service.settings.SECRET_KEY.get_secret_value(),
            algorithms=[security_service.settings.ALGORITHM],
        )
        assert decoded["sub"] == "testuser"
        assert decoded["user_id"] == data["user_id"]
        assert decoded["role"] == UserRole.USER

    def test_token_has_only_expected_claims(self, security_service: SecurityService) -> None:
        user_id = str(uuid4())
        data = {"sub": "testuser", "user_id": user_id, "role": UserRole.USER, "extra_field": "x"}
        token = security_service.create_access_token(
            data, expires_delta=timedelta(minutes=security_service.settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        decoded = jwt.decode(
            token,
            security_service.settings.SECRET_KEY.get_secret_value(),
            algorithms=[security_service.settings.ALGORITHM],
        )
        assert decoded["sub"] == "testuser"
        assert decoded["user_id"] == user_id
        assert decoded["role"] == UserRole.USER
        assert "extra_field" in decoded  # Claims are carried as provided

    def test_token_algorithm_consistency(self, security_service: SecurityService) -> None:
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
    def security_service(self, test_settings: Settings, tracer: trace.Tracer) -> SecurityService:
        return SecurityService(test_settings, tracer)

    def test_valid_token_returns_username(self, security_service: SecurityService) -> None:
        token = security_service.create_access_token({"sub": "testuser"}, expires_delta=timedelta(minutes=15))

        result = security_service.decode_token(token)

        assert result == "testuser"

    def test_expired_token_raises(self, security_service: SecurityService) -> None:
        token = security_service.create_access_token({"sub": "testuser"}, expires_delta=timedelta(seconds=-1))

        with pytest.raises(InvalidCredentialsError):
            security_service.decode_token(token)

    def test_missing_sub_raises(self, security_service: SecurityService) -> None:
        token = security_service.create_access_token({"user_id": str(uuid4())}, expires_delta=timedelta(minutes=15))

        with pytest.raises(InvalidCredentialsError):
            security_service.decode_token(token)

    def test_invalid_signature_raises(self, security_service: SecurityService) -> None:
        token = jwt.encode(
            {"sub": "testuser", "exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
            "wrong-secret-key-padded-to-32-bytes",
            algorithm=security_service.settings.ALGORITHM,
        )

        with pytest.raises(InvalidCredentialsError):
            security_service.decode_token(token)

    @pytest.mark.parametrize("bad_token", ["not.a.token", "invalid_base64", ""])
    def test_malformed_token_raises(self, security_service: SecurityService, bad_token: str) -> None:
        with pytest.raises(InvalidCredentialsError):
            security_service.decode_token(bad_token)

    @pytest.mark.parametrize(
        "claims,lifetime,key,reason",
        [
            ({"sub": "u"}, timedelta(seconds=-5), None, "expired"),
            ({"sub": "u"}, timedelta(minutes=5), "wrong-secret-key-padded-to-32-bytes", "invalid_signature"),
            ({"user_id": "x"}, timedelta(minutes=5), None, "missing_subject"),
            (None, timedelta(minutes=5), None, "invalid"),
        ],
    )
    def test_rejected_token_records_reason(
        self,
        test_settings: Settings,
        claims: dict[str, object] | None,
        lifetime: timedelta,
        key: str | None,
        reason: str,
        tracer: trace.Tracer,
        span_exporter: InMemorySpanExporter,
    ) -> None:
        svc = SecurityService(test_settings, tracer)
        token = (
            "not.a.token"
            if claims is None
            else jwt.encode(
                {**claims, "exp": datetime.now(timezone.utc) + lifetime},
                key or test_settings.SECRET_KEY.get_secret_value(),
                algorithm=test_settings.ALGORITHM,
            )
        )

        with pytest.raises(InvalidCredentialsError):
            svc.decode_token(token)

        [span] = span_exporter.get_finished_spans()
        assert (span.name, span.attributes) == ("auth.token_rejected", {"auth.reason": reason})

    def test_valid_token_records_no_failure(
        self, test_settings: Settings, tracer: trace.Tracer, span_exporter: InMemorySpanExporter
    ) -> None:
        svc = SecurityService(test_settings, tracer)

        svc.decode_token(svc.create_access_token({"sub": "u"}, expires_delta=timedelta(minutes=5)))

        assert span_exporter.get_finished_spans() == ()


class TestDecodeUserId:
    """SecurityService.decode_user_id gives an id only for a valid token that carries one."""

    def test_valid_token_returns_user_id(self, test_settings: Settings, tracer: trace.Tracer) -> None:
        svc = SecurityService(test_settings, tracer)
        token = svc.create_access_token({"sub": "u", "user_id": "user-1"}, expires_delta=timedelta(minutes=5))

        assert svc.decode_user_id(token) == "user-1"

    @pytest.mark.parametrize(
        ("claims", "lifetime", "key"),
        [
            ({"sub": "u", "user_id": "user-1"}, timedelta(seconds=-5), None),
            ({"sub": "u", "user_id": "user-1"}, timedelta(minutes=5), "wrong-secret-key-padded-to-32-bytes"),
            ({"sub": "u"}, timedelta(minutes=5), None),
            (None, timedelta(minutes=5), None),
        ],
        ids=["expired", "wrong_signature", "no_user_id", "malformed"],
    )
    def test_unusable_token_raises_without_counting_a_failure(
        self,
        test_settings: Settings,
        tracer: trace.Tracer,
        span_exporter: InMemorySpanExporter,
        claims: dict[str, object] | None,
        lifetime: timedelta,
        key: str | None,
    ) -> None:
        svc = SecurityService(test_settings, tracer)
        token = (
            "not.a.token"
            if claims is None
            else jwt.encode(
                {**claims, "exp": datetime.now(timezone.utc) + lifetime},
                key or test_settings.SECRET_KEY.get_secret_value(),
                algorithm=test_settings.ALGORITHM,
            )
        )

        with pytest.raises(InvalidCredentialsError):
            svc.decode_user_id(token)
        assert span_exporter.get_finished_spans() == ()
