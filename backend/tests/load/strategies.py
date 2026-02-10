from __future__ import annotations

from hypothesis import strategies as st

# Type alias for JSON values
type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]

# Generic JSON strategies (bounded sizes to keep payloads realistic)
json_scalar = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-10_000, max_value=10_000),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.text(min_size=0, max_size=256),
)

json_value: st.SearchStrategy[JsonValue]
json_value = st.recursive(
    json_scalar,
    lambda children: st.one_of(
        st.lists(children, min_size=0, max_size=8),
        st.dictionaries(
            keys=st.text(min_size=0, max_size=32), values=children, min_size=0, max_size=8
        ),
    ),
    max_leaves=32,
)


# UserCreate payloads for /auth/register
username = st.text(min_size=1, max_size=32).filter(lambda s: all(c not in s for c in " \n\t\r"))
email_local = st.text(min_size=1, max_size=32).filter(lambda s: all(c not in s for c in " \n\t\r@"))
email_domain = st.text(min_size=1, max_size=32).filter(lambda s: all(c not in s for c in " \n\t\r@"))
email = st.builds(lambda a, b: f"{a}@{b}", email_local, email_domain)
password = st.text(min_size=6, max_size=64)

user_create = st.fixed_dictionaries(
    {
        "username": username,
        "email": email,
        "password": password,
    }
)
