# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""How large an image may be. Decoding needs memory in proportion to the pixel count, so huge images could
exhaust a small server (a Raspberry Pi). JPEGs are decoded at a fraction of their size for thumbnails, so
they may be much larger than other formats.

Importing this module raises Pillow's own limit, which applies to every format, to the JPEG limit; the
importer checks each format's limit itself."""

from PIL import Image

JPEG_MAX_PIXELS = 1_000_000_000
OTHER_MAX_PIXELS = 178_956_970  # Pillow's default limit
_JPEG_FORMATS = {"JPEG", "MPO"}

# Pillow refuses images over twice this value and warns above it.
Image.MAX_IMAGE_PIXELS = JPEG_MAX_PIXELS


def max_pixels(pillow_format: str) -> int:
    return JPEG_MAX_PIXELS if pillow_format in _JPEG_FORMATS else OTHER_MAX_PIXELS
