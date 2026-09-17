# Contributing to plethos

Thanks for your interest in contributing. Contributions of any
size are welcome (bug reports, docs fixes, small patches or larger features).

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). By participating, you're
expected to uphold it.

## Project layout

This is a `uv` workspace with two apps and a shared library:

```
.
├── adr/                # architecture decision records
├── charts/plethos/       # Helm chart to deploy plethos
├── components/
│   ├── controller/     # KOPF k8s controller
│   ├── portal/         # FastAPI + HTMX app
│   └── shared/         # shared package
└── k8s/                # standalone k8s reference material (e.g. Velero backup setup)
```

## Versioning and releases

Plethos has three independently versioned release artifacts: the portal image, the controller image and the `plethos` Helm chart. Each follows [Semantic Versioning](https://semver.org/) and has its own version number and changelog. 

The portal's and controller's version lives in their `pyproject.toml` and both have a `CHANGELOG.md` in their workspace directory. The chart's version lives in `charts/plethos/Chart.yaml`,
and its `CHANGELOG.md` is the repository's root, since the Helm chart bundles the portal and the controller together and is the main artifact people actually install.

## Set up for local development

Prerequisites: `uv`, `kubectl`, Docker and [kind](https://kind.sigs.k8s.io/) (the controller's
test suite specifically drives a `kind` cluster).

Install dependencies:

```bash
uv sync --all-packages
```

To run the portal and controller together locally:

1. Create a local cluster and the namespace both components use:
   ```bash
   kind create cluster
   kubectl create namespace plethos-system  # you can choose a different name
   ```
2. Apply the `VClusterClaim` CRD:
   ```bash
   kubectl apply -f charts/plethos/crds/vclusterclaim.yaml
   ```
3. Apply the `plethos-vcluster-installer` ClusterRole:
   ```bash
   kubectl apply -f charts/plethos/templates/controller/vcluster-installer-rbac.yaml
   ```
   The controller creates one `helm-installer` ServiceAccount per vCluster namespace and
   binds it to this ClusterRole. This ServiceAccount is used to install the `vCluster` chart 
   into the corresponding namespace.
4. Seed the portal's settings `ConfigMap` (admin emails, quotas):
   ```bash
   kubectl create configmap plethos-portal-settings -n plethos-system \
     --from-literal=adminEmails="testuser@example.com" \
     --from-literal=maxVclustersPerUser="5" \
     --from-literal=maxTeamSize="5"
   ```
5. Start Keycloak as a local IdP that the portal authenticates against (includes Mailpit):
   ```bash
   docker compose -f components/portal/dev-setup/docker-compose.yml up
   ```
   Keycloak runs at `http://localhost:9090` and Mailpit at `http://localhost:8025`. It comes preloaded with two dummy users
   (password matches the username):

   | Email | Type | Password |
   |---|---|---|
   | `testuser@example.com` | Admin | test |
   | `testuser2@example.com` | User | test |
6. In separate terminals, run the controller and the portal (both from the project root):
   ```bash
   uv run kopf run components/controller/src/main.py --namespace plethos-system --verbose
   uv run uvicorn main:app --reload --app-dir components/portal/src
   ```
7. Open `http://localhost:8000` and log in with one of the seeded users above.

For component-specific details (configuration options, admin settings, the `VClusterClaim` spec,
etc.), see [components/portal/README.md](components/portal/README.md) and
[components/controller/README.md](components/controller/README.md).

## Type prefixes

Branch names, commit messages and PR titles all use the same set of type prefixes, following
[Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Use for |
|---|---|
| `feat:` | A new feature |
| `fix:` | A bug fix |
| `refactor:` | A code change that neither fixes a bug nor adds a feature |
| `test:` | Adding or updating tests |
| `doc:` | Documentation only |
| `chore:` | Everything else (tooling, deps, CI, config) |

## Making changes

This project follows trunk-based development: `main` is the trunk and all work happens on short-lived branches created off it and merged back via PR.

1. Create a branch off `main`, named `<prefix>/<short-description>` using a prefix from the
   [table above](#type-prefixes) (e.g. `feat/vcluster-export`, `fix/name-hash-collision`).
2. Keep changes focused, prefer several small, reviewable PRs over one large one where possible.
3. Add or update tests for behavior you change.
4. Update relevant docs (component `README.md`, Helm chart `README.md`) if your change affects them.

## Lint and format

This project uses `ruff` for linting and formatting and `pyright` as a type checker:

```bash
uv run ruff check .          # lint
uv run ruff check --fix .    # lint + autofix
uv run ruff format .         # format
uv run pyright               # type check
```
Please run these before opening a PR.

## Tests

Tests live in `components/controller/tests/`, `components/portal/tests/` and `components/shared/tests/`. Run them from inside a component:

```bash
cd components/portal      && uv run pytest
cd components/controller  && uv run pytest
cd components/shared      && uv run pytest
```

## Commit messages

Prefix commits with a type from the [table above](#type-prefixes). Use short, imperative commit
messages that describe *why* a change was made, not just what changed (e.g.
`fix: prevent vcluster name collisions on shortened hash` rather than `update code`).

## Opening a Pull Request

- Prefix the PR title with a type from the [table above](#type-prefixes), matching the branch
  name (e.g. `feat: add vCluster PVC export`).
- Describe what the change does and why.
- Link to a relevant issue if there is any.
- Describe how to test the changes.
- Make sure the CI pipeline passes.
- Wait for a maintainer to review your changes.

## Reporting bugs and proposing features

Please open an issue describing:

- For bugs: What you expected to happen vs. what actually happened, including steps to reproduce.
- For feature proposals: The motivation and rough shape and scope of the change.

## Security issues

See [SECURITY.md](SECURITY.md) for how to report a vulnerability.

## License

By contributing, you agree that your contributions will be licensed under the project's
[AGPL-3.0](LICENSE) license.