# vCluster Controller

A Kopf-based Kubernetes controller that provisions virtual clusters (using Loft Labs _vCluster_) on demand via `VClusterClaim` custom resources.

## Prerequisites

- Kubernetes cluster (e.g _minikube_ for local development)
- `kubectl`
- `uv`

## Setup
Create a namespace where the `VClusterClaim` resources will live:
```bash
kubectl create namespace vcluster-system
```

Apply the `VClusterClaim` CRD:
```bash
kubectl apply -f k8s/crds/vclusterclaim.yaml
```

## Running the controller:
**Note:** Run everything from the root directory of this project.

```bash
uv run kopf run components/controller/src/main.py --verbose
```

#### Exampe usag:
Try to create a `VClusterClaim`, for example using the provided test resource:
```bash
kubectl apply -f components/controller/tests/resources/test-vcluster-claim.yaml
```

You should the controller starting to setup the vCluster. You can check the status of the reconsilation:
```bash
kubectl get vcc -n vcluster-system -w
```

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `VCLUSTERCLAIMS_NAMESPACE` | `vcluster-system` | Namespace where claims live |

## Phases

| Phase | Meaning |
|---|---|
| `Provisioning` | Creating namespace and RBAC |
| `Pending` | Helm install job running |
| `Ready` | VCluster is up |
| `Error` | Something went wrong |