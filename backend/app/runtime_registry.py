from __future__ import annotations

from typing import Dict, List, NamedTuple


class RuntimeConfig(NamedTuple):
    image: str          # Full Docker image reference
    file_name: str      # Name that will be mounted under /scripts/
    command: List[str]  # Entrypoint executed inside the container


LANGUAGE_SPECS: Dict[str, dict] = {
    "python": {
        "versions": ["3.7", "3.8", "3.9", "3.10", "3.11", "3.12"],
        "image_tpl": "python:{version}-slim",
        "file_ext": "py",
        "interpreter": ["python"],
    },
    "node": {
        "versions": ["18", "20", "22"],
        "image_tpl": "node:{version}-alpine",
        "file_ext": "js",
        "interpreter": ["node"],
    },
    "ruby": {
        "versions": ["3.1", "3.2", "3.3"],
        "image_tpl": "ruby:{version}-alpine",
        "file_ext": "rb",
        "interpreter": ["ruby"],
    },
    "bash": {
        "versions": ["5.1", "5.2", "5.3"],
        "image_tpl": "bash:{version}",
        "file_ext": "sh",
        "interpreter": ["bash"],
    },
    "go": {
        "versions": ["1.20", "1.21", "1.22"],
        "image_tpl": "golang:{version}-alpine",
        "file_ext": "go",
        "interpreter": ["sh", "-c", "go run /scripts/main.go"],
    },
}

def _make_runtime_configs() -> Dict[str, Dict[str, RuntimeConfig]]:
    registry: Dict[str, Dict[str, RuntimeConfig]] = {}

    for lang, spec in LANGUAGE_SPECS.items():
        versions = spec["versions"]
        image_tpl: str = spec["image_tpl"]
        file_ext: str = spec["file_ext"]
        interpreter_cmd: List[str] = spec["interpreter"]

        file_name = f"main.{file_ext}"
        full_path = f"/scripts/{file_name}"

        registry[lang] = {
            v: RuntimeConfig(
                image=image_tpl.format(version=v),
                file_name=file_name,
                command=(
                    interpreter_cmd
                    if "{file}" in " ".join(interpreter_cmd)
                    else interpreter_cmd + [full_path]
                ),
            )
            for v in versions
        }

    return registry


RUNTIME_REGISTRY: Dict[str, Dict[str, RuntimeConfig]] = _make_runtime_configs()

SUPPORTED_RUNTIMES: Dict[str, List[str]] = {
    lang: list(versions.keys()) for lang, versions in RUNTIME_REGISTRY.items()
}
