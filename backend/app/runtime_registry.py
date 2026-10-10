from typing import NamedTuple, TypedDict

from app.domain.execution import LanguageInfoDomain


# --8<-- [start:RuntimeConfig]
class RuntimeConfig(NamedTuple):
    image: str  # Full Docker image reference
    file_name: str  # Name that will be mounted under /scripts/
    command: list[str]  # Entrypoint executed inside the container


# --8<-- [end:RuntimeConfig]


# --8<-- [start:LanguageSpec]
class LanguageSpec(TypedDict):
    versions: list[str]
    image_tpl: str
    file_ext: str
    interpreter: list[str]


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
        "interpreter": ["go", "run"],
    },
}
# --8<-- [end:LANGUAGE_SPECS]

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


def _make_runtime_configs() -> dict[str, dict[str, RuntimeConfig]]:
    registry: dict[str, dict[str, RuntimeConfig]] = {}

    for lang, spec in LANGUAGE_SPECS.items():
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
                command=(interpreter_cmd if "{file}" in " ".join(interpreter_cmd) else interpreter_cmd + [full_path]),
            )
            for v in versions
        }

    return registry


RUNTIME_REGISTRY: dict[str, dict[str, RuntimeConfig]] = _make_runtime_configs()

SUPPORTED_RUNTIMES: dict[str, LanguageInfoDomain] = {
    lang: LanguageInfoDomain(versions=spec["versions"], file_ext=spec["file_ext"])
    for lang, spec in LANGUAGE_SPECS.items()
}
