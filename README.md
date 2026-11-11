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

## License

GPL-3.0-or-later, see [LICENSE](LICENSE).
