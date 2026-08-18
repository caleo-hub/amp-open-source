from __future__ import annotations

import argparse
import re
from pathlib import Path

KINDS = {
    "service": ("python-service", "services", "service"),
    "agent": ("langgraph-agent", "agents", "agent"),
}


def valid_slug(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", value):
        raise argparse.ArgumentTypeError("use lowercase kebab-case, for example billing-api")
    return value


def render(template: str, slug: str) -> str:
    display_name = " ".join(part.capitalize() for part in slug.split("-"))
    return template.replace("{{SLUG}}", slug).replace("{{DISPLAY_NAME}}", display_name)


def scaffold(kind: str, slug: str, root: Path) -> Path:
    template_name, parent, suffix = KINDS[kind]
    destination = root / parent / f"{slug}-{suffix}"
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")

    module = f"amp_{slug.replace('-', '_')}_{suffix}"
    source = root / "templates" / template_name
    for template_path in source.rglob("*.tmpl"):
        relative = template_path.relative_to(source)
        output_name = relative.name.removesuffix(".tmpl")
        if output_name in {"main.py", "graph.py"}:
            output = destination / "src" / module / output_name
        else:
            output = destination / relative.with_name(output_name)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render(template_path.read_text(encoding="utf-8"), slug), encoding="utf-8")

    init_file = destination / "src" / module / "__init__.py"
    init_file.write_text("", encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an AMP component from a template")
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument("name", type=valid_slug)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(scaffold(args.kind, args.name, args.root.resolve()))


if __name__ == "__main__":
    main()
