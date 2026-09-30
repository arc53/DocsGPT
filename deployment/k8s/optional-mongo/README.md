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

Then set these under `stringData` in `docsgpt-secrets.yaml` (or point
`MONGO_URI` at your Atlas/external URI) and re-apply with
`kubectl apply -k deployment/k8s/`:

```yaml
  VECTOR_STORE: mongodb
  MONGO_URI: mongodb://mongodb-service:27017/docsgpt?retryWrites=true&w=majority
```

The API and worker read the secret only at start, so restart them afterwards:
`kubectl rollout restart deployment/docsgpt-api deployment/docsgpt-worker`.
