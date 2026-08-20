---
status: "proposed"
date: 2026-08-17
decision-makers: Theodor Peifer
consulted: Prof. Dr. Johannes Ebke
informed: 
---
002-vcluster-expiration-lifecycle
# Detecting inactive vClusters and notifying, sleeping and deleting them

## Context and Problem Statement

vClusters use real cluster resources whether or not anyone is using them. The platform needs to detect inactive ones, warn their owners by email with time to react and eventually put unused clusters to sleep and delete them if inactivity continues.

This decision covers: what counts as "activity", where the periodic check for inactive/expiring clusters runs, how owners get warned by email before sleep and deletion and how much of this is automatic vs. an admin action.

## Decision Drivers

* The controller should only reconcile cluster state, optimally not send email.
* Each warning email must be sent exactly once per transition, even with multiple portal/controller replicas.
* Activity must reflect real usage of the vCluster, not just an edit to the claim's spec.
* A cluster must never be slept or deleted without its owner having been warned first.
* Manual and automatic triggers should run the same code, not duplicate logic.
* Keep the number of new moving parts small (small team, university deployment).
* Admins need visibility into inactive clusters and a way to act manually at any time.
* Self-hosters should be able to plug in their own scheduler instead of relying on ours.

## Considered Options

* **Everything in the controller**: track activity and send warning emails from the reconciliation loop.
* **Controller + K8s CronJob notifier**: controller tracks activity and does sleep/delete; a separate script, run by a `CronJob`, sends warning emails.
* **Portal handles expiration, exposes REST endpoints for potentiall CRON job**: portal computes inactivity and exposes protected endpoints that notify, suspend or delete claims that are due. An admin button and an optional `CronJob` call the same endpoints.
* **Fully manual**: controller only marks claims as inactive. An admin can trigger notify/sleep/delete from the portal.
* **Controller + in-process leader election for portal for sending emails**: same split as "Controller + K8s CronJob notifier", but the email loop runs inside the portal, with replicas electing a leader.
* **Renewable expiry date, enforced by the portal**: controller stays completely expiration-agnostic. Every claim carries a single `expires-at` deadline from the moment it's created. On expiration the cluster is automaticaly put to sleep and after another grace period is over the cluster is deleted. Before both events the owner is notified per email and can click a keep-alive link (optionally, have a keep alive button in the portal).

## Decision Outcome

**Chosen option**: *"Renewable expiry date, enforced by the portal"*.

* The controller stays completely agnostic to expiration, implementation is only portal side.
* Every VClusterClaim has a set expiration date, `EXPIRY_PERIOD_DAYS` days from the moment it's created. It must therefore be renewed to extend the expiration for `EXPIRY_PERIOD_DAYS` more days. On the day of expiration the cluster is put to sleep.
* Every VClusterClaim also has a `renewed-at` annotation. It's only written when the owner clicks a keep-alive link (if it's never been set, the claims `creationTimestamp` is used instead).
* A standalone script (`src/cluster_expiry_job.py`), run by a `CronJob` that reuses the portals image, computes `time_since_renewal = now - renewed_at` on each run. It's compared against four time offsets: `EXPIRY_PERIOD_DAYS - WARNING_LEAD_DAYS` for the first warning (before expiry), `EXPIRY_PERIOD_DAYS` for expiry and autom. sleep, `EXPIRY_PERIOD_DAYS + GRACE_PERIOD_DAYS - WARNING_LEAD_DAYS` for the second warning (before deletion) and `EXPIRY_PERIOD_DAYS + GRACE_PERIOD_DAYS` for final deletion. Every run recomputes from scratch.
* Three boolean annotations (`sleep-warning-sent`, `expired`, `deletion-warning-sent`) dedup the three emails, one per stage. `expired` is kept independent of `spec.state` on purpose: the cluster might already be asleep because the owner slept it manually before it expired and the "your cluster has expired" email still needs to fire exactly once regardless. Renewing a claim clears all three warning annotations in the same write that updates `renewed-at`, since renewal is the only thing that ever touches them.
* Unlike the other options, activity is no longer inferred from spec changes (spec changes aren't a real usage indicator after all).
* The portal UI refelcts this too: a cluster with a pending warning gets a highlighted row and a "Keep alive" button, so the owner can renew directly instead of only through the email link.

```
  ●─────────────────①────②─────────────────③─────④──▶ time

  ① shortly before expiry       "will expire and sleep soon" email
  ② expiry date                 "has expired" email, put to sleep, grace period starts
  ③ shortly before grace ends   "will be deleted soon" email
  ④ end of grace period         autom. deleted

  (not to scale - clicking the keep-alive link at any point sets renewed-at to now,
   clears the three warning annotations and restarts the line at 0)
```

### Consequences

* Good, because the controller stays a pure reconciler, entirely untouched by this feature
* Good, because both warnings give advance notice
* Good, because owners see the expiry date from day one, so nothing is ever a surprise, unlike a
  hidden inactivity clock.
* Good, because the application works normally even if people decide not to run the expiration CRON job
* Bad, because the expiration is now enforced for everyone, regardless if they actively use their cluster or not
* Bad, because operation wise another K8s has to be deployed: the CRON job (but is provisioned automatically when applying the k8s files)

### Confirmation

* A claim whose `time_since_renewal` (now minus its `renewed-at` annotation, or `creationTimestamp` if never renewed) exceeds `EXPIRY_PERIOD_DAYS - WARNING_LEAD_DAYS` gets a warning email, and `sleep-warning-sent` is set.
* At `EXPIRY_PERIOD_DAYS` (its expiry date), the claim is put to sleep (unless already asleep), an "expired and soon to be deleted" email is sent and `expired` is set.
* At `EXPIRY_PERIOD_DAYS + GRACE_PERIOD_DAYS - WARNING_LEAD_DAYS`, a second warning email is sent and `deletion-warning-sent` is set.
* At `EXPIRY_PERIOD_DAYS + GRACE_PERIOD_DAYS`, the claim is deleted (never without `deletion-warning-sent` already set).
* Clicking the keep-alive link (or button in the portal) at any point sets `renewed-at` to now and clears both warning annotations in the same write.

## Pros and Cons of the Options

### Everything in the controller

* Good, because no new deployment is needed.
* Bad, because it considers activity to be spec edits only, which doesn't capture real usage.
* Bad, because it puts email concerns inside the reconciler.

### Controller + K8s CronJob notifier

* Good, because any scheduler can trigger the same script.
* Bad, because cron granularity is less precise than a live loop (fine for week-scale warnings).
* Bad, because the script needs its own K8s RBAC to patch/delete claims, and must run in-cluster (or hold a kubeconfig) to use it.

### Portal handles expiration, protected REST endpoints

* Good, because manual and automatic triggers are the exact same code.
* Good, because there's exactly one place (the portal) that knows about inactivity thresholds.
* Good, because any HTTP-capable scheduler works, in-cluster or not.
* Bad, because of complexity: manual expiry handling through admins must have the same capabilities (sending two different warning emails, etc.), too many new admin actions, along with two new HTTP endpoints.
* Bad, because it needs custom bearer-token auth for non-interactive callers (a new secret to manage).
* Bad, because the controller no longer computes `Inactive`/`Suspended` conditions, so that state isn't visible via `kubectl describe` unless the portal takes over writing them too.

### Fully manual

* Good, because it needs no scheduler at all.
* Good, because a human acting once avoids any race.
* Bad, because it doesn't scale, someone has to remember to check regularly.

### Controller + in-process leader election

* Good, because it needs no new K8s object kind.
* Bad, because it adds a persistent background task and leader-election code to the portal.
* Bad, because the "only one runs" logic is tied to our process, not reusable by a self-hoster's own scheduler.
