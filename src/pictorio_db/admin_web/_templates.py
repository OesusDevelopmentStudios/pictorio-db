# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from pathlib import Path

from fastapi.templating import Jinja2Templates

# HTML templates escape every value they insert, so user input cannot inject markup.
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
