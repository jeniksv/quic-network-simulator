"""Measurements of the simulator packet captures of one run (sim/trace_node_{left,right}.pcap).

The simulator captures its client-side interface (eth0, left) and its server-side
interface (eth1, right), so every QUIC datagram appears twice: when it enters the
simulator and when it leaves it. The UDP payload does not change on the way, so a
datagram is matched across the captures by its client address and port, its
length and a hash of the start of its payload. Datagrams that entered but never
left were dropped by the simulator. QUIC is encrypted: the captures show
datagrams, not requests or retransmissions.
"""
from array import array
from collections import Counter, defaultdict, deque
import heapq
import mmap
import re
import struct

from .distribution import describe, median

CAPTURES = {"left": "trace_node_left.pcap", "right": "trace_node_right.pcap"}
# Side where each direction enters the simulator; it leaves it on the other.
DIRECTIONS = {"c2s": "left", "s2c": "right"}
QUIC_PORT = 443
KEY_PREFIX = 64  # payload bytes hashed for matching
FRAME_HEAD = 14 + 40 + 8 + KEY_PREFIX  # Ethernet, IPv6 and UDP headers and the key prefix
PPP_HEADER = 2  # ns-3 PointToPointNetDevice adds a PPP header to every packet on the link
MAX_PACKET = 1500 + PPP_HEADER
BURST = 10  # datagrams of a burst counted in burst_share_10
# Scenarios in which only the queue of the link drops datagrams.
QUEUE_ONLY = {"simple-p2p", "tcp-cross-traffic", "udp-cross-traffic"}
# drop-rate logs its decision about every datagram that passed the queue.
DECISION = re.compile(r"(Dropping|Forwarding) \d+ bytes \S+:(\d+) -> \S+:(\d+)")


def captured(sim_directory):
    return all((sim_directory / name).is_file() for name in CAPTURES.values())


def link(parameters):
    """Scenario name, one-way delay (s), bandwidth (bit/s) and queue size (packets) of the scenario."""
    parameters = parameters or ""
    words = parameters.split()
    delay = re.search(r"--delay=([\d.]+)(ns|us|ms|s)\b", parameters)
    bandwidth = re.search(r"--bandwidth=([\d.]+)([kKMG]?)bps\b", parameters)
    queue = re.search(r"--queue=(\d+)\b", parameters)
    seconds = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1}
    rates = {"": 1, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}
    return (words[0] if words else None,
            float(delay.group(1)) * seconds[delay.group(2)] if delay else None,
            float(bandwidth.group(1)) * rates[bandwidth.group(2)] if bandwidth else None,
            int(queue.group(1)) if queue else None)


def summarize(sim_directory, parameters):
    """Return the summary of the captures of a run and warnings about them."""
    scenario, delay, bandwidth, queue = link(parameters)
    warnings = []
    # A datagram still in the simulator after the longest possible transit was dropped;
    # without the link parameters every unmatched datagram is classified at the end.
    horizon = None
    if delay is not None and bandwidth and queue is not None:
        horizon = round((2 * (delay + queue * MAX_PACKET * 8 / bandwidth) + 1) * 1e9)
    flows = defaultdict(_Flow)
    directions = {name: _Direction(name, ingress, horizon, delay, bandwidth, flows)
                  for name, ingress in DIRECTIONS.items()}
    infos = {side: {} for side in CAPTURES}
    streams = [_datagrams(_read(sim_directory / name, infos[side]), side) for side, name in CAPTURES.items()]
    for time, side, name, flow, key, wire, payload, long_header in heapq.merge(*streams):
        direction = directions[name]
        if side == direction.ingress_side:
            direction.enter(time, flow, key, wire, payload, long_header)
        else:
            direction.leave(time, key, wire, payload)
        if side == "left":  # the client side
            flows[flow].seen(time)

    for name, direction in directions.items():
        if direction.unmatched:
            warnings.append(f"{name}: {direction.unmatched} datagrams left the simulator without entering it")

    # Causes of the drops.
    decisions = None
    if scenario == "drop-rate":
        decisions = _decisions(sim_directory / "console.log")
        if decisions is None:
            warnings.append("console.log has no decisions of drop-rate")
    summary = {}
    for name, direction in directions.items():
        random = undecided = None
        if scenario in QUEUE_ONLY:
            random = 0
        elif decisions is not None:
            random, forwarded = decisions[name]["Dropping"], decisions[name]["Forwarding"]
            if forwarded != direction.egress:
                warnings.append(f"{name}: drop-rate forwarded {forwarded} datagrams, "
                                f"{direction.egress} left the simulator")
            # drop-rate decides about every datagram that passed the queue, also about those
            # dropped shortly before the end, which the captures alone count as in flight.
            undecided = direction.datagrams - forwarded - random
            if undecided < 0:
                warnings.append(f"{name}: drop-rate decided about {forwarded + random} datagrams, "
                                f"{direction.datagrams} entered the simulator")
                random = undecided = None
        summary[name] = values = direction.finish(random, undecided)
        if values["dropped_queue"] is not None and values["dropped_queue"] < 0:
            warnings.append(f"{name}: drop-rate dropped {random} datagrams, the captures show {values['dropped']}")

    summary["connections"] = len(flows)
    summary["conn"] = {
        key: describe([value for value in map(method, flows.values()) if value is not None])
        for key, method in (("drop_rate", _Flow.drop_rate), ("queue_delay_s", _Flow.queue_delay),
                            ("duration_s", _Flow.duration))
    }

    for side, info in infos.items():
        if info["truncated"]:
            warnings.append(f"{side} capture is truncated")
        if info["ifdrop"]:
            warnings.append(f"{side} capture dropped {info['ifdrop']} packets")
    return summary, warnings


class _Direction:
    """Datagrams of one direction, matched from the side where they enter the simulator to the other."""

    def __init__(self, name, ingress_side, horizon, delay, bandwidth, flows):
        self.name = name
        self.ingress_side = ingress_side
        self.horizon = horizon
        self.delay = delay
        self.bandwidth = bandwidth
        self.flows = flows  # client address and port -> _Flow, shared by both directions
        self.pending = {}  # key -> times (ns) the datagrams in the simulator entered, oldest first
        self.order = deque()  # (time, key) of entered datagrams, oldest first
        self.datagrams = self.bytes = self.long_header = self.dropped = self.unmatched = 0
        self.sizes = array("l")
        self.transit = array("q")  # ns
        self.queue_delay = array("q")  # ns
        self.egress = self.egress_bytes = self.egress_wire_bits = 0
        self.egress_first = self.egress_last = None
        self.previous = None  # (time, wire) of the previous entered datagram, for bursts
        self.run = 0
        self.burst_lengths = array("l")

    def enter(self, time, flow, key, wire, payload, long_header):
        self._expire(time)
        self.datagrams += 1
        self.bytes += payload
        self.long_header += long_header
        self.sizes.append(payload)
        self.pending.setdefault(key, []).append(time)
        if self.horizon is not None:
            self.order.append((time, key))
        self.flows[flow].entered += 1
        if self.bandwidth:
            # Datagrams of all flows meet in one queue; one burst while they come faster
            # than half of the time the link needs to transmit the previous one.
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
            if self.name == "s2c":
                self.flows[key[0]].queue_delays.append(queue_delay)
        self.egress += 1
        self.egress_bytes += payload
        self.egress_wire_bits += wire * 8
        if self.egress_first is None:
            self.egress_first = time
        self.egress_last = time

    def _expire(self, now):
        """Count the datagrams that stayed in the simulator longer than the horizon as dropped."""
        if self.horizon is None:
            return
        while self.order and self.order[0][0] < now - self.horizon:
            time, key = self.order.popleft()
            waiting = self.pending.get(key)
            if waiting and waiting[0] == time:  # otherwise it already left
                waiting.pop(0)
                if not waiting:
                    del self.pending[key]
                self.dropped += 1
                self.flows[key[0]].dropped += 1

    def finish(self, random=None, undecided=None):
        """Classify the datagrams left in the simulator and return the summary of the direction.

        random is the number of datagrams that the loss model of the scenario dropped, undecided
        the number it did not decide about, so at most that many were in flight; None if unknown.
        """
        # A datagram that entered shortly before the last one of its direction left
        # may still have been in flight when the simulator stopped.
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
        if undecided is not None and in_flight > undecided:  # the connections keep the classification above
            self.dropped += in_flight - undecided
            in_flight = undecided
        if self.run:
            self.burst_lengths.append(self.run)
        span = (self.egress_last - self.egress_first) / 1e9 if self.egress > 1 else None  # s
        considered = self.datagrams - in_flight
        return {
            "datagrams": self.datagrams,
            "bytes": self.bytes,
            "long_header_datagrams": self.long_header,
            "dropped": self.dropped,
            "drop_rate": self.dropped / considered if considered else None,
            "dropped_random": random,
            "dropped_queue": self.dropped - random if random is not None else None,
            "in_flight_at_end": in_flight,
            "egress_datagrams": self.egress,
            "egress_bps": self.egress_bytes * 8 / span if span else None,
            "utilization": self.egress_wire_bits / (self.bandwidth * span) if self.bandwidth and span else None,
            "transit_s": describe([value / 1e9 for value in self.transit]),
            "queue_delay_s": describe([value / 1e9 for value in self.queue_delay]),
            "datagram_bytes": describe(self.sizes),
            "burst_datagrams": describe(self.burst_lengths),
            "burst_share_10": (sum(n for n in self.burst_lengths if n >= BURST) / self.datagrams
                               if self.burst_lengths else None),
        }


class _Flow:
    """One connection, identified by the address and port of the client; times seen on the client side."""

    def __init__(self):
        self.first = self.last = None
        self.entered = self.dropped = self.in_flight = 0
        self.queue_delays = array("q")  # ns, toward the client

    def seen(self, time):
        if self.first is None:
            self.first = time
        self.last = time

    def drop_rate(self):
        considered = self.entered - self.in_flight
        return self.dropped / considered if considered else None

    def queue_delay(self):
        """Median queue delay toward the client (s)."""
        return median(sorted(self.queue_delays)) / 1e9 if self.queue_delays else None

    def duration(self):
        return (self.last - self.first) / 1e9 if self.first is not None else None


def _decisions(path):
    """Datagrams that drop-rate dropped and forwarded, per direction; None without its log."""
    if not path.is_file():
        return None
    counts = {"c2s": Counter(), "s2c": Counter()}
    with open(path, errors="replace") as file:
        for line in file:
            # dumpcap writes its progress into the same lines.
            for decision, source_port, destination_port in DECISION.findall(line):
                if int(destination_port) == QUIC_PORT:
                    counts["c2s"][decision] += 1
                elif int(source_port) == QUIC_PORT:
                    counts["s2c"][decision] += 1
    return counts if any(counts.values()) else None


def _read(path, info):
    """Yield (time in ns, start of the frame) of every packet of a pcapng file; fill the capture info."""
    info.update({"ifdrop": None, "truncated": False})
    with open(path, "rb") as file, mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as data:
        position, end, nanoseconds = 0, len(data), _nanoseconds(6)
        while position + 12 <= end:
            block_type, length = struct.unpack_from("<II", data, position)
            if block_type == 0x0A0D0D0A and data[position + 8:position + 12] != b"\x4d\x3c\x2b\x1a":
                raise ValueError(f"{path}: big-endian pcapng is not supported")
            if length < 12 or position + length > end:
                info["truncated"] = True
                break
            if block_type == 6:  # Enhanced Packet Block
                _, high, low, captured_length, _ = struct.unpack_from("<IIIII", data, position + 8)
                yield (nanoseconds((high << 32) | low),
                       data[position + 28:position + 28 + min(captured_length, FRAME_HEAD)])
            elif block_type == 1:  # Interface Description Block
                link_type = struct.unpack_from("<H", data, position + 8)[0]
                if link_type != 1:
                    raise ValueError(f"{path}: link type {link_type} is not Ethernet")
                for code, value in _options(data, position + 16, position + length - 4):
                    if code == 9:  # if_tsresol
                        nanoseconds = _nanoseconds(value[0])
            elif block_type == 5:  # Interface Statistics Block
                for code, value in _options(data, position + 20, position + length - 4):
                    if code == 5 and len(value) == 8:  # isb_ifdrop
                        info["ifdrop"] = struct.unpack("<Q", value)[0]
            position += length


def _nanoseconds(tsresol):
    """Conversion of timestamps of the if_tsresol resolution to integer nanoseconds."""
    exponent = tsresol & 0x7F
    if tsresol & 0x80:  # 2^-exponent s
        return lambda ticks: ticks * 10 ** 9 >> exponent
    if exponent <= 9:  # 10^-exponent s
        factor = 10 ** (9 - exponent)
        return lambda ticks: ticks * factor
    divisor = 10 ** (exponent - 9)
    return lambda ticks: ticks // divisor


def _options(data, position, end):
    while position + 4 <= end:
        code, length = struct.unpack_from("<HH", data, position)
        if code == 0:
            return
        yield code, bytes(data[position + 4:position + 4 + length])
        position += 4 + length + (-length % 4)


def _datagrams(packets, side):
    """Yield (time, side, direction, flow, key, wire, payload, long header) of the QUIC datagrams of a capture.

    The packets are Ethernet frames; wire is the length of the packet on the simulated link,
    payload the length of the UDP payload.
    """
    for time, frame in packets:
        if len(frame) < 14:
            continue
        ethertype = struct.unpack_from("!H", frame, 12)[0]
        if ethertype == 0x0800 and len(frame) >= 34 and frame[23] == 17:
            source, destination = frame[26:30], frame[30:34]
            ip_length = struct.unpack_from("!H", frame, 16)[0]
            udp = 14 + (frame[14] & 0x0F) * 4
        elif ethertype == 0x86DD and len(frame) >= 54 and frame[20] == 17:  # no extension headers here
            source, destination = frame[22:38], frame[38:54]
            ip_length = 40 + struct.unpack_from("!H", frame, 18)[0]
            udp = 54
        else:
            continue
        if len(frame) < udp + 8:
            continue
        source_port, destination_port, udp_length = struct.unpack_from("!HHH", frame, udp)
        if source_port == QUIC_PORT:
            name, flow = "s2c", (destination, destination_port)
        elif destination_port == QUIC_PORT:
            name, flow = "c2s", (source, source_port)
        else:
            continue
        payload, head = udp_length - 8, frame[udp + 8:udp + 8 + KEY_PREFIX]
        yield (time, side, name, flow, (flow, payload, hash(head)), ip_length + PPP_HEADER, payload,
               bool(head) and bool(head[0] & 0x80))
