from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode


HUMAN_TRANSLATION_OPERATIONS = {"translate", "edit", "rollback", "reset"}


def extract_string_page_items(payload: Any) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    if isinstance(payload, list):
        candidates.append(payload)
    elif isinstance(payload, dict):
        candidates.extend([payload.get("results"), payload.get("items"), payload.get("data")])
        for container_key in ("results", "items", "data", "pagination"):
            nested = payload.get(container_key)
            if isinstance(nested, dict):
                candidates.extend([nested.get("results"), nested.get("items"), nested.get("data")])
    else:
        raise ValueError("Unsupported strings payload type.")

    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]

    raise ValueError("Could not locate string entries in detailed strings payload.")


def get_nested_pagination_value(payload: Any, *keys: str) -> Any:
    if not isinstance(payload, dict):
        return None

    for key in keys:
        if key in payload:
            return payload.get(key)

    for container_key in ("results", "items", "data", "pagination"):
        nested = payload.get(container_key)
        if isinstance(nested, dict):
            value = get_nested_pagination_value(nested, *keys)
            if value is not None:
                return value

    return None


def should_fetch_next_string_page(payload: Any, batch_size: int, page: int, page_size: int) -> bool:
    if not batch_size:
        return False

    page_count = get_nested_pagination_value(payload, "pageCount", "totalPages", "lastPage")
    if page_count is not None:
        try:
            return page < int(page_count)
        except (TypeError, ValueError):
            return False

    has_next = get_nested_pagination_value(payload, "hasNext", "hasMore")
    if isinstance(has_next, bool):
        return has_next

    next_page = get_nested_pagination_value(payload, "next", "nextPage")
    if next_page not in (None, "", 0, False):
        return True

    return batch_size >= page_size


def parse_iso_timestamp(raw_value: Any) -> datetime:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return datetime.min.replace(tzinfo=UTC)

    normalized = raw_value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def get_latest_translation_event(item: dict[str, Any]) -> dict[str, Any] | None:
    latest_event: dict[str, Any] | None = None
    latest_marker: tuple[datetime, int] | None = None
    event_index = 0

    # We compare both imported and manual history so "current translation came from a human" is based on the latest change.
    for history_field in ("importHistory", "history"):
        history = item.get(history_field)
        if not isinstance(history, list):
            continue

        for event in history:
            if not isinstance(event, dict):
                continue
            field = event.get("field")
            if not isinstance(field, str) or field.lower() != "translation":
                continue

            marker = (parse_iso_timestamp(event.get("createdAt")), event_index)
            if latest_marker is None or marker > latest_marker:
                latest_marker = marker
                latest_event = event
            event_index += 1

    return latest_event


def has_current_human_translation(item: dict[str, Any]) -> bool:
    latest_event = get_latest_translation_event(item)
    if latest_event is None:
        return False

    operation = latest_event.get("operation")
    if not isinstance(operation, str):
        return False

    return operation.lower() in HUMAN_TRANSLATION_OPERATIONS


def normalize_manual_stage_one_payload(payload: Any) -> tuple[dict[str, str], dict[str, int]]:
    if not isinstance(payload, list):
        raise ValueError("Manual stage-one filtering requires a detailed string list payload.")

    stats = {
        "total_entries": len(payload),
        "emitted_entries": 0,
        "skipped_empty_translation": 0,
        "skipped_non_stage_one": 0,
        "skipped_non_human_modified": 0,
        "duplicate_keys": 0,
    }
    mapping: dict[str, str] = {}

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

        try:
            parsed_stage = int(stage)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Entry #{index} has an invalid stage.") from error

        # This pass is intentionally narrow: only untranslated-review state entries that were last changed by a human.
        if parsed_stage != 1:
            stats["skipped_non_stage_one"] += 1
            continue
        if not translation.strip():
            stats["skipped_empty_translation"] += 1
            continue
        if not has_current_human_translation(item):
            stats["skipped_non_human_modified"] += 1
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


def collect_manual_stage_one_translations(client: Any, project_id: int, file_id: int) -> tuple[dict[str, str], dict[str, int]]:
    payload = fetch_detailed_strings(client, project_id, file_id)
    return normalize_manual_stage_one_payload(payload)


def fetch_detailed_strings(client: Any, project_id: int, file_id: int, page_size: int = 1000) -> list[dict[str, Any]]:
    page = 1
    results: list[dict[str, Any]] = []

    while True:
        # The detailed strings endpoint is only used by the en_us additive pass, so its pagination lives here.
        query = urlencode(
            {
                "file": file_id,
                "page": page,
                "pageSize": page_size,
                "detailed": 1,
            }
        )
        payload = client._get_json(f"/projects/{project_id}/strings?{query}")
        batch = extract_string_page_items(payload)
        results.extend(batch)

        if not should_fetch_next_string_page(
            payload,
            batch_size=len(batch),
            page=page,
            page_size=page_size,
        ):
            return results

        page += 1
