import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from project_config import (
    DEFAULT_CONFIG_PATH,
    build_release_line,
    get_configured_locales,
    get_configured_project_ids,
    get_current_version,
    get_primary_project_id,
    get_release_product,
    load_project_config,
    set_current_version,
    write_project_config,
)

DEFAULT_BASE_URL = "https://paratranz.cn/api"
DEFAULT_OUTPUT_DIR = "."
DEFAULT_MANIFEST_PATH = ".paratranz-sync/manifest.json"
DEFAULT_TIMEOUT = 30
DEFAULT_MIN_STAGE = 1
MAX_RETRIES = 3
RESOURCEPACK_NAME_PREFIX = "gto-translations"
MODULE_OUTPUT_PATHS = {
    "gtocore": ("assets", "gtocore", "lang"),
    "gtodyssey": ("assets", "gto", "lang"),
}


class ParatranzClient:
    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = max(1, int(timeout))
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "gto-translations-sync/1.0",
        }

    def _get_json(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            request = Request(url=url, headers=self.headers, method="GET")
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
                return json.loads(body)
            except HTTPError as error:
                last_error = error
                if error.code not in (429, 500, 502, 503, 504) or attempt == MAX_RETRIES:
                    detail = error.read().decode("utf-8", errors="ignore")
                    raise RuntimeError(f"HTTP {error.code} for {url}: {detail}") from error
            except URLError as error:
                last_error = error
                if attempt == MAX_RETRIES:
                    raise RuntimeError(f"Request failed for {url}: {error}") from error

            time.sleep(2 ** (attempt - 1))

        raise RuntimeError(f"Request failed for {url}: {last_error}")

    def get_project(self, project_id: int) -> dict[str, Any]:
        payload = self._get_json(f"/projects/{project_id}")
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected project payload for {project_id}")
        return payload

    def get_files(self, project_id: int) -> list[dict[str, Any]]:
        payload = self._get_json(f"/projects/{project_id}/files")
        if not isinstance(payload, list):
            raise ValueError(f"Unexpected file list payload for {project_id}")
        return [item for item in payload if isinstance(item, dict)]

    def get_file_translation(self, project_id: int, file_id: int) -> Any:
        return self._get_json(f"/projects/{project_id}/files/{file_id}/translation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read Paratranz translations and write Minecraft-style lang JSON files into this repository.",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"YAML config path. Defaults to {DEFAULT_CONFIG_PATH}.",
    )
    parser.add_argument(
        "--project-ids",
        help="Optional comma-separated Paratranz project IDs. Defaults to configured projects.",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("PARATRANZ_TOKEN"),
        help="Paratranz API token. Defaults to PARATRANZ_TOKEN.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Paratranz API base URL. Defaults to {DEFAULT_BASE_URL}.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP timeout in seconds. Defaults to {DEFAULT_TIMEOUT}.",
    )
    parser.add_argument(
        "--lang-root",
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where generated lang files are written. Defaults to the repository root.",
    )
    parser.add_argument(
        "--manifest",
        default=DEFAULT_MANIFEST_PATH,
        help=f"Manifest path. Defaults to {DEFAULT_MANIFEST_PATH}.",
    )
    parser.add_argument(
        "--min-stage",
        type=int,
        default=DEFAULT_MIN_STAGE,
        help=f"Only include entries whose stage is at least this value. Defaults to {DEFAULT_MIN_STAGE}.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and normalize data without writing files.",
    )
    return parser.parse_args()


def parse_project_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for part in str(raw).split(","):
        value = part.strip()
        if not value:
            continue
        ids.append(int(value))
    if not ids:
        raise ValueError("At least one project ID is required.")
    return ids


def resolve_release_line(
    client: Any,
    release_product: str,
    primary_project_id: int,
    comparison_project_ids: list[int] | tuple[int, ...] = (),
) -> dict[str, Any]:
    primary_project = client.get_project(primary_project_id)
    primary_extra = primary_project.get("extra")
    if not isinstance(primary_extra, dict):
        raise ValueError(f"Project {primary_project_id} is missing extra metadata.")

    primary_version = primary_extra.get("version")
    if not isinstance(primary_version, str) or not primary_version.strip():
        raise ValueError(f"Project {primary_project_id} is missing extra.version.")

    normalized_version = primary_version.strip()
    warnings: list[str] = []

    for project_id in comparison_project_ids:
        project = client.get_project(project_id)
        extra = project.get("extra")
        comparison_version = extra.get("version") if isinstance(extra, dict) else None
        if not isinstance(comparison_version, str) or not comparison_version.strip():
            warnings.append(
                f"Project {project_id} ({project.get('name')}) is missing extra.version; "
                f"expected {normalized_version} from primary project {primary_project_id}."
            )
            continue

        comparison_version = comparison_version.strip()
        if comparison_version != normalized_version:
            warnings.append(
                f"Project {project_id} ({project.get('name')}) reports extra.version={comparison_version}, "
                f"which differs from primary project {primary_project_id} extra.version={normalized_version}."
            )

    return {
        "release_line": build_release_line(release_product, normalized_version),
        "primary_project_id": primary_project_id,
        "primary_project_name": primary_project.get("name"),
        "primary_version": normalized_version,
        "warnings": warnings,
    }


def build_output_path(output_dir: Path, remote_name: str) -> Path:
    normalized = remote_name.replace("\\", "/").strip()
    if not normalized:
        raise ValueError("Remote file name is empty.")

    remote_path = PurePosixPath(normalized)
    if remote_path.is_absolute():
        raise ValueError(f"Absolute remote path is not allowed: {remote_name}")

    parts = list(remote_path.parts)
    if len(parts) != 2:
        raise ValueError(f"Unexpected remote path layout: {remote_name}")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"Unsafe remote path: {remote_name}")
    if any(":" in part for part in parts):
        raise ValueError(f"Unsafe remote path: {remote_name}")

    module_name, locale_file_name = parts
    module_key = module_name.lower()
    path_segments = MODULE_OUTPUT_PATHS.get(module_key)
    if path_segments is None:
        raise ValueError(f"Unexpected module name: {module_name}")

    locale_path = PurePosixPath(locale_file_name)
    locale_stem = locale_path.stem
    locale_suffix = locale_path.suffix.lower()
    if locale_suffix != ".json":
        raise ValueError(f"Unexpected file extension: {remote_name}")

    locale_parts = locale_stem.split("_")
    if len(locale_parts) != 2 or not all(locale_parts):
        raise ValueError(f"Unexpected locale format: {remote_name}")

    normalized_locale = f"{locale_parts[0].lower()}_{locale_parts[1].lower()}"
    generated_file_name = f"{normalized_locale}.json"
    candidate = output_dir / normalized_locale / "resourcepacks" / build_resourcepack_name(normalized_locale) / Path(*path_segments) / generated_file_name
    resolved_output_dir = output_dir.resolve()
    resolved_candidate = candidate.resolve(strict=False)
    if resolved_output_dir not in resolved_candidate.parents and resolved_candidate != resolved_output_dir:
        raise ValueError(f"Unsafe remote path: {remote_name}")

    return candidate


def build_pack_mcmeta_path(output_dir: Path, locale: str) -> Path:
    return output_dir / locale / "resourcepacks" / build_resourcepack_name(locale) / "pack.mcmeta"


def build_resourcepack_name(locale: str) -> str:
    return f"{RESOURCEPACK_NAME_PREFIX}-{locale}"


def build_pack_mcmeta(label: str) -> dict[str, Any]:
    return {
        "pack": {
            "pack_format": 15,
            "description": f"GTO translations resource pack ({label})",
        }
    }


def normalize_translation_payload(payload: Any, min_stage: int = DEFAULT_MIN_STAGE) -> tuple[dict[str, str], dict[str, int]]:
    stats = {
        "total_entries": 0,
        "emitted_entries": 0,
        "skipped_empty_translation": 0,
        "skipped_below_stage": 0,
        "duplicate_keys": 0,
    }

    if isinstance(payload, dict):
        mapping: dict[str, str] = {}
        for key, value in payload.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("Flat JSON payload must contain only string keys and values.")
            mapping[key] = value
        stats["total_entries"] = len(mapping)
        stats["emitted_entries"] = len(mapping)
        return dict(sorted(mapping.items())), stats

    if not isinstance(payload, list):
        raise ValueError("Unsupported translation payload type.")

    mapping: dict[str, str] = {}
    stats["total_entries"] = len(payload)
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"Entry #{index} is not an object.")

        key = item.get("key")
        translation = item.get("translation")
        stage = item.get("stage")

        if not isinstance(key, str) or not key:
            raise ValueError(f"Entry #{index} has an invalid key.")
        if translation is None:
            translation = ""
        if not isinstance(translation, str):
            raise ValueError(f"Entry #{index} has a non-string translation.")

        parsed_stage = 0
        if stage is not None:
            try:
                parsed_stage = int(stage)
            except (TypeError, ValueError) as error:
                raise ValueError(f"Entry #{index} has an invalid stage.") from error

        if parsed_stage < min_stage:
            stats["skipped_below_stage"] += 1
            continue
        if not translation.strip():
            stats["skipped_empty_translation"] += 1
            continue

        existing = mapping.get(key)
        if existing is not None:
            stats["duplicate_keys"] += 1
            if existing != translation:
                raise ValueError(f"Conflicting translations for duplicate key: {key}")
            continue

        mapping[key] = translation

    stats["emitted_entries"] = len(mapping)
    return dict(sorted(mapping.items())), stats


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=isinstance(payload, dict))
    path.write_text(text + "\n", encoding="utf-8")


def load_existing_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def collect_previous_generated_paths(
    repo_root: Path,
    manifest_payload: dict[str, Any] | None,
    configured_locales: list[str],
) -> set[Path]:
    results: set[Path] = set()
    if not manifest_payload:
        return results

    for item in manifest_payload.get("files", []):
        if not isinstance(item, dict):
            continue

        output_path = item.get("output_path")
        if isinstance(output_path, str) and output_path:
            results.add((repo_root / PurePosixPath(output_path)).resolve(strict=False))

    for extra_path in manifest_payload.get("generated_paths", []):
        if isinstance(extra_path, str) and extra_path:
            results.add((repo_root / PurePosixPath(extra_path)).resolve(strict=False))

    legacy_dir = repo_root / "mc-lang"
    for file_path in legacy_dir.rglob("*.json") if legacy_dir.exists() else []:
        if file_path.name == "manifest.json":
            continue
        results.add(file_path.resolve(strict=False))

    locale_candidates: set[str] = set(configured_locales)
    locale_candidates.update(locale.upper() for locale in configured_locales)
    locale_candidates.update(
        "_".join(part.upper() if index == 1 else part for index, part in enumerate(locale.split("_")))
        for locale in configured_locales
    )
    for locale_dir in sorted(locale_candidates):
        locale_root = repo_root / locale_dir
        if not locale_root.exists():
            continue
        for file_path in locale_root.rglob("*"):
            if file_path.is_file():
                results.add(file_path.resolve(strict=False))

    return results


def cleanup_stale_outputs(previous_paths: set[Path], keep_paths: set[Path], protected_paths: set[Path]) -> None:
    for stale_path in previous_paths - keep_paths - protected_paths:
        if stale_path.exists() and stale_path.is_file():
            stale_path.unlink()

    candidate_dirs: set[Path] = set()
    for path in previous_paths | keep_paths:
        current = path.parent
        while current.exists():
            candidate_dirs.add(current)
            parent = current.parent
            if parent == current:
                break
            current = parent

    for directory in sorted(candidate_dirs, reverse=True):
        if not directory.exists() or not directory.is_dir():
            continue
        if directory in protected_paths:
            continue
        try:
            next(directory.iterdir())
        except StopIteration:
            directory.rmdir()


def sync_projects(
    client: Any,
    release_product: str,
    project_ids: list[int],
    configured_locales: list[str],
    config_path: Path,
    config: dict[str, Any],
    output_dir: Path,
    manifest_path: Path,
    min_stage: int = DEFAULT_MIN_STAGE,
    write_files: bool = True,
    primary_project_id: int | None = None,
) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    manifest_path = manifest_path.resolve()
    previous_manifest = load_existing_manifest(manifest_path)
    previous_generated_paths = collect_previous_generated_paths(output_dir, previous_manifest, configured_locales)
    if primary_project_id is None:
        raise ValueError("primary_project_id is required.")
    comparison_project_ids = [project_id for project_id in project_ids if project_id != primary_project_id]
    release_info = resolve_release_line(
        client=client,
        release_product=release_product,
        primary_project_id=primary_project_id,
        comparison_project_ids=comparison_project_ids,
    )

    manifest: dict[str, Any] = {
        "synced_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project_ids": project_ids,
        "release_line": release_info["release_line"],
        "release_line_primary_project_id": primary_project_id,
        "release_line_primary_version": release_info["primary_version"],
        "release_line_warnings": release_info["warnings"],
        "projects": [],
        "files": [],
        "generated_paths": [],
    }

    keep_paths: set[Path] = {manifest_path}
    protected_paths: set[Path] = {manifest_path, manifest_path.parent}
    pack_locales: set[str] = set()

    for project_id in project_ids:
        project = client.get_project(project_id)
        files = client.get_files(project_id)
        project_entry = {
            "project": {
                "id": project.get("id"),
                "name": project.get("name"),
                "source": project.get("source"),
                "dest": project.get("dest"),
                "reviewMode": project.get("reviewMode"),
                "version": project.get("extra", {}).get("version") if isinstance(project.get("extra"), dict) else None,
                "compatible": project.get("extra", {}).get("compatible") if isinstance(project.get("extra"), dict) else None,
            },
            "files": [],
        }

        for file_info in files:
            file_id = file_info.get("id")
            remote_name = file_info.get("name")
            if not isinstance(file_id, int) or not isinstance(remote_name, str):
                raise ValueError(f"Unexpected file metadata in project {project_id}")

            payload = client.get_file_translation(project_id, file_id)
            mapping, stats = normalize_translation_payload(payload, min_stage=min_stage)
            output_path = build_output_path(output_dir, remote_name)
            keep_paths.add(output_path)
            pack_locales.add(str(output_path.relative_to(output_dir).parts[0]))

            file_entry = {
                "project_id": project_id,
                "project_name": project.get("name"),
                "file_id": file_id,
                "remote_name": remote_name,
                "output_path": str(output_path.relative_to(output_dir).as_posix()),
                "format": file_info.get("format"),
                "modified_at": file_info.get("modifiedAt"),
                "total": file_info.get("total"),
                "translated": file_info.get("translated"),
                "reviewed": file_info.get("reviewed"),
                "stats": stats,
            }
            manifest["files"].append(file_entry)
            project_entry["files"].append(file_entry)
            manifest["generated_paths"].append(str(output_path.relative_to(output_dir).as_posix()))

            if write_files:
                write_json_file(output_path, mapping)

        manifest["projects"].append(project_entry)

    if write_files:
        if get_current_version(config) != release_info["primary_version"]:
            set_current_version(config, release_info["primary_version"])
        write_project_config(config_path, config)

        for locale in sorted(pack_locales):
            pack_mcmeta_path = build_pack_mcmeta_path(output_dir, locale)
            keep_paths.add(pack_mcmeta_path)
            manifest["generated_paths"].append(str(pack_mcmeta_path.relative_to(output_dir).as_posix()))
            write_json_file(pack_mcmeta_path, build_pack_mcmeta(locale))

        write_json_file(manifest_path, manifest)
        cleanup_stale_outputs(
            previous_paths=previous_generated_paths,
            keep_paths=keep_paths,
            protected_paths=protected_paths,
        )

    return manifest


def main() -> int:
    args = parse_args()

    if not args.token:
        print("Missing Paratranz token. Pass --token or set PARATRANZ_TOKEN.", file=sys.stderr)
        return 1

    try:
        config = load_project_config(args.config)
        project_ids = parse_project_ids(args.project_ids) if args.project_ids else get_configured_project_ids(config)
        configured_locales = get_configured_locales(config)
        release_product = get_release_product(config)
        primary_project_id = get_primary_project_id(config)
        config_path = Path(args.config)
        output_dir = Path(args.lang_root)
        manifest_path = Path(args.manifest)
        client = ParatranzClient(
            token=args.token,
            base_url=args.base_url,
            timeout=args.timeout,
        )
        manifest = sync_projects(
            client=client,
            release_product=release_product,
            project_ids=project_ids,
            configured_locales=configured_locales,
            config_path=config_path,
            config=config,
            output_dir=output_dir,
            manifest_path=manifest_path,
            min_stage=args.min_stage,
            write_files=not args.dry_run,
            primary_project_id=primary_project_id,
        )
    except Exception as error:
        print(f"Sync failed: {error}", file=sys.stderr)
        return 1

    print("Paratranz sync summary:")
    for file_entry in manifest["files"]:
        print(
            f"- {file_entry['remote_name']} -> {file_entry['output_path']} "
            f"({file_entry['stats']['emitted_entries']} entries)"
        )

    if args.dry_run:
        print("Dry run completed without writing files.")
    else:
        print(f"Wrote outputs to {output_dir.resolve()}")
        print(f"Wrote manifest to {manifest_path.resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
