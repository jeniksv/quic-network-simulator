class Unit:
    def __init__(self, name):
        self.name = name

    def format(self, value):
        return f"{value:.4g}"


class Count(Unit):
    def format(self, value):
        return f"{value:.0f}" if float(value).is_integer() else f"{value:.1f}"


class Seconds(Unit):
    def format(self, value):
        return f"{value * 1e3:.1f} ms" if abs(value) < 10 else f"{value:.2f} s"


class BitRate(Unit):
    def format(self, value):
        return f"{value / 1e6:.2f} Mbit/s"


class ByteRate(Unit):
    def format(self, value):
        return f"{value / 1e6:.2f} MB/s"


class Rate(Unit):
    def format(self, value):
        return f"{value:.2f}/s"


RATIO = Unit("")
SECONDS = Seconds("s")
BIT_RATE = BitRate("bit/s")
BYTE_RATE = ByteRate("B/s")
RATE = Rate("1/s")
BYTES = Count("bytes")
CLIENTS = Count("clients")
DATAGRAMS = Count("datagrams")
PACKETS = Count("packets")
REQUESTS = Count("requests")
RESPONSES = Count("responses")
