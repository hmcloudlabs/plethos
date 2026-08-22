---
status: "proposed"
date: 2026-06-25
decision-makers: Theodor Peifer
consulted: Prof. Dr. Johannes Ebke
informed: 
---

# Choosing the web framework for the combined portal service

## Context and Problem Statement

[ADR 000](./000-vcluster-portal-architecture.md) decided to merge `vcluster-api` (using FastAPI) and `portal` (using Django) into one service. This ADR decides which framework to use for this consolidated service.

## Decision Drivers

* lightweight framework (easy to maintain), but still performant
* framework should be good as a fullstack-framework
* no relational database, so no integrated ORM is needed
* the service only needs to talk to the K8s API and serve templated HTML
* should have async capabilities (K8s Python client is starting to support async operations)
* setup should stay simple

## Considered Options

* **Django**: keep using Django, like the current `portal` service.
* **FastAPI**: use FastAPI, like the current `vcluster-api` service.

## Decision Outcome

**Chosen option**: *"FastAPI"*, because there is no database left to justify an ORM , FastAPI already works well for talking to the K8s API and its lightweight.

### Consequences

* Good, because FastAPI is lightweight, easy to maintain.
* Good, because the service stays small: no integrated ORM or no auth backend.
* Good, because it's natively async and therfore use the K8s async module (will make use of that in the future, when all K8s handlers are async)
* Bad, because Django is more powerful (forms, CSRF protection and session handling are lost and need to be replaced by hand).
* Bad, because Djangos template engine is more integrated than FastAPIs Jinja2 setup.

## Pros and Cons of the Options

### Django

* Good, because it is what `portal` already uses.
* Good, because it is batteries included: ORM, admin panel, auth, forms.
* Bad, because the ORM, admin panel, etc are dead weight without a database.
* Bad, because async was added later on top of a mostly sync core (ORM, middleware).



