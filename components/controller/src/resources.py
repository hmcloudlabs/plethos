from shared.vclusterclaim import GROUP


def make_namespace(name: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": f"vcluster-{name}",
            "labels": {f"{GROUP}/managed": "true"},
        },
    }


def make_service_account(name: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {
            "name": "helm-installer",
            "namespace": f"vcluster-{name}",
        },
    }


def make_cluster_role_binding(name: str) -> dict:
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRoleBinding",
        "metadata": {
            "name": f"helm-installer-{name}",
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
                "namespace": f"vcluster-{name}",
            }
        ],
    }


def make_helm_install_job(name: str, vcluster_version: str) -> dict:
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": f"helm-install-{name}",
            "namespace": f"vcluster-{name}",
            "labels": {
                f"{GROUP}/vcluster-claim": name,
                f"{GROUP}/job-type": "install",
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
                                "install",
                                f"vcluster-{name}",
                                "vcluster",
                                "--repo",
                                "https://charts.loft.sh",
                                "--namespace",
                                f"vcluster-{name}",
                                "--version",
                                vcluster_version,
                            ],
                        }
                    ],
                }
            }
        },
    }


def make_helm_uninstall_job(name: str) -> dict:
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": f"helm-uninstall-{name}",
            "namespace": f"vcluster-{name}",
            "labels": {
                f"{GROUP}/vcluster-claim": name,
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
                                f"vcluster-{name}",
                                "--namespace",
                                f"vcluster-{name}",
                            ],
                        }
                    ],
                }
            }
        },
    }
