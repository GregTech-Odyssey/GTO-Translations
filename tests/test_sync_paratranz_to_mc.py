import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import sync_paratranz_to_mc as sync_module


class FakeClient:
    def __init__(self) -> None:
        self.projects = {
            16320: {
                "id": 16320,
                "name": "GregTech-Odyssey(en)",
                "source": "zh-cn",
                "dest": "en",
                "reviewMode": 1,
                "extra": {
                    "version": "0.5.4",
                    "compatible": "GregTech.Odyssey-0.5.4-beta",
                },
            },
            16525: {
                "id": 16525,
                "name": "GregTech-Odyssey(ru)",
                "source": "zh-cn",
                "dest": "ru",
                "reviewMode": 1,
                "extra": {
                    "version": "0.5.4",
                    "compatible": "GregTech.Odyssey-0.5.4-beta",
                },
            },
            18185: {
                "id": 18185,
                "name": "GregTech-Odyssey(ja)",
                "source": "zh-cn",
                "dest": "ja",
                "reviewMode": 1,
                "extra": {
                    "version": "0.5.4",
                    "compatible": "GregTech.Odyssey-0.5.4-beta",
                },
            }
        }
        self.files = {
            16320: [
                {
                    "id": 10,
                    "name": "GTOCore/en_us.json",
                    "total": 3,
                    "translated": 2,
                    "reviewed": 1,
                    "modifiedAt": "2026-04-02T05:50:05.758Z",
                    "format": "jsonkv",
                },
                {
                    "id": 11,
                    "name": "GTOdyssey/en_us.json",
                    "total": 1,
                    "translated": 1,
                    "reviewed": 1,
                    "modifiedAt": "2026-04-02T05:52:16.017Z",
                    "format": "jsonkv",
                },
            ]
        }
        self.translations = {
            (16320, 10): [
                {"key": "key.a", "translation": "Alpha", "stage": 1},
                {"key": "key.b", "translation": "", "stage": 0},
                {"key": "key.c", "translation": "Gamma", "stage": 5},
            ],
            (16320, 11): [
                {"key": "key.d", "translation": "Delta", "stage": 1},
            ],
        }

    def get_project(self, project_id: int) -> dict:
        return self.projects[project_id]

    def get_files(self, project_id: int) -> list[dict]:
        return self.files[project_id]

    def get_file_translation(self, project_id: int, file_id: int):
        return self.translations[(project_id, file_id)]


class NormalizeTranslationPayloadTests(unittest.TestCase):
    def test_converts_paratranz_entry_list_to_flat_mapping(self) -> None:
        payload = [
            {"key": "item.alpha", "translation": "Alpha", "stage": 1},
            {"key": "item.beta", "translation": "", "stage": 1},
            {"key": "item.gamma", "translation": "Gamma", "stage": 0},
            {"key": "item.delta", "translation": "Delta", "stage": 5},
        ]

        mapping, stats = sync_module.normalize_translation_payload(
            payload,
            min_stage=1,
        )

        self.assertEqual(
            mapping,
            {
                "item.alpha": "Alpha",
                "item.delta": "Delta",
            },
        )
        self.assertEqual(stats["total_entries"], 4)
        self.assertEqual(stats["emitted_entries"], 2)
        self.assertEqual(stats["skipped_empty_translation"], 1)
        self.assertEqual(stats["skipped_below_stage"], 1)

    def test_accepts_existing_flat_json_mapping(self) -> None:
        payload = {
            "item.alpha": "Alpha",
            "item.delta": "Delta",
        }

        mapping, stats = sync_module.normalize_translation_payload(payload, min_stage=1)

        self.assertEqual(mapping, payload)
        self.assertEqual(stats["total_entries"], 2)
        self.assertEqual(stats["emitted_entries"], 2)

    def test_rejects_conflicting_duplicate_keys(self) -> None:
        payload = [
            {"key": "item.alpha", "translation": "Alpha", "stage": 1},
            {"key": "item.alpha", "translation": "Other Alpha", "stage": 5},
        ]

        with self.assertRaises(ValueError):
            sync_module.normalize_translation_payload(payload, min_stage=1)


class ResolveReleaseLineTests(unittest.TestCase):
    def test_uses_primary_project_version_for_release_line(self) -> None:
        client = FakeClient()

        result = sync_module.resolve_release_line(
            client=client,
            release_product="gto",
            primary_project_id=16320,
            comparison_project_ids=[16525, 18185],
        )

        self.assertEqual(result["release_line"], "gto-0.5.4")
        self.assertEqual(result["primary_version"], "0.5.4")
        self.assertEqual(result["warnings"], [])

    def test_warns_when_comparison_project_version_differs(self) -> None:
        client = FakeClient()
        client.projects[18185]["extra"]["version"] = "0.5.5"

        result = sync_module.resolve_release_line(
            client=client,
            release_product="gto",
            primary_project_id=16320,
            comparison_project_ids=[16525, 18185],
        )

        self.assertEqual(result["release_line"], "gto-0.5.4")
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("18185", result["warnings"][0])
        self.assertIn("0.5.5", result["warnings"][0])

    def test_rejects_missing_primary_project_version(self) -> None:
        client = FakeClient()
        del client.projects[16320]["extra"]["version"]

        with self.assertRaises(ValueError):
            sync_module.resolve_release_line(
                client=client,
                release_product="gto",
                primary_project_id=16320,
                comparison_project_ids=[16525, 18185],
            )


class PathSafetyTests(unittest.TestCase):
    def test_build_output_path_rejects_parent_traversal(self) -> None:
        output_dir = Path("F:/repositories/GTO-Translations")

        with self.assertRaises(ValueError):
            sync_module.build_output_path(output_dir, "../escape.json")

    def test_build_output_path_rejects_absolute_paths(self) -> None:
        output_dir = Path("F:/repositories/GTO-Translations")

        with self.assertRaises(ValueError):
            sync_module.build_output_path(output_dir, "/escape.json")

    def test_build_output_path_rewrites_gtocore_to_game_overlay_structure(self) -> None:
        output_dir = Path("F:/repositories/GTO-Translations")

        result = sync_module.build_output_path(output_dir, "GTOCore/en_us.json")

        self.assertEqual(
            result,
            output_dir / "en_us" / "resourcepacks" / "gto-translations-en_us" / "assets" / "gtocore" / "lang" / "en_us.json",
        )

    def test_build_output_path_rewrites_gtodyssey_to_game_overlay_structure(self) -> None:
        output_dir = Path("F:/repositories/GTO-Translations")

        result = sync_module.build_output_path(output_dir, "GTOdyssey/ja_jp.json")

        self.assertEqual(
            result,
            output_dir / "ja_jp" / "resourcepacks" / "gto-translations-ja_jp" / "assets" / "gto" / "lang" / "ja_jp.json",
        )


class SyncProjectsTests(unittest.TestCase):
    def test_sync_projects_writes_expected_files_manifest_and_cleans_stale_files(self) -> None:
        client = FakeClient()
        temp_root = REPO_ROOT / f".tmp-sync-test-{uuid.uuid4().hex}"
        try:
            temp_root.mkdir(parents=True, exist_ok=False)
            output_dir = temp_root
            stale_file = output_dir / "en_us" / "stale.json"
            stale_file.parent.mkdir(parents=True, exist_ok=True)
            stale_file.write_text("{}", encoding="utf-8")

            manifest_path = temp_root / ".paratranz-sync" / "manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "files": [
                            {
                                "output_path": "en_us/stale.json",
                            }
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            manifest = sync_module.sync_projects(
                client=client,
                release_product="gto",
                project_ids=[16320],
                configured_locales=["en_us", "ru_ru", "ja_jp"],
                output_dir=output_dir,
                manifest_path=manifest_path,
                min_stage=1,
                primary_project_id=16320,
            )

            core_path = output_dir / "en_us" / "resourcepacks" / "gto-translations-en_us" / "assets" / "gtocore" / "lang" / "en_us.json"
            odyssey_path = output_dir / "en_us" / "resourcepacks" / "gto-translations-en_us" / "assets" / "gto" / "lang" / "en_us.json"
            pack_meta_path = output_dir / "en_us" / "resourcepacks" / "gto-translations-en_us" / "pack.mcmeta"

            self.assertFalse(stale_file.exists())
            self.assertTrue(core_path.exists())
            self.assertTrue(odyssey_path.exists())
            self.assertTrue(pack_meta_path.exists())
            self.assertEqual(
                json.loads(pack_meta_path.read_text(encoding="utf-8"))["pack"]["description"],
                "GTO translations resource pack (en_us)",
            )

            self.assertEqual(
                json.loads(core_path.read_text(encoding="utf-8")),
                {
                    "key.a": "Alpha",
                    "key.c": "Gamma",
                },
            )
            self.assertEqual(
                json.loads(odyssey_path.read_text(encoding="utf-8")),
                {
                    "key.d": "Delta",
                },
            )

            written_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["projects"][0]["project"]["id"], 16320)
            self.assertEqual(manifest["release_line"], "gto-0.5.4")
            self.assertEqual(written_manifest["release_line"], "gto-0.5.4")
            self.assertEqual(written_manifest["release_line_warnings"], [])
            self.assertEqual(written_manifest["files"][0]["remote_name"], "GTOCore/en_us.json")
            self.assertEqual(written_manifest["files"][0]["stats"]["emitted_entries"], 2)
            self.assertEqual(
                written_manifest["files"][0]["output_path"],
                "en_us/resourcepacks/gto-translations-en_us/assets/gtocore/lang/en_us.json",
            )
            self.assertIn(
                "en_us/resourcepacks/gto-translations-en_us/pack.mcmeta",
                written_manifest["generated_paths"],
            )
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
