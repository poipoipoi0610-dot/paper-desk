import json
import os
from pathlib import Path, PureWindowsPath
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from codex_bridge import MAC_CHATGPT_CODEX, find_codex
from app_paths import instance_identity
from zotero_client import local_file_path, ZoteroError
import launch


class WindowsPathsTests(unittest.TestCase):
    def test_zotero_windows_drive_and_unicode(self):
        self.assertEqual(
            local_file_path('file:///C:/Users/%E4%B8%AD%E6%96%87/Zotero/paper%20%231.pdf', 'nt'),
            PureWindowsPath('C:/Users/中文/Zotero/paper #1.pdf'))
        self.assertEqual(
            local_file_path('file://localhost/D:/My%20Library/a.pdf', 'nt'),
            PureWindowsPath('D:/My Library/a.pdf'))

    def test_zotero_rejects_remote_device_and_relative_paths(self):
        for uri in ['https://example.org/a.pdf', 'file://server/share/a.pdf',
                    'file:////server/share/a.pdf', 'file:////?/C:/a.pdf',
                    'file:///relative/a.pdf', 'file:C:a.pdf', 'file:///C:/a%00.pdf',
                    'file:///C:/a.pdf?download=1']:
            with self.subTest(uri=uri), self.assertRaises(ZoteroError):
                local_file_path(uri, 'nt')

    def test_posix_unicode_path_is_preserved(self):
        self.assertEqual(str(local_file_path('file:///Users/%E4%B8%AD%E6%96%87/paper%20one.pdf', 'posix')),
                         '/Users/中文/paper one.pdf')

    def test_bundled_codex_wins_over_global_npm_shim(self):
        with tempfile.TemporaryDirectory(prefix='阅研 portable ') as tmp:
            root = Path(tmp)
            native = root / 'tools/codex/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
            native.parent.mkdir(parents=True)
            native.touch()
            shim = root / 'codex.cmd'
            shim.touch()
            with patch.dict(os.environ, {}, clear=True), patch('codex_bridge.shutil.which', return_value=str(shim)):
                self.assertEqual(find_codex(root, 'win32'), str(native.resolve()))
                native.unlink()
                with self.assertRaises(RuntimeError):
                    find_codex(root, 'win32')

    def test_explicit_native_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            native = Path(tmp) / 'my codex.exe'
            native.touch()
            with patch.dict(os.environ, {'PAPER_DESK_CODEX': str(native)}):
                self.assertEqual(find_codex(Path(tmp), 'win32'), str(native.resolve()))

    def test_mac_uses_chatgpt_codex_with_bundled_fallback(self):
        with tempfile.TemporaryDirectory(prefix='阅研 portable ') as tmp:
            root = Path(tmp)
            native = root / 'tools/codex/vendor/aarch64-apple-darwin/bin/codex'
            global_install = Path('/other/codex')
            available = {native, global_install}
            with patch.dict(os.environ, {}, clear=True), \
                 patch('codex_bridge.host_platform.machine', return_value='arm64'), \
                 patch('codex_bridge.shutil.which', return_value=str(global_install)), \
                 patch.object(Path, 'is_file', lambda path: path in available):
                self.assertEqual(find_codex(root, 'darwin'), str(native.resolve()))
                available.add(MAC_CHATGPT_CODEX)
                self.assertEqual(find_codex(root, 'darwin'), str(MAC_CHATGPT_CODEX.resolve()))


class LauncherTests(unittest.TestCase):
    def test_incomplete_package_reports_the_missing_module(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(launch, 'ROOT', Path(tmp)):
            with self.assertRaisesRegex(RuntimeError, 'codex_bridge.py'):
                launch.preflight()

    def test_relocated_reader_does_not_open_another_data_folder(self):
        states = ['other-reader', 'absent', 'ready']
        with patch.object(launch, 'URL', 'http://127.0.0.1:8766'), \
             patch.object(launch, 'server_state', side_effect=states):
            self.assertEqual(launch.select_address(), 'ready')
            self.assertEqual(launch.URL, 'http://127.0.0.1:8768')

    def test_explicit_occupied_port_does_not_open_another_reader(self):
        with patch.object(launch, 'URL', 'http://127.0.0.1:8766'), \
             patch.object(launch, 'server_state', return_value='other-reader'):
            self.assertEqual(launch.select_address(9876), 'occupied')

    def test_data_directory_write_failure_has_actionable_error(self):
        with patch('launch.tempfile.mkstemp', side_effect=PermissionError):
            with self.assertRaisesRegex(RuntimeError, 'Program Files'):
                launch.preflight()


class PortableServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='阅研 portable ')
        data = Path(cls.temp.name) / '论文 data'
        cls.data = data
        folder = data / ('a' * 24)
        folder.mkdir(parents=True)
        fixture = {'id': folder.name, 'title': '中文迁移测试', 'titleZh': '中文标题',
                   'createdAt': '2026-01-01', 'status': 'ready', 'pages': [],
                   'chat': [{'role': 'user', 'text': '中文伴读记录'}], 'framework': None}
        (folder / 'paper.json').write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.url = f'http://127.0.0.1:{port}'
        cls.opener = build_opener(ProxyHandler({}))
        cls.log = (Path(cls.temp.name) / 'server.log').open('wb')
        cls.proc = subprocess.Popen([sys.executable, '-E', '-s', '-B', '-X', 'utf8', str(ROOT/'server.py'), '--port', str(port)],
                                    env={**os.environ, 'PAPER_DESK_DATA': str(data)},
                                    stdout=cls.log, stderr=subprocess.STDOUT, cwd=ROOT)
        for _ in range(100):
            try:
                with cls.opener.open(cls.url + '/api/bootstrap', timeout=0.3):
                    return
            except OSError:
                if cls.proc.poll() is not None:
                    raise RuntimeError('Server failed: ' + (Path(cls.temp.name)/'server.log').read_text(encoding='utf-8'))
                time.sleep(0.05)
        raise RuntimeError('Server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        cls.log.close()
        cls.temp.cleanup()

    def test_utf8_library_and_conversation_survive_restart(self):
        with self.opener.open(self.url + '/api/papers/' + 'a'*24) as response:
            paper = json.load(response)
        self.assertEqual(paper['titleZh'], '中文标题')
        self.assertEqual(paper['chat'][0]['text'], '中文伴读记录')

    def test_module_and_page_mime_types(self):
        for route, expected in [('/app.js', 'text/javascript'), ('/sync.js', 'text/javascript'),
                                ('/theme.css', 'text/css'), ('/', 'text/html')]:
            with self.subTest(route=route), self.opener.open(self.url + route) as response:
                self.assertEqual(response.headers.get_content_type(), expected)
                self.assertGreater(len(response.read()), 100)

    def test_launcher_detects_existing_reader(self):
        with patch.object(launch, 'URL', self.url), patch('launch.webbrowser.open') as browser, \
             patch.dict(os.environ, {'PAPER_DESK_DATA': str(self.data)}):
            self.assertEqual(launch.server_state(), 'ready')
            self.assertEqual(launch.main(), 0)
            browser.assert_called_once_with(self.url)

    def test_running_reader_for_different_data_is_recognized(self):
        with patch.object(launch, 'URL', self.url), \
             patch.dict(os.environ, {'PAPER_DESK_DATA': str(self.data / 'another-copy')}):
            self.assertEqual(launch.server_state(), 'other-reader')


if __name__ == '__main__':
    unittest.main()
