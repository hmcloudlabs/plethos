class AppExposureConvention:
    """
    The contract for exposing an app publicly from within a vCluster. An app is whatever workload
    the owner puts behind the app Service, only HTTP can be exposed.

    An owner deploys a Service named `SERVICE_NAME` in `NAMESPACE` on port 80 *inside* their
    vCluster. The controller keeps an Ingress pointing at that Service that vCluster synced to the
    host, whether or not the Service exists yet.
    """

    SERVICE_NAME = "http"
    NAMESPACE = "default"
