# Backups

To backup VClusterClaims and their corresponding vCluster, [Velero](https://velero.io) should be used. Like the expiration notifier CRON job, setting up the Velero backup is optional but highly recommended.

## Set up
### 1. Check your storage class
_Note: If your cluster's default storage class uses a CSI driver, you should be good-to-go. If it doesn't, it's worth switching to it and running the check below._

In case you're adding the Velero backup after already running a vkube instance with existing vClusters:

Velero silently skips `hostPath`-backed volumes and it still reports `Phase: Completed`.
So to check if any volumes lie on `hostPath` storage, run this first:

```bash
kubectl get pv -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.spec.hostPath}{"\n"}{end}'
```

- **Empty output** -> your storage is fine, continue to step 2.
- **Non-empty output** -> you have `hostPath`-backed PVCs that will silently not be backed up. Switch to a storage class that isn't `hostPath`-backed and re-run this check before trusting any of it.

### 2. Install Velero

```bash
velero install \
  --provider <your-provider> \
  --plugins <your-plugin> \
  --bucket <your-bucket> \
  --backup-location-config <your-config> \
  --secret-file <your-credentials> \
  --use-node-agent \
  --features=EnableCSI
```

See the [Velero install docs](https://velero.io/docs/latest/basic-install/) for the
provider/plugins/bucket values, which depend on where your bucket lives.

If your storage class supports CSI snapshots and its `VolumeSnapshotClass` isn't labeled already, label it:

```bash
kubectl label volumesnapshotclass <your-class> velero.io/csi-volumesnapshot-class=true
```

Not required, but without it, everything just uses file-copy backup instead.

### 3. Apply the backup Schedule

In `/k8s/backup/` are example Velero resources which contain the recommended Velero backup configuration.

The backup should first try to use volume snapshots on all PVCs which are on CSI storage and then fall back on using plain FSB (file system backup). This rule is defined in the `velero-volume-policy.yaml`. There you must edit in your default storage class name and then apply:
```bash
kubectl apply -f k8s/backup/velero-volume-policy.yaml
```

Then you can apply the Velero schedule. Adjust `excludedNamespaces` in the file first if your host cluster runs anything besides vkube and
its ingress controller and change the CRON tab, TTL to your liking. Then apply:
```bash
kubectl apply -f k8s/backup/velero-schedule.yaml
```

The backup Schedule now runs.

## Restoring

```bash
velero backup get # find a backup to restore from
velero restore create --from-backup <backup-name>
```
