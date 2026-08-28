class GatewayConvention:
    """
    The contract for exposing a workload publicly within a vCluster.

    An owner deploys a Service named `SERVICE_NAME` in `NAMESPACE` on port 80 *inside* their
    vCluster, the controller finds its synced counterpart on the host and creates an Ingress for it.
    """

    SERVICE_NAME = "gateway"
    NAMESPACE = "default"
    SUBDOMAIN = "plethos-apps"

    @classmethod
    def host(cls, vcluster_name: str, base_domain: str) -> str:
        """The public host a vCluster's gateway Service is served under."""

        return f"{vcluster_name}.{cls.SUBDOMAIN}.{base_domain}"
