import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import NamedTuple, NotRequired, TypedDict


# --8<-- [start:RuntimeConfig]
class RuntimeConfig(NamedTuple):
    image: str  # Full Docker image reference
    file_name: str  # Name that will be mounted under /scripts/
    command: list[str]  # Entrypoint executed inside the container


# --8<-- [end:RuntimeConfig]


@dataclass(frozen=True)
class PodRuntimeConfig:
    env: dict[str, str] = field(default_factory=dict)
    tmp_size: str = "10Mi"
    min_cpu: str | None = None
    min_memory: str | None = None
    min_timeout_seconds: int | None = None


_QUANTITY = re.compile(r"(\d+(?:\.\d+)?)([KMGT]i|[mkMGT])?")
_QUANTITY_SCALE = {
    None: Decimal(1),
    "m": Decimal("0.001"),
    "k": Decimal(10**3),
    "M": Decimal(10**6),
    "G": Decimal(10**9),
    "T": Decimal(10**12),
    "Ki": Decimal(2**10),
    "Mi": Decimal(2**20),
    "Gi": Decimal(2**30),
    "Ti": Decimal(2**40),
}


def parse_quantity(value: str) -> Decimal:
    """Parse a Kubernetes resource quantity such as ``500m`` or ``320Mi`` into base units.

    Raises:
        ValueError: If the quantity uses a format this parser does not support.
    """
    match = _QUANTITY.fullmatch(value)
    if not match:
        raise ValueError(f"Unsupported resource quantity: {value!r}")
    return Decimal(match[1]) * _QUANTITY_SCALE[match[2]]


def at_least(configured: str, minimum: str | None) -> str:
    """Return the larger of a configured quantity and an optional minimum."""
    if minimum is None or parse_quantity(configured) >= parse_quantity(minimum):
        return configured
    return minimum


# --8<-- [start:LanguageSpec]
class LanguageSpec(TypedDict):
    versions: list[str]
    image_tpl: str
    file_ext: str
    interpreter: list[str]
    pod: NotRequired[PodRuntimeConfig]


# --8<-- [end:LanguageSpec]


# --8<-- [start:LANGUAGE_SPECS]
LANGUAGE_SPECS: dict[str, LanguageSpec] = {
    "python": {
        "versions": ["3.14", "3.13", "3.12", "3.11"],
        "image_tpl": "python:{version}-slim",
        "file_ext": "py",
        "interpreter": ["python"],
    },
    "node": {
        "versions": ["26", "24", "22"],
        "image_tpl": "node:{version}-alpine",
        "file_ext": "js",
        "interpreter": ["node"],
    },
    "ruby": {
        "versions": ["4.0", "3.4", "3.3"],
        "image_tpl": "ruby:{version}-alpine",
        "file_ext": "rb",
        "interpreter": ["ruby"],
    },
    "bash": {
        "versions": ["5.3"],
        "image_tpl": "bash:{version}",
        "file_ext": "sh",
        "interpreter": ["bash"],
    },
    "go": {
        "versions": ["1.27", "1.26"],
        "image_tpl": "golang:{version}-alpine",
        "file_ext": "go",
        # exec keeps the PID, so the entrypoint measures the program instead of the go tool that built it
        "interpreter": [
            "sh",
            "-c",
            'go build -o /tmp/main -ldflags="-s -w" -gcflags=all=-dwarf=false "$0" && exec /tmp/main',
        ],
        # A cold build compiles the runtime and std into GOCACHE: about 50Mi of /tmp, 230Mi RSS, 10s of CPU.
        "pod": PodRuntimeConfig(
            env={"HOME": "/tmp", "GOCACHE": "/tmp/go-cache"},  # nosec B108: paths inside the executor pod
            tmp_size="64Mi",
            min_cpu="1000m",
            min_memory="320Mi",
            min_timeout_seconds=30,
        ),
    },
}
# --8<-- [end:LANGUAGE_SPECS]

DEFAULT_LANG = "python"
DEFAULT_LANG_VERSION = LANGUAGE_SPECS[DEFAULT_LANG]["versions"][0]

# --8<-- [start:EXAMPLE_SCRIPTS]
EXAMPLE_SCRIPTS: dict[str, str] = {
    "python": """
import itertools
import platform

print(f"Hello from a Python {platform.python_version()} script!")


# Structural pattern matching and X | Y unions work on every offered version (3.11+).
def process_data(value: int | str | None) -> str:
    match value:
        case None:
            return "No value"
        case int() if value > 10:
            return f"Big number: {value}"
        case _:
            return f"Got: {value}"


print(process_data(42))
print(process_data("hello"))
print(process_data(None))

# itertools.batched() arrived in Python 3.12, so check for it first.
if hasattr(itertools, "batched"):
    print(f"itertools.batched() is available (Python 3.12+): {list(itertools.batched('abcdef', 2))}")
else:
    print("itertools.batched() is not available on this version (needs Python 3.12+).")
""",
    "node": """
console.log(`Hello from Node.js ${process.version}!`);

// Promise.withResolvers() (Node.js 22+) works on every offered version.
const { promise, resolve } = Promise.withResolvers();
promise.then((msg) => console.log(`Promise.withResolvers() resolved with: ${msg}`));
resolve('Success');

// RegExp.escape() arrived in Node.js 24, so check for it first.
if (typeof RegExp.escape === 'function') {
  console.log(`RegExp.escape() is available (Node.js 24+): ${RegExp.escape('(1+1)?')}`);
} else {
  console.log('RegExp.escape() is not available on this version (needs Node.js 24+).');
}
""",
    "ruby": """
puts "Hello from Ruby #{RUBY_VERSION}!"

# Data objects (Ruby 3.2+) work on every offered version.
Point = Data.define(:x, :y)
point = Point.new(x: 1, y: 2)
puts "Data objects are supported. Created point: #{point.inspect}"

# Array#fetch_values arrived in Ruby 3.4, so check for it first.
if [].respond_to?(:fetch_values)
  puts "Array#fetch_values is available (Ruby 3.4+): #{%w[a b c].fetch_values(0, 2).inspect}"
else
  puts "Array#fetch_values is not available on this version (needs Ruby 3.4+)."
end
""",
    "bash": """
echo "Hello from Bash version $BASH_VERSION"
echo "Bash major version: ${BASH_VERSINFO[0]}"
echo "Bash minor version: ${BASH_VERSINFO[1]}"

# The ${var@U} uppercase expansion (Bash 5.1+) works on every offered version.
my_var="hello"
echo "Original: $my_var, Uppercased: ${my_var@U}"

# ${ command; } runs a command substitution without a subshell (Bash 5.3+), so check the version first.
if (( BASH_VERSINFO[0] > 5 || (BASH_VERSINFO[0] == 5 && BASH_VERSINFO[1] >= 3) )); then
    counter=1
    result=${ counter=2; echo "no subshell"; }
    echo "Command substitution ran with $result, counter is now $counter (Bash 5.3+)"
else
    echo "The \\${ command; } substitution is not available in this Bash version (needs Bash 5.3+)."
fi
""",
    "go": """
package main

import (
    "fmt"
    "runtime"
)

// Generics (Go 1.18+) work on every offered version.
func Print[T any](s T) {
    fmt.Println(s)
}

func main() {
    Print(fmt.Sprintf("Hello from Go version %s!", runtime.Version()))

    // The clear() builtin (Go 1.21+) empties maps and slices.
    myMap := map[string]int{"a": 1}
    Print(fmt.Sprintf("Map before clear: %v", myMap))
    clear(myMap)
    Print(fmt.Sprintf("Map after clear: length is %d", len(myMap)))

    // new() accepts an expression since Go 1.26.
    answer := new(len(myMap) + 42)
    Print(fmt.Sprintf("new(expr) (Go 1.26+) points to %d", *answer))
}
""",
}
# --8<-- [end:EXAMPLE_SCRIPTS]


def _make_runtime_configs(specs: dict[str, LanguageSpec]) -> dict[str, dict[str, RuntimeConfig]]:
    registry: dict[str, dict[str, RuntimeConfig]] = {}

    for lang, spec in specs.items():
        versions = spec["versions"]
        image_tpl: str = spec["image_tpl"]
        file_ext: str = spec["file_ext"]
        interpreter_cmd: list[str] = spec["interpreter"]

        file_name = f"main.{file_ext}"
        full_path = f"/scripts/{file_name}"

        registry[lang] = {
            v: RuntimeConfig(
                image=image_tpl.format(version=v),
                file_name=file_name,
                command=[*interpreter_cmd, full_path],
            )
            for v in versions
        }

    return registry


RUNTIME_REGISTRY: dict[str, dict[str, RuntimeConfig]] = _make_runtime_configs(LANGUAGE_SPECS)

POD_RUNTIME_CONFIGS: dict[str, PodRuntimeConfig] = {
    lang: spec.get("pod", PodRuntimeConfig()) for lang, spec in LANGUAGE_SPECS.items()
}
