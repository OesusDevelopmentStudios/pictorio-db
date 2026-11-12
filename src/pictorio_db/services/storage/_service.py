# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from collections.abc import Callable, Collection
from pathlib import Path

from pictorio_db.services.settings import SettingsService
from pictorio_db.services.storage._paths import DEFAULT_PATH_TEMPLATE, PathTemplate, parse_path_template

PATH_TEMPLATE_SETTING = "path_template"


class StorageService:
    """The library folder and its layout. `namespace_names` returns the namespaces that exist, which the
    path template may use."""

    def __init__(
        self, settings: SettingsService, library_dir: Path, namespace_names: Callable[[], Collection[str]]
    ) -> None:
        self._settings = settings
        self._namespace_names = namespace_names
        self.library_dir = library_dir

    def path_template(self) -> PathTemplate:
        stored_text = self._settings.get(PATH_TEMPLATE_SETTING)
        text = DEFAULT_PATH_TEMPLATE if stored_text is None else stored_text
        return parse_path_template(text, self._namespace_names())

    def path_template_namespaces(self) -> frozenset[str]:
        return self.path_template().namespaces

    def set_path_template(self, text: str) -> PathTemplate:
        """Checks and stores the template. Raises 422 validation_error; the stored one then stays."""
        template = parse_path_template(text.strip(), self._namespace_names())
        self._settings.set(PATH_TEMPLATE_SETTING, template.text)
        return template
