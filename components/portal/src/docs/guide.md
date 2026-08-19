## Getting started

### 1. Sign in

Click **Sign in via SSO** on the home page and log in with your organization account.

### 2. Create a cluster

Go to **clusters** and click **Create cluster**. Give it a name - this becomes part of the
cluster's internal address, so stick to lowercase letters, numbers and hyphens.

Your cluster starts in the `Pending` phase while it's being provisioned. This usually takes a
minute or two.

### 3. Connect to it

Once your cluster shows `Ready`, open it and click **Download kubeconfig**. Point `kubectl` at it:

```bash
export KUBECONFIG=~/Downloads/<your-cluster>-kubeconfig.yaml
kubectl get namespaces
```

That's it - it's a real Kubernetes cluster, isolated from everyone else's. Anything you'd
normally do with `kubectl`, Helm, or any Kubernetes tooling works exactly the same here.

## Managing your cluster

### Sleeping and waking

A sleeping cluster is scaled down to zero - it costs nothing to keep around, but nothing in it
is reachable until you wake it back up. Open a cluster and use **Sleep** / **Wake** to switch
between the two. Waking a cluster takes a short while, same as the initial provisioning.

### Exporting your data

Open a cluster and click **Export data** to download a tarball of everything stored in its
persistent volumes. Useful before deleting a cluster, or just for backups.

### Sharing a cluster

Open a cluster and add teammates by email under **Manage access**. Shared members can see the
cluster, sleep and wake it, and download its kubeconfig - only the owner can delete it or manage
who else has access.

### Deleting a cluster

Open a cluster and click **Delete**. This is permanent - export any data you need first.
