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

# Since v0.20.0 the chart's default image is `vcluster-pro`, which contains Pro features
# not licensed in Apache 2.0, therefore pin the pure open-source build instead.
_VCLUSTER_IMAGE_VALUES = {
    "controlPlane": {"statefulSet": {"image": {"repository": "loft-sh/vcluster-oss"}}}
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

    The control-plane path requires an ingress controller with SSL passthrough enabled,
    since the control plane speaks mTLS directly (there's no TLS termination to do). The
    gateway path, (i.e. the gateway Service) is plain HTTP, terminated by
    the host clusters's ingress controller.
    """

    if not base_domain:
        return []

    host = f"{vcluster_name}.{base_domain}"

    values = {
        "controlPlane": {
            "ingress": {
                "enabled": True,
                "host": host,
            },
            "proxy": {
                "extraSANs": [host],
            },
        },
        "exportKubeConfig": {
            "server": f"https://{host}",
        },
    }

    # Allow external ingress to workload pods.
    workload_ingress_rule = [
        {
            "from": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": ingress_namespace}
                    }
                }
            ],
        }
    ]

    return [
        *_helm_set_args(values),
        "--set-json",
        f"policies.networkPolicy.workload.ingress={json.dumps(workload_ingress_rule)}",
    ]


def make_gateway_ingress(host: str, namespace: str, target_service_name: str) -> dict:
    """
    The `Ingress` routing a vCluster's gateway host (see `GatewayConvention.host`) to its
    gateway Service.

    TLS is terminated here by the host cluster's ingress controller, not passed through.
    """

    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": "gateway",
            "namespace": namespace,
        },
        "spec": {
            "tls": [{"hosts": [host]}],
            "rules": [
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "path": "/",
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": target_service_name,
                                        "port": {"number": 80},
                                    }
                                },
                            }
                        ]
                    },
                }
            ],
        },
    }


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
                                *_helm_set_args(_VCLUSTER_IMAGE_VALUES),
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
            # Same self-retry/cleanup as the install job
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
                                "uninstall",
                                vcluster_name,
                                "--namespace",
                                namespace,
                                "--ignore-not-found",
                            ],
                        }
                    ],
                }
            },
        },
    }
