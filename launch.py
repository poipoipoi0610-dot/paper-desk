#!/usr/bin/env python3
"""Portable browser launcher; the server and data remain on this computer."""
import argparse
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import build_opener, ProxyHandler
import webbrowser

ROOT = Path(__file__).resolve().parent
# The Windows embeddable interpreter can omit the directory of the entry script.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_paths import data_directory, instance_identity

URL = 'http://127.0.0.1:8766'
LOCAL_HTTP = build_opener(ProxyHandler({}))


def server_state():
    """Recognize this data folder, rather than opening a different installation."""
    try:
        with LOCAL_HTTP.open(URL + '/api/bootstrap', timeout=0.7) as response:
            value = json.loads(response.read(4_000_000))
        if isinstance(value, dict) and value.get('app') == 'paper-desk':
            return 'ready' if value.get('instance') == instance_identity() else 'other-reader'
        return 'occupied'
    except (OSError, ValueError) as exc:
        # HTTP error is evidence that another service is listening.
        return 'occupied' if getattr(exc, 'code', None) else 'absent'


def preflight():
    required = ('server.py', 'app_paths.py', 'codex_bridge.py', 'pdf_engine.py',
                'zotero_client.py', 'static/index.html', 'static/app.js')
    missing = [name for name in required if not (ROOT / name).is_file()]
    if missing:
        raise RuntimeError('安装包不完整，请重新完整解压。缺少：' + ', '.join(missing))
    for name in ('codex_bridge', 'zotero_client', 'pdf_engine'):
        importlib.import_module(name)
    data = data_directory()
    try:
        data.mkdir(parents=True, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix='.write-check-', dir=data)
        os.close(fd)
        Path(probe).unlink()
    except OSError as exc:
        raise RuntimeError(f'无法保存文献到 {data}。请把整个文件夹移到你有写入权限的位置，例如 Documents；Windows 请勿放到 Program Files。') from exc


def select_address(port=None):
    global URL
    base = port or int(URL.rsplit(':', 1)[1])
    first_free = None
    for candidate in range(base, base + (1 if port else 20)):
        URL = f'http://127.0.0.1:{candidate}'
        state = server_state()
        if state == 'ready':
            return state
        if state == 'absent' and first_free is None:
            first_free = URL
    if first_free:
        URL = first_free
        return 'absent'
    return 'occupied'


def open_when_ready(stop):
    for _ in range(100):
        if stop.is_set():
            return
        if server_state() == 'ready':
            if not webbrowser.open(URL):
                print(f'请在浏览器打开：{URL}', flush=True)
            return
        stop.wait(0.2)
    if not stop.is_set():
        print(f'浏览器未自动打开，请手动访问 {URL}，或查看窗口中的错误。', flush=True)


def start_background(open_browser=True):
    """Detach the Mac server from the terminal and retain startup errors."""
    if os.name == 'nt':
        print('Windows 请使用 Start Paper Desk.bat 启动。')
        return 1
    log_dir = data_directory() / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / 'server.log'
    with log_path.open('ab') as log:
        proc = subprocess.Popen(
            [sys.executable, '-E', '-s', '-B', '-X', 'utf8', '-u', str(ROOT / 'server.py'), '--port', URL.rsplit(':', 1)[1]],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True,
        )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            print(f'阅研启动失败，请查看日志：{log_path}', file=sys.stderr)
            return 1
        if server_state() == 'ready':
            if open_browser:
                webbrowser.open(URL)
            print(f'阅研已在后台运行：{URL}\n可以关闭此窗口。日志：{log_path}', flush=True)
            return 0
        time.sleep(0.2)
    proc.terminate()
    proc.wait(timeout=5)
    print(f'阅研启动超时，请查看日志：{log_path}', file=sys.stderr)
    return 1


def main(*, background=False, open_browser=True, port=None):
    os.chdir(ROOT)
    preflight()
    state = select_address(port)
    if state == 'ready':
        if open_browser:
            webbrowser.open(URL)
        print(f'阅研已经在运行：{URL}')
        return 0
    if state == 'occupied':
        print('本机阅读端口已被占用。请关闭先前的阅读器窗口，或通过 --port 指定其他端口。')
        return 1
    if background:
        return start_background(open_browser)
    print('正在启动阅研。请保留此窗口，按 Ctrl+C 可停止。', flush=True)
    stop = threading.Event()
    if open_browser:
        browser = threading.Thread(target=open_when_ready, args=(stop,), daemon=True)
        browser.start()
    # Inherit the console so Ctrl+C reaches the server on both Windows and Mac.
    proc = subprocess.Popen([sys.executable, '-E', '-s', '-B', '-X', 'utf8', '-u', str(ROOT / 'server.py'),
                             '--port', URL.rsplit(':', 1)[1]], cwd=ROOT)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        print('\n正在停止阅研…', flush=True)
        try:
            proc.wait(timeout=8)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            proc.terminate()
            proc.wait(timeout=5)
        return 0
    finally:
        stop.set()


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser(description='Start the local Paper Desk reader')
        parser.add_argument('--background', action='store_true', help='Run in the background on Mac')
        parser.add_argument('--no-browser', action='store_true', help='Start without opening a browser')
        parser.add_argument('--port', type=int, choices=range(1024, 65536), metavar='1024-65535', help='Use a specific local port')
        args = parser.parse_args()
        raise SystemExit(main(background=args.background, open_browser=not args.no_browser, port=args.port))
    except Exception as exc:
        print(f'启动失败：{exc}', file=sys.stderr)
        raise SystemExit(1)
