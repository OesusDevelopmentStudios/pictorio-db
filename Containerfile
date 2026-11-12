# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios
#
# Container image for pictorio-db (amd64 and arm64). Build and run:
#
#   podman build -t pictorio-db .
#   podman run -d --name pictorio-db -p 8737:8737 \
#       -v pictorio-data:/data -v ~/Pictures/pictorio-library:/library:Z pictorio-db

# The Debian release is named, so a rebuild does not switch the system underneath.
FROM docker.io/library/python:3.14-slim-trixie

# No .pyc files in the image, log lines appear at once, no pip cache or update checks
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt/pictorio-db
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install .

# The server does not need root. UID 1000 is the first user account on most systems, so files it
# writes into mounted folders can belong to that user.
RUN groupadd --gid 1000 pictorio \
    && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin pictorio \
    && mkdir /data /library /import \
    && chown pictorio:pictorio /data /library /import
USER pictorio

# Listen on all interfaces inside the container; publish the port with -p 8737:8737.
# Mount volumes at /data and /library, or the database and the images are lost when the container
# is removed. Folders to import from can be mounted at /import.
ENV PICTORIO_HOST=0.0.0.0 \
    PICTORIO_PORT=8737 \
    PICTORIO_DATA_DIR=/data \
    PICTORIO_LIBRARY_DIR=/library \
    PICTORIO_IMPORT_DIR=/import
EXPOSE 8737

CMD ["pictorio-db", "serve"]
