# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Renaming, merging and deleting tags, with real files and the real worker."""

import time
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import pytest
from PIL import ExifTags, Image

from pictorio_db.db import Database
from pictorio_db.services.access import AccessService, Restrictions
from pictorio_db.services.auth import AuthService, Role
from pictorio_db.services.images import ImageRecord, ImagesService
from pictorio_db.services.importer import ImporterService, UploadMetadata
from pictorio_db.services.jobs import JobInfo, JobKind, JobsService, JobStatus, Relayout
from pictorio_db.services.preferences import PreferencesService
from pictorio_db.services.settings import SettingsService
from pictorio_db.services.storage import StorageService
from pictorio_db.services.tag_admin import TagAdmin
from pictorio_db.services.tags import TagName, TagsService
from pictorio_db.services.thumbnails import ThumbnailsService
from pictorio_db.utils.problems import Problem


class Library:
    def __init__(self, database: Database, tmp_path: Path) -> None:
        self.library_dir = tmp_path / "library"
        settings = SettingsService(database)
        self.tags = TagsService(database, lambda: self.storage.path_template_namespaces())
        self.storage = StorageService(database, settings, self.library_dir, self.tags.namespace_names)
        self.images = ImagesService(database, self.tags, self.storage)
        thumbnails = ThumbnailsService(tmp_path / "thumbnails")
        self.importer = ImporterService(self.images, self.tags, self.storage, thumbnails, settings)
        self.access = AccessService(database, self.tags.namespace_names)
        self.preferences = PreferencesService(database, self.tags.namespace_names)
        self.jobs = JobsService(database)
        relayout = Relayout(self.jobs, self.images)
        self.jobs.register(JobKind.RELAYOUT, relayout.run)
        self.tag_admin = TagAdmin(self.tags, self.images, self.access, self.preferences, self.storage, relayout)
        auth = AuthService(database)
        self.admin = auth.create_user("apo", "correct horse battery", Role.ADMIN)
        self.kid = auth.create_user("kid", "correct horse battery", Role.USER)

    def add_image(self, colour: str, tags: tuple[str, ...]) -> ImageRecord:
        """Taken in 2024, so its folder is <category>/<author>/2024."""
        incoming = self.importer.new_incoming_path()
        exif = Image.Exif()
        exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = "2024:05:01 10:00:00"
        Image.new("RGB", (8, 8), colour).save(incoming, format="JPEG", exif=exif)
        return self.importer.import_image(incoming, UploadMetadata(f"{colour}.jpg", tags=tags), None, Restrictions([]))

    def rename(self, old_tag: str, new_tag: str) -> tuple[TagName, JobInfo | None]:
        return self.tag_admin.rename_tag(TagName(*old_tag.split(":")), new_tag, self.admin.id)

    def delete(self, tag: str) -> JobInfo | None:
        return self.tag_admin.delete_tag(TagName(*tag.split(":")), self.admin.id)

    def tags_of(self, image: ImageRecord) -> list[str]:
        return [str(tag) for tag in self.images.get_image(image.id).tags]

    def folder_of(self, image: ImageRecord) -> str:
        return str(PurePosixPath(self.images.get_image(image.id).storage_path).parent)

    def exists(self, tag: str) -> bool:
        return self.tags.tag_exists(TagName(*tag.split(":")))

    def wait_for(self, job: JobInfo | None) -> JobInfo:
        assert job is not None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = self.jobs.get_job(job.id, self.admin)
            if job.status in (JobStatus.DONE, JobStatus.FAILED):
                return job

            time.sleep(0.01)

        raise AssertionError("The job did not finish in time")


@pytest.fixture
def library(database: Database, tmp_path: Path) -> Iterator[Library]:
    started = Library(database, tmp_path)
    started.jobs.start()
    yield started
    started.jobs.stop()


def problem_of(action: object) -> Problem:
    with pytest.raises(Problem) as raised:
        action()  # type: ignore[operator]
    return raised.value


# --- Renaming and merging

def test_renames_a_tag_on_every_image(library: Library) -> None:
    images = [library.add_image(colour, ("sunset",)) for colour in ("red", "green")]

    new_tag, job = library.rename("general:sunset", "Golden Hour")

    assert (str(new_tag), job) == ("general:golden_hour", None)  # general forms no folder: nothing moves
    assert [library.tags_of(image) for image in images] == [["general:golden_hour"]] * 2
    assert not library.exists("general:sunset")


def test_merges_into_an_existing_tag(library: Library) -> None:
    both = library.add_image("red", ("sea", "ocean"))
    one = library.add_image("green", ("sea",))

    library.rename("general:sea", "ocean")

    assert library.tags_of(both) == library.tags_of(one) == ["general:ocean"]
    assert not library.exists("general:sea")


def test_renaming_a_folder_tag_moves_the_files(library: Library) -> None:
    image = library.add_image("red", ("category:photo", "author:anon_one"))

    _new_tag, job = library.rename("author:anon_one", "author:anon_two")

    assert library.wait_for(job).result == {"moved": 1, "unchanged": 0, "failed": []}
    assert library.folder_of(image) == "photo/anon_two/2024"
    assert (library.library_dir / library.images.get_image(image.id).storage_path).is_file()


def test_new_tag_in_a_single_value_namespace_replaces_the_current_one(library: Library) -> None:
    image = library.add_image("red", ("category:photo", "painting"))

    _new_tag, job = library.rename("general:painting", "category:artwork")

    library.wait_for(job)
    assert library.tags_of(image) == ["category:artwork"]
    assert library.folder_of(image) == "artwork/_unknown/2024"


def test_tag_without_images_is_renamed_too(library: Library) -> None:
    image = library.add_image("red", ("sunset",))
    library.images.change_tags(image.id, add_tags=[], remove_tags=["sunset"], restrictions=Restrictions([]))

    assert library.rename("general:sunset", "dusk") == (TagName("general", "dusk"), None)
    assert library.exists("general:dusk") and not library.exists("general:sunset")


def test_renaming_to_the_same_tag_changes_nothing(library: Library) -> None:
    image = library.add_image("red", ("sunset",))

    assert library.rename("general:sunset", "Sunset") == (TagName("general", "sunset"), None)
    assert library.tags_of(image) == ["general:sunset"]


@pytest.mark.parametrize("new_tag", ["sunset", "dusk"])
def test_unknown_tag_is_not_found(library: Library, new_tag: str) -> None:
    assert problem_of(lambda: library.rename("general:sunset", new_tag)).status == 404


def test_invalid_new_tag_changes_nothing(library: Library) -> None:
    image = library.add_image("red", ("rating:sfw",))

    problem = problem_of(lambda: library.rename("rating:sfw", "rating:safe"))  # not an allowed rating

    assert problem.code == "invalid_tag"
    assert library.tags_of(image) == ["rating:sfw"]


# --- Deleting

def test_deletes_a_tag_from_every_image(library: Library) -> None:
    images = [library.add_image(colour, ("sunset", "beach")) for colour in ("red", "green")]

    assert library.delete("general:sunset") is None
    assert [library.tags_of(image) for image in images] == [["general:beach"]] * 2
    assert not library.exists("general:sunset")


def test_deleting_a_folder_tag_moves_the_files(library: Library) -> None:
    image = library.add_image("red", ("category:photo", "author:anon_one"))

    library.wait_for(library.delete("author:anon_one"))

    assert library.folder_of(image) == "photo/_unknown/2024"


def test_deleting_an_unknown_tag_is_not_found(library: Library) -> None:
    assert problem_of(lambda: library.delete("general:sunset")).status == 404


# --- Restrictions and hidden filters follow

def test_restrictions_and_hidden_filters_follow_a_rename(library: Library) -> None:
    library.tags.set_rating_values(["sfw", "nsfw", "explicit"])
    library.access.set_restricted_terms(library.kid.id, ["rating:nsfw", "character:*"])
    library.preferences.set_hidden_filters(library.kid.id, ["rating:nsfw|sfw", "beach"])
    image = library.add_image("red", ("rating:nsfw",))

    library.rename("rating:nsfw", "rating:explicit")

    assert library.access.restricted_terms(library.kid.id) == ["character:*", "rating:explicit"]
    assert library.preferences.hidden_filters(library.kid.id) == ["rating:explicit|rating:sfw", "beach"]
    kid_restrictions = library.access.restrictions_for(library.kid)
    assert not library.images.is_visible(image.id, kid_restrictions)  # still hidden from the kid


def test_restrictions_and_hidden_filters_lose_a_deleted_tag(library: Library) -> None:
    library.access.set_restricted_terms(library.kid.id, ["rating:nsfw", "category:photo,rating:nsfw", "character:*"])
    library.preferences.set_hidden_filters(library.kid.id, ["rating:nsfw|sfw"])
    image = library.add_image("red", ("rating:nsfw",))

    library.delete("rating:nsfw")

    assert library.access.restricted_terms(library.kid.id) == ["character:*"]
    assert library.preferences.hidden_filters(library.kid.id) == ["rating:sfw"]
    assert library.images.is_visible(image.id, library.access.restrictions_for(library.kid))  # expected


def test_unknown_tag_leaves_the_lists_alone(library: Library) -> None:
    library.access.set_restricted_terms(library.kid.id, ["rating:nsfw"])

    problem_of(lambda: library.delete("rating:nsfw"))  # no image ever had it, so it does not exist

    assert library.access.restricted_terms(library.kid.id) == ["rating:nsfw"]
