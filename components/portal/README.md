# vkube Portal

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
kubectl create namespace vkube-system
```

Seed the settings `ConfigMap` the portal requires to start (admin emails, quotas):

```bash
kubectl apply -f k8s/portal/configmap.yaml
```

**Note:** the shipped ConfigMap only lists `testuser@example.com` as an admin. Add your own
email (see [Admin settings](#admin-settings)) or edit the ConfigMap directly for local admin access.

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
`vkube-portal-settings` ConfigMap (see [Admin settings](#admin-settings)).

## Features

- Create, sleep/wake and delete your own vClusters (always provisioned at the newest version the
  controller supports, see `SUPPORTED_VCLUSTER_VERSIONS`)
- Download a cluster's kubeconfig, view control-plane logs, export PVC/workload data as a tar
- Share a cluster with other users by email, subject to the team-size quota; shared members can
  sleep/wake, only the owner can delete
- Admins additionally get: every cluster across all users, with sleep/wake/delete/log access
  regardless of owner; an owners overview with bulk-delete; and the settings below

## Admin settings

All portal-wide settings live in the `vkube-portal-settings` ConfigMap, edited through the admin
dashboard (`/admin`), never directly:

| Setting | Global key | Per-user override key |
|---|---|---|
| Max vClusters per user | `maxVclustersPerUser` | `maxVclustersPerUserOverrides` (email -> int) |
| Max team size (shared members) | `maxTeamSize` | `maxTeamSizeOverrides` (email -> int) |
| Admin emails | `adminEmails` | - |

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `PORTAL_HOST` | `0.0.0.0` | uvicorn bind host |
| `PORTAL_PORT` | `8000` | uvicorn bind port |
| `PORTAL_SESSION_SECRET` | `dev-secret-change-me` | Signs the session cookie - set a real secret in production |
| `OIDC_ISSUER` | `http://localhost:9090/realms/vkube-portal` | OIDC issuer base URL |
| `OIDC_CLIENT_ID` | `vkube-portal` | OAuth2 client id |
| `OIDC_CLIENT_SECRET` | _(unset)_ | OAuth2 client secret |
| `OIDC_SCOPES` | `openid email profile` | Requested OIDC scopes |
| `VCLUSTERCLAIMS_NAMESPACE` | `vkube-system` | Namespace holding `VClusterClaim` resources, must match the controller's `VCLUSTERCLAIMS_NAMESPACE` |
| `CACHE_TTL_SECONDS` | `3.0` | TTL for the in-process caches (claim lists, settings) |
| `SUPPORT_EMAIL` | _(unset)_ | Contact address shown in the footer. Left blank, no contact link is shown |
| `SUPPORTED_VCLUSTER_VERSIONS` | `0.20.0,0.35.0` | Must match the controller's value, the portal always provisions the highest version |

## Testing

```bash
cd components/portal
uv run pytest
```

Unlike the controller's suite, this one is fully mocked and needs no cluster.