# plethos Helm chart

Official way to install plethos (portal + controller + notifier CronJob + the
VClusterClaim CRD).

## Prerequisites

- A Kubernetes cluster with an ingress controller that supports SSL passthrough
  (e.g. nginx-ingress with `--enable-ssl-passthrough`).
- An OIDC provider for the portal to authenticate against (see
  [components/portal/README.md](../../components/portal/README.md#logging-in)).
- To make owner-deployed workloads publicly reachable: a wildcard certificate for
  `*.plethos-apps.<vclustersBaseDomain>` configured as the ingress controller's default certificate plus a DNS record pointing `*.<vclustersBaseDomain>` at the ingress controller.
## Installing

1. Write your own values file (start from `values.yaml`) and set every value in it for
   your environment (several are placeholders, like `example.com` addresses, `admin@example.com`, `localhost` SMTP/base URL) that fail silently rather than error if left unset.
   
2. Install:
   ```bash
   helm install plethos ./charts/plethos \
     --namespace plethos-system --create-namespace \
     -f my-values.yaml
   ```

3. Create the secret the portal reads OIDC/session/SMTP credentials from:
   ```bash
   kubectl create secret generic plethos-portal-secrets -n plethos-system \
     --from-literal=PORTAL_SESSION_SECRET="$(openssl rand -hex 32)" \
     --from-literal=OIDC_CLIENT_SECRET="<your OIDC client secret>" \
     --from-literal=SMTP_USERNAME="<your SMTP username>" \
     --from-literal=SMTP_PASSWORD="<your SMTP password>"
   ```

  If the portal pod started before the secret existed, it'll be stuck in a
  `CreateContainerConfigError`. In that case, restart:

   ```bash
   kubectl rollout restart deployment/plethos-portal -n plethos-system
   ```

## Upgrading

```bash
helm upgrade plethos ./charts/plethos -n plethos-system -f my-values.yaml
```

Note: the CRD in `crds/vclusterclaim.yaml` is installed on first `helm install`
but **not** updated by `helm upgrade` (that's a Helm limitation for the `crds/` directory). If it changes, re-apply it manually:

```bash
kubectl apply -f charts/plethos/crds/vclusterclaim.yaml
```

## Values

See [`values.yaml`](values.yaml) for the full list with defaults and comments.
Full env var reference (including sensible defaults for anything not exposed
as a value): [controller](../../components/controller/README.md#configuration),
[portal](../../components/portal/README.md#configuration).
