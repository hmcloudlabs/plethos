# Plethos Helm chart

Official way to install Plethos (portal + controller + notifier CronJob + the
VClusterClaim CRD).

## Prerequisites

- A Kubernetes cluster with an ingress controller that supports SSL passthrough (e.g. nginx-ingress with `--enable-ssl-passthrough`).
- An OIDC provider for the portal to authenticate against (see [components/portal/README.md](../../components/portal/README.md#logging-in)).
- A wildcard DNS record for `*.<vClusterApiBaseDomain>`, so users can reach their vCluster's API. No certificate needed, each vCluster serves its own via SSL passthrough.
- To make owner-deployed workloads publicly reachable: a wildcard certificate for `*.<exposedAppsBaseDomain>` configured as the ingress controller's default certificat and a wildcard DNS record for `*.<exposedAppsBaseDomain>`. If the ingress controller runs with `hostNetwork: true`, also set `controller.ingressControllerIpRanges` to the node IP range, or the vClusters' NetworkPolicies block it from reaching the apps.

`vClusterApiBaseDomain` and `exposedAppsBaseDomain` are independent and don't need to share a parent domain.

## Installing

The chart is published at `oci://codeberg.org/hmcloudlabs/plethos`. Replace `<version>` below
with the chart version you want to install.

1. Write your own values file, starting from the chart's defaults:
   ```bash
   helm show values oci://codeberg.org/hmcloudlabs/plethos --version <version> > values.yaml
   ```
   Set every value in it for your environment (several are placeholders, like `example.com` addresses, `admin@example.com`, `localhost` URLs which _must_ be changed).

2. Install using your values file (you can choose your own namespace name):
   ```bash
   helm install plethos oci://codeberg.org/hmcloudlabs/plethos --version <version> \
     --namespace plethos-system --create-namespace \
     -f values.yaml
   ```

3. Create the secret the portal reads OIDC/session/SMTP credentials from:
   ```bash
   kubectl create secret generic plethos-portal-secrets -n plethos-system \
     --from-literal=PORTAL_SESSION_SECRET="$(openssl rand -hex 32)" \
     --from-literal=CSRF_TOKEN_SECRET="$(openssl rand -hex 32)" \
     --from-literal=OIDC_CLIENT_SECRET="<your OIDC client secret>" \
     --from-literal=SMTP_USERNAME="<your SMTP username>" \
     --from-literal=SMTP_PASSWORD="<your SMTP password>"
   ```

   `SMTP_USERNAME` and `SMTP_PASSWORD` are optional, leave them out if your SMTP server doesn't
   require authentication.

  If the portal pod started before the secret existed you must restart:

   ```bash
   kubectl rollout restart deployment/plethos-portal -n plethos-system
   ```

## Upgrading

```bash
helm upgrade plethos oci://codeberg.org/hmcloudlabs/plethos --version <version> \
  -n plethos-system -f values.yaml
```

Note: the CRD in `crds/vclusterclaim.yaml` is installed on first `helm install`
but **not** updated by `helm upgrade` (that's a Helm limitation for the `crds/` directory). If it changes, re-apply it manually before upgrading:

```bash
helm show crds oci://codeberg.org/hmcloudlabs/plethos --version <version> | kubectl apply -f -
```

## Values

See [`values.yaml`](values.yaml) for the full list with defaults and comments.
Full env var reference (including sensible defaults for anything not exposed
as a value): [controller](../../components/controller/README.md#configuration),
[portal](../../components/portal/README.md#configuration).
