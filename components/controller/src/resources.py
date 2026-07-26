import json

from shared.vclusterclaim import GROUP


_PSA_LABELS = {
    "pod-security.kubernetes.io/enforce": "baseline",
    "pod-security.kubernetes.io/audit": "restricted",
    "pod-security.kubernetes.io/warn": "restricted",
}

# Isolation values for a vCluster release, passed to `helm install` as `--set` flags.
_VCLUSTER_ISOLATION_VALUES = {
    "policies": {
        "podSecurityStandard": "baseline",
        "networkPolicy": {"enabled": True},
        "resourceQuota": {"enabled": False},
        "limitRange": {"enabled": False},
    }
}


def make_namespace(namespace: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": namespace,
            "labels": {f"{GROUP}/managed": "true", **_PSA_LABELS},
        },
    }


def _helm_set_args(values: dict, prefix: str = "") -> list[str]:
    """Flattens a nested values dict into `--set key.path=value` CLI args."""

    args = []
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            args.extend(_helm_set_args(value, path))
        elif isinstance(value, list):
            rendered = "{" + ",".join(str(v) for v in value) + "}"
            args.extend(["--set", f"{path}={rendered}"])
        else:
            rendered = str(value).lower() if isinstance(value, bool) else str(value)
            args.extend(["--set", f"{path}={rendered}"])
    return args


def make_service_account(namespace: str, service_account_name: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {
            "name": service_account_name,
            "namespace": namespace,
        },
    }


def make_cluster_role_binding(namespace: str, crb_name: str) -> dict:
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRoleBinding",
        "metadata": {
            "name": crb_name,
        },
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": "cluster-admin",
        },
        "subjects": [
            {
                "kind": "ServiceAccount",
                "name": "helm-installer",
                "namespace": namespace,
            }
        ],
    }


def _ingress_helm_args(vcluster_name: str, base_domain: str, ingress_namespace: str) -> list[str]:
    """Extra `helm` args exposing the vCluster via ingress, or `[]` if `base_domain` is unset.

    Requires an ingress controller with SSL passthrough enabled, since the control plane
    speaks mTLS directly (there's no TLS termination to do). The NetworkPolicy rule is
    passed via `--set-json` (not `--set`, which can't represent a list of nested dicts):
    vCluster's own `policies.networkPolicy` otherwise only allows traffic between the
    vCluster's own control-plane/workload pods, so without it the ingress controller
    can route to the Service but the packets get dropped.
    """

    if not base_domain:
        return []

    host = f"{vcluster_name}.{base_domain}"
    
    values = {
        "controlPlane": {
            "endpoint": f"https://{host}",
            "ingress": {
                "enabled": True,
                "host": host,
            },
            "proxy": {
                "extraSANs": [host],
            },
        },
    }
    network_policy_rule = [
        {
            "from": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": ingress_namespace}
                    }
                }
            ],
            "ports": [{"port": 443, "protocol": "TCP"}],
        }
    ]

    return [
        *_helm_set_args(values),
        "--set-json",
        f"policies.networkPolicy.controlPlane.ingress={json.dumps(network_policy_rule)}",
    ]


def make_helm_install_job(
    claim_name: str,
    namespace: str,
    helm_install_name: str,
    vcluster_name: str,
    vcluster_version: str,
    base_domain: str,
    ingress_namespace: str,
) -> dict:
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": helm_install_name,
            "namespace": namespace,
            "labels": {
                f"{GROUP}/vcluster-claim": claim_name,
                f"{GROUP}/job-type": "install",
            },
        },
        "spec": {
            # Job retries failures itself and cleans itself up once finished.
            # Using `upgrade --install` to make every (re)try idempotent.
            "backoffLimit": 3,
            "ttlSecondsAfterFinished": 120,
            "template": {
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": "helm-installer",
                    "containers": [
                        {
                            "name": "helm",
                            "image": "alpine/helm:3.14.0",
                            "command": [
                                "helm",
                                "upgrade",
                                "--install",
                                vcluster_name,
                                "vcluster",
                                "--repo",
                                "https://charts.loft.sh",
                                "--namespace",
                                namespace,
                                "--version",
                                vcluster_version,
                                *_helm_set_args(_VCLUSTER_ISOLATION_VALUES),
                                *_ingress_helm_args(vcluster_name, base_domain, ingress_namespace),
                            ],
                        }
                    ],
                }
            },
        },
    }


def make_helm_uninstall_job(
    claim_name: str, namespace: str, helm_uninstall_name: str, vcluster_name: str
) -> dict:
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": helm_uninstall_name,
            "namespace": namespace,
            "labels": {
                f"{GROUP}/vcluster-claim": claim_name,
                f"{GROUP}/job-type": "uninstall",
            },
        },
        "spec": {
            "template": {
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": "helm-installer",
                    "containers": [
                        {
                            "name": "helm",
                            "image": "alpine/helm:3.14.0",
                            "command": [
                                "helm",
                                "uninstall",
                                vcluster_name,
                                "--namespace",
                                namespace,
                            ],
                        }
                    ],
                }
            }
        },
    }
