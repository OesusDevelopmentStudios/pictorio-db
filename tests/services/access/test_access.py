# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from datetime import datetime

import pytest
from sqlalchemy import delete, select

from pictorio_db.db import Database
from pictorio_db.db.models import Image, Namespace, Tag, User, image_tag
from pictorio_db.services.access import AccessService, Restrictions
from pictorio_db.services.auth import AuthService, Role, UserInfo
from pictorio_db.services.tags import TagName
from pictorio_db.utils.problems import Problem

NAMESPACES = {"category", "author", "character", "rating", "album", "general"}

# name → (tags, taken_at)
LIBRARY = {
    "safe_photo": (["category:photo", "rating:sfw", "general:beach"], datetime(2024, 5, 1)),
    "nsfw_art": (["category:artwork", "rating:nsfw"], datetime(2024, 5, 2)),
    "hero_art": (["category:artwork", "character:hero"], datetime(2024, 5, 3)),
    "nude_art": (["category:artwork", "general:nude"], datetime(2024, 5, 4)),
    "nude_photo": (["general:nude", "general:photo"], datetime(2024, 5, 5)),
    "old_untagged": ([], datetime(2020, 1, 1)),
}


def tags(*texts: str) -> list[TagName]:
    return [TagName(*text.split(":")) for text in texts]


@pytest.fixture
def access(database: Database) -> AccessService:
    return AccessService(database, lambda: NAMESPACES)


@pytest.fixture
def users(database: Database) -> dict[str, UserInfo]:
    auth = AuthService(database)
    return {
        "kid": auth.create_user("kid", "correct horse battery", Role.USER),
        "admin": auth.create_user("apo", "correct horse battery", Role.ADMIN),
    }


@pytest.fixture
def library(database: Database) -> Database:
    with database.session() as session:
        namespace_rows = session.execute(select(Namespace.name, Namespace.id))
        namespace_ids = {name: namespace_id for name, namespace_id in namespace_rows}
        tag_ids: dict[str, int] = {}
        for number, (name, (tag_texts, taken_at)) in enumerate(LIBRARY.items()):
            image = Image(
                sha256=f"{number:064x}", storage_path=name, original_filename=name, mime_type="image/jpeg",
                width=1, height=1, file_size=1, taken_at=taken_at, taken_at_source="exif",
                imported_at=taken_at, updated_at=taken_at,
            )
            session.add(image)
            session.flush()
            for tag_text in tag_texts:
                if tag_text not in tag_ids:
                    namespace, tag_name = tag_text.split(":")
                    tag = Tag(namespace_id=namespace_ids[namespace], name=tag_name)
                    session.add(tag)
                    session.flush()
                    tag_ids[tag_text] = tag.id

                session.execute(image_tag.insert().values(image_id=image.id, tag_id=tag_ids[tag_text]))

        session.commit()

    return database


def restrictions(access: AccessService, user: UserInfo, terms: list[str]) -> Restrictions:
    access.set_restricted_terms(user.id, terms)
    return access.restrictions_for(user)


def visible(database: Database, user_restrictions: Restrictions) -> set[str]:
    with database.session() as session:
        return set(session.scalars(select(Image.original_filename).where(user_restrictions.visible_images_filter())))


# --- Storing restrictions

def test_no_restrictions_until_set(access: AccessService, users: dict[str, UserInfo]) -> None:
    assert access.restricted_terms(users["kid"].id) == []
    assert not access.restrictions_for(users["kid"]).active


def test_replaces_the_whole_list_sorted_and_without_repeats(access: AccessService, users: dict[str, UserInfo]) -> None:
    access.set_restricted_terms(users["kid"].id, ["rating:nsfw", "character:*"])
    stored = access.set_restricted_terms(users["kid"].id, [" rating:nsfw ", "category:refs", "rating:nsfw"])

    assert stored == ["category:refs", "rating:nsfw"]
    assert access.restricted_terms(users["kid"].id) == stored


def test_terms_may_name_tags_that_do_not_exist_yet(access: AccessService, users: dict[str, UserInfo]) -> None:
    assert access.set_restricted_terms(users["kid"].id, ["rating:explicit"]) == ["rating:explicit"]


@pytest.mark.parametrize("term", ["two terms", "-rating:nsfw", "(a"])
def test_refuses_invalid_terms(access: AccessService, users: dict[str, UserInfo], term: str) -> None:
    with pytest.raises(Problem) as raised:
        access.set_restricted_terms(users["kid"].id, ["rating:nsfw", term])

    assert raised.value.extra["errors"][0]["field"] == "body.restricted_tags.1"
    assert access.restricted_terms(users["kid"].id) == []


def test_admins_are_never_restricted(access: AccessService, users: dict[str, UserInfo]) -> None:
    access.set_restricted_terms(users["admin"].id, ["rating:nsfw"])

    assert access.restricted_terms(users["admin"].id) == ["rating:nsfw"]  # kept, in case the role changes
    assert not access.restrictions_for(users["admin"]).active


def test_restrictions_go_with_the_user(access: AccessService, users: dict[str, UserInfo], database: Database) -> None:
    access.set_restricted_terms(users["kid"].id, ["rating:nsfw"])

    with database.session() as session:
        session.execute(delete(User).where(User.id == users["kid"].id))
        session.commit()

    assert access.restricted_terms(users["kid"].id) == []


# --- Which images a restricted user sees

@pytest.mark.parametrize(
    ("terms", "hidden"),
    [
        (["rating:nsfw"], {"nsfw_art"}),
        (["rating:nsfw|questionable"], {"nsfw_art"}),
        (["character:*"], {"hero_art"}),
        (["general:nude,photo"], {"nude_photo"}),  # nude artworks stay visible
        (["category:artwork", "year:2020"], {"nsfw_art", "hero_art", "nude_art", "old_untagged"}),
    ],
)
def test_hides_images_matching_any_term(
    access: AccessService, users: dict[str, UserInfo], library: Database, terms: list[str], hidden: set[str]
) -> None:
    assert visible(library, restrictions(access, users["kid"], terms)) == set(LIBRARY) - hidden


def test_unrestricted_user_sees_everything(
    access: AccessService, users: dict[str, UserInfo], library: Database
) -> None:
    assert visible(library, access.restrictions_for(users["kid"])) == set(LIBRARY)


# --- Which tags a restricted user may use

def test_refuses_tags_that_would_restrict_the_image(access: AccessService, users: dict[str, UserInfo]) -> None:
    user_restrictions = restrictions(access, users["kid"], ["rating:nsfw", "general:nude,photo"])

    with pytest.raises(Problem) as raised:
        user_restrictions.check_tags_allowed(tags("category:photo", "general:nude", "general:photo"), None)

    assert (raised.value.status, raised.value.code) == (403, "tag_restricted")
    assert raised.value.extra["tags"] == ["general:nude", "general:photo"]


def test_allows_tags_that_keep_the_image_visible(access: AccessService, users: dict[str, UserInfo]) -> None:
    user_restrictions = restrictions(access, users["kid"], ["rating:nsfw", "general:nude,photo"])

    user_restrictions.check_tags_allowed(tags("category:artwork", "general:nude"), None)


def test_names_the_restricted_tag(access: AccessService, users: dict[str, UserInfo]) -> None:
    user_restrictions = restrictions(access, users["kid"], ["rating:nsfw"])

    with pytest.raises(Problem) as raised:
        user_restrictions.check_tags_allowed(tags("general:beach", "rating:nsfw"), None)

    assert raised.value.extra["tags"] == ["rating:nsfw"]


@pytest.mark.parametrize(
    ("tag", "hidden"),
    [
        ("rating:nsfw", True),
        ("rating:sfw", False),
        ("character:hero", True),  # character:* hides every character
        ("general:nude", False),  # restricted only together with general:photo
    ],
)
def test_hides_restricted_tags_from_autocomplete(
    access: AccessService, users: dict[str, UserInfo], tag: str, hidden: bool
) -> None:
    user_restrictions = restrictions(access, users["kid"], ["rating:nsfw", "character:*", "general:nude,photo"])

    assert user_restrictions.is_tag_hidden(tags(tag)[0]) is hidden


def test_lists_the_users_whose_restrictions_apply(access: AccessService, users: dict[str, UserInfo]) -> None:
    access.set_restricted_terms(users["kid"].id, ["rating:nsfw"])
    access.set_restricted_terms(users["admin"].id, ["rating:nsfw"])  # an admin: never restricted

    restricted = access.restricted_users()

    assert list(restricted) == ["kid"]
    assert not restricted["kid"].is_visible(tags("rating:nsfw"), None)
