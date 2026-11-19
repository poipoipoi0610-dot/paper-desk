"""Read-only Zotero Desktop integration. No credentials or direct database access."""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, unquote
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class ZoteroError(ValueError):
    pass


def local_file_path(uri, platform=None):
    """Decode Zotero's local file URI using the target platform's path rules."""
    platform = platform or os.name
    parsed = urlparse(uri)
    if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost') or parsed.query or parsed.fragment:
        raise ZoteroError('PDF 尚未保存在本机，请先在 Zotero 中打开并下载附件。')
    if platform == 'nt':
        from nturl2path import url2pathname
        try:
            path = PureWindowsPath(url2pathname(parsed.path))
        except OSError:
            raise ZoteroError('Zotero 附件路径无效。') from None
        # A local drive is required; reject UNC and device paths.
        if not re.fullmatch(r'[A-Za-z]:', path.drive):
            raise ZoteroError('Zotero 附件需要位于本机磁盘，请先下载到本机。')
    else:
        path = PurePosixPath(unquote(parsed.path))
    if not path.is_absolute() or '\x00' in str(path):
        raise ZoteroError('Zotero 附件路径无效。')
    return path


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def library_path(library):
    if library == 'user':
        return '/users/0'
    if re.fullmatch(r'group:[1-9][0-9]{0,14}', library):
        return '/groups/' + library.split(':')[1]
    raise ZoteroError('文献库标识无效。')


def item_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Z0-9]{8}', value):
        raise ZoteroError('文献标识无效，请刷新文献列表。')
    return value


def is_pdf(data):
    return data.get('contentType') == 'application/pdf' or str(data.get('filename', '')).lower().endswith('.pdf')


def normalize_catalog(top, attachments, collections):
    """Only pass bibliographic fields to the browser; omit local paths and notes."""
    by_parent = {}
    for row in attachments:
        d = row['data']
        if d.get('deleted') or not is_pdf(d):
            continue
        by_parent.setdefault(d.get('parentItem') or row['key'], []).append({
            'key': row['key'], 'title': d.get('title') or d.get('filename') or 'PDF',
            'filename': d.get('filename', ''), 'linkMode': d.get('linkMode', ''),
        })
    items = []
    for row in top:
        d = row['data']
        if d.get('deleted') or d.get('parentItem') or d.get('itemType') in ('note', 'annotation'):
            continue
        if d.get('itemType') == 'attachment' and not is_pdf(d):
            continue
        creators = [' '.join(filter(None, [c.get('firstName'), c.get('lastName')])) or c.get('name', '')
                    for c in d.get('creators', [])]
        year = re.search(r'\b(?:19|20)\d{2}\b', d.get('date', ''))
        items.append({'key': row['key'], 'title': d.get('title') or '未命名文献',
                      'authors': ', '.join(creators), 'year': year[0] if year else '',
                      'type': d.get('itemType', ''), 'doi': d.get('DOI', ''),
                      'tags': [t['tag'] for t in d.get('tags', []) if t.get('tag')],
                      'collections': d.get('collections', []), 'dateAdded': d.get('dateAdded', ''),
                      'pdfs': by_parent.get(row['key'], [])})
    return {'items': items, 'collections': [
        {'key': c['key'], 'name': c['data']['name'], 'parent': c['data'].get('parentCollection') or None}
        for c in collections if not c['data'].get('deleted')]}


class ZoteroClient:
    def __init__(self):
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.lock = threading.RLock()
        self.cache = {}

    def request(self, route, params=None, server_id=None, raw=False):
        # All routes are constructed here; never accept a browser-supplied URL or file path.
        url = 'http://127.0.0.1:23119/api' + route
        if params:
            url += '?' + urlencode(params, doseq=True)
        headers = {'Zotero-API-Version': '3', 'Accept': 'application/json'}
        if server_id:
            headers['Zotero-Server-ID'] = server_id
        try:
            with self.opener.open(Request(url, headers=headers), timeout=12) as response:
                data = response.read(16 * 1024 * 1024 + 1)
                if len(data) > 16 * 1024 * 1024:
                    raise ZoteroError('Zotero 返回的数据过大，请稍后重试。')
                return (data if raw else json.loads(data)), response.headers
        except HTTPError as e:
            messages = {403: '请在 Zotero「设置 → 高级」开启「允许此计算机上的其他应用程序与 Zotero 通信」。',
                        404: '这篇文献或附件已移动、删除，或 PDF 尚未下载到本机。请在 Zotero 中打开它后重试。',
                        412: 'Zotero 文献库已切换，请刷新列表后重新选择。'}
            raise ZoteroError(messages.get(e.code, f'Zotero 暂时无法读取（HTTP {e.code}），请重试。')) from None
        except (URLError, TimeoutError, ConnectionError):
            raise ZoteroError('无法连接 Zotero。请先打开这台电脑上的 Zotero，再点击刷新。') from None
        except (ValueError, UnicodeDecodeError):
            raise ZoteroError('Zotero 返回了无法识别的数据，请更新或重启 Zotero 后重试。') from None

    def identity(self):
        _, headers = self.request('/', raw=True)
        server_id = headers.get('Zotero-Server-ID')
        if not server_id:
            raise ZoteroError('此功能需要 Zotero 10 或更新版本，请升级 Zotero。')
        return server_id

    def all_rows(self, route, server_id, params=None):
        rows, versions, start = [], set(), 0
        while True:
            batch, headers = self.request(route, {**(params or {}), 'limit': 100, 'start': start}, server_id)
            if not isinstance(batch, list):
                raise ZoteroError('Zotero 列表格式异常。')
            versions.add(headers.get('Last-Modified-Version'))
            rows.extend(batch)
            start += len(batch)
            total = int(headers.get('Total-Results', start))
            if not batch or start >= total:
                return rows, versions

    def catalog(self, library='user', force=False):
        prefix = library_path(library)
        with self.lock:
            cached = self.cache.get(library)
            if cached and not force and time.monotonic() - cached['time'] < 15:
                return copy.deepcopy(cached['value'])
            server_id = self.identity()
            groups, _ = self.request('/users/0/groups', server_id=server_id)
            libraries = [{'id': 'user', 'name': '我的文库'}] + [
                {'id': f'group:{g["id"]}', 'name': g.get('data', {}).get('name', '群组文库')} for g in groups]
            if library not in {x['id'] for x in libraries}:
                raise ZoteroError('该 Zotero 文库已不可用，请切换文库。')
            _, head = self.request(prefix + '/items', {'limit': 1, 'format': 'versions'}, server_id)
            version = head.get('Last-Modified-Version')
            if cached and cached['value']['serverId'] == server_id and cached['value']['version'] == version:
                value = copy.deepcopy(cached['value'])
            else:
                # A concurrent Zotero sync must not leave a mixed-version catalog in cache.
                for attempt in range(3):
                    collections, cv = self.all_rows(prefix + '/collections', server_id)
                    top, tv = self.all_rows(prefix + '/items/top', server_id)
                    attachments, av = self.all_rows(prefix + '/items', server_id, {'itemType': 'attachment'})
                    versions = cv | tv | av
                    if len(versions) == 1:
                        break
                else:
                    raise ZoteroError('Zotero 正在同步大量变更，请稍后刷新。')
                value = normalize_catalog(top, attachments, collections)
                value.update(serverId=server_id, version=next(iter(versions)), library=library)
            value.update(connected=True, libraries=libraries, syncedAt=datetime.now(timezone.utc).isoformat())
            self.cache[library] = {'time': time.monotonic(), 'value': value}
            return copy.deepcopy(value)

    def read_pdf(self, library, parent_key, attachment_key, server_id, max_bytes):
        prefix = library_path(library)
        parent_key, attachment_key = item_key(parent_key), item_key(attachment_key)
        if not server_id or self.identity() != server_id:
            raise ZoteroError('Zotero 文献库已切换，请刷新列表后重新选择。')
        parent, _ = self.request(prefix + '/items/' + parent_key, server_id=server_id)
        attachment, _ = self.request(prefix + '/items/' + attachment_key, server_id=server_id)
        d = attachment['data']
        if parent['data'].get('deleted') or d.get('deleted'):
            raise ZoteroError('这篇文献或附件已在 Zotero 中删除，请刷新列表。')
        if d.get('itemType') != 'attachment' or (d.get('parentItem') or attachment_key) != parent_key or not is_pdf(d):
            raise ZoteroError('所选附件不属于这篇文献，或不是 PDF。请刷新列表。')
        if d.get('linkMode') not in ('imported_file', 'imported_url', 'linked_file'):
            raise ZoteroError('此附件只有网页链接，请先在 Zotero 中保存 PDF。')
        raw, _ = self.request(prefix + '/items/' + attachment_key + '/file/view/url', server_id=server_id, raw=True)
        path = Path(local_file_path(raw.decode('utf-8').strip()))
        try:
            with path.open('rb') as f:
                info = os.fstat(f.fileno())
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= max_bytes:
                    raise ZoteroError('PDF 文件为空或超过 64 MB。')
                data = f.read(max_bytes + 1)
        except (FileNotFoundError, PermissionError, IsADirectoryError):
            raise ZoteroError('无法读取本机 PDF。请在 Zotero 中打开该附件，完成下载或修复文件链接后重试。') from None
        if len(data) > max_bytes or not data.lstrip().startswith(b'%PDF-'):
            raise ZoteroError('附件不是有效的 PDF，或超过 64 MB。')
        reference = {'provider': 'zotero', 'serverId': server_id, 'library': library,
                     'itemKey': parent_key, 'attachmentKey': attachment_key,
                     'title': parent['data'].get('title', '')}
        return data, path.name, reference
