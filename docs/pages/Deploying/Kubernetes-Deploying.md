# Self-hosting DocsGPT on Kubernetes

This guide will walk you through deploying DocsGPT on Kubernetes.

## Prerequisites

Ensure you have the following installed before proceeding:

- [kubectl](https://kubernetes.io/docs/tasks/tools/install-kubectl/)
- Access to a Kubernetes cluster

## Folder Structure

The `k8s` folder contains the necessary deployment and service configuration files:

- `deployments/`
- `services/`
- `docsgpt-secrets.yaml`

## Deployment Instructions

1. **Clone the Repository**

   ```sh
   git clone https://github.com/arc53/DocsGPT.git
   cd docsgpt/k8s
   ```

2. **Configure Secrets (optional)**

   Ensure that you have all the necessary secrets in `docsgpt-secrets.yaml`. Update it with your secrets before applying if you want. By default we will use qdrant as a vectorstore and public docsgpt llm as llm for inference.

3. **Apply Kubernetes Deployments**

   Deploy your DocsGPT resources using the following commands:

   ```sh
   kubectl apply -f deployments/
   ```

4. **Apply Kubernetes Services**

   Set up your services using the following commands:

   ```sh
   kubectl apply -f services/
   ```

5. **Apply Secrets**

   Apply the secret configurations:

   ```sh
   kubectl apply -f docsgpt-secrets.yaml
   ```

6. **Substitute API URL**

   After deploying the services, you need to update the environment variable `VITE_API_HOST` in your deployment file `deployments/docsgpt-deploy.yaml` with the actual endpoint URL created by your `docsgpt-api-service`.

   You can get the value of the `docsgpt-api-service` by running:

   ```sh
   kubectl get services/docsgpt-api-service | awk 'NR>1 {print $4}'
   ```

   Update the `<your-api-endpoint>` field with your API endpoint URL by running this command and pasting endpoint from previous command:

   ```sh
   read -p "Enter the API endpoint: " api_endpoint && sed -i "s|<your-api-endpoint>|$api_endpoint|g" deployments/docsgpt-deploy.yaml
    ```

7. **Rerun Deployment**

   After making the changes, reapply the deployment configuration to update the environment variables:

   ```sh
   kubectl apply -f deployments/
   ```

## Verifying the Deployment

To verify if everything is set up correctly, you can run the following:

```sh
kubectl get pods
kubectl get services
```

Ensure that the pods are running and the services are available.

## Accessing DocsGPT

To access DocsGPT, you need to find the external IP address of the frontend service. You can do this by running:

```sh
kubectl get services/docsgpt-frontend-service | awk 'NR>1 {print "http://" $4}'
```

## Troubleshooting

If you encounter any issues, you can check the logs of the pods for more details:

```sh
kubectl logs <pod-name>
```

Replace `<pod-name>` with the actual name of your DocsGPT pod.