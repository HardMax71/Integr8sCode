# Runtime registry

`backend/app/runtime_registry.py` is the one place that says which languages and versions run, which image each one uses and how the pod starts the script. The API validates requests against it, the k8s worker builds pods from it, and the frontend reads it through `GET /api/v1/k8s-limits`.

## Languages and versions

```python
--8<-- "backend/app/runtime_registry.py:LANGUAGE_SPECS"
```

Each entry follows this shape:

```python
--8<-- "backend/app/runtime_registry.py:LanguageSpec"
```

The registry offers only versions that upstream still supports, and lists them newest first. Today that is Python 3.14, 3.13, 3.12 and 3.11, Node 26, 24 and 22, Ruby 4.0, 3.4 and 3.3, Go 1.27 and 1.26, and Bash 5.3. A unit test in `tests/unit/app/test_runtime_registry.py` pins that order.

`DEFAULT_LANG` is `"python"` and `DEFAULT_LANG_VERSION` is the first Python version, so 3.14 today. Every `lang` and `lang_version` default in the schemas, domain models and documents reads these two constants, except in the saved-script update models, where both default to None so an update leaves them alone.

## From spec to pod

`_make_runtime_configs()` turns each language and version into a `RuntimeConfig`:

```python
--8<-- "backend/app/runtime_registry.py:RuntimeConfig"
```

The file is always `main.{file_ext}`, and the command is the interpreter plus `/scripts/main.{file_ext}`, so Python 3.12 gets `python:3.12-slim` and `["python", "/scripts/main.py"]`. `ExecutionService` copies image, command and file name into the `ExecutionRequestedEvent`, and they travel through the saga to the k8s worker.

The worker puts the script into a ConfigMap, mounts it read-only at `/scripts`, and starts the container as `/bin/sh /entry/entrypoint.sh <command>`. The entrypoint runs the command as plain arguments, with no shell in between. On startup the worker also runs a pre-puller DaemonSet that pulls every image in the registry.

## Per-language pod settings

Most languages get the same pod. A language that needs more sets `pod` to a `PodRuntimeConfig`, which carries extra env vars, the size of the `/tmp` emptyDir (10Mi by default) and optional minimums for CPU limit, memory limit and timeout. `PodBuilder` applies one rule: the effective value is the larger of the configured limit and the language minimum. The configured limits come from the admin system settings, which fall back to `K8S_POD_CPU_LIMIT`, `K8S_POD_MEMORY_LIMIT` and `K8S_POD_EXECUTION_TIMEOUT`. Requests aren't touched.

Go is the only language with settings today. It builds and runs the way the Rust example below does, `go build` into `/tmp` and then `exec`, so the entrypoint measures the program and not the go tool; `go run` would report the go tool's own 25MB and leave the program out. A cold build compiles the runtime and standard library first, so Go pods get `HOME=/tmp` and `GOCACHE=/tmp/go-cache` (the root filesystem is read-only), 64Mi of `/tmp`, and at least 1000m CPU, 320Mi memory and 30 seconds.

`GET /api/v1/k8s-limits` reports the configured limits at the top level and the effective ones per language under `language_limits`. The editor shows the entry for the selected language. The result processor rates peak memory against the same effective limit, and `parse_quantity` and `at_least` in the registry are the one copy of that rule for all three.

## Dropped versions

A version that leaves the list stops working everywhere:

- `POST /api/v1/execute` rejects it with 422 while validating `ExecutionRequest`.
- `POST /api/v1/executions/{execution_id}/retry` raises `RuntimeNotSupportedError`, which is a 422.
- Creating or updating a saved script with it raises the same 422.

The editor doesn't send one. On load it swaps a stored version that's gone for the newest offered version of that language, the first one the API lists, and if the language itself is gone it takes the first language the API returns. Opening a saved script with a dropped version makes the language picker switch to the newest version and say so in a toast.

## Example scripts

`GET /api/v1/example-scripts` returns one starter script per language, and the editor's example button loads the one for the selected language. Every script runs on every offered version. A feature older than the oldest offered version is used directly. A newer one is checked first: Python looks for `itertools.batched`, Node for `RegExp.escape`, Ruby for `Array#fetch_values`, and Bash compares `BASH_VERSINFO`. Go can't check at runtime, so its script sticks to what Go 1.26 has.

??? example "EXAMPLE_SCRIPTS"

    ```python
    --8<-- "backend/app/runtime_registry.py:EXAMPLE_SCRIPTS"
    ```

## Adding a language

1. Add an entry to `LANGUAGE_SPECS` with versions newest first, and a `pod` config if the defaults aren't enough.
2. Add a script to `EXAMPLE_SCRIPTS` that runs on every listed version.
3. Add a loader for the language's CodeMirror mode in `frontend/src/lib/editor/languages.ts`. It's a dynamic `import()`, so the mode loads only when someone picks the language. Without one the editor shows plain text.

Request validation, `SUPPORTED_RUNTIMES`, the version picker, file upload by extension and the image pre-puller all derive from the registry.

A compiled language needs a build step before the run, and the command has no shell to chain them. Wrap both in `sh -c` and let the appended script path arrive as `$0`. For Rust, whose upstream supports only the latest stable release:

```python
"rust": {
    "versions": ["1.99"],
    "image_tpl": "rust:{version}-slim",
    "file_ext": "rs",
    # The registry appends /scripts/main.rs, which sh hands to the script as $0.
    "interpreter": ["sh", "-c", 'rustc -C strip=symbols -o /tmp/main "$0" && exec /tmp/main'],
},
```

There's no `{file}` placeholder: the path is always appended as the last argument. The binary goes to `/tmp` because the root filesystem is read-only, and `-C strip=symbols` keeps it small: a hello world comes out at about 340KB instead of 4.4MB. Under the default pod (10Mi of `/tmp`, 128Mi, 1000m) that build takes about 0.2 s and peaks near 60MiB, so small programs fit; give the language a `pod` entry if bigger ones run out of memory, disk or time. The `rust:1.99-slim` image is about 330MB compressed, so the pre-puller's first pull takes a while.
