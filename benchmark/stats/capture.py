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
from collections import defaultdict, deque
import heapq
import mmap
import re
import struct

from .distribution import describe

CAPTURES = {"left": "trace_node_left.pcap", "right": "trace_node_right.pcap"}
# Each direction enters the simulator on one side and leaves it on the other.
DIRECTIONS = {"c2s": ("left", "right"), "s2c": ("right", "left")}
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
ISB_OPTIONS = {4: "ifrecv", 5: "ifdrop"}


def captured(sim_directory):
    return all((sim_directory / name).is_file() for name in CAPTURES.values())


def link(parameters):
    """Scenario name, one-way delay (s), bandwidth (bit/s) and queue size (packets) of the scenario."""
    parameters = parameters or ""
    delay = re.search(r"--delay=([\d.]+)(ns|us|ms|s)\b", parameters)
    bandwidth = re.search(r"--bandwidth=([\d.]+)([kKMG]?)bps\b", parameters)
    queue = re.search(r"--queue=(\d+)\b", parameters)
    seconds = {"ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1}
    rates = {"": 1, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}
    return {
        "scenario": parameters.split()[0] if parameters.split() else None,
        "delay_s": float(delay.group(1)) * seconds[delay.group(2)] if delay else None,
        "bandwidth_bps": float(bandwidth.group(1)) * rates[bandwidth.group(2)] if bandwidth else None,
        "queue_packets": int(queue.group(1)) if queue else None,
    }


def summarize(sim_directory, parameters):
    """Return the summary of the captures of a run and warnings about them."""
    scenario = link(parameters)
    delay, bandwidth = scenario["delay_s"], scenario["bandwidth_bps"]
    warnings = []
    # A datagram still in the simulator after the longest possible transit was dropped;
    # without the link parameters every unmatched datagram is classified at the end.
    horizon = None
    if delay is not None and bandwidth and scenario["queue_packets"] is not None:
        horizon = round((2 * (delay + scenario["queue_packets"] * MAX_PACKET * 8 / bandwidth) + 1) * 1e9)
    directions = {name: _Direction(name, ingress, horizon, delay, bandwidth)
                  for name, (ingress, _) in DIRECTIONS.items()}
    flows = defaultdict(_Flow)
    infos = {side: {} for side in CAPTURES}
    streams = [_datagrams(_read(sim_directory / name, infos[side]), side) for side, name in CAPTURES.items()]
    for time, side, name, flow, key, wire, payload, long_header in heapq.merge(*streams):
        direction = directions[name]
        if side == direction.ingress_side:
            direction.enter(time, flow, key, wire, payload, long_header, flows)
        else:
            direction.leave(time, key, wire, payload, flows)
        if side == "left":  # the client side
            flows[flow].seen(time)

    summary = {name: direction.finish(flows) for name, direction in directions.items()}
    for name, direction in directions.items():
        if direction.unmatched:
            warnings.append(f"{name}: {direction.unmatched} datagrams left the simulator without entering it")

    # Causes of the drops.
    decisions = None
    if scenario["scenario"] == "drop-rate":
        decisions = _decisions(sim_directory / "console.log")
        if decisions is None:
            warnings.append("console.log has no decisions of drop-rate")
    for name, values in summary.items():
        random = None
        if scenario["scenario"] in QUEUE_ONLY:
            random = 0
        elif decisions is not None:
            random, forwarded = decisions[name]["Dropping"], decisions[name]["Forwarding"]
            if forwarded != values["egress_datagrams"]:
                warnings.append(f"{name}: drop-rate forwarded {forwarded} datagrams, "
                                f"{values['egress_datagrams']} left the simulator")
            # drop-rate decides about every datagram that passed the queue, also about those
            # dropped shortly before the end, which the captures alone count as in flight.
            undecided = values["datagrams"] - forwarded - random
            if undecided < 0:
                warnings.append(f"{name}: drop-rate decided about {forwarded + random} datagrams, "
                                f"{values['datagrams']} entered the simulator")
                random = None
            elif values["in_flight_at_end"] > undecided:  # the connections keep the classification of the captures
                values["in_flight_at_end"] = undecided
                values["dropped"] = values["datagrams"] - values["egress_datagrams"] - undecided
                considered = values["datagrams"] - undecided
                values["drop_rate"] = values["dropped"] / considered if considered else None
        values["dropped_random"] = random
        values["dropped_queue"] = values["dropped"] - random if random is not None else None
        if values["dropped_queue"] is not None and values["dropped_queue"] < 0:
            warnings.append(f"{name}: drop-rate dropped {random} datagrams, the captures show {values['dropped']}")

    summary["s2c"]["utilization"] = None
    if bandwidth and directions["s2c"].egress_span:
        summary["s2c"]["utilization"] = directions["s2c"].egress_wire_bits / (bandwidth * directions["s2c"].egress_span)
    summary["s2c"].update(directions["s2c"].bursts())
    summary["connections"] = len(flows)
    summary["conn"] = {
        "drop_rate": describe([rate for flow in flows.values() if (rate := flow.drop_rate()) is not None]),
        "queue_delay_s": describe([delay for flow in flows.values() if (delay := flow.queue_delay()) is not None]),
        "duration_s": describe([duration for flow in flows.values() if (duration := flow.duration()) is not None]),
    }

    for side, info in infos.items():
        if info["truncated"]:
            warnings.append(f"{side} capture is truncated")
        if info["ifdrop"]:
            warnings.append(f"{side} capture dropped {info['ifdrop']} packets")
    return summary, warnings


class _Direction:
    """Datagrams of one direction, matched from the side where they enter the simulator to the other."""

    def __init__(self, name, ingress_side, horizon, delay, bandwidth):
        self.name = name
        self.ingress_side = ingress_side
        self.horizon = horizon
        self.delay = delay
        self.bandwidth = bandwidth
        self.pending = {}  # key -> deque of (time, flow, wire) of datagrams in the simulator
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

    def enter(self, time, flow, key, wire, payload, long_header, flows):
        self._expire(time, flows)
        self.datagrams += 1
        self.bytes += payload
        self.long_header += long_header
        self.sizes.append(payload)
        self.pending.setdefault(key, deque()).append((time, flow, wire))
        if self.horizon is not None:
            self.order.append((time, key))
        flows[flow].entered += 1
        if self.bandwidth and self.name == "s2c":
            # Datagrams of all flows meet in one queue; one burst while they come faster
            # than half of the time the link needs to transmit the previous one.
            if self.previous and time - self.previous[0] < self.previous[1] * 8 / self.bandwidth * 1e9 / 2:
                self.run += 1
            else:
                if self.run:
                    self.burst_lengths.append(self.run)
                self.run = 1
            self.previous = (time, wire)

    def leave(self, time, key, wire, payload, flows):
        self._expire(time, flows)
        waiting = self.pending.get(key)
        if not waiting:
            self.unmatched += 1
            return
        entered, flow, _ = waiting.popleft()
        if not waiting:
            del self.pending[key]
        transit = time - entered
        self.transit.append(transit)
        if self.delay is not None and self.bandwidth:
            queue_delay = transit - round(self.delay * 1e9 + wire * 8 / self.bandwidth * 1e9)
            self.queue_delay.append(queue_delay)
            if self.name == "s2c":
                flows[flow].queue_delays.append(queue_delay)
        self.egress += 1
        self.egress_bytes += payload
        self.egress_wire_bits += wire * 8
        if self.egress_first is None:
            self.egress_first = time
        self.egress_last = time

    def _expire(self, now, flows):
        """Count the datagrams that stayed in the simulator longer than the horizon as dropped."""
        if self.horizon is None:
            return
        while self.order and self.order[0][0] < now - self.horizon:
            time, key = self.order.popleft()
            waiting = self.pending.get(key)
            if waiting and waiting[0][0] == time:  # otherwise it already left
                _, flow, _ = waiting.popleft()
                if not waiting:
                    del self.pending[key]
                self.dropped += 1
                flows[flow].dropped += 1

    def finish(self, flows):
        """Classify the datagrams left in the simulator and return the summary of the direction."""
        # A datagram that entered shortly before the last one of its direction left
        # may still have been in flight when the simulator stopped.
        longest = max(self.transit, default=0)
        in_flight = 0
        for waiting in self.pending.values():
            for time, flow, _ in waiting:
                if self.egress_last is None or time + longest > self.egress_last:
                    in_flight += 1
                    flows[flow].in_flight += 1
                else:
                    self.dropped += 1
                    flows[flow].dropped += 1
        if self.run:
            self.burst_lengths.append(self.run)
            self.run = 0
        considered = self.datagrams - in_flight
        return {
            "datagrams": self.datagrams,
            "bytes": self.bytes,
            "long_header_datagrams": self.long_header,
            "dropped": self.dropped,
            "drop_rate": self.dropped / considered if considered else None,
            "in_flight_at_end": in_flight,
            "egress_datagrams": self.egress,
            "egress_bps": self.egress_bytes * 8 / self.egress_span if self.egress_span else None,
            "transit_s": describe([value / 1e9 for value in self.transit]),
            "queue_delay_s": describe([value / 1e9 for value in self.queue_delay]),
            "datagram_bytes": describe(self.sizes),
        }

    @property
    def egress_span(self):
        """Seconds from the first to the last datagram that left the simulator."""
        return (self.egress_last - self.egress_first) / 1e9 if self.egress > 1 else None

    def bursts(self):
        if not self.burst_lengths:
            return {"burst_datagrams": None, "burst_share_10": None}
        return {"burst_datagrams": describe(self.burst_lengths),
                "burst_share_10": sum(n for n in self.burst_lengths if n >= BURST) / self.datagrams}


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
        if not self.queue_delays:
            return None
        ordered = sorted(self.queue_delays)
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
        return median / 1e9

    def duration(self):
        return (self.last - self.first) / 1e9 if self.first is not None else None


def _decisions(path):
    """Datagrams that drop-rate dropped and forwarded, per direction; None without its log."""
    counts = {"c2s": {"Dropping": 0, "Forwarding": 0}, "s2c": {"Dropping": 0, "Forwarding": 0}}
    if not path.is_file():
        return None
    with open(path, errors="replace") as file:
        for line in file:
            # dumpcap writes its progress into the same lines.
            for decision, source_port, destination_port in DECISION.findall(line):
                if int(destination_port) == QUIC_PORT:
                    counts["c2s"][decision] += 1
                elif int(source_port) == QUIC_PORT:
                    counts["s2c"][decision] += 1
    return counts if any(sum(direction.values()) for direction in counts.values()) else None


def _read(path, info):
    """Yield (time in ns, start of the frame) of every packet of a pcapng file; fill the capture info."""
    info.update({"packets": 0, "ifrecv": None, "ifdrop": None, "truncated": False})
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
                info["packets"] += 1
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
                    if code in ISB_OPTIONS and len(value) == 8:
                        info[ISB_OPTIONS[code]] = struct.unpack("<Q", value)[0]
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

    wire is the length of the packet on the simulated link, payload the length of the UDP payload.
    """
    for time, frame in packets:
        udp = _udp(frame)
        if udp is None:
            continue
        source, destination, source_port, destination_port, ip_length, payload, head = udp
        if source_port == QUIC_PORT:
            name, flow = "s2c", (destination, destination_port)
        elif destination_port == QUIC_PORT:
            name, flow = "c2s", (source, source_port)
        else:
            continue
        yield (time, side, name, flow, (flow, payload, hash(head)), ip_length + PPP_HEADER, payload,
               bool(head) and bool(head[0] & 0x80))


def _udp(frame):
    """Return the addresses, ports, lengths and payload start of an Ethernet UDP frame."""
    if len(frame) < 14:
        return None
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
        return None
    if len(frame) < udp + 8:
        return None
    source_port, destination_port, udp_length = struct.unpack_from("!HHH", frame, udp)
    return (source, destination, source_port, destination_port, ip_length, udp_length - 8,
            frame[udp + 8:udp + 8 + KEY_PREFIX])
