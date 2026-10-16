from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class NginxDirective:
    name: str
    value: str

    def __post_init__(self):
        self.validate()

    def validate(self):
        patterns = {
            "listen": r"(?:443|\[::\]:443) quic=(?:nginx|quiche) reuseport",
            "quic_congestion_control": r"(?:cubic|reno|bbr|bbr2)",
        }
        if self.name not in patterns:
            raise ValueError(f"Unsupported benchmark NGINX directive: {self.name}")
        if not isinstance(self.value, str) or not re.fullmatch(patterns[self.name], self.value):
            raise ValueError(f"Invalid value for NGINX directive {self.name}: {self.value!r}")

    def __str__(self) -> str:
        return f"{self.name} {self.value};"


@dataclass(frozen=True)
class NginxConfig:
    directives: tuple[NginxDirective, ...]
    server_params = "-c /logs/nginx.conf"

    def render(self, template: str) -> str:
        values = {}
        for directive in self.directives:
            directive.validate()
            values.setdefault(directive.name.upper(), []).append(directive)
        for name, directives in values.items():
            if name != "LISTEN" and len(directives) != 1:
                raise ValueError(f"Duplicate NGINX directive: {name.lower()}")

        pattern = re.compile(r"^([ \t]*)__([A-Z_]+)__[ \t]*$", re.MULTILINE)
        placeholders = {match[2] for match in pattern.finditer(template)}
        if placeholders != values.keys():
            raise ValueError("NGINX template placeholders do not match configured directives: "
                             + ", ".join(sorted(placeholders ^ values.keys())))

        config = pattern.sub(lambda match: "\n".join(
            f"{match[1]}{directive}" for directive in values[match[2]]), template)
        if re.search(r"__[A-Z_]+__", config):
            raise ValueError("NGINX directive placeholders must occupy a whole line")
        return config

    def write(self, template: str, directory: Path):
        (directory / "server/nginx.conf").write_text(self.render(template))
