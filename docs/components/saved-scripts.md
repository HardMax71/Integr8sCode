# Saved scripts

Users can save scripts to their account and load them back into the editor. Each script stores the code, its language and version, a name and an optional description, and belongs to the user who created it. Every repository query filters by `user_id`, so a user only ever sees their own scripts. Someone else's script id answers 404.

```python
--8<-- "backend/app/schemas_pydantic/saved_script.py:SavedScriptResponse"
```

## Runtime check

Create and update refuse a language version the runtime registry doesn't offer, with a 422 `RuntimeNotSupportedError`. An update that changes only the language or only the version is checked against the stored other half. Reads aren't checked, so a script saved on a version that has since been dropped still loads. Running it is what fails.

```python
--8<-- "backend/app/services/saved_script_service.py:create_saved_script"
```

## API

<swagger-ui src="../reference/openapi.json" filter="scripts" docExpansion="none" defaultModelsExpandDepth="-1" supportedSubmitMethods="[]"/>

## Storage

Scripts live in the `saved_scripts` collection, with a unique index on `script_id` and an index on `user_id`.

## Frontend

The editor lists saved scripts in its options panel. Loading one sets the code, the language and the version. Save updates the loaded script, or creates a new one if nothing is loaded, the name was changed, or the update answers 404.

## Key files

| File | Purpose |
|------|---------|
| [`saved_script_service.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/services/saved_script_service.py) | Business logic and runtime check |
| [`saved_scripts.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/api/routes/saved_scripts.py) | API routes |
| [`saved_script.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/schemas_pydantic/saved_script.py) | Request and response models |
| [`saved_script_repository.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/db/repositories/saved_script_repository.py) | MongoDB access |
