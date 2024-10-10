# TODO

```bash
/backend
│
├── app
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   │
│   ├── api
│   │   ├── __init__.py
│   │   ├── routes
│   │   │   ├── __init__.py
│   │   │   ├── execution.py
│   │   │   └── health.py
│   │   │
│   │   └── dependencies.py
│   │
│   ├── core
│   │   ├── __init__.py
│   │   ├── security.py
│   │   └── exceptions.py
│   │
│   ├── db
│   │   ├── __init__.py
│   │   ├── mongodb.py
│   │   └── repositories
│   │       ├── __init__.py
│   │       └── execution_repository.py
│   │
│   ├── models
│   │   ├── __init__.py
│   │   └── execution.py
│   │
│   ├── schemas
│   │   ├── __init__.py
│   │   └── execution.py
│   │
│   └── services
│       ├── __init__.py
│       ├── execution_service.py
│       └── kubernetes_service.py
│
├── tests
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api
│   │   ├── __init__.py
│   │   └── test_execution.py
│   │
│   └── test_services
│       ├── __init__.py
│       └── test_execution_service.py
│
├── alembic
│   ├── versions
│   │   └── (migration files)
│   ├── env.py
│   └── script.py.mako
│
├── requirements.txt
├── Dockerfile
├── .env
└── README.md
```