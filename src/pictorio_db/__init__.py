# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""pictorio-db: image library server for Pictorio."""

from importlib.metadata import version

# Taken from pyproject.toml, so the version is written in one place only.
__version__: str = version("pictorio-db")
