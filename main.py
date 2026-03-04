import os
import sys

import fire  # type: ignore[import]
import loguru


class App:
    def __init__(self) -> None:
        from gto_translation_compare.cmd import Action

        self.action = Action()


def setup_logger() -> None:
    from typing import Dict, Any

    logger_level = "INFO"
    if os.getenv("GTO_TC_DEBUG"):
        logger_level = "DEBUG"

    def remove_logger_global_name_prefix(record: Dict[str, Any]) -> None:
        record["name"] = record["name"].removeprefix("gto_translation_compare.")

    loguru.logger = loguru.logger.patch(remove_logger_global_name_prefix)  # type: ignore[arg-type]
    loguru.logger.configure(handlers=[{"sink": sys.stderr, "level": logger_level, "colorize": True}])


if __name__ == "__main__":
    setup_logger()
    fire.Fire(App, name="gto-translation-compare")
