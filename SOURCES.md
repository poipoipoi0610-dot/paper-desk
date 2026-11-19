# Source code and bundled components

All Paper Desk Python and browser code and the platform launch scripts are provided with the release. The project's license is [AGPL-3.0](LICENSE). The app runs as Python and static web assets, so building the app itself requires no compilation.

The platform directories under `packaging/` record the scripts, locked dependencies, and exact upstream download URLs and SHA-256 values. The same runtime manifest accompanies each portable ZIP.

- [PyMuPDF 2.0 source distribution](https://files.pythonhosted.org/packages/b0/23/3575cf6652171bba33fd4b41d34ab92c7ee75bb5e5790f5a2a044b9ba49b/pymupdf-2.0.tar.gz) · SHA-256 `7733136f626fffe98677daa53c906eb45f2eb486a6450dbcfd652cbbd760f1e2`.
- [MuPDF 1.28.5 source, including third-party dependencies](https://mupdf.com/downloads/archive/mupdf-1.28.5-source.tar.gz). This is the native PDF library used by the PyMuPDF 2.0 wheel.
- [CPython 3.13.16 source](https://www.python.org/ftp/python/3.13.16/Python-3.13.16.tar.xz) for the Windows embeddable runtime.
- [CPython 3.13.18 source](https://www.python.org/ftp/python/3.13.18/Python-3.13.18.tar.xz) and [python-build-standalone release 20261110](https://github.com/astral-sh/python-build-standalone/releases/tag/20261110) for the macOS runtime.
- [OpenAI Codex 0.169.1 source](https://github.com/openai/codex/tree/rust-v0.169.1). Codex voice runtime notices and upstream source references ship under `tools/codex/vendor/*/codex-resources/voice/`.
- Other Python dependencies retain their upstream notices and package metadata under `site-packages/`. The manifest identifies their pinned PyPI versions and wheel hashes.

To run from this repository, follow the source setup in [README.md](README.md). A portable bundle places the platform launcher at the app root next to `launch.py`, with Python under `runtime/python`, its wheel contents under `site-packages`, and the matching Codex package under `tools/codex`.
