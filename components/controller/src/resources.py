import json

from shared.vclusterclaim import GROUP


# The ClusterRole the plethos chart ships for the helm-installer SA, see
# charts/plethos/templates/controller/vcluster-installer-rbac.yaml.
VCLUSTER_INSTALLER_ROLE = "plethos-vcluster-installer"


def make_namespace(namespace: str) -> dict:
    psa_labels = {
        "pod-security.kubernetes.io/enforce": "baseline",
        "pod-security.kubernetes.io/audit": "restricted",
        "pod-security.kubernetes.io/warn": "restricted",
    }

    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": namespace,
            "labels": {f"{GROUP}/managed": "true", **psa_labels},
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


def make_role_binding(namespace: str, service_account: str, role_binding: str) -> dict:
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": {
            "name": role_binding,
            "namespace": namespace,
        },
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "ClusterRole",
            "name": VCLUSTER_INSTALLER_ROLE,
        },
        "subjects": [
            {
                "kind": "ServiceAccount",
                "name": service_account,
                "namespace": namespace,
            }
        ],
    }


def _control_plane_ingress_helm_args(
    vcluster_name: str, vcluster_api_base_domain: str
) -> list[str]:
    """Extra Helm args for exposing the vCluster's control plane via ingress."""

    if not vcluster_api_base_domain:
        return []

    host = f"{vcluster_name}.{vcluster_api_base_domain}"

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

    return _helm_set_args(values)


def _app_ingress_helm_args(
    exposed_apps_base_domain: str,
    ingress_namespace: str,
    ingress_controller_ip_ranges: tuple[str, ...],
) -> list[str]:
    """
    Extra Helm args letting the host cluster's ingress controller reach the vCluster's workload pods.

    The `namespaceSelector` only matches a controller running with its own pod IPs. A controller
    with `hostNetwork: true` sends from its node's IP instead, which only
    `ingress_controller_ip_ranges` can match.
    """

    if not exposed_apps_base_domain:
        return []

    workload_ingress_rule = [
        {
            "from": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": ingress_namespace}
                    }
                },
                *({"ipBlock": {"cidr": ip_range}} for ip_range in ingress_controller_ip_ranges),
            ],
        }
    ]

    return [
        "--set-json",
        f"policies.networkPolicy.workload.ingress={json.dumps(workload_ingress_rule)}",
    ]


def make_app_ingress(host: str, namespace: str, target_service_name: str) -> dict:
    """
    The `Ingress` routing a vCluster's app host (see `ensure_app_ingress`) to its app Service.
    This manifest will be used if the controller detects a Service named `http` in the default
    namespace.
    """

    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": "app",
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
    service_account: str,
    helm_install_name: str,
    vcluster_name: str,
    vcluster_version: str,
    vcluster_api_base_domain: str,
    exposed_apps_base_domain: str,
    ingress_namespace: str,
    ingress_controller_ip_ranges: tuple[str, ...],
) -> dict:
    isolation_values = {
        "policies": {
            "podSecurityStandard": "baseline",
            "networkPolicy": {"enabled": True},
            "resourceQuota": {"enabled": False},
            "limitRange": {"enabled": False},
        },
        "rbac": {"enableVolumeSnapshotRules": {"enabled": False}},
    }

    # Since v0.20.0 the chart's default image is `vcluster-pro`, which contains Pro features
    # not licensed in Apache 2.0, therefore pin the pure open-source build instead.
    image_values = {
        "controlPlane": {"statefulSet": {"image": {"repository": "loft-sh/vcluster-oss"}}}
    }

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
                    "serviceAccountName": service_account,
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
                                *_helm_set_args(isolation_values),
                                *_helm_set_args(image_values),
                                *_control_plane_ingress_helm_args(
                                    vcluster_name, vcluster_api_base_domain
                                ),
                                *_app_ingress_helm_args(
                                    exposed_apps_base_domain,
                                    ingress_namespace,
                                    ingress_controller_ip_ranges,
                                ),
                            ],
                        }
                    ],
                }
            },
        },
    }


def make_helm_uninstall_job(
    claim_name: str,
    namespace: str,
    service_account: str,
    helm_uninstall_name: str,
    vcluster_name: str,
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
                    "serviceAccountName": service_account,
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
