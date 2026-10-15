class NginxDirective:
    name = None
    default = None
    optional = False

    def __init__(self, value):
        self.value = value

    @classmethod
    def placeholder(cls):
        return f"__{cls.name.upper()}__"

    def render(self):
        if self.name is None:
            raise NotImplementedError("Use a concrete NginxDirective subclass")

        return f"{self.name} {self.value};"


class DaemonDirective(NginxDirective):
    name = "daemon"
    default = "on"


class WorkerProcessesDirective(NginxDirective):
    name = "worker_processes"
    default = 1


class BackendDirective(NginxDirective):
    name = "backend"
    default = "quiche"

    @classmethod
    def placeholder(cls):
        return f"__LISTEN__"

    def render(self):
        return f"listen 443 quic={self.value} reuseport;"


class CongestionControlDirective(NginxDirective):
    name = "quic_congestion_control"
    optional = True


class StreamBufferSizeDirective(NginxDirective):
    name = "http3_stream_buffer_size"
    default = "4m"
    optional = True


class QuicPktsBetweenProbesDirective(NginxDirective):
    name = "quic_pkts_between_probes"
    optional = True


DIRECTIVE_TYPES = (
    BackendDirective,
    DaemonDirective,
    WorkerProcessesDirective,
    CongestionControlDirective,
    StreamBufferSizeDirective,
    QuicPktsBetweenProbesDirective,
)
