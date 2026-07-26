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
kubectl create namespace vkube-system
```

Apply the `VClusterClaim` CRD:

```bash
kubectl apply -f k8s/crds/vclusterclaim.yaml
```

## Running the controller

**Note:** Run everything from the root directory of this project.

```bash
uv run kopf run components/controller/src/main.py --namespace vkube-system --verbose
```

## Creating a claim

Apply a `VClusterClaim` (the controller watches the `vkube-system` namespace by default):

```yaml
apiVersion: vkube.cs.hm.edu/v1alpha1
kind: VClusterClaim
metadata:
  name: my-cluster
  namespace: vkube-system
spec:
  name: my-cluster
  ownerSubject: user-oidc-sub
  ownerEmail: user@example.com
  # vClusterVersion: "0.35.0"   # optional
```

Watch the reconciliation progress:

```bash
kubectl get vcc -n vkube-system -w
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
| `accessRules` | no | no | `[]` | List of `{ subject: { sub, email }, role }`, role is `admin` or `viewer` |

## Sleep and wake

Setting `spec.state` toggles the vCluster between running and asleep. `Sleeping` scales the
vCluster StatefulSet to zero replicas (recording the original replica count in the
`loft.sh/paused*` annotations); `Running` scales it back up. The claim reports `Sleeping` /
`Waking` / `Ready` accordingly.

## Version selection

Each claim pins its vCluster version via the immutable `spec.vClusterVersion` field. The controller only installs versions listed in
`SUPPORTED_VCLUSTER_VERSIONS`. This environment variable is controlled by the person deploying the controller.

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `VCLUSTERCLAIMS_NAMESPACE` | `vkube-system` | Namespace the controller watches for claims |
| `RECONCILIATION_INTERVAL` | `30` | Seconds between timer-driven reconciliations |
| `SUPPORTED_VCLUSTER_VERSIONS` | `0.20.0,0.35.0` | Comma-separated vCluster versions the controller may install |
| `VCLUSTERS_BASE_DOMAIN` | _(unset)_ | Domain each vCluster gets exposed under, as `<vcluster-name>.<base_domain>`. Requires an ingress controller with SSL passthrough (vCluster's API server does mTLS). Unset by default so local/dev setups keep the chart's default `localhost:8443` kubeconfig. |
| `VCLUSTERS_INGRESS_NAMESPACE` | `ingress-nginx` | Namespace the ingress controller runs in - each vCluster's NetworkPolicy needs an explicit exception to let it through, since network isolation blocks everything else. |

## Phases

The `status.phase` field described the operator-controlled status of a `VClusterClaim` resource:

| Phase | Meaning |
|---|---|
| `Provisioning` | Creating (or retrying) the Helm install Job |
| `Pending` | Install Job running / vCluster still booting |
| `Ready` | vCluster is up |
| `Sleeping` | vCluster scaled to zero |
| `Waking` | vCluster scaling back up after sleep |
| `Error` | Terminal problem (e.g. unsupported version, resource creation failed) |
| `Deleting` | Claim is being torn down |

## Conditions

`status.conditions` holds machine-readable conditions. The `Ready` condition is `True` only
when the vCluster is actually up, and `False` otherwise with the current phase as its
`reason`. This supports:

```bash
kubectl wait --for=condition=Ready vcc/my-cluster -n vkube-system
```

## Testing

The test suite is end-to-end and runs against a real cluster, so it additionally needs
**Docker** and **kind**.

```bash
cd components/controller
uv run pytest
```

The suite reuses a running **kind** cluster.