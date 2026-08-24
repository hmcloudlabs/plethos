# vkube (bachelor thesis 2026)

uv workspace with two apps (`portal`, `controller`) and a shared library.

```
vkube-manager/
├── components/
│   ├── portal/        # FastAPI + HTMX app
│   ├── controller/    # KOPF k8s controller
│   └── shared/        # shared package
├── charts/vkube/      # Helm chart to deploy vkube, see charts/vkube/README.md
└── k8s/               # standalone k8s reference material (e.g. Velero backup setup), see k8s/README.md
```

## Install

```bash
uv sync --all-packages
```

### To install more deps in the future
```bash
uv add --package portal <pkg>
uv add --package controller <pkg>
uv add --package shared <pkg>
```

## Run

### Portal:
Please refer to the [components/portal/README.md](components/portal/README.md) for setup (auth, admin settings, etc.).
```bash
# portal  -> http://localhost:8000
uv run uvicorn main:app --reload --app-dir components/portal/src
```

### Controller:
Please refer to the [components/controller/README.md](components/controller/README.md) on how to prepare your K8s cluster.
```bash
uv run kopf run components/controller/src/main.py --namespace vkube-system --verbose # namespace name might be different
```

## Deploy

To deploy vkube to a Kubernetes cluster, see [charts/vkube/README.md](charts/vkube/README.md).
For optional Velero backups, see [k8s/backup/README.md](k8s/backup/README.md).

## Lint

```bash
uv run ruff check .          # lint
uv run ruff check --fix .    # lint + autofix
uv run ruff format .         # format
```

## Test

Tests live per component in `<component>/tests/`. Run them from inside a component
(each sets its own `pythonpath`):

```bash
cd components/portal      && uv run pytest
cd components/controller  && uv run pytest
cd components/shared      && uv run pytest
```


## TODO

### Portal:
- [x] ConfigMap for storing admin emails, per user vCluster quota
- [x] per specific user vCluster quota override
- [x] per vCluster ingress
- [x] PVC export
- [x] max team/member size admin config
- [x] per specific user
- [x] caching
- [x] vCluster expiration
- [x] email invite for members
- [x] documentation
- [x] portal testing
- [x] email notification for expiring clusters
- [x] logging
- [x] k8s setup files or helm chart setup
- [x] expiration tests
- [x] backup strategy
- [x] style emails
- [ ] fix potential isloation escape because of per vCluster ClusterRole
- [ ] initial GitLab CI pipeline
