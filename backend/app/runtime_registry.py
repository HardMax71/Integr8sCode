from typing import NamedTuple, TypedDict


class RuntimeConfig(NamedTuple):
    image: str  # Full Docker image reference
    file_name: str  # Name that will be mounted under /scripts/
    command: list[str]  # Entrypoint executed inside the container


class LanguageSpec(TypedDict):
    versions: list[str]
    image_tpl: str
    file_ext: str
    interpreter: list[str]


LANGUAGE_SPECS: dict[str, LanguageSpec] = {
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
        "interpreter": ["go", "run"],
    },
}

EXAMPLE_SCRIPTS: dict[str, str] = {
    "python": """
# This f-string formatting works on all supported Python versions (3.7+)
py_version = "3.x"
print(f"Hello from a Python {py_version} script!")

# The following block uses Structural Pattern Matching,
# which was introduced in Python 3.10.
# THIS WILL CAUSE A SYNTAX ERROR ON VERSIONS < 3.10.

lang_code = 1
match lang_code:
    case 1:
        print("Structural Pattern Matching is available on this version (Python 3.10+).")
    case _:
        print("Default case.")

# Union types using | operator (Python 3.10+)
def process_data(value: int | str | None) -> str:
    if value is None:
        return "No value"
    return f"Got: {value}"

print(process_data(42))
print(process_data("hello"))
print(process_data(None))
""",
    "node": """
// This works on all supported Node versions (18+)
console.log(`Hello from Node.js ${process.version}!`);

// The Promise.withResolvers() static method was introduced in Node.js 22.
// This will throw a TypeError on versions < 22.
if (typeof Promise.withResolvers === 'function') {
  const { promise, resolve } = Promise.withResolvers();
  console.log("Promise.withResolvers() is supported (Node.js 22+).");
  resolve('Success');
  promise.then(msg => console.log(`Resolved with: ${msg}`));
} else {
  console.log("Promise.withResolvers() is not supported on this version.");
}
""",
    "ruby": """
# This works on all supported Ruby versions (3.1+)
puts "Hello from Ruby #{RUBY_VERSION}!"

# The Data class for immutable value objects was introduced in Ruby 3.2.
# This will cause an error on Ruby 3.1.
begin
  # This line will fail on Ruby < 3.2
  Point = Data.define(:x, :y)
  p = Point.new(1, 2)
  puts "Data objects are supported (Ruby 3.2+). Created point: #{p.inspect}"
rescue NameError
  puts "Data objects are not supported on this version."
end
""",
    "bash": """
# This works on any modern Bash version
echo "Hello from Bash version $BASH_VERSION"

# BASH_VERSINFO is an array holding version details.
# We can check the major and minor version numbers.
echo "Bash major version: ${BASH_VERSINFO[0]}"
echo "Bash minor version: ${BASH_VERSINFO[1]}"

# The ${var@U} expansion for uppercasing was added in Bash 5.2
if [[ "${BASH_VERSINFO[0]}" -ge 5 && "${BASH_VERSINFO[1]}" -ge 2 ]]; then
    my_var="hello"
    echo "Testing variable expansion (Bash 5.2+ feature)..."
    echo "Original: $my_var, Uppercased: ${my_var@U}"
else
    echo "The '${var@U}' expansion is not available in this Bash version."
fi
""",
    "go": """
package main

import (
    "fmt"
    "runtime"
)

// This function uses generics, available since Go 1.18,
// so it will work on all supported versions (1.20+).
func Print[T any](s T) {
    fmt.Println(s)
}

func main() {
    Print(fmt.Sprintf("Hello from Go version %s!", runtime.Version()))

    // The built-in 'clear' function for maps and slices
    // was introduced in Go 1.21.
    // THIS WILL FAIL TO COMPILE on Go 1.20.
    myMap := make(map[string]int)
    myMap["a"] = 1
    Print(fmt.Sprintf("Map before clear: %v", myMap))
    clear(myMap) // This line will fail on Go < 1.21
    Print(fmt.Sprintf("Map after 'clear' (Go 1.21+ feature): length is %d", len(myMap)))
}
""",
}


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

SUPPORTED_RUNTIMES: dict[str, list[str]] = {lang: list(versions.keys()) for lang, versions in RUNTIME_REGISTRY.items()}
