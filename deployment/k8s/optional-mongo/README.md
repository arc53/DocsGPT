# Optional: MongoDB manifests

These manifests are **opt-in**. The default DocsGPT install uses Postgres
for user data (see `deployment/k8s/deployments/postgres-deploy.yaml`).

They run a single in-cluster MongoDB, which you might want in two cases:

- As the source for a one-shot `scripts/db/backfill.py` migration of an
  old Mongo-based install into Postgres. The script needs
  `pip install 'pymongo>=4.6'`; see
  [PostgreSQL for User Data](https://docs.docsgpt.cloud/Deploying/Postgres-Migration).
- For the MongoDB vector store (`VECTOR_STORE=mongodb`). That store searches
  with Atlas `$vectorSearch`, which the plain `mongo` image deployed here
  does not provide, so it needs MongoDB Atlas or another deployment that
  supports `$vectorSearch`. For Atlas, skip these manifests and point
  `MONGO_URI` at it.

User data always lives in Postgres; MongoDB is never the user-data store.
These manifests are not applied by the default `kubectl apply -k deployment/k8s/`.

## Usage

```bash
kubectl apply -f deployment/k8s/optional-mongo/deployments/mongo-deploy.yaml
kubectl apply -f deployment/k8s/optional-mongo/services/mongo-service.yaml
```

For a backfill, run `scripts/db/backfill.py` from a checkout that can reach
the service (for example through `kubectl port-forward svc/mongodb-service 27017`),
with `MONGO_URI` pointing at it.

For the vector store, set these under `stringData` in `docsgpt-secrets.yaml`
and re-apply with `kubectl apply -k deployment/k8s/`. `MONGO_URI` must reach a
deployment that supports `$vectorSearch`: an Atlas URI, or the in-cluster
address below only if you have added search support to this MongoDB.

```yaml
  VECTOR_STORE: mongodb
  MONGO_URI: mongodb://mongodb-service:27017/docsgpt?retryWrites=true&w=majority
```

The API and worker read the secret only at start, so restart them afterwards:
`kubectl rollout restart deployment/docsgpt-api deployment/docsgpt-worker`.
