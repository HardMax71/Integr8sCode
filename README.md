<p align="center">
 <img src="./files_for_readme/logo.png" alt="Integr8sCode Logo" width="250" height="250">
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
  <a href="https://github.com/HardMax71/Integr8sCode/actions/workflows/docker.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/HardMax71/Integr8sCode/docker.yml?branch=main&label=docker&logo=docker&logoColor=white" alt="Docker Scan Status" />
  </a>
  <a href="https://github.com/HardMax71/Integr8sCode/actions/workflows/tests.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/HardMax71/Integr8sCode/tests.yml?branch=main&label=tests&logo=pytest" alt="Tests Status" />
  </a>
  <a href="https://codecov.io/gh/HardMax71/Integr8sCode">
    <img src="https://img.shields.io/codecov/c/github/HardMax71/Integr8sCode?flag=backend&label=backend%20coverage&logo=codecov" alt="Backend Coverage" />
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

1. Clone this repository
2. Check if docker is enabled, kubernetes is running and kubectl is installed
3. `docker-compose up --build`

- Frontend: `https://127.0.0.1:5001/`
- Backend: `https://127.0.0.1:443/`
  - To check if it works, you can use `curl -k https://127.0.0.1/api/v1/k8s-limits`, should return JSON with current limits
- Grafana: `http://127.0.0.1:3000` (login - `admin`, pw - `admin123`)
  

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

> [!WARNING]
> Detailed, up-to-date architecture diagrams are in [this file](files_for_readme/ARCHITECTURE_IN_DETAILS.md).

<img src="./files_for_readme/system_diagram.svg" alt="system diagram">

The platform is built on three main pillars:

- **Frontend**: A sleek Svelte app that users interact with.
- **Backend**: Powered by FastAPI, Python, and MongoDB to handle all the heavy lifting.
- **Kubernetes Cluster**: Each script runs in its own pod, ensuring isolation and resource control.

## Kubernetes Integration

### Pod Setup

- **Docker Image**:Lightweight Python image with just what we need is used.
- **Isolation**: Every script gets its own pod for security and reliability.
- **Cleanup**: Once your script is done, the pod goes away to keep things tidy.

### Resource Management

> [!TIP]
> By limiting resources, we ensure fair usage and prevent any single script from hogging the system.

- **CPU & Memory Limits**: Each pod has caps to prevent overuse (128 Mi for RAM and 1000m for CPU).
- **Timeouts**: Scripts can't run forever—they'll stop after a set time (default: 5s).
- **Disk Space**: Limited to prevent excessive storage use.

> You can find actual limits in dropdown above execution output. 

### Security Considerations

> [!CAUTION]
> Running user-provided code is risky. We take security seriously to protect both our system and other users.

- **Network Restrictions**: Pods can't make external network calls.
- **No Privileged Access**: Pods run without elevated permissions.

  

