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

Setting `spec.state` toggles the vCluster between running and asleep. `Sleeping` scales the vCluster StatefulSet to `0` replicas and deletes the workload pods the vCluster synced into the host namespace. `Running` scales it back up.

### How it works:

Deleting the synced workload pods is what actually frees the host resources: the synced pods are identified by the `vcluster.loft.sh/managed-by=<vcluster>` label. Before deleting them, the control plane has to be scaled to `0` replicas, otherwise it would just recreate the pods. The amount of replicas the control had running before scale down is noted as an annotation `plethos.cs.hm.edu/scaled-down-replicas` in the vCluster StatefulSet.

 _Note: Pods, which aren't inside a StatefulSet or ReplicaSet will not be able to be recreated and are lost forever. Since single pods are a Kubernetes antipattern this is behavoir is accepted._

_Note: The `vcluster` CLI's own `pause`/`resume` are *not* interchangeable with this. Running `vcluster resume` against a sleeping claim just gets the cluster put back to sleep on the next reconciliation._

## Version selection

Each claim pins its vCluster version via the immutable `spec.vClusterVersion` field. The controller only installs versions listed in
`SUPPORTED_VCLUSTER_VERSIONS`. This environment variable is controlled by the person deploying the controller.

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `VCLUSTERCLAIMS_NAMESPACE` | `plethos-system` | Namespace the controller watches for claims |
| `RECONCILIATION_INTERVAL` | `30` | Seconds between timer-driven reconciliations |
| `SUPPORTED_VCLUSTER_VERSIONS` | `0.35.0` | Comma-separated vCluster versions the controller may install, must be >=`0.35.0` |
| `VCLUSTERS_BASE_DOMAIN` | _(unset)_ | Domain each vCluster gets exposed under, as `<vcluster-name>.<base_domain>`. Requires an ingress controller with SSL passthrough (vCluster's API server does mTLS). Unset by default so local/dev setups keep the chart's default `localhost:8443` kubeconfig. |
| `VCLUSTERS_INGRESS_NAMESPACE` | `ingress-nginx` | Namespace the ingress controller runs in - each vCluster's NetworkPolicy needs an explicit exception to let it through, since network isolation blocks everything else. |

## Public gateway

If an owner deploys a `Service` named `gateway` in their vCluster's `default` namespace on
port 80, it becomes publicly reachable at `https://<vcluster-name>.plethos-apps.<base_domain>`. Requires `VCLUSTERS_BASE_DOMAIN` to be set.

Each vCluster gets exactly **one** host.

The `plethos-apps` subdomain keeps this apart from the control-plane host, which is `<vcluster-name>.<base_domain>` and needs SSL passthrough.

## Phases

The `status.phase` field described the operator-controlled status of a `VClusterClaim` resource:

| Phase | Meaning |
|---|---|
| `Provisioning` | Creating the Helm install Job, or the Job is still running |
| `Pending` | vCluster StatefulSet exists but isn't ready yet |
| `Ready` | vCluster is up |
| `Sleeping` | vCluster scaled to zero and its workload pods deleted |
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