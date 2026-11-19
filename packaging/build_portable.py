"""Build the portable release using only the tagged source and pinned upstream inputs."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import file_digest, sha256
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile

PLATFORMS = ('Windows-x64', 'macOS-arm64')
APP_FILES = (
    'LICENSE', 'README.md', 'SOURCES.md', 'THIRD_PARTY_NOTICES.txt',
    'app_paths.py', 'codex_bridge.py', 'diagnose.py', 'launch.py', 'pdf_engine.py',
    'requirements.txt', 'server.py', 'zotero_client.py', 'licenses/Codex-Apache-2.0.txt',
)
ALLOWED_HOSTS = {'www.python.org', 'github.com', 'files.pythonhosted.org', 'registry.npmjs.org'}

def hash_file(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()

def download(item, cache):
    name = item['name']
    url = urlparse(item['url'])
    if Path(name).name != name or url.scheme != 'https' or url.netloc not in ALLOWED_HOSTS:
        raise ValueError(f'Unexpected runtime source for {name}')
    path = cache / name
    scratch = path.with_suffix(path.suffix + '.part')
    if path.is_file() and hash_file(path) == item['sha256']:
        return path
    for attempt in range(3):
        try:
            headers = {'User-Agent': 'Paper Desk release builder'}
            with urlopen(Request(item['url'], headers=headers), timeout=60) as response, scratch.open('wb') as output:
                if urlparse(response.geturl()).scheme != 'https':
                    raise ValueError('A runtime archive redirected outside HTTPS.')
                shutil.copyfileobj(response, output)
            if hash_file(scratch) != item['sha256']:
                raise ValueError(f'Checksum mismatch for {name}')
            scratch.replace(path)
            return path
        except (OSError, URLError):
            if attempt == 2:
                raise
            time.sleep(1 + attempt)
        finally:
            scratch.unlink(missing_ok=True)

def safe_name(name):
    path = PurePosixPath(name)
    if not path.parts or path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError(f'Invalid archive path {name!r}')
    return path.as_posix()

class Bundle:
    def __init__(self, output, platform, date):
        self.zip = output
        self.prefix = f'PaperDesk-{platform}/'
        self.timestamp = tuple(int(part) for part in date.split('-')) + (0, 0, 0)
        self.hashes = {}

    def add(self, name, source, mode=stat.S_IFREG | 0o644):
        name = safe_name(name)
        if name in self.hashes:
            raise ValueError(f'Duplicate bundle entry {name}')
        info = zipfile.ZipInfo(self.prefix + name, self.timestamp)
        info.create_system = 3
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = mode << 16
        digest = sha256()
        with self.zip.open(info, 'w') as out:
            while chunk := source.read(1024 * 1024):
                out.write(chunk)
                digest.update(chunk)
        self.hashes[name] = digest.hexdigest()

    def text(self, name, contents):
        self.add(name, io.BytesIO(contents.encode('utf-8')))

    def file(self, name, path):
        mode = (stat.S_IFREG | 0o755) if name.endswith('.command') else (stat.S_IFREG | 0o644)
        with path.open('rb') as stream:
            self.add(name, stream, mode)

    def zip_input(self, archive, prefix, exclude=()):
        with zipfile.ZipFile(archive) as incoming:
            for entry in incoming.infolist():
                if entry.is_dir() or entry.filename in exclude:
                    continue
                with incoming.open(entry) as stream:
                    self.add(prefix + safe_name(entry.filename), stream)

    def tar_input(self, archive, prefix, root):
        with tarfile.open(archive, 'r:gz') as incoming:
            for entry in incoming:
                if entry.isdir():
                    continue
                relative = safe_name(entry.name)
                if not relative.startswith(root + '/'):
                    raise ValueError(f'Unexpected archive root for {entry.name}')
                name = prefix + relative.removeprefix(root + '/')
                if entry.issym():
                    target = posixpath.normpath(posixpath.join(posixpath.dirname(relative), entry.linkname))
                    if not target.startswith(root + '/'):
                        raise ValueError(f'Unsafe link in upstream archive: {entry.name}')
                    self.add(name, io.BytesIO(entry.linkname.encode('utf-8')), stat.S_IFLNK | 0o777)
                elif entry.isfile() or entry.islnk():
                    with incoming.extractfile(entry) as stream:
                        self.add(name, stream, stat.S_IFREG | (entry.mode & 0o777))
                else:
                    raise ValueError(f'Unsupported upstream archive entry {entry.name}')

    def finish(self):
        content = ''.join(f'{digest}  {name}\n' for name, digest in sorted(self.hashes.items()))
        self.text('files-sha256.txt', content)

def encode_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'

def build(source, platform, version, output_dir, cache):
    package_dir = source / 'packaging' / platform
    pinned = json.loads((package_dir / 'runtime-sources.json').read_bytes())
    tag = 'v' + version['version']
    output = output_dir / f'PaperDesk-{platform}-{tag}.zip'
    site = 'runtime/python/Lib/site-packages/' if platform == 'Windows-x64' else 'runtime/python/lib/python3.13/site-packages/'
    with ThreadPoolExecutor(max_workers=5) as pool:
        inputs = list(pool.map(lambda item: download(item, cache), pinned))
    with zipfile.ZipFile(output, 'w') as zipout:
        book = Bundle(zipout, platform, version['releaseDate'])
        for name, archive in zip((item['name'] for item in pinned), inputs):
            if name.startswith('python-') and name.endswith('.zip'):
                book.zip_input(archive, 'runtime/python/', exclude=('python313._pth',))
                book.text('runtime/python/python313._pth', 'python313.zip\n.\nLib/site-packages\n../..\nimport site\n')
            elif name.startswith('cpython-') and name.endswith('.tar.gz'):
                book.tar_input(archive, 'runtime/python/', 'python')
            elif name.startswith('codex-') and name.endswith('.tgz'):
                book.tar_input(archive, 'tools/codex/', 'package')
            elif name.endswith('.whl'):
                book.zip_input(archive, site)
            else:
                raise ValueError(f'Unknown runtime format: {name}')
        for name in APP_FILES:
            book.file(name, source / name)
        for directory, suffixes in (('static', {'.js', '.css', '.html', '.svg'}), ('tests', {'.py', '.mjs'})):
            for path in sorted((source / directory).iterdir()):
                if path.is_file() and path.suffix in suffixes:
                    book.file(path.relative_to(source).as_posix(), path)
        for path in sorted(package_dir.iterdir()):
            if path.is_file():
                book.file(path.name, path)
        book.text('data/.keep', '')
        book.text('version.json', encode_json(version | {'platform': platform, 'libraryPapers': 0}))
        book.finish()
    print(f'Built {output.name} ({output.stat().st_size:,} bytes)', flush=True)
    return output

def test_windows(package, folder):
    with zipfile.ZipFile(package) as archive:
        archive.extractall(folder)
    root = folder / 'PaperDesk-Windows-x64'
    python = root / 'runtime' / 'python' / 'python.exe'
    codex = root / 'tools' / 'codex' / 'vendor' / 'x86_64-pc-windows-msvc' / 'bin' / 'codex.exe'
    subprocess.run([str(codex), '--version'], cwd=root, check=True, timeout=30)
    env = os.environ | {'PAPER_DESK_DATA': str(folder / 'smoke-data')}
    subprocess.run([str(python), '-E', '-s', '-B', '-X', 'utf8', str(root / 'launch.py'), '--help'],
                   cwd=root, env=env, check=True, timeout=30)
    subprocess.run([str(python), '-E', '-s', '-B', '-X', 'utf8', '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                   cwd=root, env=env, check=True, timeout=90)

def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--source', type=Path, required=True)
    cli.add_argument('--output', type=Path, required=True)
    cli.add_argument('--test-windows', action='store_true')
    args = cli.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    version = json.loads((source / 'version.json').read_bytes())
    with tempfile.TemporaryDirectory(prefix='paper-desk-build-') as work:
        cache = Path(work)
        assets = [build(source, platform, version, output, cache) for platform in PLATFORMS]
        if args.test_windows:
            if os.name != 'nt':
                raise RuntimeError('--test-windows requires Windows')
            test_windows(assets[0], cache / 'test')
    (output / 'SHA256SUMS.txt').write_text(
        ''.join(f'{hash_file(asset)}  {asset.name}\n' for asset in sorted(assets)), encoding='ascii', newline='\n')

if __name__ == '__main__':
    main()
