from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = ".paratranz-sync.yml"


def parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [parse_scalar(part) for part in inner.split(",")]
    try:
        return int(value)
    except ValueError:
        pass
    return value


def parse_simple_yaml(text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    current_section: str | None = None
    current_item: dict[str, Any] | None = None

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        if indent == 0:
            if not stripped.endswith(":"):
                raise ValueError(f"Invalid top-level YAML line {lineno}: {raw_line}")
            current_section = stripped[:-1]
            current_item = None
            if current_section == "projects":
                payload[current_section] = []
            else:
                payload[current_section] = {}
            continue

        if current_section is None:
            raise ValueError(f"Unexpected indentation before a section at line {lineno}.")

        if current_section == "release":
            if indent != 2 or ":" not in stripped:
                raise ValueError(f"Invalid release entry at line {lineno}: {raw_line}")
            key, value = stripped.split(":", 1)
            payload["release"][key.strip()] = parse_scalar(value)
            continue

        if current_section == "projects":
            if indent == 2 and stripped.startswith("- "):
                item_content = stripped[2:].strip()
                current_item = {}
                payload["projects"].append(current_item)
                if item_content:
                    if ":" not in item_content:
                        raise ValueError(f"Invalid project entry at line {lineno}: {raw_line}")
                    key, value = item_content.split(":", 1)
                    current_item[key.strip()] = parse_scalar(value)
                continue

            if indent == 4 and current_item is not None and ":" in stripped:
                key, value = stripped.split(":", 1)
                current_item[key.strip()] = parse_scalar(value)
                continue

            raise ValueError(f"Invalid projects entry at line {lineno}: {raw_line}")

        raise ValueError(f"Unsupported section '{current_section}' at line {lineno}.")

    return payload


def load_project_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config_path = Path(path)
    payload = parse_simple_yaml(config_path.read_text(encoding="utf-8"))

    release = payload.get("release")
    projects = payload.get("projects")
    if not isinstance(release, dict):
        raise ValueError("Project config is missing a release section.")
    if not isinstance(projects, list) or not projects:
        raise ValueError("Project config must define at least one project.")

    product = release.get("product")
    primary_project_id = release.get("primary_project_id")
    current_version = release.get("current_version")
    if not isinstance(product, str) or not product.strip():
        raise ValueError("release.product must be a non-empty string.")
    if not isinstance(primary_project_id, int):
        raise ValueError("release.primary_project_id must be an integer.")
    if current_version is not None and (not isinstance(current_version, str) or not current_version.strip()):
        raise ValueError("release.current_version must be a non-empty string when present.")

    normalized_projects: list[dict[str, Any]] = []
    seen_locales: set[str] = set()
    for index, item in enumerate(projects):
        if not isinstance(item, dict):
            raise ValueError(f"projects[{index}] must be an object.")
        locale = item.get("locale")
        project_id = item.get("project_id")
        min_stage = item.get("min_stage", 1)
        allowed_stages = item.get("allowed_stages")
        if not isinstance(locale, str) or not locale.strip():
            raise ValueError(f"projects[{index}].locale must be a non-empty string.")
        if not isinstance(project_id, int):
            raise ValueError(f"projects[{index}].project_id must be an integer.")
        if allowed_stages is not None:
            if not isinstance(allowed_stages, list) or not allowed_stages:
                raise ValueError(f"projects[{index}].allowed_stages must be a non-empty list of integers.")
            if not all(isinstance(stage, int) for stage in allowed_stages):
                raise ValueError(f"projects[{index}].allowed_stages must contain only integers.")
        elif not isinstance(min_stage, int):
            raise ValueError(f"projects[{index}].min_stage must be an integer.")
        normalized_locale = locale.strip()
        if normalized_locale in seen_locales:
            raise ValueError(f"Duplicate locale in config: {normalized_locale}")
        seen_locales.add(normalized_locale)
        normalized_item = {
            "locale": normalized_locale,
            "project_id": project_id,
            "artifact_label": item.get("artifact_label", normalized_locale),
        }
        if allowed_stages is not None:
            normalized_item["allowed_stages"] = [int(stage) for stage in allowed_stages]
        else:
            normalized_item["min_stage"] = min_stage
        normalized_projects.append(normalized_item)

    return {
        "release": {
            "product": product.strip(),
            "primary_project_id": primary_project_id,
            "current_version": current_version.strip() if isinstance(current_version, str) else None,
        },
        "projects": normalized_projects,
    }


def get_release_product(config: dict[str, Any]) -> str:
    return str(config["release"]["product"])


def get_primary_project_id(config: dict[str, Any]) -> int:
    return int(config["release"]["primary_project_id"])


def get_current_version(config: dict[str, Any]) -> str | None:
    value = config["release"].get("current_version")
    return str(value) if isinstance(value, str) and value else None


def set_current_version(config: dict[str, Any], version: str) -> None:
    normalized_version = str(version).strip()
    if not normalized_version:
        raise ValueError("current version must be a non-empty string.")
    config["release"]["current_version"] = normalized_version


def build_release_line(product: str, version: str) -> str:
    return f"{str(product).strip()}-{str(version).strip()}"


def get_configured_locales(config: dict[str, Any]) -> list[str]:
    return [str(item["locale"]) for item in config["projects"]]


def get_configured_project_ids(config: dict[str, Any]) -> list[int]:
    return [int(item["project_id"]) for item in config["projects"]]


def get_project_entries(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(item) for item in config["projects"]]


def dump_project_config(config: dict[str, Any]) -> str:
    release = config["release"]
    lines = [
        "release:",
        f"  product: {release['product']}",
        f"  primary_project_id: {release['primary_project_id']}",
    ]
    current_version = release.get("current_version")
    if isinstance(current_version, str) and current_version:
        lines.append(f"  current_version: {current_version}")

    lines.extend(["", "projects:"])
    for item in config["projects"]:
        lines.append(f"  - locale: {item['locale']}")
        lines.append(f"    project_id: {item['project_id']}")
        allowed_stages = item.get("allowed_stages")
        if isinstance(allowed_stages, list) and allowed_stages:
            rendered = ", ".join(str(stage) for stage in allowed_stages)
            lines.append(f"    allowed_stages: [{rendered}]")
        else:
            lines.append(f"    min_stage: {item.get('min_stage', 1)}")
        artifact_label = item.get("artifact_label")
        if isinstance(artifact_label, str) and artifact_label and artifact_label != item["locale"]:
            lines.append(f"    artifact_label: {artifact_label}")

    return "\n".join(lines) + "\n"


def write_project_config(path: str | Path, config: dict[str, Any]) -> None:
    Path(path).write_text(dump_project_config(config), encoding="utf-8")
