---
status: "proposed"
date: 2026-08-20
decision-makers: Theodor Peifer
consulted: Prof. Dr. Johannes Ebke
informed:
---

# Backing up and restoring plethoss state

## Context and Problem Statement

All of plethos's state lives in one of two places:

* in the `plethos-system` namespace: contains every `VClusterClaim` (ownership, members, expiry annotations) and the `plethos-portal-settings` ConfigMap.
* in one of the namespaces created per `VClusterClaim`: contains the vClusters `StatefulSet`, the K8s objects the owner created inside the vCluster, any workload PVCs (the data their applications created).

None of this is currently backed up. Deleting a claims namespace by mistake, or losing the host clusters storage, destroys a users cluster permanently.

This decision covers how that state gets backed up automatically and can how it can be restored.

## Decision Drivers

* Must produce a real restore path, not another manual export.
* Must cover everything the main `plethos-system` namespace with its resources and the vCluster namespaces, along with all the vCluster created and user created PVCs inside them.
* Must stay optional, like the expiration CronJob and not be wired into the codebase or `k8s/base`.
* Must work when the portal or controller is gone
* Must store the backups at an S3 compatible storage outside the server running the host cluster.

## Considered Options

* **Velero**: install Velero and schedule backups to S3-compatible object storage.
* **`vcluster snapshot` + `CronJob`**: use vCluster's built-in snapshot commands, backup the plethos resources seperately.
* **Custom backup script + `CronJob`** (similar shape as `cluster_expiry_job.py`): serialize claims to YAML, upload to object storage, extend and reuse the existing volume-export code to use for extracting backups.

## Decision Outcome

**Chosen option**: *"Velero"*, because it covers both layers with one tool and needs no custom backup/restore logic to be maintained.

* Velero must be installed as prerequisite, e.g like vCluster itself or the ingress controller.
* It's optional to set up.
* The `Schedule` backs up all namespaces except host-cluster infrastructure. Velero's `includedNamespaces` only matches literal names or `*`, but we can exluse namespaces via `excludedNamespaces`.
* Both `snapshotVolumes: true` and `defaultVolumesToFsBackup: true` are set, with volume snapshots as a default and fs-backup as a fallback (this must be enforced in a Config `resourcePolicy` ConfigMap). Reason for both mechanisms is that we want to take snapshots of every PVC that supports it but also need to backup volumes that don't, and therefore fallback to fs-backup.
* CSI additionally needs `--features=EnableCSI` on `velero install` (not on by default) and a `VolumeSnapshotClass` labeled `velero.io/csi-volumesnapshot-class: "true"`.
* Restoring puts the `VClusterClaim`, ConfigMap and each vCluster's namespace back into the K8s API.
* This matches vClusters suggestion to use Velero in the ["Back up a vCluster"](https://www.vcluster.com/docs/vcluster/manage/backup-restore/velero) guidance.

### Consequences

* Good, because K8s objects and PVC are backed up and restored together.
* Good, because no new service or logic is added to this repo.
* Good, because skipping setting up Velero costs nothing.
* Bad, because it's a new cluster-level tool to install.
* Bad, because the namespace selector is wildcard-with-excludes, so any unrelated namespace added to the host cluster gets backed up unless excluded by hand.
* Bad, because neither mechanism can back up volumes on `hostPath` storage, and the failure is silent (Velero logs a warning and still reports `Phase: Completed`). We therefore need to warn people before they set up Velero and must suggest to use CSI. But since it's cluster dependent and we don't enforce how people set this up, they might run into problems.

### Confirmation

Verified end-to-end against a live deployment (Velero v1.15.2 + MinIO as object storage, dev cluster):

* A scheduled backup captured `plethos-system` and every per-`VClusterClaim namespace.
* With the volume policy, a vClusters datastore PVC on a CSI storage class was snapshotted correctly and produced a `VolumeSnapshotContent`, while `emptyDir` volumes were correctly backed up using simple fs-backup.
* Deleting a `VClusterClaim` and restoring from that backup brought the `VClusterClaim`, its namespace, its PVC and a running vCluster (with all its internal resources) back.
* The same backup silently skipped the datastore PVCs of older vClusters still on `hostPath` storage, confirming the warning metioned above. Switching the cluster's default storage class to CSI does not migrate volumes that already existed on `hostPath` storage unfortunately.

One problem found during the restore: it was stuck for a long time because the restored `VolumeSnapshotContent` had no `snapshot.storage.kubernetes.io/managed-by` label. Adding the label by hand resolved it immediately (reason not quite understood but something to do with nodes, this is likely a cluster specific problem and not a Velero flaw).

A backup/restore test should be done on the production cluster first, before trusting all of this.

## Pros and Cons of the Options

### `vcluster snapshot` + `CronJob`

* Good, because it's vClusters own mechanism for its embedded datastore, no third-party tool.
* Good, because it needs no host-cluster-level installation.
* Bad, because it only covers the vClusters own state, not the `VClusterClaim`/ConfigMap layer on the host cluster, therfore a second mechanism would still be needed.
* Bad, because restoring needs custom orchestration (create the claim, wait for the vCluster, then restore into it) with no existing reconciler behavior to lean on.

### Custom backup script + `CronJob`

* Good, because it reuses patterns already in this repo (`cluster_expiry_job.py`, the volume-export code in `vclusterclaim_repository.py`).
* Bad, because it means writing and maintaining backup/restore logic ourselves.
* Bad, because it duplicates what existing projects (like Velero) already do


