# Saved Scripts

Users can save scripts to their account for later reuse. Scripts are stored in MongoDB and associated with the user who created them. Each script includes the code, language, version, and optional description.

## Data Model

Each saved script contains:

```python
--8<-- "backend/app/schemas_pydantic/saved_script.py:SavedScriptResponse"
```

Scripts are scoped to individual users—a user can only access their own saved scripts.

## API Endpoints

<swagger-ui src="../reference/openapi.json" filter="scripts" docExpansion="none" defaultModelsExpandDepth="-1" supportedSubmitMethods="[]"/>

## Service Layer

The `SavedScriptService` handles business logic with comprehensive logging:

```python
--8<-- "backend/app/services/saved_script_service.py:create_saved_script"
```

All operations log the user ID, script ID, and relevant metadata for auditing.

## Storage

Scripts are stored in the `saved_scripts` MongoDB collection with individual indexes on `script_id` (unique) and `user_id` for efficient per-user queries.

The repository enforces user isolation—queries always filter by `user_id` to prevent cross-user access.

## Frontend Integration

The frontend displays saved scripts in a dropdown, allowing users to:

1. Select a saved script to load into the editor
2. Save the current editor content as a new script
3. Update an existing script with new content
4. Delete scripts they no longer need

When loading a script, the frontend sets both the code content and the language/version selectors to match the saved values.

## Key Files

| File | Purpose |
|------|---------|
| [`services/saved_script_service.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/services/saved_script_service.py) | Business logic |
| [`api/routes/saved_scripts.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/api/routes/saved_scripts.py) | API endpoints |
| [`schemas_pydantic/saved_script.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/schemas_pydantic/saved_script.py) | Request/response models |
| [`db/repositories/saved_script_repository.py`](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/db/repositories/saved_script_repository.py) | MongoDB operations |
