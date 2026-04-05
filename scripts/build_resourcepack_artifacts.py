import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Iterable

from project_config import DEFAULT_CONFIG_PATH, get_configured_locales, load_project_config

RESOURCEPACK_NAME_PREFIX = "gto-lang"
ARTIFACT_METADATA_FILE_NAME = "gto-artifact-metadata.json"
DEFAULT_COMBINED_LABEL = "all-locales"
PROGRESS_METADATA_FILE_NAME = ".gto-progress.json"
MODULE_DISPLAY_NAMES = {
    "gtocore": "GTOCore",
    "gtodyssey": "GTOdyssey",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage per-locale and combined resource-pack artifacts from generated translation directories.",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root containing locale directories.",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"YAML config path. Defaults to {DEFAULT_CONFIG_PATH}.",
    )
    parser.add_argument(
        "--output-dir",
        default="dist/artifacts",
        help="Directory where staged artifact folders are written.",
    )
    parser.add_argument(
        "--locales",
        help="Optional comma-separated locale directories to package. Defaults to locales from config.",
    )
    parser.add_argument(
        "--artifact-version",
        help="Optional immutable version identifier written into each staged artifact.",
    )
    parser.add_argument(
        "--release-line",
        help="Optional compatibility line such as gto-0.5.4.",
    )
    parser.add_argument(
        "--source-revision",
        help="Optional source revision, usually the Git commit SHA.",
    )
    parser.add_argument(
        "--built-at",
        help="Optional build timestamp to embed in artifact metadata.",
    )
    return parser.parse_args()


def parse_locales(raw: str) -> list[str]:
    locales = [part.strip() for part in str(raw).split(",") if part.strip()]
    if not locales:
        raise ValueError("At least one locale is required.")
    return locales


def get_resourcepack_root(repo_root: Path, locale: str) -> Path:
    return repo_root / locale / "resourcepacks" / build_resourcepack_name(locale)


def build_resourcepack_name(label: str) -> str:
    return f"{RESOURCEPACK_NAME_PREFIX}-{label}"


def build_packaged_resourcepack_name(label: str, version: str | None = None) -> str:
    base_name = build_resourcepack_name(label)
    if not version:
        return base_name
    return f"{base_name}-{version}"


def ensure_resourcepack_exists(repo_root: Path, locale: str) -> Path:
    resourcepack_root = get_resourcepack_root(repo_root, locale)
    if not resourcepack_root.exists():
        raise FileNotFoundError(f"Resource pack for locale '{locale}' does not exist: {resourcepack_root}")
    return resourcepack_root


def reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_tree_contents(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
        else:
            shutil.copy2(child, target)


def read_pack_mcmeta(resourcepack_root: Path) -> dict:
    path = resourcepack_root / "pack.mcmeta"
    return json.loads(path.read_text(encoding="utf-8"))


def extract_module_key(remote_name: str) -> str | None:
    normalized = str(remote_name).replace("\\", "/").strip()
    if "/" not in normalized:
        return None
    module_name = normalized.split("/", 1)[0].lower()
    return module_name if module_name in MODULE_DISPLAY_NAMES else None


def format_progress_percentage(emitted_entries: int, total_entries: int | None) -> str:
    safe_total = int(total_entries) if isinstance(total_entries, int) and total_entries > 0 else 0
    if safe_total <= 0:
        return "0.0%"
    return f"{(float(emitted_entries) / float(safe_total)) * 100:.1f}%"


def build_progress_suffix(file_entries: list[dict[str, Any]]) -> str:
    segments: list[str] = []
    for module_key in MODULE_DISPLAY_NAMES:
        module_entries = [
            entry
            for entry in file_entries
            if extract_module_key(str(entry.get("remote_name", ""))) == module_key
        ]
        if not module_entries:
            continue
        emitted_total = 0
        declared_total = 0
        # Combined artifacts report aggregate progress across every included locale for each module.
        for entry in module_entries:
            stats = entry.get("stats")
            emitted_total += int(stats.get("emitted_entries", 0)) if isinstance(stats, dict) else 0
            declared_total += int(entry.get("total", 0)) if isinstance(entry.get("total"), int) else 0
        segments.append(f"{MODULE_DISPLAY_NAMES[module_key]} {format_progress_percentage(emitted_total, declared_total)}")
    return " | ".join(segments)


def load_locale_progress_metadata(repo_root: Path, locale: str) -> list[dict[str, Any]]:
    # Combined packaging may run in a separate job, so it reads committed per-locale progress instead of the ignored manifest.
    metadata_path = repo_root / locale / PROGRESS_METADATA_FILE_NAME
    if not metadata_path.exists():
        return []
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    files = payload.get("files")
    if not isinstance(files, list):
        return []
    return [entry for entry in files if isinstance(entry, dict)]


def build_combined_pack_description(repo_root: Path, locales: Iterable[str]) -> str:
    base_description = f"GTO translations ({DEFAULT_COMBINED_LABEL})"
    matching_entries: list[dict[str, Any]] = []
    for locale in locales:
        matching_entries.extend(load_locale_progress_metadata(repo_root, locale))

    progress_suffix = build_progress_suffix(matching_entries)
    if not progress_suffix:
        return base_description
    return f"{base_description} | {progress_suffix}"


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_artifact_metadata(
    *,
    artifact_version: str | None,
    artifact_kind: str,
    locales: list[str],
    release_line: str | None = None,
    source_revision: str | None = None,
    built_at: str | None = None,
) -> dict[str, Any] | None:
    if not any((artifact_version, release_line, source_revision, built_at)):
        return None

    metadata: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": artifact_kind,
        "locales": locales,
    }
    if artifact_version:
        metadata["artifact_version"] = artifact_version
    if release_line:
        metadata["release_line"] = release_line
    if source_revision:
        metadata["source_revision"] = source_revision
    if built_at:
        metadata["built_at"] = built_at
    return metadata


def write_artifact_metadata(resourcepack_root: Path, metadata: dict[str, Any] | None) -> None:
    if metadata is None:
        return
    write_json_file(resourcepack_root / ARTIFACT_METADATA_FILE_NAME, metadata)


def build_combined_pack_mcmeta(pack_format: int, description: str) -> dict:
    return {
        "pack": {
            "pack_format": pack_format,
            "description": description,
        }
    }


def stage_single_locale_artifact(
    repo_root: Path,
    output_dir: Path,
    locale: str,
    artifact_metadata: dict[str, Any] | None = None,
) -> Path:
    source = ensure_resourcepack_exists(repo_root, locale)
    packaged_name = build_packaged_resourcepack_name(
        locale,
        artifact_metadata.get("artifact_version") if isinstance(artifact_metadata, dict) else None,
    )
    target = output_dir / packaged_name
    reset_dir(target)
    shutil.copytree(source, target, dirs_exist_ok=True)
    write_artifact_metadata(target, artifact_metadata)
    return target


def stage_combined_artifact(
    repo_root: Path,
    output_dir: Path,
    locales: Iterable[str],
    artifact_metadata: dict[str, Any] | None = None,
) -> Path:
    locales = list(locales)
    if not locales:
        raise ValueError("Cannot build combined artifact without locales.")

    packaged_name = build_packaged_resourcepack_name(
        DEFAULT_COMBINED_LABEL,
        artifact_metadata.get("artifact_version") if isinstance(artifact_metadata, dict) else None,
    )
    target = output_dir / packaged_name
    reset_dir(target)

    expected_pack_format: int | None = None
    for locale in locales:
        source = ensure_resourcepack_exists(repo_root, locale)
        pack_mcmeta = read_pack_mcmeta(source)
        pack = pack_mcmeta.get("pack", {})
        pack_format = pack.get("pack_format")
        if not isinstance(pack_format, int):
            raise ValueError(f"Invalid pack.mcmeta for locale '{locale}'")
        if expected_pack_format is None:
            expected_pack_format = pack_format
        elif pack_format != expected_pack_format:
            raise ValueError(f"pack_format mismatch for locale '{locale}'")

        # Each locale pack already has the right assets layout, so the combined pack is just a tree merge.
        copy_tree_contents(source, target)

    if expected_pack_format is None:
        raise ValueError("Cannot build combined artifact without pack metadata.")

    description = build_combined_pack_description(repo_root, locales)
    (target / "pack.mcmeta").write_text(
        json.dumps(build_combined_pack_mcmeta(expected_pack_format, description), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_artifact_metadata(target, artifact_metadata)

    return target


def main() -> int:
    args = parse_args()

    try:
        config = load_project_config(args.config)
        repo_root = Path(args.repo_root).resolve()
        output_dir = Path(args.output_dir).resolve()
        locales = parse_locales(args.locales) if args.locales else get_configured_locales(config)
        reset_dir(output_dir)

        staged_paths: list[Path] = []
        for locale in locales:
            artifact_metadata = build_artifact_metadata(
                artifact_version=args.artifact_version,
                artifact_kind="locale",
                locales=[locale],
                release_line=args.release_line,
                source_revision=args.source_revision,
                built_at=args.built_at,
            )
            staged_paths.append(stage_single_locale_artifact(
                repo_root,
                output_dir,
                locale,
                artifact_metadata=artifact_metadata,
            ))

        combined_metadata = build_artifact_metadata(
            artifact_version=args.artifact_version,
            artifact_kind="combined",
            locales=locales,
            release_line=args.release_line,
            source_revision=args.source_revision,
            built_at=args.built_at,
        )
        staged_paths.append(stage_combined_artifact(repo_root, output_dir, locales, artifact_metadata=combined_metadata))
    except Exception as error:
        print(f"Artifact build failed: {error}", file=sys.stderr)
        return 1

    print("Staged resource-pack artifacts:")
    for path in staged_paths:
        print(f"- {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
