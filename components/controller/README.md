# vCluster Controller

A [Kopf](https://kopf.readthedocs.io/)-based Kubernetes operator that manages the full
lifecycle of virtual clusters (Loft Labs [_vCluster_](https://www.vcluster.com/)) from
`VClusterClaim` custom resources: it provisions them, puts them to sleep and wakes them,
and tears them down.

## Prerequisites

- A Kubernetes cluster (e.g. [_kind_](https://kind.sigs.k8s.io/) or _minikube_ for local development)
- `kubectl`
- [`uv`](https://docs.astral.sh/uv/)

## Setup

Create the namespace the `VClusterClaim` resources will live in:

```bash
kubectl create namespace plethos-system
```

Apply the `VClusterClaim` CRD:

```bash
kubectl apply -f charts/plethos/crds/vclusterclaim.yaml
```

(For a full cluster deployment rather than local development, see [charts/plethos/README.md](../../charts/plethos/README.md).)

## Running the controller

**Note:** Run everything from the root directory of this project.

```bash
uv run kopf run components/controller/src/main.py --namespace plethos-system --verbose
```

## Creating a claim

Apply a `VClusterClaim` (the controller watches the `plethos-system` namespace by default):

```yaml
apiVersion: plethos.cs.hm.edu/v1alpha1
kind: VClusterClaim
metadata:
  name: my-cluster
  namespace: plethos-system
spec:
  name: my-cluster
  ownerSubject: user-oidc-sub
  ownerEmail: user@example.com
  # vClusterVersion: "0.35.0"   # optional
```

Watch the reconciliation progress:

```bash
kubectl get vcc -n plethos-system -w
```

The `vcc` short name prints the cluster name, owner, desired state, current phase and the
`Ready` condition.

## Spec reference

| Field | Required | Immutable | Default | Description |
|---|---|---|---|---|
| `name` | yes | yes | - | Name of the vCluster |
| `ownerSubject` | yes | yes | - | OIDC subject of the owner |
| `ownerEmail` | yes | yes | - | Email of the owner |
| `vClusterVersion` | no | yes | `0.35.0` | vCluster chart version (see [Version selection](#version-selection)) |
| `state` | no | no | `Running` | `Running` or `Sleeping` (see [Sleep and wake](#sleep-and-wake)) |
| `members` | no | no | `[]` | List of `{ email }` - users the claim is shared with |

## Sleep and wake

Setting `spec.state` toggles the vCluster between running and asleep. `Sleeping` scales the
vCluster StatefulSet to zero replicas (recording the original replica count in
`plethos.cs.hm.edu/paused*` annotations); `Running` scales it back up. The claim reports `Sleeping` / `Waking` / `Ready` accordingly.

## Version selection

Each claim pins its vCluster version via the immutable `spec.vClusterVersion` field. The controller only installs versions listed in
`SUPPORTED_VCLUSTER_VERSIONS`. This environment variable is controlled by the person deploying the controller.

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `VCLUSTERCLAIMS_NAMESPACE` | `plethos-system` | Namespace the controller watches for claims |
| `RECONCILIATION_INTERVAL` | `30` | Seconds between timer-driven reconciliations |
| `SUPPORTED_VCLUSTER_VERSIONS` | `0.20.0,0.35.0` | Comma-separated vCluster versions the controller may install, must be >=`0.20.0` |
| `VCLUSTERS_BASE_DOMAIN` | _(unset)_ | Domain each vCluster gets exposed under, as `<vcluster-name>.<base_domain>`. Requires an ingress controller with SSL passthrough (vCluster's API server does mTLS). Unset by default so local/dev setups keep the chart's default `localhost:8443` kubeconfig. |
| `VCLUSTERS_INGRESS_NAMESPACE` | `ingress-nginx` | Namespace the ingress controller runs in - each vCluster's NetworkPolicy needs an explicit exception to let it through, since network isolation blocks everything else. |
| `VCLUSTERS_CERT_ISSUER` | _(unset)_ | Name of a cert-manager `ClusterIssuer` (must support DNS-01, for wildcard certs) used to expose owner-deployed workloads (see [Public gateway](#public-gateway)). Unset by default, which disables this feature. |

## Public gateway

If a tenant deploys a `Service` with the name `gateway` in their vClusters `default` namespace, they can access that service publicly from the internet/network. To route to mutliple public apps with their own subdomains, an ingress controller can be deployed in the `Serivce`.

To make this feature work, `VCLUSTERS_BASE_DOMAIN` and `VCLUSTERS_CERT_ISSUER` have to be set when deploying this controller, so each vCluster can get their wildcard host `*.<vcluster-name>.<base_domain>`.

TLS is terminated by the host cluster's ingress controller, not passed through: the controller requests a wildcard `Certificate` from `VCLUSTERS_CERT_ISSUER` and stores it as a `gateway-tls` Secret, so owners never has to manage certificates themselves.

## Phases

The `status.phase` field described the operator-controlled status of a `VClusterClaim` resource:

| Phase | Meaning |
|---|---|
| `Provisioning` | Creating the Helm install Job, or the Job is still running |
| `Pending` | vCluster StatefulSet exists but isn't ready yet |
| `Ready` | vCluster is up |
| `Sleeping` | vCluster scaled to zero |
| `Waking` | vCluster scaling back up after sleep |
| `Error` | Terminal problem (e.g. unsupported version, resource creation failed) |
| `Deleting` | Claim is being torn down |

## Conditions

`status.conditions` holds machine-readable conditions:

| Type | `True` means |
|---|---|
| `Ready` | The vCluster is actually up (`False` otherwise, with the current phase as `reason`) |

`Ready` supports:

```bash
kubectl wait --for=condition=Ready vcc/my-cluster -n plethos-system
```

## Testing

The test suite is end-to-end and runs against a real cluster, so it additionally needs
**Docker** and **kind**.

```bash
cd components/controller
uv run pytest
```

The suite reuses a running **kind** cluster.