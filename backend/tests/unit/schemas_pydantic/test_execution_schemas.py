from datetime import datetime, timezone

import pytest

from app.schemas_pydantic.execution import ExecutionRequest


def test_execution_request_valid_supported_runtime():
    req = ExecutionRequest(script="print('ok')", lang="python", lang_version="3.11")
    assert req.lang == "python" and req.lang_version == "3.11"


def test_execution_request_unsupported_language_raises():
    with pytest.raises(ValueError) as e:
        ExecutionRequest(script="print(1)", lang="rust", lang_version="1.0")
    assert "Language 'rust' not supported" in str(e.value)


def test_execution_request_unsupported_version_raises():
    with pytest.raises(ValueError) as e:
        ExecutionRequest(script="print(1)", lang="python", lang_version="9.9")
    assert "Version '9.9' not supported for python" in str(e.value)

