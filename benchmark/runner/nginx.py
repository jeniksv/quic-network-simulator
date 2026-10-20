from pathlib import Path
import re


class NginxConf:
    def __init__(self, name, directives):
        self.name = name
        self.directives = directives

    def render(self):
        template = Path(__file__).resolve().parents[1] / "conf/nginx.conf.template"
        text = template.read_text()

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
