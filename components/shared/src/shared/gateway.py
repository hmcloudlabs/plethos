class GatewayConvention:
    """
    The contract for exposing a workload publicly within a vCluster.

    An owner deploys a Service named `SERVICE_NAME` in `NAMESPACE` on port 80 *inside* their
    vCluster, the controller finds its synced counterpart on the host and creates an Ingress for it.
    """

    SERVICE_NAME = "gateway"
    NAMESPACE = "default"


def make_gateway_host(vcluster_name: str, apps_subdomain: str, base_domain: str) -> str:
    """The public host a vCluster's gateway Service is served under."""

    return f"{vcluster_name}.{apps_subdomain}.{base_domain}"
