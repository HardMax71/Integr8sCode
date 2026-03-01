<p align="center">
 <img src="./docs/assets/images/logo.png" alt="Integr8sCode Logo" width="250" height="250">
 <h1 align="center"><b>Integr8sCode</b></h1>
</p>
<p align="center">
  <a href="https://github.com/HardMax71/Integr8sCode/actions/workflows/ruff.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/HardMax71/Integr8sCode/ruff.yml?branch=main&label=ruff&logo=python&logoColor=white" alt="Ruff Status" />
  </a>
  <a href="https://github.com/HardMax71/Integr8sCode/actions/workflows/mypy.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/HardMax71/Integr8sCode/mypy.yml?branch=main&label=mypy&logo=python&logoColor=white" alt="Mypy Status" />
  </a>
  <a href="https://github.com/HardMax71/Integr8sCode/actions/workflows/security.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/HardMax71/Integr8sCode/security.yml?branch=main&label=security&logo=shieldsdotio&logoColor=white" alt="Security Scan Status" />
  </a>
  <a href="https://github.com/HardMax71/Integr8sCode/actions/workflows/grimp.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/HardMax71/Integr8sCode/grimp.yml?branch=main&label=dead%20code&logo=python&logoColor=white" alt="Dead Code Check" />
  </a>
  <a href="https://github.com/HardMax71/Integr8sCode/actions/workflows/docker.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/HardMax71/Integr8sCode/docker.yml?branch=main&label=docker&logo=docker&logoColor=white" alt="Docker Scan Status" />
  </a>
  <a href="https://github.com/HardMax71/Integr8sCode/actions/workflows/stack-tests.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/HardMax71/Integr8sCode/stack-tests.yml?branch=main&label=backend&logo=python&logoColor=white" alt="Backend Tests" />
  </a>
  <a href="https://github.com/HardMax71/Integr8sCode/actions/workflows/stack-tests.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/HardMax71/Integr8sCode/stack-tests.yml?branch=main&label=frontend&logo=svelte&logoColor=white" alt="Frontend Tests" />
  </a>
  <a href="https://github.com/HardMax71/Integr8sCode/actions/workflows/frontend-ci.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/HardMax71/Integr8sCode/frontend-ci.yml?branch=main&label=lint&logo=eslint&logoColor=white" alt="Frontend Lint" />
  </a>
</p>
<p align="center">
  <a href="https://app.codecov.io/gh/HardMax71/Integr8sCode/components?component=backend">
    <img src="https://codecov.io/gh/HardMax71/Integr8sCode/branch/main/graph/badge.svg?component=backend" alt="Backend Coverage" />
  </a>
  <a href="https://app.codecov.io/gh/HardMax71/Integr8sCode/components?component=frontend">
    <img src="https://codecov.io/gh/HardMax71/Integr8sCode/branch/main/graph/badge.svg?component=frontend" alt="Frontend Coverage" />
  </a>
</p>
<p align="center">
  <a href="https://sonarcloud.io/dashboard?id=HardMax71_Integr8sCode">
    <img src="https://sonarcloud.io/api/project_badges/measure?project=HardMax71_Integr8sCode&metric=alert_status" alt="Quality Gate Status">
  </a>
  <a href="https://sonarcloud.io/dashboard?id=HardMax71_Integr8sCode">
    <img src="https://sonarcloud.io/api/project_badges/measure?project=HardMax71_Integr8sCode&metric=vulnerabilities" alt="Vulnerabilities">
  </a>
  <a href="https://sonarcloud.io/dashboard?id=HardMax71_Integr8sCode">
    <img src="https://sonarcloud.io/api/project_badges/measure?project=HardMax71_Integr8sCode&metric=bugs" alt="Bugs">
  </a>
</p>

Welcome to **Integr8sCode**! This is a platform where you can run Python scripts online with ease. Just paste your
script, and the platform run it in an isolated environment within its own Kubernetes pod, complete with resource limits
to keep
things safe and efficient. You'll get the results back in no time.


> [!NOTE]
> A deployed and working version of Integr8sCode is available at https://app.integr8scode.cc/ .

<details>
<summary>How to deploy</summary>

### Prerequisites

- Docker and Docker Compose
- Kubernetes cluster (k3s, Docker Desktop K8s, or minikube) with `kubectl` configured

### Quick start

```bash
git clone https://github.com/HardMax71/Integr8sCode.git
cd Integr8sCode
cp backend/secrets.example.toml backend/secrets.toml
./deploy.sh dev
```

The `secrets.toml` file holds credentials and is gitignored. The example template has working development defaults.

### Verify

```bash
curl -k https://localhost/api/v1/health/live
```

### Access

| Service            | URL                                                    |
|--------------------|--------------------------------------------------------|
| Frontend           | [https://localhost:5001](https://localhost:5001)       |
| Backend API        | [https://localhost:443](https://localhost:443)         |
| Kafdrop (Kafka UI) | [http://localhost:9000](http://localhost:9000)         |
| Grafana            | [http://localhost:3000](http://localhost:3000)         |
| Jaeger (Tracing)   | [http://localhost:16686](http://localhost:16686)       |

Default credentials: `user` / `user123` (regular), `admin` / `admin123` (admin).

Self-signed TLS certs are generated automatically — accept the browser warning.

### Run tests

```bash
./deploy.sh test
```

### Stop

```bash
./deploy.sh down
```

See the [full deployment guide](https://hardmax71.github.io/Integr8sCode/operations/deployment/) for Docker build strategy, troubleshooting, pre-built images, and more.

</details>

<details>
<summary>Sample test</summary>

You can check correctness of start by running a sample test script:
1. Open website at `https://127.0.0.1:5001/`, go to Editor
2. In code window, paste following code:
```python
from typing import TypeGuard

def is_string(value: object) -> TypeGuard[str]:
    return isinstance(value, str)

def example_function(data: object):
    match data:  # Match statement introduced in Python 3.10
        case int() if data > 10:
            print("An integer greater than 10")
        case str() if is_string(data):
            print(f"A string: {data}")
        case _:
            print("Something else")

example_function(15)
example_function("hello")
example_function([1, 2, 3])
```

First, select `>= Python 3.10` and run script, will output:
```
Status: completed
Execution ID: <some hex number>
Output:
  An integer greater than 10
  A string: hello
  Something else
```

Then, select `< Python 3.10` and do the same:
```
Status: completed
Execution ID: <some other hex number>
Output:
  File "/scripts/script.py", line 7
    match data:  # Match statement introduced in Python 3.10
          ^
SyntaxError: invalid syntax
```
This shows that pods with specified python versions are creating and working as expected. Btw, the latter throws error
cause `match-case` was introduced first in `Python 3.10`.

</details>


## Architecture Overview

> [!TIP]
> Full documentation is available at https://hardmax71.github.io/Integr8sCode/

<img src="./docs/assets/images/system_diagram.svg" alt="system diagram">

The platform is built on three main pillars:

- Frontend: Svelte app that users interact with.
- Backend: Powered by FastAPI, Python, and MongoDB to handle all the heavy lifting.
- Kubernetes Cluster: Each script runs in its own pod, ensuring isolation and resource control.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
