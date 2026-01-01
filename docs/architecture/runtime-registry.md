# Runtime Registry

The runtime registry defines how each programming language is executed inside Kubernetes pods. It maps language/version
pairs to Docker images, file extensions, and interpreter commands. Adding a new language or version is a matter of
extending the specification dictionary.

## Supported Languages

| Language | Versions                        | Image Template            | File Extension |
|----------|---------------------------------|---------------------------|----------------|
| Python   | 3.7, 3.8, 3.9, 3.10, 3.11, 3.12 | `python:{version}-slim`   | `.py`          |
| Node.js  | 18, 20, 22                      | `node:{version}-alpine`   | `.js`          |
| Ruby     | 3.1, 3.2, 3.3                   | `ruby:{version}-alpine`   | `.rb`          |
| Go       | 1.20, 1.21, 1.22                | `golang:{version}-alpine` | `.go`          |
| Bash     | 5.1, 5.2, 5.3                   | `bash:{version}`          | `.sh`          |

## Language Specification

Each language is defined by a `LanguageSpec` dictionary containing the available versions, Docker image template, file
extension, and interpreter command:

```python
--8<-- "backend/app/runtime_registry.py:12:17"
```

The full specification for all languages:

```python
--8<-- "backend/app/runtime_registry.py:19:50"
```

## Runtime Configuration

The registry generates a `RuntimeConfig` for each language/version combination. This contains everything needed to run a
script in a pod:

```python
--8<-- "backend/app/runtime_registry.py:6:10"
```

- **image**: The full Docker image reference (e.g., `python:3.11-slim`)
- **file_name**: The script filename mounted at `/scripts/` (e.g., `main.py`)
- **command**: The command to execute (e.g., `["python", "/scripts/main.py"]`)

## Adding a New Language

To add support for a new programming language:

1. Add an entry to `LANGUAGE_SPECS` with versions, image template, file extension, and interpreter
2. Add an example script to `EXAMPLE_SCRIPTS` demonstrating version-specific features
3. The `_make_runtime_configs()` function automatically generates runtime configs

For example, to add Rust support:

```python
"rust": {
    "versions": ["1.75", "1.76", "1.77"],
    "image_tpl": "rust:{version}-slim",
    "file_ext": "rs",
    "interpreter": ["rustc", "-o", "/tmp/main", "{file}", "&&", "/tmp/main"],
}
```

The image template uses `{version}` as a placeholder, which gets replaced with each version number when generating the
registry.

## Example Scripts

Each language includes an example script that demonstrates both universal features and version-specific syntax. These
scripts are shown in the frontend editor as templates:

```python
--8<-- "backend/app/runtime_registry.py:52:78"
```

The example scripts intentionally use features that may not work on older versions, helping users understand version
compatibility. For instance, Python's match statement (3.10+), Node's `Promise.withResolvers()` (22+), and Go's
`clear()` function (1.21+).

## API Endpoint

The `/api/v1/languages` endpoint returns the available runtimes:

```json
{
  "python": {"versions": ["3.7", "3.8", "3.9", "3.10", "3.11", "3.12"], "file_ext": "py"},
  "node": {"versions": ["18", "20", "22"], "file_ext": "js"},
  "ruby": {"versions": ["3.1", "3.2", "3.3"], "file_ext": "rb"},
  "go": {"versions": ["1.20", "1.21", "1.22"], "file_ext": "go"},
  "bash": {"versions": ["5.1", "5.2", "5.3"], "file_ext": "sh"}
}
```

## Key Files

| File                                                                                                                 | Purpose                                               |
|----------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------|
| [`runtime_registry.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/runtime_registry.py)         | Language specifications and runtime config generation |
| [`api/routes/languages.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/api/routes/languages.py) | API endpoint for available languages                  |
