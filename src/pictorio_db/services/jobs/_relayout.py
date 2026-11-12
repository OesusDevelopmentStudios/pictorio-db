# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import logging
from typing import Any

from pictorio_db.services.images import ImagesService
from pictorio_db.services.jobs._service import JobContext, JobInfo, JobKind, JobsService

_logger = logging.getLogger(__name__)


class Relayout:
    """Moves every image's file to where the path template places it, after the template changed. Images
    imported or retagged meanwhile already follow the new template."""

    def __init__(self, jobs: JobsService, images: ImagesService) -> None:
        self._jobs = jobs
        self._images = images

    def start(self, user_id: int | None) -> JobInfo:
        return self._jobs.submit(JobKind.RELAYOUT, {}, user_id)

    def run(self, context: JobContext) -> dict[str, Any]:
        image_ids = self._images.all_image_ids()
        moved = 0
        failed: list[dict[str, Any]] = []
        context.report_progress(0, len(image_ids))
        for done, image_id in enumerate(image_ids, start=1):
            try:
                moved += self._images.move_file_to_layout(image_id)
            except Exception:
                _logger.exception("Could not move the file of image %s to the new layout", image_id)
                failed.append({"image_id": image_id, "code": "move_failed"})  # it stays where it was

            context.report_progress(done, len(image_ids))

        return {"moved": moved, "unchanged": len(image_ids) - moved - len(failed), "failed": failed}
