# Updating Docker Image and Backend in DigitalOcean Kubernetes Cluster

When you modify your backend implementation (e.g., code changes, bug fixes, or extensions), you need to update the Docker image and redeploy the updated backend in your DigitalOcean Kubernetes cluster. This guide provides the step-by-step process for updating your image and backend deployment.

## Step 1: Make Changes to Your Backend

Make any necessary changes to your FastAPI code or other backend components.

## Step 2: Rebuild the Docker Image

After making changes, rebuild the Docker image for your backend with the updated code.

```bash
docker buildx build --platform linux/amd64 -t <your-dockerhub-username>/backend .
```


## Step 3: Push the Updated Image to DockerHub

Once the image is rebuilt, push it to DockerHub or another container registry.

```bash
docker push <your-dockerhub-username>/backend
```


## Step 4: Update the Kubernetes Deployment

To apply the updated image in your DigitalOcean Kubernetes cluster, restart the backend deployment. Kubernetes will pull the latest version of the image and update the running pods.

```bash
kubectl rollout restart deployment backend
```


This command will recreate the pods using the updated image from your container registry.

## Step 5: Verify the Update

Check the status of the pods to ensure the new pods are running successfully with the updated image.

```bash
kubectl get pods
```

Ensure that the new pods are in the `Running` state. You can also check the logs of the updated pods to verify the changes are applied correctly:

```bash 
kubectl logs <backend-pod-name>
```


## Step 6: Access the Updated Backend

Once the deployment is updated, you can access the backend as usual through the service’s **EXTERNAL-IP**:

```bash
http://<EXTERNAL-IP>:8000
```


## Step 7: Rollback (If Needed)

If the update caused issues, you can rollback to the previous version using:

```bash
kubectl rollout undo deployment backend
```

This command will revert the deployment to the previous version, allowing you to investigate and fix any issues with the updated version.