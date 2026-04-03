import shutil
import sys
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import project_config as config_module


class ProjectConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = REPO_ROOT / f".tmp-config-test-{uuid.uuid4().hex}"
        self.temp_root.mkdir(parents=True, exist_ok=False)
        self.config_path = self.temp_root / "config.yml"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_loads_release_and_project_configuration(self) -> None:
        self.config_path.write_text(
            "\n".join(
                [
                    "release:",
                    "  product: gto",
                    "  primary_project_id: 16320",
                    "  current_version: 0.5.4",
                    "projects:",
                    "  - locale: en_us",
                    "    project_id: 16320",
                    "    allowed_stages: [-1, 5, 9]",
                    "  - locale: ru_ru",
                    "    project_id: 16525",
                    "    allowed_stages: [-1, 5, 9]",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        config = config_module.load_project_config(self.config_path)

        self.assertEqual(config_module.get_release_product(config), "gto")
        self.assertEqual(config_module.get_primary_project_id(config), 16320)
        self.assertEqual(config_module.get_current_version(config), "0.5.4")
        self.assertEqual(config_module.get_configured_locales(config), ["en_us", "ru_ru"])
        self.assertEqual(config_module.get_configured_project_ids(config), [16320, 16525])
        self.assertEqual(config_module.get_project_entries(config)[0]["allowed_stages"], [-1, 5, 9])

    def test_rejects_missing_projects(self) -> None:
        self.config_path.write_text(
            "\n".join(
                [
                    "release:",
                    "  product: gto",
                    "  primary_project_id: 16320",
                    "projects: []",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            config_module.load_project_config(self.config_path)

    def test_write_project_config_persists_current_version(self) -> None:
        config = {
            "release": {
                "product": "gto",
                "primary_project_id": 16320,
                "current_version": None,
            },
            "projects": [
                {"locale": "en_us", "project_id": 16320, "allowed_stages": [-1, 5, 9], "artifact_label": "en_us"},
                {"locale": "ru_ru", "project_id": 16525, "allowed_stages": [-1, 5, 9], "artifact_label": "ru_ru"},
            ],
        }

        config_module.set_current_version(config, "0.5.5")
        config_module.write_project_config(self.config_path, config)
        reloaded = config_module.load_project_config(self.config_path)

        self.assertEqual(config_module.get_current_version(reloaded), "0.5.5")
        self.assertEqual(config_module.build_release_line("gto", "0.5.5"), "gto-0.5.5")
        self.assertEqual(config_module.get_project_entries(reloaded)[0]["allowed_stages"], [-1, 5, 9])
