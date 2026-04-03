import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_resourcepack_artifacts as artifacts_module


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class BuildResourcepackArtifactsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = REPO_ROOT / f".tmp-artifact-test-{uuid.uuid4().hex}"
        self.output_dir = self.temp_root / "dist"
        self.temp_root.mkdir(parents=True, exist_ok=False)

        for locale in ("en_us", "ru_ru"):
            base = self.temp_root / locale / "resourcepacks" / f"gto-translations-{locale}"
            write_json(
                base / "pack.mcmeta",
                {
                    "pack": {
                        "pack_format": 15,
                        "description": f"GTO translations resource pack ({locale})",
                    }
                },
            )
            write_json(
                base / "assets" / "gtocore" / "lang" / f"{locale}.json",
                {
                    f"core.{locale}": f"core-{locale}",
                },
            )
            write_json(
                base / "assets" / "gto" / "lang" / f"{locale}.json",
                {
                    f"quest.{locale}": f"quest-{locale}",
                },
            )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_stage_single_locale_artifact_preserves_resourcepack_layout(self) -> None:
        metadata = artifacts_module.build_artifact_metadata(
            artifact_version="gto-0.5.4-dev-26.04.04.12-abcd1234",
            artifact_kind="locale",
            locales=["en_us"],
            release_line="gto-0.5.4",
            source_revision="abcd1234",
            built_at="2026-04-04T00:00:00Z",
        )
        artifact_root = artifacts_module.stage_single_locale_artifact(
            repo_root=self.temp_root,
            output_dir=self.output_dir,
            locale="en_us",
            artifact_metadata=metadata,
        )

        self.assertEqual(artifact_root, self.output_dir / "en_us" / "resourcepacks")
        self.assertTrue((artifact_root / "gto-translations-en_us" / "pack.mcmeta").exists())
        self.assertTrue((artifact_root / "gto-translations-en_us" / "assets" / "gtocore" / "lang" / "en_us.json").exists())
        self.assertEqual(
            json.loads(
                (artifact_root / "gto-translations-en_us" / artifacts_module.ARTIFACT_METADATA_FILE_NAME).read_text(encoding="utf-8")
            )["artifact_version"],
            "gto-0.5.4-dev-26.04.04.12-abcd1234",
        )

    def test_stage_combined_artifact_merges_all_locale_lang_files(self) -> None:
        metadata = artifacts_module.build_artifact_metadata(
            artifact_version="gto-0.5.4-dev-26.04.04.12-abcd1234",
            artifact_kind="combined",
            locales=["en_us", "ru_ru"],
            release_line="gto-0.5.4",
            source_revision="abcd1234",
            built_at="2026-04-04T00:00:00Z",
        )
        artifact_root = artifacts_module.stage_combined_artifact(
            repo_root=self.temp_root,
            output_dir=self.output_dir,
            locales=["en_us", "ru_ru"],
            artifact_metadata=metadata,
        )

        combined_pack = artifact_root / "gto-translations-all-locales"
        self.assertTrue((combined_pack / "pack.mcmeta").exists())
        self.assertEqual(
            json.loads((combined_pack / "pack.mcmeta").read_text(encoding="utf-8"))["pack"]["description"],
            "GTO translations resource pack (all-locales)",
        )
        self.assertTrue((combined_pack / "assets" / "gtocore" / "lang" / "en_us.json").exists())
        self.assertTrue((combined_pack / "assets" / "gtocore" / "lang" / "ru_ru.json").exists())
        self.assertTrue((combined_pack / "assets" / "gto" / "lang" / "en_us.json").exists())
        self.assertTrue((combined_pack / "assets" / "gto" / "lang" / "ru_ru.json").exists())
        self.assertEqual(
            json.loads((combined_pack / artifacts_module.ARTIFACT_METADATA_FILE_NAME).read_text(encoding="utf-8"))["artifact_kind"],
            "combined",
        )

    def test_stage_combined_artifact_rejects_mismatched_pack_metadata(self) -> None:
        write_json(
            self.temp_root / "ru_ru" / "resourcepacks" / "gto-translations-ru_ru" / "pack.mcmeta",
            {
                "pack": {
                    "pack_format": 99,
                    "description": "Different",
                }
            },
        )

        with self.assertRaises(ValueError):
            artifacts_module.stage_combined_artifact(
                repo_root=self.temp_root,
                output_dir=self.output_dir,
                locales=["en_us", "ru_ru"],
            )

if __name__ == "__main__":
    unittest.main()
