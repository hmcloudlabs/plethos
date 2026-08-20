## Getting started

### 1. Sign in

Click **Sign in via SSO** on the home page and log in with your organization account.

### 2. Create a cluster

Go to **clusters**, enter a name in the **New Cluster** bock and click **+ create cluster**. The name becomes part of the
cluster's internal address, so use lowercase letters, numbers and hyphens.

Your cluster will the be provisioned (this usually takes a minute or two).

### 3. Connect to it

Once your cluster shows `Running`, open it and click **Connect**. This will download the kubeconfig file to which you can point `kubectl` to:

```bash
export KUBECONFIG=~/Downloads/<your-cluster>-kubeconfig.yaml
kubectl get namespaces
```

That's it, you are connected to your new Kubernetes cluster.

**Note:** Even though this a virtual cluster running inside a host cluster using *vCluster*, it works like any real Kuberneters cluster. Anything you'd normally do with `kubectl`, Helm, or any Kubernetes tooling works exactly the same here.

## Managing your cluster

### Sleeping and waking

A sleeping cluster is scaled down to zero - it costs nothing to keep around, but nothing in it
is reachable until you wake it back up. Open a cluster and use **Sleep** / **Wake** to switch
between the two. Waking a cluster takes a short while, same as the initial provisioning.

### Exporting your data

Open a cluster and click **Data** to download a tarball of everything stored in its
persistent volumes. Useful before deleting a cluster, or just for backups.

### Sharing a cluster

Open a cluster and add teammates by clicking the button with the *team* icon. There you can invite members by their email.
Once invited, they can an email with an invitation link that they have to click to join. Shared members can see the
cluster, sleep and wake it and download its kubeconfig - only the owner can delete it or manage who else has access.

### Deleting a cluster

Open a cluster and click the *trash* icon to delete it. This is permanent, so export any data you need first.

## Cluster expiration

### Lifecycle

Clusters expire after **{{ '%g'|format(config.expiry_period_days) }} days**. **{{ '%g'|format(config.warning_lead_days) }} days**
before that deadline, the owner gets a warning email with a renewal link.

If the cluster isn't renewed by then, it's automatically put to sleep once it expires, then
deleted after another **{{ '%g'|format(config.grace_period_days) }} days**. **{{ '%g'|format(config.warning_lead_days) }} days**
before that deletion, a second warning email with another renewal link is sent.

### How to renew
You can renew a cluster using either the warning email or the **/clusters** page. On the latter, the clusters table marks expired or soon-to-expire clusters and includes a **Keep Alive** button.

