# Backend and MongoDB Deployment Guide on DigitalOcean Kubernetes

This guide provides step-by-step instructions on how to deploy a FastAPI backend and MongoDB database on a Kubernetes cluster in DigitalOcean. We will create a Docker image for the backend, push it to a registry, deploy it alongside MongoDB on Kubernetes, and expose the backend via a LoadBalancer.

## Prerequisites

- A DockerHub account or a similar container registry.
- `kubectl` installed and configured to manage your DigitalOcean Kubernetes cluster.
- `doctl` (DigitalOcean CLI) installed.
- Access to a DigitalOcean Kubernetes cluster.

## Step 1: Create a DigitalOcean Kubernetes Cluster

Run the following command to create a Kubernetes cluster with a single node in the `fra1` (Frankfurt) region:

```bash
doctl kubernetes cluster create example-cluster \
  --region fra1 \
  --node-pool "name=small-pool;size=s-1vcpu-2gb;count=1"
```

This will create the cluster and configure the `kubectl` context to use it.

## Step 2: Build and Push Docker Image for Backend

1. Ensure your backend code includes a `Dockerfile` with the following content:

```Dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt . RUN pip install --no-cache-dir -r requirements.txt

COPY ./app /app/app COPY .env /app/.env COPY kubeconfig.yaml /app/kubeconfig.yaml

CMD ["uvicorn", "app.main
", "--host", "0.0.0.0", "--port", "8000"]
```


2. Build the Docker image and push it to your DockerHub repository:

```bash
docker buildx build --platform linux/amd64 -t <your-dockerhub-username>/backend
. docker push <your-dockerhub-username>/backend
```


This ensures the image is built for the correct architecture (x86_64).

## Step 3: Create Kubernetes Manifests for MongoDB

1. Create a `mongo-deployment.yaml` file
2. Create a `mongo-service.yaml` file


Apply these files to Kubernetes:

```bash
kubectl apply -f mongo-deployment.yaml 
kubectl apply -f mongo-service.yaml
```

## Step 4: Create Kubernetes Manifests for Backend

1. Create a `backend-deployment.yaml` file
2. Create a `backend-service.yaml` file


Apply these files to Kubernetes:

```bash
kubectl apply -f backend-deployment.yaml 
kubectl apply -f backend-service.yaml
```


## Step 5: Verify the Deployment

Check the status of your pods and services:

```bash
kubectl get pods 
kubectl get svc
```

If the `EXTERNAL-IP` of the `backend-service` is `<pending>`, wait a few minutes for the LoadBalancer to provision. You can check again using `kubectl get svc`.

## Step 6: Debugging Issues

1. If the backend pod shows a `CrashLoopBackOff` error, use the following command to check logs:

```bash
kubectl logs <backend-pod-name>
```


2. If you see an `exec format error`, rebuild the Docker image ensuring the correct architecture using:

```bash
docker buildx build --platform linux/amd64 -t <your-dockerhub-username>/backend
. docker push <your-dockerhub-username>/backend
```

> Problem with local architecture vs. cluster architecture (local was ARM/MacM1, cluster was x86_64).


3. After rebuilding, restart the backend deployment:

```bash
kubectl rollout restart deployment backend
```

## Step 7: Access the Backend

Once the `EXTERNAL-IP` is available, you can access the FastAPI backend via the public IP on port 8000.

```bash
http://<EXTERNAL-IP>:8000
```