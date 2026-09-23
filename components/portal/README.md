# Plethos Portal

A FastAPI + HTMX web app that lets users provision, sleep/wake, share and delete their own
[_vCluster_](https://www.vcluster.com/) instances by creating `VClusterClaim` custom
resources. The actual provisioning is done by the [controller](../controller/README.md).

## Prerequisites

- A Kubernetes cluster with the `VClusterClaim` CRD installed and the
  [controller](../controller/README.md) running (see its README)
- An OIDC-compliant identity provider (a local Keycloak is provided for development, see [Logging in](#logging-in))
- `kubectl`
- [`uv`](https://docs.astral.sh/uv/)

## Setup

Create the namespace (skip if the controller already created it):

```bash
kubectl create namespace plethos-system
```

Seed the settings `ConfigMap` the portal requires to start (admin emails, quotas) - replace
`testuser@example.com` with your own for local admin access (see [Admin settings](#admin-settings)):

```bash
kubectl create configmap plethos-portal-settings -n plethos-system \
  --from-literal=adminEmails="testuser@example.com" \
  --from-literal=maxVclustersPerUser="5" \
  --from-literal=maxTeamSize="5"
```

(For a full cluster deployment rather than local development, see [charts/plethos/README.md](../../charts/plethos/README.md).)

## Running the portal

**Note:** Run everything from the root directory of this project.

```bash
uv run uvicorn main:app --reload --app-dir components/portal/src
```

Runs at `http://localhost:8000` by default.

## Logging in

Auth is a standard OIDC authorization-code flow (via `authlib`), IdP-agnostic, so anything that
serves a `.well-known/openid-configuration` document works (Keycloak, Auth0, Entra ID, Dex, ...).

For local development, a pre-configured Keycloak realm is included:

```bash
docker compose -f components/portal/dev-setup/docker-compose.yml up
```

Keycloak runs at `http://localhost:9090`, matching the default `OIDC_ISSUER`. Seeded users
(password matches the username, e.g. `admin`/`admin`):

| User | Email |
|---|---|
| `admin` | `admin@example.com` |
| `testuser` | `testuser@example.com` |
| `testuser2` | `testuser2@example.com` |

A user's OIDC `sub` claim becomes `spec.ownerSubject` on every `VClusterClaim` they create - it's
the stable identifier a claim is scoped to, not the email (which can change).

"Admin" isn't an OIDC role - it's just membership in the `adminEmails` list in the
`plethos-portal-settings` ConfigMap (see [Admin settings](#admin-settings)).

## Features

- Create, sleep/wake and delete your own vClusters (always provisioned at the newest version the
  controller supports, see `SUPPORTED_VCLUSTER_VERSIONS`)
- Download a cluster's kubeconfig, view control-plane logs, export PVC/workload data as a tar
- Share a cluster with other users by email, subject to the team-size quota; shared members can
  sleep/wake, only the owner can delete (needs `SMTP_HOST` reachable for invite emails to send,
  see [Configuration](#configuration) - defaults to the local dev mailpit)
- Admins additionally get: every cluster across all users, with sleep/wake/delete/log access
  regardless of owner; an owners overview with bulk-delete; and the settings below

## Admin settings

All portal-wide settings live in the `plethos-portal-settings` ConfigMap, edited through the admin
dashboard (`/admin`), never directly:

| Setting | Global key | Per-user override key |
|---|---|---|
| Max vClusters per user | `maxVclustersPerUser` | `maxVclustersPerUserOverrides` (email -> int) |
| Max team size (shared members) | `maxTeamSize` | `maxTeamSizeOverrides` (email -> int) |
| Admin emails | `adminEmails` | - |

## Cluster expiry

`src/cluster_expiry_job.py` is a standalone script, run on a schedule by the CronJob in
[`charts/plethos/templates/notifier/cronjob.yaml`](../../charts/plethos/templates/notifier/cronjob.yaml).
It reuses the portal's own image and `ServiceAccount`, so there's nothing extra to deploy.

Every VClusterClaim carries a `renewed-at` annotation, updated each time its owner clicks a
keep-alive link. If it's never been set, the claim's creation time is used instead. Measured
from there:

1. `WARNING_LEAD_DAYS` before the claim reaches its `EXPIRY_PERIOD_DAYS` expiry date, the job emails the owner a warning that it will be put to sleep, along with a keep-alive link.
2. On the expiry date itself, it puts the cluster to sleep and emails the owner that it did, in case the first warning was missed.
3. `WARNING_LEAD_DAYS` before the end of the `GRACE_PERIOD_DAYS` that follows, it emails a further warning that the cluster will be deleted.
4. At the end of the grace period, it deletes the VClusterClaim and therefore the cluster.

Clicking the keep-alive link in any of these emails is the *only* thing that renews a claim -
other portal actions (waking, editing members, etc.) don't. A VClusterClaim is never deleted
without a warning naming that exact deadline having been sent first.

## Logging

Console logging (level via `LOG_LEVEL`, default `INFO`) is always on. Set `LOG_DIR` to also write
rotating log files there. Note: in-cluster, `LOG_DIR` needs a `PersistentVolumeClaim` mounted at
that path to survive pod restarts.

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `PORTAL_HOST` | `0.0.0.0` | uvicorn bind host |
| `PORTAL_PORT` | `8000` | uvicorn bind port |
| `PORTAL_SESSION_SECRET` | `dev-secret-change-me` | Signs the session cookie and emailed links (set a real secret in production) |
| `CSRF_TOKEN_SECRET` | `dev-secret-change-me` | Signs CSRF tokens (set a real secret in production) |
| `TOKEN_MAX_AGE_SECONDS` | `604800` (7 days) | How long signed links (member invites, keep-alive) stay valid |
| `LOG_LEVEL` | `INFO` | Root log level (see [Logging](#logging)) |
| `LOG_DIR` | _(unset)_ | Directory to also write rotating log files to. Left unset, logging is console-only |
| `OIDC_ISSUER` | `http://localhost:9090/realms/plethos-portal` | OIDC issuer base URL |
| `OIDC_CLIENT_ID` | `plethos-portal` | OAuth2 client id |
| `OIDC_CLIENT_SECRET` | _(unset)_ | OAuth2 client secret |
| `OIDC_SCOPES` | `openid email profile` | Requested OIDC scopes |
| `VCLUSTERCLAIMS_NAMESPACE` | `plethos-system` | Namespace holding `VClusterClaim` resources, must match the controller's `VCLUSTERCLAIMS_NAMESPACE` |
| `BASE_DOMAIN` | _(unset)_ | Only used to display each cluster's public host (must match the controller's value) |
| `APPS_SUBDOMAIN` | `plethos-apps` | Subdomain under which the apps exposed by the users are shown under, e.g <vcluster>.plethos-apps.plethos.example.org |
| `CACHE_TTL_SECONDS` | `3.0` | TTL for the in-process caches (claim lists, settings) |
| `SUPPORT_EMAIL` | _(unset)_ | Contact address shown in the footer. Left blank, no contact link is shown |
| `SUPPORTED_VCLUSTER_VERSIONS` | `0.35.0` | Must match the controller's value, the portal always provisions the highest version |
| `SMTP_HOST` | `localhost` | SMTP server for sending member-invite and keep-alive emails (mailpit default) |
| `SMTP_PORT` | `1025` | SMTP server port (mailpit default) |
| `SMTP_USERNAME` | _(unset)_ | SMTP auth username |
| `SMTP_PASSWORD` | _(unset)_ | SMTP auth password |
| `SMTP_FROM_ADDRESS` | `plethos@example.com` | `From` address on invite/keep-alive emails |
| `PORTAL_URL` | `http://localhost:8000` | Absolute base URL for links in emails sent outside a request (the cluster expiry job's keep-alive links) |
| `EXPIRY_PERIOD_DAYS` | `90` | Days a claim stays valid since it was last renewed before it expires and is put to sleep (see [Cluster expiry](#cluster-expiry)) |
| `GRACE_PERIOD_DAYS` | `60` | Days a claim may stay asleep, unrenewed, before it's deleted |
| `WARNING_LEAD_DAYS` | `7` | Days of advance notice before each of the two warning emails (before sleep, before deletion) |

## Testing

```bash
cd components/portal
uv run pytest
```

Unlike the controller's suite, this one is fully mocked and needs no cluster.