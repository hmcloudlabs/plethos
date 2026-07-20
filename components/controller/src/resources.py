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


def make_helm_install_job(
    claim_name: str,
    namespace: str,
    helm_install_name: str,
    vcluster_name: str,
    vcluster_version: str,
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
