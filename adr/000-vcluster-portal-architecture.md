---
status: "accepted"
date: 2026-06-23
decision-makers: Theodor Peifer, Prof. Dr. Johannes Ebke
consulted: 
informed: 
---

# Re-desiging the current architecture of the vCluster portal to be more minimal, easier to maintain and more K8s idiomatic.

## Context and Problem Statement

Currently, the vCluster portal has the following architecture:

![portal-architecture](adr/images/portal-architecture.png)

As shown in the figure, there are currently four main components (next to the K8s cluster itself) that make up the platform:
- the `vcluster-api` service: This works as a proxy for delegating different vCluster CRUD operations to the Kubernetes API
- the `portal` service: A Django application which communitcated with the `vcluster-api` and serves the frontend
- a PostgreSQL database: Stores user data, vCluster data and the relationship between them
- a Keycloak instance: Used for identity management
- and the Kubernetes cluster

This vCluster management portal was developed to deployed in a university envrionment where the resources and time for maintainance are slim. So even the shown architecture is quite common, it opens four different possible points of failure and a big surface for maintainance.

Therefore, the architectural design of could be simplified, to ensure to just better maintainability but also extendability. 

## Decision Drivers
* less and easier maintainance (for example by combining the `vcluster-api` and `portal`)
* be Kubernetes native/idiomatic (since it manages K8s resources, common K8s patterns should be respected)
* easy to setup (less components mean easier setup)
* open-source readiness (making the application with open-source in mind can ensure more focus on extenability and ease-of-use)

## Considered Options

**Note:** All the following options use just a single repository, since the `vcluster-api` and `portal` will be combined into a single service.

* **Namespace Annotation define ownership**:
    Since the current database is mainly used to map users to the vClusters they own, the ownership information could be instead stored in the K8s vCluster resources instead. The namespace, which is created per vCluster can store the user id and other information to map it to their owner.
* **VClusterClaim CRD**:
    Again, instead of a DB, the ownership will be stored in K8s itself. This time as a Custom Resource Definition (e.g named _VClusterClaim_) which will be created for each vCluster. It stores all information necessary, such as ownership (user-id, etc.) but can also be used to store other state, like the status/phase of the vCluster, other user-id which have access. The Python service will create all resources together: The _VClusterClaim_ and all resources necessary for provisioning a vCluster.
* **VClusterClaim CRD with a custom controller**:
    This option is the same as above, but the Python service will just work with the _VClusterClaim_ CRD to define the desired state of vClusters. A K8s controller will then run in the host cluster to reconsile the desired state of all vClusters in an K8s idiomatic way.
* **PortalUser CRD**:
    This option also uses a CRD but this time one per user, not per vCluster. When a user creates a vCluster, it will be added to their _PortalUser_ resource which creates a simple ownership model. More information per vCluster can also be stored here. Though this treats the CRD more as an application data store than a K8s state store.
* **SQlite as persistent volume**:
    This approach is similar to the current architecture, but replaces the PostgreSQl service with a single SQLite file, which takes away a whole process. It will still store every user that logged in via SSO and map them to their owned vClusters.

## Decision Outcome

**Chosen option**: _"VClusterClaim CRD with a custom controller"_, because it represents the most K8s idiomatic way to handle vCluster resources.

### Consequences
* **Good, because** it uses a controller to handle the state of vClusters, which is the correct approach when working with K8s resources.
* **Good, because** it gets rid of the relational database, which introduces more complexity, and uses Kuberenetes' etcd directly to store the state.
* **Bad, because** it still requires to maintain two different services, the portal and the controller


<br /><br /><br />
# BELOW IS NOT YET FILLED OUT

### Confirmation

{Describe how the implementation / compliance of the ADR can/will be confirmed. Is there any automated or manual fitness function? If so, list it and explain how it is applied. Is the chosen design and its implementation in line with the decision? E.g., a design/code review or a test with a library such as ArchUnit can help validate this. Note that although we classify this element as optional, it is included in many ADRs.}

<!-- This is an optional element. Feel free to remove. -->
## Pros and Cons of the Options

### {title of option 1}

<!-- This is an optional element. Feel free to remove. -->
{example | description | pointer to more information | …}

* Good, because {argument a}
* Good, because {argument b}
<!-- use "neutral" if the given argument weights neither for good nor bad -->
* Neutral, because {argument c}
* Bad, because {argument d}
* … <!-- numbers of pros and cons can vary -->

### {title of other option}

{example | description | pointer to more information | …}

* Good, because {argument a}
* Neutral, because {argument b}
* Bad, because {argument c}
* …

<!-- This is an optional element. Feel free to remove. -->
## More Information

{You might want to provide additional evidence/confidence for the decision outcome here and/or document the team agreement on the decision and/or define when/how this decision the decision should be realized and if/when it should be re-visited. Links to other decisions and resources might appear here as well.}