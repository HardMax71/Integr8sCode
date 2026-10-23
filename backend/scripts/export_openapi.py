import json
from pathlib import Path

from app.main import create_app
from app.settings import Settings

SPEC_PATH = Path(__file__).resolve().parents[2] / "docs" / "reference" / "openapi.json"


def export_openapi() -> None:
    """Write the API's OpenAPI spec to docs/reference/openapi.json, where the frontend's client generator reads it."""
    # config.toml's collector address resolves only inside compose; exporting there adds 11 s of failed retries
    app = create_app(settings=Settings().model_copy(update={"OTEL_EXPORTER_OTLP_ENDPOINT": None}))
    SPEC_PATH.write_text(json.dumps(app.openapi(), indent=2) + "\n")


if __name__ == "__main__":
    export_openapi()
