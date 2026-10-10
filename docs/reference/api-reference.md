# API reference

Every route lives under `/api/v1`. Login sets a JWT in the httpOnly `access_token` cookie and a readable `csrf_token` cookie. Any request other than GET, HEAD or OPTIONS from a logged-in user must echo that token in an `X-CSRF-Token` header; login and register are exempt.

The page below renders `docs/reference/openapi.json`, which `./deploy.sh openapi` regenerates from the FastAPI app. The running backend serves its own `/docs` only when `DEVELOPMENT_MODE` is on.

<swagger-ui src="openapi.json" deepLinking="true" docExpansion="list" supportedSubmitMethods="[]"/>
