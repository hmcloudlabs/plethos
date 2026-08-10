# k8s manifests

Kustomize layout for deploying vkube. `base/` is generic and not deployable
as-is (it has no real hostname, image, secret, or namespace name in it - it just uses
`vkube-system` as a placeholder). To deploy, write your own overlay (copy `overlays/example/`
as a starting point) that patches in your environment's values, including the namespace.

```bash
k8s/
├── base/                       # generic manifests, not meant to be applied directly
│   ├── kustomization.yaml
│   ├── namespace.yaml
│   ├── crds/vclusterclaim.yaml
│   ├── portal/                 # Deployment, Service, Ingress, RBAC, settings ConfigMap
│   └── controller/             # Deployment, RBAC
└── overlays/
    └── example/                # real overlay showing what to patch (copy and adapt this)
        ├── kustomization.yaml
        ├── ingress-patch.yaml
        ├── configmap-patch.yaml
        ├── controller-env-patch.yaml
        └── portal-env-patch.yaml
```

## Prerequisites

- A Kubernetes cluster with an ingress controller that supports SSL passthrough (e.g.
  nginx-ingress with `--enable-ssl-passthrough`).
- `kubectl` (contains `kustomize`, no separate install)
- Container images for `portal` and `controller`, built from
  [`components/portal/Dockerfile`](../components/portal/Dockerfile) and
  [`components/controller/Dockerfile`](../components/controller/Dockerfile) and pushed to a
  registry your cluster can pull from
- An OIDC provider for the portal to authenticate against (see
  [components/portal/README.md](../components/portal/README.md#logging-in))

## Deploying

1. Copy `overlays/example/` to your own overlay, e.g. `overlays/prod/`.
2. Edit its `kustomization.yaml` and patch files (see the table below for what must change).
3. Create the secret referenced by `portal-env-patch.yaml` (never commit real secret values):

   ```bash
   NAMESPACE=vkube-system  # must match `namespace:` in your overlay's kustomization.yaml
   kubectl create namespace "$NAMESPACE"
   kubectl create secret generic vkube-portal-secrets -n "$NAMESPACE" \
     --from-literal=PORTAL_SESSION_SECRET="$(openssl rand -hex 32)" \
     --from-literal=OIDC_CLIENT_SECRET="<your OIDC client secret>" \
     --from-literal=SMTP_USERNAME="<your SMTP username>" \
     --from-literal=SMTP_PASSWORD="<your SMTP password>"
   ```

   The `SMTP_*` values are required for cluster invites to actually work (see [components/portal/README.md](../components/portal/README.md) for why).

   (`kubectl apply -k` would create the namespace too via `namespace.yaml` in `base/` - creating
   it manually here first just lets the secret be created before that apply happens.)

1. Apply it:

   ```bash
   kubectl apply -k overlays/prod
   ```

## Fields you must customize

| What | Where | Notes |
|---|---|---|
| Namespace | `kustomization.yaml` → `namespace:` | Also update `VCLUSTERCLAIMS_NAMESPACE` to match in both `controller-env-patch.yaml` and `portal-env-patch.yaml` - that's a plain env string, so the namespace rename doesn't reach it automatically |
| Portal hostname | `ingress-patch.yaml` | Must resolve to your ingress controller |
| Container images | `kustomization.yaml` → `images:` | Point at your registry/tag, not `:latest` |
| Admin emails / quotas | `configmap-patch.yaml` | See [portal admin settings](../components/portal/README.md#admin-settings) |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID` | `portal-env-patch.yaml` | Your IdP's issuer URL and the client id registered there |
| `PORTAL_SESSION_SECRET`, `OIDC_CLIENT_SECRET` | Secret `vkube-portal-secrets` (created out-of-band, see above) | Never commit these - the patch only references the secret by name/key |
| `SMTP_HOST`, `SMTP_FROM_ADDRESS`, `SMTP_USERNAME`, `SMTP_PASSWORD` | `portal-env-patch.yaml` / Secret `vkube-portal-secrets` | Required for member invites to work (see [portal docs](../components/portal/README.md)) |
| `VCLUSTERS_BASE_DOMAIN` | `controller-env-patch.yaml` | Domain each vCluster is exposed under, `<name>.<base-domain>`; leave unset only for a domain-less/local setup |
| `SUPPORTED_VCLUSTER_VERSIONS` | both `controller-env-patch.yaml` and `portal-env-patch.yaml` | Must be identical in both - the portal always provisions the newest version the controller supports |

Full env var reference (including sensible defaults for anything not listed above):
[controller](../components/controller/README.md#configuration),
[portal](../components/portal/README.md#configuration).

