# vkube (bachelor thesis 2026)

uv workspace with two apps (`portal`, `controller`) and a shared library.

```
vkube-manager/
├── components/
│   ├── portal/        # FastAPI + HTMX app
│   ├── controller/    # KOPF k8s controller
│   └── shared/        # shared package
└── k8s/               # cluster manifests
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
- [ ] portal testing
- [ ] backup strategy
- [ ] fix potential isloation escape because of per vCluster ClusterRole
- [x] documentation
- [ ] initial GitLab CI pipeline
- [ ] k8s setup files
- [ ] email notification for expiring clusters