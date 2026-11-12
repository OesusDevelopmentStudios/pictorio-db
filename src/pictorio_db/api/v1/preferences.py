# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""/preferences: the logged-in user's own settings."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from pictorio_db.api.v1.dependencies import CurrentAuthentication, PreferencesServiceDependency
from pictorio_db.services.preferences import HIDDEN_FILTER_MAX_LENGTH, MAX_HIDDEN_FILTERS
from pictorio_db.utils.problems import problem_responses

router = APIRouter(prefix="/preferences", tags=["preferences"])


class Preferences(BaseModel):
    hidden_filters: list[str] = Field(
        max_length=MAX_HIDDEN_FILTERS,
        description=(
            "Search terms hidden from the default view unless a search mentions one of their tags; "
            f"one term each, without '-', at most {HIDDEN_FILTER_MAX_LENGTH} characters"
        ),
        examples=[["rating:nsfw", "category:refs"]],
    )


@router.get("", summary="Your preferences", responses=problem_responses(401))
def get_preferences(authentication: CurrentAuthentication, preferences: PreferencesServiceDependency) -> Preferences:
    return Preferences(hidden_filters=preferences.hidden_filters(authentication.user.id))


@router.put("", summary="Replace your preferences", responses=problem_responses(401, 422))
def put_preferences(
    new_preferences: Preferences, authentication: CurrentAuthentication, preferences: PreferencesServiceDependency
) -> Preferences:
    stored = preferences.set_hidden_filters(authentication.user.id, new_preferences.hidden_filters)
    return Preferences(hidden_filters=stored)
