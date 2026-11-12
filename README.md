# pictorio-db

Image library server for [Pictorio](https://github.com/OesusDevelopmentStudios/pictorio).

pictorio-db stores your images in a library folder, arranges them by their tags and keeps a database
of tags and metadata. The Pictorio desktop app connects to it to search, browse, tag and upload
images. A web page on the server is used to configure it.

It runs on a desktop PC, a NAS or a Raspberry Pi (64-bit systems only).

> **Status:** early development. There is nothing to use yet.

## Development

Needs Python 3.12 or newer.

Set up a virtual environment in the repository and install the project with its development tools:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Run the tests and the style check:

```sh
pytest
flake8
```

Run the server (in the virtual environment):

```sh
pictorio-db serve
curl http://127.0.0.1:8737/api/v1/server/info
```

On the first start the server logs a one-time **setup code**. Open
<http://127.0.0.1:8737/admin/setup>, enter the code and create the first admin account. Until then,
the server prints a new code every time it starts.

The interactive API documentation is at <http://127.0.0.1:8737/api/docs>.

| Environment variable | Default | Meaning |
|---|---|---|
| `PICTORIO_HOST` | `127.0.0.1` | Address to listen on. `0.0.0.0` makes the server reachable from other computers |
| `PICTORIO_PORT` | `8737` | Port to listen on |
| `PICTORIO_DATA_DIR` | `~/.local/share/pictorio-db` | Folder for the database. Created if missing |
| `PICTORIO_LIBRARY_DIR` | `~/Pictures/pictorio-library` | Folder for the images, arranged by their tags. Created if missing |
| `PICTORIO_IMPORT_DIR` | not set | Folder that admins can import from with an import job, e.g. a NAS share. Unset: no folder imports |

During development, point `PICTORIO_DATA_DIR` and `PICTORIO_LIBRARY_DIR` at scratch folders to keep
test data out of your home folder, e.g.
`PICTORIO_DATA_DIR=/tmp/pictorio-dev/data PICTORIO_LIBRARY_DIR=/tmp/pictorio-dev/library pictorio-db serve`.
The tests always use temporary folders of their own.

The API schema is committed as [docs/openapi.json](docs/openapi.json), and a test checks that it
matches the code. After an intended API change, update it with:

```sh
pictorio-db openapi > docs/openapi.json
```

## Container

The [Containerfile](Containerfile) builds an image for amd64 or arm64 (64-bit Raspberry Pi):

```sh
mkdir -p ~/Pictures/pictorio-library
podman build -t pictorio-db .
podman run -d --name pictorio-db -p 8737:8737 \
    -v pictorio-data:/data -v ~/Pictures/pictorio-library:/library:Z pictorio-db
curl http://127.0.0.1:8737/api/v1/server/info
```

The database is in the volume mounted at `/data` (here the named volume `pictorio-data`) and the
images in the folder mounted at `/library`, so both are kept when the container is removed or the
image is updated. `:Z` lets the container use the folder on systems with SELinux.

To import folders that are already on the server, mount them at `/import`, e.g.
`-v /srv/photos-inbox:/import:ro,Z`. Mount it without `ro` if the import should remove the originals.

On an amd64 PC, `podman build --platform linux/arm64 -t pictorio-db:arm64 .` builds the arm64 image;
it needs QEMU's user-mode emulation (Fedora: `qemu-user-static-aarch64`). That build replaces the
local copy of the Python base image with its arm64 variant, so build the normal image with
`podman build --platform linux/amd64 -t pictorio-db .` afterwards. The image also works with Docker.

The server in the container runs as user `pictorio` (UID 1000), not as root.

### Starting it with systemd

[deploy/pictorio-db.container](deploy/pictorio-db.container) is a Podman Quadlet unit. After
building the image, as your normal user:

```sh
mkdir -p ~/Pictures/pictorio-library ~/.config/containers/systemd
cp deploy/pictorio-db.container ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user start pictorio-db
```

To start it at boot without logging in: `loginctl enable-linger $USER`.

## License

GPL-3.0-or-later, see [LICENSE](LICENSE).
