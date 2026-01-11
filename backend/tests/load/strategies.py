from __future__ import annotations

from datetime import datetime, timedelta

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


# Grafana webhook strategy (approximate schema)
severity = st.sampled_from(["info", "warning", "error", "critical"])  # common values
label_key = st.text(min_size=1, max_size=24)
label_val = st.text(min_size=0, max_size=64)
label_dict = st.dictionaries(label_key, label_val, max_size=8)
annotation_dict = st.dictionaries(label_key, label_val, max_size=8)

def _iso_time() -> st.SearchStrategy[str]:
    base = datetime(2024, 1, 1)
    return st.integers(min_value=0, max_value=86_400).map(
        lambda sec: (base + timedelta(seconds=int(sec))).isoformat() + "Z"
    )

alert = st.fixed_dictionaries(
    {
        "status": st.sampled_from(["firing", "resolved"]),
        "labels": label_dict,
        "annotations": annotation_dict,
        "startsAt": _iso_time(),
        "endsAt": _iso_time(),
        "generatorURL": st.text(min_size=0, max_size=120),
        "fingerprint": st.text(min_size=1, max_size=64),
    }
)

grafana_webhook = st.fixed_dictionaries(
    {
        "receiver": st.text(min_size=1, max_size=64),
        "status": st.sampled_from(["firing", "resolved"]),
        "alerts": st.lists(alert, min_size=1, max_size=5),
        "groupKey": st.text(min_size=0, max_size=64),
        "groupLabels": label_dict,
        "commonLabels": label_dict,
        "commonAnnotations": annotation_dict,
        "externalURL": st.text(min_size=0, max_size=120),
        "version": st.text(min_size=1, max_size=16),
    }
)
