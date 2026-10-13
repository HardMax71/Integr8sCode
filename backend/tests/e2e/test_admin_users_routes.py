import uuid

import pytest
from httpx2 import AsyncClient

from app.domain.enums import UserRole
from app.schemas_pydantic.admin_user_overview import AdminUserOverview
from app.schemas_pydantic.user import (
    DeleteUserResponse,
    MessageResponse,
    PasswordResetRequest,
    RateLimitUpdateRequest,
    RateLimitUpdateResponse,
    UnlockResponse,
    UserCreate,
    UserListResponse,
    UserRateLimitsResponse,
    UserResponse,
    UserUpdate,
)

pytestmark = [pytest.mark.e2e]


def make_user_create(prefix: str, role: UserRole = UserRole.USER) -> UserCreate:
    """Helper to create UserCreate with unique username/email."""
    uid = uuid.uuid4().hex[:8]
    return UserCreate(
        username=f"{prefix}_{uid}",
        email=f"{prefix}_{uid}@example.com",
        password="password123",
        role=role,
    )


class TestListUsers:
    """Tests for GET /api/v1/admin/users/."""

    async def test_list_users(self, test_admin: AsyncClient) -> None:
        """Admin can list all users."""
        response = await test_admin.get("/api/v1/admin/users/")

        assert response.status_code == 200
        result = UserListResponse.model_validate(response.json())

        assert result.total >= 1  # at least admin + test users
        assert result.offset == 0
        assert result.limit == 100  # default

    async def test_list_users_with_pagination(self, test_admin: AsyncClient) -> None:
        """Pagination parameters work correctly."""
        response = await test_admin.get(
            "/api/v1/admin/users/",
            params={"limit": 10, "offset": 0},
        )

        assert response.status_code == 200
        result = UserListResponse.model_validate(response.json())
        assert result.limit == 10
        assert result.offset == 0

    async def test_list_users_with_search(self, test_admin: AsyncClient) -> None:
        """Search filter works correctly."""
        response = await test_admin.get(
            "/api/v1/admin/users/",
            params={"search": "test"},
        )

        assert response.status_code == 200
        UserListResponse.model_validate(response.json())

    async def test_list_users_with_role_filter(self, test_admin: AsyncClient) -> None:
        """Role filter works correctly."""
        response = await test_admin.get(
            "/api/v1/admin/users/",
            params={"role": UserRole.USER},
        )

        assert response.status_code == 200
        result = UserListResponse.model_validate(response.json())

        assert result.users
        assert {user.role for user in result.users} == {UserRole.USER}

    async def test_list_users_pages_on_the_server(self, test_admin: AsyncClient) -> None:
        """The total counts every match, and offset reaches the users past the first page."""
        prefix = f"page_{uuid.uuid4().hex[:6]}"
        names: set[str] = set()
        for _ in range(3):
            created = await test_admin.post("/api/v1/admin/users/", json=make_user_create(prefix).model_dump())
            names.add(created.json()["username"])

        first = UserListResponse.model_validate(
            (await test_admin.get("/api/v1/admin/users/", params={"search": prefix, "limit": 2})).json()
        )
        rest = UserListResponse.model_validate(
            (await test_admin.get("/api/v1/admin/users/", params={"search": prefix, "limit": 2, "offset": 2})).json()
        )

        assert (first.total, len(first.users), rest.total, len(rest.users)) == (3, 2, 3, 1)
        assert {u.username for u in first.users + rest.users} == names

    async def test_list_users_by_active_status(self, test_admin: AsyncClient) -> None:
        """is_active keeps only active or only disabled users."""
        request = make_user_create("inactive")
        user_id = (await test_admin.post("/api/v1/admin/users/", json=request.model_dump())).json()["user_id"]
        update = UserUpdate(is_active=False)
        await test_admin.put(f"/api/v1/admin/users/{user_id}", json=update.model_dump(exclude_none=True))

        disabled = await test_admin.get("/api/v1/admin/users/", params={"search": request.username, "is_active": False})
        active = await test_admin.get("/api/v1/admin/users/", params={"search": request.username, "is_active": True})

        assert [u.user_id for u in UserListResponse.model_validate(disabled.json()).users] == [user_id]
        assert UserListResponse.model_validate(active.json()).users == []

    @pytest.mark.parametrize(
        ("limits", "params", "listed"),
        [
            ({"bypass_rate_limit": True, "global_multiplier": 1.0}, {"bypass_rate_limit": True}, True),
            ({"bypass_rate_limit": True, "global_multiplier": 1.0}, {"bypass_rate_limit": False}, False),
            ({"bypass_rate_limit": False, "global_multiplier": 1.5}, {"custom_multiplier": True}, True),
            ({"bypass_rate_limit": False, "global_multiplier": 1.5}, {"custom_multiplier": False}, False),
            ({"bypass_rate_limit": False, "global_multiplier": 1.5}, {"has_custom_limits": True}, True),
            ({"bypass_rate_limit": False, "global_multiplier": 1.5}, {"has_custom_limits": False}, False),
            ({"bypass_rate_limit": False, "global_multiplier": 1.5}, {"bypass_rate_limit": True}, False),
        ],
    )
    async def test_list_users_by_rate_limits(
        self, test_admin: AsyncClient, limits: dict[str, object], params: dict[str, bool], listed: bool
    ) -> None:
        """The rate limit filters match the user's override."""
        request = make_user_create("ratelimited")
        user_id = (await test_admin.post("/api/v1/admin/users/", json=request.model_dump())).json()["user_id"]
        update = RateLimitUpdateRequest.model_validate({**limits, "rules": []})
        await test_admin.put(f"/api/v1/admin/rate-limits/{user_id}", json=update.model_dump())

        response = await test_admin.get("/api/v1/admin/users/", params={"search": request.username, **params})

        assert response.status_code == 200
        result = UserListResponse.model_validate(response.json())
        assert [u.user_id for u in result.users] == ([user_id] if listed else [])
        assert result.total == (1 if listed else 0)

    async def test_list_users_forbidden_for_regular_user(self, test_user: AsyncClient) -> None:
        """Regular user cannot list users."""
        response = await test_user.get("/api/v1/admin/users/")
        assert response.status_code == 403

    async def test_list_users_unauthenticated(self, client: AsyncClient) -> None:
        """Unauthenticated request returns 401."""
        response = await client.get("/api/v1/admin/users/")
        assert response.status_code == 401


class TestCreateUser:
    """Tests for POST /api/v1/admin/users/."""

    async def test_create_user(self, test_admin: AsyncClient) -> None:
        """Admin can create a new user."""
        request = make_user_create("newuser")
        response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())

        assert response.status_code == 200
        raw_data = response.json()
        user = UserResponse.model_validate(raw_data)

        assert user.user_id
        assert user.username == request.username
        assert user.email == request.email
        assert user.role == UserRole.USER
        assert user.is_active is True

        # Security: password must not be exposed in response
        assert "password" not in raw_data
        assert "hashed_password" not in raw_data

    async def test_create_admin_user(self, test_admin: AsyncClient) -> None:
        """Admin can create another admin user."""
        request = make_user_create("newadmin", role=UserRole.ADMIN)
        response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())

        assert response.status_code == 200
        user = UserResponse.model_validate(response.json())
        assert user.role == UserRole.ADMIN

    async def test_create_user_duplicate_username(self, test_admin: AsyncClient) -> None:
        """Cannot create user with duplicate username."""
        uid = uuid.uuid4().hex[:8]
        first_user = UserCreate(
            username=f"duplicate_{uid}",
            email=f"first_{uid}@example.com",
            password="password123",
            role=UserRole.USER,
        )

        # Create first user and verify success
        first_response = await test_admin.post(
            "/api/v1/admin/users/",
            json=first_user.model_dump(),
        )
        assert first_response.status_code == 200
        created_user = UserResponse.model_validate(first_response.json())
        assert created_user.username == first_user.username

        # Try to create second user with same username
        duplicate_user = UserCreate(
            username=f"duplicate_{uid}",
            email=f"second_{uid}@example.com",
            password="password123",
            role=UserRole.USER,
        )
        response = await test_admin.post(
            "/api/v1/admin/users/",
            json=duplicate_user.model_dump(),
        )

        assert response.status_code == 409

    async def test_create_user_invalid_password(self, test_admin: AsyncClient) -> None:
        """Cannot create user with too short password."""
        response = await test_admin.post(
            "/api/v1/admin/users/",
            json={
                "username": "shortpw",
                "email": "shortpw@example.com",
                "password": "short",  # less than 8 chars
                "role": UserRole.USER,
            },
        )

        assert response.status_code == 422

    async def test_create_user_forbidden_for_regular_user(self, test_user: AsyncClient) -> None:
        """Regular user cannot create users."""
        response = await test_user.post(
            "/api/v1/admin/users/",
            json={
                "username": "forbidden",
                "email": "forbidden@example.com",
                "password": "password123",
                "role": UserRole.USER,
            },
        )
        assert response.status_code == 403


class TestGetUser:
    """Tests for GET /api/v1/admin/users/{user_id}."""

    async def test_get_user(self, test_admin: AsyncClient) -> None:
        """Admin can get a specific user."""
        # Create user first
        request = make_user_create("getuser")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        created_user = UserResponse.model_validate(create_response.json())

        # Get user
        response = await test_admin.get(f"/api/v1/admin/users/{created_user.user_id}")

        assert response.status_code == 200
        user = UserResponse.model_validate(response.json())

        assert user.user_id == created_user.user_id
        assert user.username == request.username
        assert user.email == request.email

    async def test_get_user_not_found(self, test_admin: AsyncClient) -> None:
        """Get nonexistent user returns 404."""
        response = await test_admin.get("/api/v1/admin/users/nonexistent-user-id")
        assert response.status_code == 404
        assert response.json() == {"detail": "User 'nonexistent-user-id' not found", "status": 404}

    async def test_get_user_forbidden_for_regular_user(self, test_user: AsyncClient, test_admin: AsyncClient) -> None:
        """Regular user cannot get user details."""
        # Create user as admin first
        request = make_user_create("target")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Try to get as regular user
        response = await test_user.get(f"/api/v1/admin/users/{user_id}")
        assert response.status_code == 403


class TestGetUserOverview:
    """Tests for GET /api/v1/admin/users/{user_id}/overview."""

    async def test_get_user_overview(self, test_admin: AsyncClient) -> None:
        """Admin can get user overview."""
        # Create user first
        request = make_user_create("overview")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Get overview
        response = await test_admin.get(f"/api/v1/admin/users/{user_id}/overview")

        assert response.status_code == 200
        overview = AdminUserOverview.model_validate(response.json())

        assert overview.user.user_id == user_id

    async def test_get_user_overview_not_found(self, test_admin: AsyncClient) -> None:
        """Get overview for nonexistent user returns 404."""
        response = await test_admin.get("/api/v1/admin/users/nonexistent-user-id/overview")
        assert response.status_code == 404
        assert response.json() == {"detail": "User 'nonexistent-user-id' not found", "status": 404}

    async def test_get_user_overview_forbidden_for_regular_user(
        self, test_user: AsyncClient, test_admin: AsyncClient
    ) -> None:
        """Regular user cannot get user overview."""
        # Create user as admin
        request = make_user_create("target")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Try as regular user
        response = await test_user.get(f"/api/v1/admin/users/{user_id}/overview")
        assert response.status_code == 403


class TestUpdateUser:
    """Tests for PUT /api/v1/admin/users/{user_id}."""

    async def test_update_user_username(self, test_admin: AsyncClient) -> None:
        """Admin can update user's username."""
        # Create user
        request = make_user_create("original")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user = UserResponse.model_validate(create_response.json())

        # Update username
        new_username = f"updated_{uuid.uuid4().hex[:8]}"
        update = UserUpdate(username=new_username)
        response = await test_admin.put(
            f"/api/v1/admin/users/{user.user_id}",
            json=update.model_dump(exclude_none=True),
        )

        assert response.status_code == 200
        updated = UserResponse.model_validate(response.json())
        assert updated.username == new_username
        assert updated.updated_at > user.updated_at

    @pytest.mark.parametrize("field", ["username", "email"])
    async def test_update_user_to_taken_value_conflicts(self, test_admin: AsyncClient, field: str) -> None:
        """Renaming a user to another user's username or email is a 409, not a 500."""
        taken = UserResponse.model_validate(
            (await test_admin.post("/api/v1/admin/users/", json=make_user_create("taken").model_dump())).json()
        )
        target = UserResponse.model_validate(
            (await test_admin.post("/api/v1/admin/users/", json=make_user_create("target").model_dump())).json()
        )

        response = await test_admin.put(f"/api/v1/admin/users/{target.user_id}", json={field: getattr(taken, field)})

        assert response.status_code == 409
        assert response.json() == {"detail": f"{field.capitalize()} already exists", "status": 409}

    async def test_update_user_role(self, test_admin: AsyncClient) -> None:
        """Admin can update user's role."""
        # Create user
        request = make_user_create("roletest")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Update role
        update = UserUpdate(role=UserRole.ADMIN)
        response = await test_admin.put(
            f"/api/v1/admin/users/{user_id}",
            json=update.model_dump(exclude_none=True),
        )

        assert response.status_code == 200
        updated = UserResponse.model_validate(response.json())
        assert updated.role == UserRole.ADMIN

    async def test_update_user_deactivate(self, test_admin: AsyncClient) -> None:
        """Admin can deactivate a user."""
        # Create user
        request = make_user_create("deactivate")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Deactivate
        update = UserUpdate(is_active=False)
        response = await test_admin.put(
            f"/api/v1/admin/users/{user_id}",
            json=update.model_dump(exclude_none=True),
        )

        assert response.status_code == 200
        updated = UserResponse.model_validate(response.json())
        assert updated.is_active is False

    async def test_update_user_not_found(self, test_admin: AsyncClient) -> None:
        """Update nonexistent user returns 404."""
        response = await test_admin.put(
            "/api/v1/admin/users/nonexistent-user-id",
            json={"username": "test"},
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "User 'nonexistent-user-id' not found", "status": 404}

    async def test_update_user_forbidden_for_regular_user(
        self, test_user: AsyncClient, test_admin: AsyncClient
    ) -> None:
        """Regular user cannot update other users."""
        # Create user as admin
        request = make_user_create("target")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Try to update as regular user (raw dict - testing invalid access)
        response = await test_user.put(
            f"/api/v1/admin/users/{user_id}",
            json={"username": "hacked"},
        )
        assert response.status_code == 403


class TestDeleteUser:
    """Tests for DELETE /api/v1/admin/users/{user_id}."""

    async def test_delete_user(self, test_admin: AsyncClient) -> None:
        """Admin can delete a user."""
        # Create user
        request = make_user_create("delete")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Delete
        response = await test_admin.delete(f"/api/v1/admin/users/{user_id}")

        assert response.status_code == 200
        result = DeleteUserResponse.model_validate(response.json())
        assert result.user_deleted is True

        # Verify deleted
        get_response = await test_admin.get(f"/api/v1/admin/users/{user_id}")
        assert get_response.status_code == 404

    async def test_delete_user_cascade(self, test_admin: AsyncClient) -> None:
        """Delete user with cascade option."""
        # Create user
        request = make_user_create("cascade")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Delete with cascade
        response = await test_admin.delete(
            f"/api/v1/admin/users/{user_id}",
            params={"cascade": True},
        )

        assert response.status_code == 200
        result = DeleteUserResponse.model_validate(response.json())
        assert result.user_deleted is True

    async def test_delete_user_not_found(self, test_admin: AsyncClient) -> None:
        """Delete nonexistent user returns 404."""
        response = await test_admin.delete("/api/v1/admin/users/nonexistent-user-id")
        assert response.status_code == 404
        assert response.json() == {"detail": "User 'nonexistent-user-id' not found", "status": 404}

    async def test_delete_self_forbidden(self, test_admin: AsyncClient) -> None:
        """Admin cannot delete their own account."""
        # Get admin's own user_id
        me_response = await test_admin.get("/api/v1/auth/me")
        admin_user_id = me_response.json()["user_id"]

        # Try to delete self
        response = await test_admin.delete(f"/api/v1/admin/users/{admin_user_id}")
        assert response.status_code == 400
        assert response.json() == {"detail": "Cannot delete your own account", "status": 400}

    async def test_delete_user_forbidden_for_regular_user(
        self, test_user: AsyncClient, test_admin: AsyncClient
    ) -> None:
        """Regular user cannot delete users."""
        # Create user as admin
        request = make_user_create("target")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Try to delete as regular user
        response = await test_user.delete(f"/api/v1/admin/users/{user_id}")
        assert response.status_code == 403


class TestResetPassword:
    """Tests for POST /api/v1/admin/users/{user_id}/reset-password."""

    async def test_reset_password(self, test_admin: AsyncClient) -> None:
        """Admin can reset user's password."""
        # Create user
        request = make_user_create("pwreset")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Reset password
        reset_request = PasswordResetRequest(new_password="newpassword456")
        response = await test_admin.post(
            f"/api/v1/admin/users/{user_id}/reset-password",
            json=reset_request.model_dump(),
        )

        assert response.status_code == 200
        result = MessageResponse.model_validate(response.json())
        assert "reset" in result.message.lower()
        assert user_id in result.message

    async def test_reset_password_short_password(self, test_admin: AsyncClient) -> None:
        """Cannot reset to password shorter than 8 chars."""
        # Create user
        request = make_user_create("shortpw")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Try to reset with short password (raw dict - testing validation error)
        response = await test_admin.post(
            f"/api/v1/admin/users/{user_id}/reset-password",
            json={"new_password": "short"},
        )

        assert response.status_code == 422

    async def test_reset_password_user_not_found(self, test_admin: AsyncClient) -> None:
        """Reset password for nonexistent user returns 404."""
        response = await test_admin.post(
            "/api/v1/admin/users/nonexistent-user-id/reset-password",
            json=PasswordResetRequest(new_password="newpassword456").model_dump(),
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "User 'nonexistent-user-id' not found", "status": 404}

    async def test_reset_password_forbidden_for_regular_user(
        self, test_user: AsyncClient, test_admin: AsyncClient
    ) -> None:
        """Regular user cannot reset passwords."""
        # Create user as admin
        request = make_user_create("target")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Try as regular user (raw dict - testing forbidden access)
        response = await test_user.post(
            f"/api/v1/admin/users/{user_id}/reset-password",
            json={"new_password": "newpassword123"},
        )
        assert response.status_code == 403


class TestGetUserRateLimits:
    """Tests for GET /api/v1/admin/rate-limits/{user_id}."""

    async def test_get_user_rate_limits(self, test_admin: AsyncClient) -> None:
        """Admin can get user's rate limits."""
        # Create user
        request = make_user_create("ratelimit")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Get rate limits
        response = await test_admin.get(f"/api/v1/admin/rate-limits/{user_id}")

        assert response.status_code == 200
        result = UserRateLimitsResponse.model_validate(response.json())

        assert result.user_id == user_id
        assert result.current_usage == {}

    async def test_get_user_rate_limits_forbidden_for_regular_user(
        self, test_user: AsyncClient, test_admin: AsyncClient
    ) -> None:
        """Regular user cannot get rate limits."""
        # Create user as admin
        request = make_user_create("target")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Try as regular user
        response = await test_user.get(f"/api/v1/admin/rate-limits/{user_id}")
        assert response.status_code == 403


class TestUpdateUserRateLimits:
    """Tests for PUT /api/v1/admin/rate-limits/{user_id}."""

    async def test_update_user_rate_limits(self, test_admin: AsyncClient) -> None:
        """Admin can update user's rate limits."""
        # Create user
        request = make_user_create("updatelimit")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Update rate limits
        update_request = RateLimitUpdateRequest(
            bypass_rate_limit=False,
            global_multiplier=1.5,
            rules=[],
        )
        response = await test_admin.put(
            f"/api/v1/admin/rate-limits/{user_id}",
            json=update_request.model_dump(),
        )

        assert response.status_code == 200
        result = RateLimitUpdateResponse.model_validate(response.json())

        assert result.user_id == user_id
        assert result.updated is True
        assert result.config is not None
        assert result.config.global_multiplier == 1.5

    async def test_update_user_rate_limits_bypass(self, test_admin: AsyncClient) -> None:
        """Admin can enable rate limit bypass for user."""
        # Create user
        request = make_user_create("bypass")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Enable bypass
        update_request = RateLimitUpdateRequest(
            bypass_rate_limit=True,
            global_multiplier=1.0,
            rules=[],
        )
        response = await test_admin.put(
            f"/api/v1/admin/rate-limits/{user_id}",
            json=update_request.model_dump(),
        )

        assert response.status_code == 200
        result = RateLimitUpdateResponse.model_validate(response.json())
        assert result.config.bypass_rate_limit is True

    async def test_update_user_rate_limits_forbidden_for_regular_user(
        self, test_user: AsyncClient, test_admin: AsyncClient
    ) -> None:
        """Regular user cannot update rate limits."""
        # Create user as admin
        request = make_user_create("target")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Try as regular user (raw dict - testing forbidden access)
        response = await test_user.put(
            f"/api/v1/admin/rate-limits/{user_id}",
            json={
                "bypass_rate_limit": True,
                "global_multiplier": 2.0,
                "rules": [],
            },
        )
        assert response.status_code == 403


class TestResetUserRateLimits:
    """Tests for POST /api/v1/admin/rate-limits/{user_id}/reset."""

    async def test_reset_user_rate_limits(self, test_admin: AsyncClient) -> None:
        """Admin can reset user's rate limits."""
        # Create user
        request = make_user_create("resetlimit")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Reset rate limits
        response = await test_admin.post(f"/api/v1/admin/rate-limits/{user_id}/reset")

        assert response.status_code == 200
        result = MessageResponse.model_validate(response.json())
        assert "reset" in result.message.lower()
        assert user_id in result.message

    async def test_reset_user_rate_limits_forbidden_for_regular_user(
        self, test_user: AsyncClient, test_admin: AsyncClient
    ) -> None:
        """Regular user cannot reset rate limits."""
        # Create user as admin
        request = make_user_create("target")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        # Try as regular user
        response = await test_user.post(f"/api/v1/admin/rate-limits/{user_id}/reset")
        assert response.status_code == 403


class TestUnlockUser:
    """Tests for POST /api/v1/admin/users/{user_id}/unlock."""

    async def test_unlock_user(self, test_admin: AsyncClient) -> None:
        """Admin can unlock a user account."""
        request = make_user_create("locked")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        response = await test_admin.post(f"/api/v1/admin/users/{user_id}/unlock")

        assert response.status_code == 200
        result = UnlockResponse.model_validate(response.json())
        assert result.user_id == user_id
        assert "unlocked" in result.message.lower()

    async def test_unlock_user_not_found(self, test_admin: AsyncClient) -> None:
        """Unlock nonexistent user returns 404."""
        response = await test_admin.post("/api/v1/admin/users/nonexistent-user-id/unlock")
        assert response.status_code == 404
        assert response.json() == {"detail": "User 'nonexistent-user-id' not found", "status": 404}

    async def test_unlock_user_forbidden_for_regular_user(
        self, test_user: AsyncClient, test_admin: AsyncClient
    ) -> None:
        """Regular user cannot unlock accounts."""
        request = make_user_create("target")
        create_response = await test_admin.post("/api/v1/admin/users/", json=request.model_dump())
        user_id = create_response.json()["user_id"]

        response = await test_user.post(f"/api/v1/admin/users/{user_id}/unlock")
        assert response.status_code == 403
