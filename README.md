# Integr8sCode

Welcome to **Integr8sCode**! This is a platform where you can run Python scripts online with ease. Just paste your script, and we'll run it in an isolated environment within its own Kubernetes pod, complete with resource limits to keep things safe and efficient. You'll get the results back in no time.

> [!NOTE]
> This document is just an outline of the project description. Project is under development, newer versions will be pushed soon. 

## Table of Contents

- [Introduction](#introduction)
- [Architecture Overview](#architecture-overview)
- [Backend Details](#backend-details)
  - [API Endpoints](#api-endpoints)
  - [Script Execution Workflow](#script-execution-workflow)
  - [Database Design](#database-design)
- [Frontend Details](#frontend-details)
  - [User Interface Components](#user-interface-components)
  - [State Management](#state-management)
- [Kubernetes Integration](#kubernetes-integration)
  - [Pod Setup](#pod-setup)
  - [Resource Management](#resource-management)
  - [Security Considerations](#security-considerations)
- [User Authentication](#user-authentication)
- [Logging and Monitoring](#logging-and-monitoring)
- [Testing Strategy](#testing-strategy)
- [Deployment Plan](#deployment-plan)
- [Future Plans](#future-plans)

## Introduction

Integr8sCode aims to make running Python scripts online a breeze. No need to set up environments or worry about dependencies—just code and run. It's perfect for testing snippets, sharing code, or learning Python.

## Architecture Overview

The platform is built on three main pillars:

- **Frontend**: A sleek Svelte app that users interact with.
- **Backend**: Powered by FastAPI, Python, and MongoDB to handle all the heavy lifting.
- **Kubernetes Cluster**: Each script runs in its own pod, ensuring isolation and resource control.

## Backend Details

### API Endpoints

I've designed some straightforward API endpoints:

- **POST /execute**
  - **Purpose**: Send us your Python script, and we'll get it running.
  - **What You Send**:
    ```json
    {
      "script": "print('Hello, Integr8sCode!')"
    }
    ```
  - **What You Get Back**:
    ```json
    {
      "execution_id": "abc123",
      "status": "queued"
    }
    ```

- **GET /result/{execution_id}**
  - **Purpose**: Check on your script's result.
  - **What You Get Back**:
    ```json
    {
      "execution_id": "abc123",
      "status": "completed",
      "output": "Hello, Integr8sCode!\n",
      "errors": null
    }
    ```

### Script Execution Workflow

Here's how we handle your scripts:

1. **Receive Script**: You send us your code via the `/execute` endpoint.
2. **Spin Up Pod**: We create a Kubernetes pod just for your script.
3. **Run Script**: Your code runs inside this isolated pod.
4. **Capture Output**: We grab any output or errors.
5. **Store Results**: Everything gets saved in MongoDB.
6. **Update Status**: We keep you informed about the execution status.

### Database Design

Our MongoDB setup includes an `executions` collection:

- **Fields**:
  - `execution_id`: Unique ID for each execution.
  - `script`: The code you provided.
  - `output`: What your script printed out.
  - `errors`: Any errors that occurred.
  - `status`: Where your script is in the process (`queued`, `running`, `completed`, `failed`).
  - `created_at` and `updated_at`: Timestamps for tracking.

## Frontend Details

### User Interface Components

Our Svelte app includes:

- **Code Editor**: A place to write or paste your Python code.
- **Run Button**: Kick off the execution.
- **Output Area**: See the results or errors from your script.
- **Status Display**: Know if your script is queued, running, or done.

### State Management

- **Stores**: We use Svelte's built-in stores to keep track of your script and its execution status.
- **API Calls**: Functions that talk to our backend endpoints and handle responses smoothly.

## Kubernetes Integration

### Pod Setup

- **Docker Image**: We use a lightweight Python image with just what we need.
- **Isolation**: Every script gets its own pod for security and reliability.
- **Cleanup**: Once your script is done, the pod goes away to keep things tidy.

### Resource Management

> [!TIP]
> By limiting resources, we ensure fair usage and prevent any single script from hogging the system.

- **CPU & Memory Limits**: Each pod has caps to prevent overuse.
- **Timeouts**: Scripts can't run forever—they'll stop after a set time.
- **Disk Space**: Limited to prevent excessive storage use.

### Security Considerations

> [!CAUTION]
> Running user-provided code is risky. We take security seriously to protect both our system and other users.

- **Network Restrictions**: Pods can't make external network calls.
- **No Privileged Access**: Pods run without elevated permissions.
- **Sandboxing**: We consider tools like gVisor for extra isolation layers.

## User Authentication

- **Accounts**: Optional—users can sign up to save scripts.
- **Security**: We use JWT tokens to secure API endpoints.
- **Permissions**: Potential to add roles (like admin, user) down the line.

## Logging and Monitoring

- **Logs**: Centralized logging helps us track what's happening across pods.
- **Monitoring Tools**: Using Prometheus and Grafana to keep an eye on system health.
- **Alerts**: Set up notifications for when things go wrong.

## Testing Strategy

- **Unit Tests**: For individual components and functions.
- **Integration Tests**: To ensure the frontend and backend work seamlessly together.
- **Load Testing**: Simulate multiple users to see how the system holds up.

## Deployment Plan

- **CI/CD**: Implement pipelines with tools like GitHub Actions.
- **Infrastructure as Code**: Manage resources with Terraform or Helm charts.
- **Configuration Management**: Use environment variables for settings.

## Future Plans

- **More Languages**: Expand to support languages beyond Python.
- **Enhanced Editor**: Add features like syntax highlighting and auto-completion.
- **Collaboration**: Allow users to share and collaborate on scripts.
- **Persistent Storage**: Provide options to read/write files within the execution environment.

