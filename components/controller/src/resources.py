from shared.vclusterclaim import GROUP


def make_namespace(namespace: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": namespace,
            "labels": {f"{GROUP}/managed": "true"},
        },
    }


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
    namespace: str, helm_install_name: str, vcluster_name: str, vcluster_version: str
) -> dict:
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": helm_install_name,
            "namespace": namespace,
            "labels": {
                f"{GROUP}/vcluster-claim": vcluster_name,
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
                                vcluster_name,
                                "vcluster",
                                "--repo",
                                "https://charts.loft.sh",
                                "--namespace",
                                namespace,
                                "--version",
                                vcluster_version,
                            ],
                        }
                    ],
                }
            }
        },
    }


def make_helm_uninstall_job(namespace: str, helm_uninstall_name: str, vcluster_name: str) -> dict:
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": helm_uninstall_name,
            "namespace": namespace,
            "labels": {
                f"{GROUP}/vcluster-claim": vcluster_name,
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
