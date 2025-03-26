<p align="center">
 <img src="./files_for_readme/logo.png" alt="Integr8sCode Logo" width="100" height="100">
 <h1 align="center"><b>Integr8sCode</b></h1>
</p>

<p align="center">
  <a href="https://github.com/HardMax71/integr8scode/actions/workflows/backend-checks.yml?query=workflow%3A%22Mypy+Type+Checking%22">
    <img src="https://img.shields.io/github/actions/workflow/status/HardMax71/integr8scode/backend-checks.yml?branch=main&label=mypy&logo=python&logoColor=white" alt="Mypy Status" />
  </a>
  <a href="https://github.com/HardMax71/integr8scode/actions/workflows/backend-checks.yml?query=workflow%3A%22Ruff+Linting%22">
    <img src="https://img.shields.io/github/actions/workflow/status/HardMax71/integr8scode/backend-checks.yml?branch=main&label=ruff&logo=python&logoColor=white" alt="Ruff Status" />
  </a>
  <a href="https://github.com/HardMax71/integr8scode/actions/workflows/backend-checks.yml?query=workflow%3A%22Security+Scanning%22">
    <img src="https://img.shields.io/github/actions/workflow/status/HardMax71/integr8scode/backend-checks.yml?branch=main&label=security&logo=shieldsdotio&logoColor=white" alt="Security Scan Status" />
  </a>
  <a href="https://github.com/HardMax71/integr8scode/actions/workflows/backend-checks.yml?query=workflow%3A%22Docker+Build+%26+Scan%22">
    <img src="https://img.shields.io/github/actions/workflow/status/HardMax71/integr8scode/backend-checks.yml?branch=main&label=docker&logo=docker&logoColor=white" alt="Docker Scan Status" />
  </a>
</p>

---

Welcome to **Integr8sCode**! This is a platform where you can run Python scripts online with ease. Just paste your
script, and the platform run it in an isolated environment within its own Kubernetes pod, complete with resource limits
to keep
things safe and efficient. You'll get the results back in no time.


<details>
<summary><b>Full demo</b></summary>

https://github.com/user-attachments/assets/eb42c578-f540-43cc-aed4-39ef2777eb91

</details>

<details>
<summary>How to deploy</summary>

1. Clone this repository
2. Check if docker is enabled, kubernetes is running and kubectl is installed
3. `docker-compose up --build`

- Frontend: `https://127.0.0.1:5001/`
- Backend: `https://127.0.0.1:443/`
  - To check if it works, you can use `curl -k https://127.0.0.1/api/v1/k8s-limits`, should return JSON with current limits
- Grafana: `http://127.0.0.1:3000` (login - `admin`, pw - `admin123`)
- Prometheus: `http://127.0.0.1:9090/targets` (`integr8scode` must be `1/1 up`)

You may also find out that k8s doesn't capture metrics (`CPU` and `Memory` params are `null`), it may well be that metrics server
for k8s is turned off/not enabled. To enable, execute:
```bash
kubectl create -f https://raw.githubusercontent.com/pythianarora/total-practice/master/sample-kubernetes-code/metrics-server.yaml
```

and test output by writing `kubectl top node` in console, should output sth like:
``` 
PS C:\Users\User\Desktop\Integr8sCode> kubectl top node                                                                                                                 
NAME             CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%   
docker-desktop   267m         3%     4732Mi          29%
```

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

The platform is built on three main pillars:

- **Frontend**: A sleek Svelte app that users interact with.
- **Backend**: Powered by FastAPI, Python, and MongoDB to handle all the heavy lifting.
- **Kubernetes Cluster**: Each script runs in its own pod, ensuring isolation and resource control.

<details>
<summary>Components diagram</summary>

<img src="./files_for_readme/components-diagram.png">

</details>

<details>
<summary>Backend Details</summary>

### Script Execution Workflow

Here's how your script gets executed:

1. **Receive Script**: You send your code via the `/execute` endpoint.
2. **Spin Up Pod**: K8s creates a new pod for your script.
3. **Run Script**: Your code is executed in the pod.
4. **Capture Output**: Any output or errors are recorded.
5. **Store Results**: Everything gets saved in MongoDB.
6. **Update Status**: Execution status is updated for you.

### Database Design

MongoDB setup includes an `executions` collection:

- **Fields**:
    - `execution_id`: Unique ID for each execution.
    - `script`: The code provided.
    - `output`: What the script printed out.
    - `errors`: Any errors that occurred.
    - `status`: Whether your script is in the process (`queued`, `running`, `completed`, `failed`).
    - `created_at` and `updated_at`: Timestamps for tracking.

</details>

<details>
<summary>Frontend Details</summary>

### User Interface Components

Svelte app includes:

- **Code Editor**: A place to write or paste Python code.
- **Run Button**: Kick off the execution.
- **Output Area**: See the results or errors from the script.
- **Status Display**: Know if your script is queued, running, or done.

### State Management

- **Stores**: Svelte's built-in stores are used to keep track of your script and its execution status.
- **API Calls**: Functions that talk to backend endpoints and handle responses smoothly.

</details>

## Kubernetes Integration

### Pod Setup

- **Docker Image**:Lightweight Python image with just what we need is used.
- **Isolation**: Every script gets its own pod for security and reliability.
- **Cleanup**: Once your script is done, the pod goes away to keep things tidy.

### Resource Management

> [!TIP]
> By limiting resources, we ensure fair usage and prevent any single script from hogging the system.

- **CPU & Memory Limits**: Each pod has caps to prevent overuse (128 Mi for RAM and 100m for CPU).
- **Timeouts**: Scripts can't run forever—they'll stop after a set time (default: 5s).
- **Disk Space**: Limited to prevent excessive storage use.

> You can find actual limits in dropdown above execution output. 

### Security Considerations

> [!CAUTION]
> Running user-provided code is risky. We take security seriously to protect both our system and other users.

- **Network Restrictions**: Pods can't make external network calls.
- **No Privileged Access**: Pods run without elevated permissions.

## User Authentication

- **Accounts**: Optional—users can sign up to save scripts.
- **Security**: We use JWT tokens to secure API endpoints.

## Logging and Monitoring

- **Logs**: Centralized logging helps us track what's happening across pods.
- **Monitoring Tools**: Using Prometheus and Grafana to keep an eye on system health.
- **Alerts**: Set up notifications for when things go wrong.

To access:

- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (login with admin/admin123)

## Testing Strategy

<details>
<summary>Unit Tests</summary>

**Repository Tests**: Testing individual database operations

- Located in `tests/unit/test_repositories/`
- Testing CRUD operations for each model
- Using real MongoDB test instance
- Ensuring data integrity and constraints
- Running with pytest-asyncio for async operations

**Service Tests**: Testing business logic and service layer

- Located in `tests/unit/test_services/`
- Testing service methods independently
- Using actual repositories with test database
- Ensuring proper error handling
- Verifying state changes and data transformations

</details>

<details>
<summary>Integration Tests</summary>

**API Endpoint Tests**: Testing complete HTTP workflows

- Located in `tests/integration/test_api_endpoints.py`
- Testing all REST endpoints
- Using FastAPI TestClient
- Verifying response codes and payloads
- Testing authentication and authorization
- Ensuring proper error responses

**Kubernetes Integration Tests**: Testing pod execution

- Located in `tests/integration/test_k8s_integration.py`
- Testing script execution in pods
- Verifying resource limits and constraints
- Testing cleanup and error scenarios
- Using test Kubernetes cluster

</details>

<details>
<summary>Load Testing</summary>

**Performance Scenarios**: Using Locust for load testing

- Located in `tests/load/`
- Different load profiles:
    - Smoke Test: 1 user, basic functionality
    - Light Load: 10 users, 5 minutes
    - Medium Load: 50 users, 10 minutes
    - Heavy Load: 100 users, 15 minutes
    - Stress Test: 200 users, 30 minutes
- Measuring:
    - Response times
    - Error rates
    - System resource usage
    - Database performance
    - Kubernetes scaling

Main results:

<img src="./files_for_readme/load_testing_results.png">

</details>

<details>
<summary>Test Configuration</summary>

**Environment Setup**:

- `.env.test` for test environment variables
- `pytest.ini` for pytest configuration
- `conftest.py` for shared fixtures
- Docker compose for test dependencies

**Test Database**:

- Separate MongoDB instance for testing
- Fresh database for each test run
- Automated cleanup after tests

**Test Coverage**:

- `pytest-cov` for coverage reporting
- 92% coverage of core functionality
- Coverage reports in HTML and XML

</details>

