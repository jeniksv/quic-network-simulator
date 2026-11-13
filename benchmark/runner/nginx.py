from pathlib import Path
import re

from .directives import DIRECTIVE_TYPES

TEMPLATE = Path(__file__).resolve().parents[1] / "conf/nginx.conf.template"


class NginxConf:
    def __init__(self, name, config):
        self.name = name
        self.directives = dict()

        for directive_type in DIRECTIVE_TYPES:
            value = config.get(directive_type.name, directive_type.default)
            if value is not None:
                self.directives[directive_type.placeholder()] = directive_type(value).render()
            elif directive_type.optional:
                self.directives[directive_type.placeholder()] = ""
            else:
                raise ValueError(f"{name}: missing required directive {directive_type.name}")

    def render(self):
        text = TEMPLATE.read_text()

        for placeholder, value in self.directives.items():
            if value and placeholder not in text:
                raise ValueError(f"Missing placeholder in nginx.conf.template: {placeholder}")
            text = text.replace(placeholder, value)

        unknown = re.search(r"__[A-Z][A-Z0-9_]*__", text)
        if unknown:
            raise ValueError(f"Unknown placeholder in nginx.conf.template: {unknown.group()}")

        return text

    def write(self, path):
        Path(path).write_text(self.render())
