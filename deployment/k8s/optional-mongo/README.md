# Optional: MongoDB manifests

These manifests are **opt-in**. The default DocsGPT install uses Postgres
for user data (see `deployment/k8s/deployments/postgres-deploy.yaml`).

Apply the manifests in this directory only if you run DocsGPT with the
MongoDB-backed vector store (`VECTOR_STORE=mongodb`) and need an
in-cluster MongoDB, or if you are intentionally running on the legacy
MongoDB user-data store during the Postgres migration window.

Mirrors `deployment/optional/` for compose — not applied by the default
`kubectl apply -k deployment/k8s/`.

## Usage

```bash
kubectl apply -f deployment/k8s/optional-mongo/deployments/mongo-deploy.yaml
kubectl apply -f deployment/k8s/optional-mongo/services/mongo-service.yaml
```

Then extend `docsgpt-secrets.yaml` with a base64-encoded `MONGO_URI`
pointing at `mongodb://mongodb-service:27017/docsgpt?retryWrites=true&w=majority`
(or your Atlas/external URI) before re-applying the secret.
