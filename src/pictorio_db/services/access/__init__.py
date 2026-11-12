# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Restricted tags per user: which images a user may see and which tags they may use."""

from pictorio_db.services.access._service import AccessService, Restrictions

__all__ = ["AccessService", "Restrictions"]
