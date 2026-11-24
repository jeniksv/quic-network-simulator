from array import array
from collections import Counter, defaultdict, deque
import heapq
import mmap
import re
import struct

from .sample import Sample

CAPTURES = {"left": "trace_node_left.pcap", "right": "trace_node_right.pcap"}
CLIENT_SIDE = "left"
INGRESS = {"c2s": "left", "s2c": "right"}
QUIC_PORT = 443
ETHERNET_HEADER = 14
IPV6_HEADER = 40
UDP_HEADER = 8
KEY_PREFIX = 64
FRAME_HEAD = ETHERNET_HEADER + IPV6_HEADER + UDP_HEADER + KEY_PREFIX
PPP_HEADER = 2
MAX_PACKET = 1500 + PPP_HEADER
LONG_BURST = 10
SECONDS = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1}
RATES = {"": 1, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}
DECISION = re.compile(r"(Dropping|Forwarding) \d+ bytes \S+:(\d+) -> \S+:(\d+)")

SECTION_HEADER_BLOCK = 0x0A0D0D0A
INTERFACE_DESCRIPTION_BLOCK = 1
INTERFACE_STATISTICS_BLOCK = 5
ENHANCED_PACKET_BLOCK = 6
LITTLE_ENDIAN_MAGIC = b"\x4d\x3c\x2b\x1a"
LINKTYPE_ETHERNET = 1
OPT_ENDOFOPT = 0
IF_TSRESOL = 9
ISB_IFDROP = 5
DEFAULT_RESOLUTION = 10 ** 6
IPV4 = 0x0800
IPV6 = 0x86DD
UDP = 17
BLOCK = struct.Struct("<II")
ENHANCED_PACKET = struct.Struct("<IIIII")
OPTION = struct.Struct("<HH")
SHORT = struct.Struct("!H")
PORTS = struct.Struct("!HHH")


class Captures:
    def __init__(self, directory):
        self.directory = directory
        self.captures = [Capture(directory / name, side) for side, name in CAPTURES.items()]
        self.warnings = []

    def exists(self):
        return all(capture.path.is_file() for capture in self.captures)

    def summarize(self, parameters):
        link = Link(parameters)
        flows = defaultdict(Flow)
        directions = {name: Direction(name, ingress, link, flows) for name, ingress in INGRESS.items()}
        self._match(directions, flows)
        for name, direction in directions.items():
            if direction.unmatched:
                self.warnings.append(f"{name}: {direction.unmatched} datagrams left the simulator without entering it")

        model = self._loss_model(link.scenario)
        summary = {}
        for name, direction in directions.items():
            random, undecided = model.drops(direction)
            summary[name] = values = direction.finish(random, undecided)
            if values["dropped_queue"] is not None and values["dropped_queue"] < 0:
                self.warnings.append(f"{name}: drop-rate dropped {random} datagrams, the captures show "
                                     f"{values['dropped']}")

        summary["connections"] = len(flows)
        summary["conn"] = self._connections(flows)
        for capture in self.captures:
            if capture.truncated:
                self.warnings.append(f"{capture.side} capture is truncated")
            if capture.ifdrop:
                self.warnings.append(f"{capture.side} capture dropped {capture.ifdrop} packets")
        return summary

    def _match(self, directions, flows):
        datagrams = heapq.merge(*(capture.datagrams() for capture in self.captures))
        for time, side, name, flow, key, wire, payload, long_header in datagrams:
            direction = directions[name]
            if side == direction.ingress:
                direction.enter(time, flow, key, wire, payload, long_header)
            else:
                direction.leave(time, key, wire, payload)
            if side == CLIENT_SIDE:
                flows[flow].seen(time)

    def _loss_model(self, scenario):
        for model in LOSS_MODELS:
            if scenario in model.scenarios:
                return model(self.directory, self.warnings)
        return LossModel(self.directory, self.warnings)

    @staticmethod
    def _connections(flows):
        values = {"drop_rate": [], "queue_delay_s": [], "duration_s": []}
        for flow in flows.values():
            for key, value in flow.summary().items():
                if value is not None:
                    values[key].append(value)
        return {key: Sample(sample).describe() for key, sample in values.items()}


class Link:
    def __init__(self, parameters):
        parameters = parameters or ""
        words = parameters.split()
        delay = re.search(r"--delay=([\d.]+)(ns|us|ms|s)\b", parameters)
        bandwidth = re.search(r"--bandwidth=([\d.]+)([kKMG]?)bps\b", parameters)
        queue = re.search(r"--queue=(\d+)\b", parameters)
        self.scenario = words[0] if words else None
        self.delay = float(delay[1]) * SECONDS[delay[2]] if delay else None
        self.bandwidth = float(bandwidth[1]) * RATES[bandwidth[2]] if bandwidth else None
        self.queue = int(queue[1]) if queue else None

    @property
    def horizon(self):
        if self.delay is None or not self.bandwidth or self.queue is None:
            return None
        return round((2 * (self.delay + self.queue * MAX_PACKET * 8 / self.bandwidth) + 1) * 1e9)


class LossModel:
    scenarios = ()

    def __init__(self, directory, warnings):
        self.directory = directory
        self.warnings = warnings

    def drops(self, direction):
        return None, None


class QueueOnly(LossModel):
    scenarios = ("simple-p2p", "tcp-cross-traffic", "udp-cross-traffic")

    def drops(self, direction):
        return 0, None


class DropRate(LossModel):
    scenarios = ("drop-rate",)

    def __init__(self, directory, warnings):
        super().__init__(directory, warnings)
        self.decisions = self._decisions()
        if self.decisions is None:
            self.warnings.append("console.log has no decisions of drop-rate")

    def drops(self, direction):
        if self.decisions is None:
            return None, None

        decisions = self.decisions[direction.name]
        random, forwarded = decisions["Dropping"], decisions["Forwarding"]
        if forwarded != direction.egress:
            self.warnings.append(f"{direction.name}: drop-rate forwarded {forwarded} datagrams, "
                                 f"{direction.egress} left the simulator")
        undecided = direction.datagrams - forwarded - random
        if undecided < 0:
            self.warnings.append(f"{direction.name}: drop-rate decided about {forwarded + random} datagrams, "
                                 f"{direction.datagrams} entered the simulator")
            return None, None
        return random, undecided

    def _decisions(self):
        path = self.directory / "console.log"
        if not path.is_file():
            return None

        counts = {"c2s": Counter(), "s2c": Counter()}
        with open(path, errors="replace") as file:
            for line in file:
                for decision, source_port, destination_port in DECISION.findall(line):
                    if int(destination_port) == QUIC_PORT:
                        counts["c2s"][decision] += 1
                    elif int(source_port) == QUIC_PORT:
                        counts["s2c"][decision] += 1
        return counts if any(counts.values()) else None


LOSS_MODELS = (QueueOnly, DropRate)


class Direction:
    def __init__(self, name, ingress, link, flows):
        self.name = name
        self.ingress = ingress
        self.toward_client = ingress != CLIENT_SIDE
        self.horizon = link.horizon
        self.delay = link.delay
        self.bandwidth = link.bandwidth
        self.flows = flows
        self.pending = {}
        self.order = deque()
        self.long_header = self.dropped = self.unmatched = 0
        self.sizes = array("l")
        self.transit = array("q")
        self.queue_delay = array("q")
        self.egress_bytes = self.egress_wire_bits = 0
        self.egress_first = self.egress_last = None
        self.previous = None
        self.run = 0
        self.burst_lengths = array("l")

    @property
    def datagrams(self):
        return len(self.sizes)

    @property
    def egress(self):
        return len(self.transit)

    def enter(self, time, flow, key, wire, payload, long_header):
        self._expire(time)
        self.long_header += long_header
        self.sizes.append(payload)
        self.pending.setdefault(key, []).append(time)
        if self.horizon is not None:
            self.order.append((time, key))
        self.flows[flow].entered += 1
        if self.bandwidth:
            if self.previous and time - self.previous[0] < self.previous[1] * 8 / self.bandwidth * 1e9 / 2:
                self.run += 1
            else:
                if self.run:
                    self.burst_lengths.append(self.run)
                self.run = 1
            self.previous = (time, wire)

    def leave(self, time, key, wire, payload):
        self._expire(time)
        waiting = self.pending.get(key)
        if not waiting:
            self.unmatched += 1
            return

        entered = waiting.pop(0)
        if not waiting:
            del self.pending[key]
        transit = time - entered
        self.transit.append(transit)
        if self.delay is not None and self.bandwidth:
            queue_delay = transit - round(self.delay * 1e9 + wire * 8 / self.bandwidth * 1e9)
            self.queue_delay.append(queue_delay)
            if self.toward_client:
                self.flows[key[0]].queue_delays.append(queue_delay)
        self.egress_bytes += payload
        self.egress_wire_bits += wire * 8
        if self.egress_first is None:
            self.egress_first = time
        self.egress_last = time

    def finish(self, random, undecided):
        longest = max(self.transit, default=0)
        in_flight = 0
        for key, waiting in self.pending.items():
            flow = self.flows[key[0]]
            for time in waiting:
                if self.egress_last is None or time + longest > self.egress_last:
                    in_flight += 1
                    flow.in_flight += 1
                else:
                    self.dropped += 1
                    flow.dropped += 1
        if undecided is not None and in_flight > undecided:
            self.dropped += in_flight - undecided
            in_flight = undecided
        if self.run:
            self.burst_lengths.append(self.run)

        span = (self.egress_last - self.egress_first) / 1e9 if self.egress > 1 else None
        considered = self.datagrams - in_flight
        return {
            "datagrams": self.datagrams,
            "bytes": sum(self.sizes),
            "long_header_datagrams": self.long_header,
            "dropped": self.dropped,
            "drop_rate": self.dropped / considered if considered else None,
            "dropped_random": random,
            "dropped_queue": self.dropped - random if random is not None else None,
            "in_flight_at_end": in_flight,
            "egress_bps": self.egress_bytes * 8 / span if span else None,
            "utilization": self.egress_wire_bits / (self.bandwidth * span) if self.bandwidth and span else None,
            "transit_s": Sample(value / 1e9 for value in self.transit).describe(),
            "queue_delay_s": Sample(value / 1e9 for value in self.queue_delay).describe(),
            "datagram_bytes": Sample(self.sizes).describe(),
            "burst_datagrams": Sample(self.burst_lengths).describe(),
            "burst_share_10": (sum(n for n in self.burst_lengths if n >= LONG_BURST) / self.datagrams
                               if self.burst_lengths else None),
        }

    def _expire(self, now):
        if self.horizon is None:
            return

        while self.order and self.order[0][0] < now - self.horizon:
            time, key = self.order.popleft()
            waiting = self.pending.get(key)
            if waiting and waiting[0] == time:
                waiting.pop(0)
                if not waiting:
                    del self.pending[key]
                self.dropped += 1
                self.flows[key[0]].dropped += 1


class Flow:
    def __init__(self):
        self.first = self.last = None
        self.entered = self.dropped = self.in_flight = 0
        self.queue_delays = array("q")

    def seen(self, time):
        if self.first is None:
            self.first = time
        self.last = time

    def summary(self):
        considered = self.entered - self.in_flight
        return {
            "drop_rate": self.dropped / considered if considered else None,
            "queue_delay_s": Sample(self.queue_delays).median() / 1e9 if self.queue_delays else None,
            "duration_s": (self.last - self.first) / 1e9 if self.first is not None else None,
        }


class Capture:
    def __init__(self, path, side):
        self.path = path
        self.side = side
        self.ifdrop = None
        self.truncated = False

    def datagrams(self):
        side = self.side
        for time, frame in self._packets():
            if len(frame) < ETHERNET_HEADER:
                continue
            ethertype = SHORT.unpack_from(frame, 12)[0]
            if ethertype == IPV4 and len(frame) >= 34 and frame[23] == UDP:
                source, destination = frame[26:30], frame[30:34]
                ip_length = SHORT.unpack_from(frame, 16)[0]
                udp = ETHERNET_HEADER + (frame[14] & 0x0F) * 4
            elif ethertype == IPV6 and len(frame) >= 54 and frame[20] == UDP:
                source, destination = frame[22:38], frame[38:54]
                ip_length = IPV6_HEADER + SHORT.unpack_from(frame, 18)[0]
                udp = ETHERNET_HEADER + IPV6_HEADER
            else:
                continue
            if len(frame) < udp + UDP_HEADER:
                continue

            source_port, destination_port, udp_length = PORTS.unpack_from(frame, udp)
            if source_port == QUIC_PORT:
                name, flow = "s2c", (destination, destination_port)
            elif destination_port == QUIC_PORT:
                name, flow = "c2s", (source, source_port)
            else:
                continue
            payload, head = udp_length - UDP_HEADER, frame[udp + UDP_HEADER:udp + UDP_HEADER + KEY_PREFIX]
            yield (time, side, name, flow, (flow, payload, hash(head)), ip_length + PPP_HEADER, payload,
                   bool(head) and bool(head[0] & 0x80))

    def _packets(self):
        with open(self.path, "rb") as file, mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as data:
            position, end, resolution = 0, len(data), DEFAULT_RESOLUTION
            while position + 12 <= end:
                block_type, length = BLOCK.unpack_from(data, position)
                if block_type == SECTION_HEADER_BLOCK and data[position + 8:position + 12] != LITTLE_ENDIAN_MAGIC:
                    raise ValueError(f"{self.path}: big-endian pcapng is not supported")
                if length < 12 or position + length > end:
                    self.truncated = True
                    break

                if block_type == ENHANCED_PACKET_BLOCK:
                    _, high, low, captured_length, _ = ENHANCED_PACKET.unpack_from(data, position + 8)
                    yield (((high << 32) | low) * 10 ** 9 // resolution,
                           data[position + 28:position + 28 + min(captured_length, FRAME_HEAD)])
                elif block_type == INTERFACE_DESCRIPTION_BLOCK:
                    link_type = struct.unpack_from("<H", data, position + 8)[0]
                    if link_type != LINKTYPE_ETHERNET:
                        raise ValueError(f"{self.path}: link type {link_type} is not Ethernet")
                    for code, value in self._options(data, position + 16, position + length - 4):
                        if code == IF_TSRESOL:
                            base = 2 if value[0] & 0x80 else 10
                            resolution = base ** (value[0] & 0x7F)
                elif block_type == INTERFACE_STATISTICS_BLOCK:
                    for code, value in self._options(data, position + 20, position + length - 4):
                        if code == ISB_IFDROP and len(value) == 8:
                            self.ifdrop = int.from_bytes(value, "little")
                position += length

    @staticmethod
    def _options(data, position, end):
        while position + 4 <= end:
            code, length = OPTION.unpack_from(data, position)
            if code == OPT_ENDOFOPT:
                return
            yield code, bytes(data[position + 4:position + 4 + length])
            position += 4 + length + (-length % 4)
