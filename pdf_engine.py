"""PDF extraction, layout-preserving translation and safe public URL import."""
from pathlib import Path
import html
from html.parser import HTMLParser
import http.client
import ipaddress
import re
import socket
import ssl
import threading
from urllib.parse import urlparse, urljoin, quote
import pymupdf as fitz

PDF_LOCK = threading.RLock()  # MuPDF calls must not run concurrently in one process.
MAX_BYTES = 64 * 1024 * 1024
MAX_PAGES = 300


def normalize_url(value):
    value = value.strip()
    match = re.fullmatch(r'(?:arxiv:)?(\d{4}\.\d{4,5}(?:v\d+)?)', value, re.I)
    if match:
        return 'https://arxiv.org/pdf/' + match[1]
    if re.match(r'^10\.\d{4,9}/\S+$', value):
        return 'https://doi.org/' + value
    p = urlparse(value)
    if p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password:
        raise ValueError('请输入 PDF 网址、论文网页、arXiv 编号或 DOI。')
    if p.hostname.lower() in ('arxiv.org', 'www.arxiv.org', 'export.arxiv.org'):
        value = re.sub(r'/abs/', '/pdf/', value)
    return value


def public_addresses(host, port):
    addresses = list(dict.fromkeys(x[4][0] for x in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(x).is_global for x in addresses):
        raise ValueError('论文链接必须是公开互联网地址，不能访问本机或内网。')
    return addresses


def fetch_public(url):
    """Validate every redirect; pin the connection to the validated address."""
    for _ in range(8):
        p = urlparse(url)
        if p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password:
            raise ValueError('链接跳转到了不支持的地址。')
        port = p.port or (443 if p.scheme == 'https' else 80)
        if port not in (80, 443):
            raise ValueError('仅支持标准 HTTP / HTTPS 端口。')
        addresses = public_addresses(p.hostname, port)
        conn = http.client.HTTPSConnection(p.hostname, port, timeout=40, context=ssl.create_default_context()) if p.scheme == 'https' else http.client.HTTPConnection(p.hostname, port, timeout=40)
        conn._create_connection = lambda _addr, timeout=None, source_address=None: socket.create_connection((addresses[0], port), timeout, source_address)
        try:
            conn.request('GET', quote(p.path or '/', safe='/%:@+~!$&\'()*;,=-._') + ('?' + p.query if p.query else ''),
                         headers={'User-Agent': 'PaperDesk/1.0 (personal academic reader)', 'Accept': 'application/pdf,text/html;q=0.9', 'Accept-Encoding': 'identity'})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308):
                location = r.getheader('Location')
                if not location:
                    raise ValueError('网页重定向缺少目标地址。')
                url = urljoin(url, location)
                continue
            if r.status != 200:
                raise ValueError(f'网站返回 HTTP {r.status}。可下载 PDF 后直接上传。')
            if int(r.getheader('Content-Length', '0')) > MAX_BYTES:
                raise ValueError('PDF 超过 64 MB，请先压缩。')
            data = r.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('下载文件超过 64 MB。')
            return data, r.getheader('Content-Type', ''), url
        finally:
            conn.close()
    raise ValueError('论文链接跳转次数过多。')


class PDFLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.links = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta' and a.get('name', '').lower() in ('citation_pdf_url', 'wkhealth_pdf_url'):
            self.meta.append(a.get('content', ''))
        if tag in ('a', 'link'):
            href = a.get('href', '')
            if re.search(r'\.pdf(?:\?|$)|/pdf/', href, re.I) or a.get('type') == 'application/pdf':
                self.links.append(href)


def download_paper(value):
    url = normalize_url(value)
    data, ctype, final = fetch_public(url)
    if data.lstrip().startswith(b'%PDF-'):
        return data, final
    if 'html' not in ctype and not data.lstrip().startswith(b'<'):
        raise ValueError('链接没有返回 PDF 或可识别的论文网页。')
    parser = PDFLinks()
    parser.feed(data.decode('utf-8', 'replace'))
    for href in (parser.meta + parser.links)[:5]:
        try:
            result, _, dest = fetch_public(urljoin(final, href))
            if result.lstrip().startswith(b'%PDF-'):
                return result, dest
        except (ValueError, OSError):
            continue
    raise ValueError('网页中没有可公开下载的 PDF。请打开论文网站下载后上传；不支持绕过登录或付费墙。')


def extract_pdf(path):
    with PDF_LOCK, fitz.open(path) as doc:
        if doc.needs_pass:
            raise ValueError('PDF 有密码保护，请先解锁后上传。')
        if not 0 < len(doc) <= MAX_PAGES:
            raise ValueError(f'支持 1–{MAX_PAGES} 页的 PDF。')
        pages = []
        for i, page in enumerate(doc):
            blocks = []
            raw = page.get_text('dict', sort=True)
            images = [fitz.Rect(b['bbox']) for b in raw['blocks'] if b['type'] == 1]
            text_blocks = []
            for b in raw['blocks']:
                if b['type'] != 0:
                    continue
                lines = b.get('lines', [])
                # PDF tables often group an entire row (or several rows) into one block.
                # Keep each cell's own box so translation cannot flatten columns or move numbers.
                same_row = max((sum(abs(other['bbox'][1]-line['bbox'][1]) < 3 for other in lines) for line in lines), default=0)
                separated_rows = {round(line['bbox'][1]) for line in lines if any(
                    abs(other['bbox'][1]-line['bbox'][1]) < 3 and other['bbox'][0]-line['bbox'][2] > 12
                    for other in lines)}
                wide_pair = any(abs(a['bbox'][1]-b['bbox'][1]) < 3 and b['bbox'][0]-a['bbox'][2] > 25
                                for a in lines for b in lines)
                if same_row >= 3 or len(separated_rows) >= 2 or wide_pair:
                    text_blocks.extend({'type':0,'bbox':line['bbox'],'lines':[line]} for line in lines)
                else:
                    text_blocks.append(b)
            for b in text_blocks:
                if b['type'] != 0:
                    continue
                lines = b.get('lines', [])
                text = '\n'.join(''.join(s['text'] for s in ln['spans']) for ln in lines).strip()
                if not text:
                    continue
                rect = fitz.Rect(b['bbox'])
                sizes = [s['size'] for ln in lines for s in ln['spans']]
                fonts = [s['font'] for ln in lines for s in ln['spans']]
                # Keep figure internals, standalone formulas, numeric cells, and URLs untouched.
                inside_image = any((rect & im).get_area() > rect.get_area() * .75 for im in images)
                letters = len(re.findall('[A-Za-z]', text))
                math_fonts = sum(bool(re.search('Math|Symbol|CMSY|CMMI|CMEX', f)) for f in fonts)
                rotated = any(abs(ln.get('dir', (1, 0))[1]) > .1 for ln in lines)
                translate = letters >= 3 and not inside_image and not rotated and not (math_fonts > len(fonts) / 2)
                if max(sizes, default=10) < 7.5 or re.fullmatch(r'(?:Qwen\S*|HODAGENT|ReAct|XPENG ROBOTICS)', text, re.I):
                    translate = False
                if re.fullmatch(r'(?:https?://\S+|\S+@\S+|arXiv:\S+)', text):
                    translate = False
                new_block = {'id': f'p{i+1}-b{len(blocks)}', 'bbox': [round(v, 2) for v in rect],
                               'lines': [[round(v, 2) for v in ln['bbox']] for ln in lines],
                               'text': text, 'zh': '', 'translate': translate,
                               'fontSize': round(sum(sizes) / len(sizes), 2) if sizes else 10,
                               'bold': any('Bold' in f for f in fonts)}
                if blocks and blocks[-1]['text'].endswith('-') and abs(blocks[-1]['bbox'][0]-rect.x0)<3 and 0 <= rect.y0-blocks[-1]['bbox'][3] < 6 and blocks[-1]['translate'] == translate:
                    previous = blocks[-1]
                    previous['text'] = previous['text'][:-1] + text
                    previous['bbox'] = list(fitz.Rect(previous['bbox']) | rect)
                    previous['lines'] += new_block['lines']
                else:
                    blocks.append(new_block)
            pages.append({'number': i+1, 'width': page.rect.width, 'height': page.rect.height,
                          'blocks': blocks, 'translated': False, 'summary': '', 'warnings': []})
        if sum(len(b['text']) for p in pages for b in p['blocks']) < 80:
            raise ValueError('这份 PDF 没有可提取的文字，可能是扫描件。请先进行 OCR 后再上传。')
        title = (doc.metadata or {}).get('title', '').strip()
        if not title or title.lower() in ('untitled', 'document'):
            candidates = [b for b in pages[0]['blocks'] if len(b['text']) > 15 and b['bbox'][1] < pages[0]['height'] * .45]
            title = max(candidates, key=lambda b: b['fontSize'])['text'] if candidates else Path(path).stem
        return title.replace('\n', ' ')[:250], pages


def translated_page(source, page_data, output):
    with PDF_LOCK, fitz.open(source) as src:
        doc = fitz.open()
        doc.insert_pdf(src, from_page=page_data['number']-1, to_page=page_data['number']-1)
        page = doc[0]
        replacements, warnings = [], []
        for block in page_data['blocks']:
            if not block.get('zh') or not block['translate'] or block['zh'].strip() == block['text'].strip():
                continue
            box = fitz.Rect(block['bbox'])
            size = max(7, min(block['fontSize'], 18))
            translated = block['zh']
            if box.height < size * 1.5:
                # Side-by-side heading/footnote fragments are sometimes extracted with newlines.
                translated = translated.replace('\n', ' ')
                below = [b['bbox'][1] for b in page_data['blocks'] if b['bbox'][1] >= box.y1 and b['bbox'][0] < box.x1 and b['bbox'][2] > box.x0]
                room = max(0, min(below, default=page.rect.height-20) - box.y1 - 1)
                box.y1 += min(3, room)
            content = '<div>' + html.escape(translated).replace('\n', '<br>') + '</div>'
            css = f'* {{font-family: sans-serif; font-size:{size}px; line-height:1.15; margin:0; padding:0; color:#15201c;}} div {{font-weight:{700 if block["bold"] else 400};}}'
            # Lay out first. If it cannot fit, preserve the source and show full text when the paragraph is selected.
            probe = fitz.open()
            test = probe.new_page(width=page.rect.width, height=page.rect.height)
            spare, scale = test.insert_htmlbox(box, content, css=css, scale_low=.60)
            probe.close()
            if spare < 0:
                warnings.append(f'{block["id"]}：译文较长，原位保留英文；点击对应段落查看完整译文。')
                continue
            replacements.append((box, content, css))
            for line in block['lines']:
                page.add_redact_annot(fitz.Rect(line), fill=False)
        page.apply_redactions(images=0, graphics=0, text=0)
        for box, content, css in replacements:
            page.insert_htmlbox(box, content, css=css, scale_low=.60)
        page.insert_text((8, 10), f'AI Chinese translation | Original page {page_data["number"]}', fontsize=5, color=(.4,.5,.44))
        dest = Path(output)
        temp = dest.with_suffix('.tmp.pdf')
        doc.save(temp, garbage=4, deflate=True)
        doc.close()
        temp.replace(dest)
        return warnings


def render_page(source, number, output, scale=1.7):
    with PDF_LOCK, fitz.open(source) as doc:
        doc[number-1].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).save(output)


def render_svg(source, number, output, clip=None):
    """Keep text and line art as vectors and embedded images at source resolution."""
    with PDF_LOCK, fitz.open(source) as doc:
        svg = doc[number-1].get_svg_image(text_as_path=True)
        if clip is not None:
            rect = fitz.Rect(clip) & doc[number-1].rect
            if rect.is_empty:
                raise ValueError('图片区域不存在。')
            # Change only the root viewport; preserve all PDF paths, transforms and fonts.
            head, rest = svg.split('>', 1)
            head = re.sub(r'\bviewBox="[^"]*"', f'viewBox="{rect.x0} {rect.y0} {rect.width} {rect.height}"', head)
            head = re.sub(r'\bwidth="[^"]*"', f'width="{rect.width}"', head)
            head = re.sub(r'\bheight="[^"]*"', f'height="{rect.height}"', head)
            svg = head + '>' + rest
        dest = Path(output)
        temp = dest.with_suffix('.tmp.svg')
        temp.write_text(svg, encoding='utf-8')
        temp.replace(dest)


def extract_figures(source, number):
    """Group nearby raster / vector objects into clickable visual regions."""
    with PDF_LOCK, fitz.open(source) as doc:
        page = doc[number-1]
        image_rects = [fitz.Rect(x['bbox']) * page.rotation_matrix for x in page.get_image_info()]
        rectangles = image_rects.copy()
        rectangles += [fitz.Rect(x['rect']) * page.rotation_matrix for x in page.get_drawings()]
        area = page.rect.get_area()
        rectangles = [r & page.rect for r in rectangles if r.width > 2 and r.height > 2 and 12 < r.get_area() < area * .45]
        groups = []
        for rect in rectangles:
            changed = True
            while changed:
                changed = False
                for other in groups[:]:
                    if (rect + (-9, -9, 9, 9)).intersects(other):
                        rect |= other
                        groups.remove(other)
                        changed = True
            groups.append(rect)
        text_blocks = [(fitz.Rect(b[:4]) * page.rotation_matrix, b[4].strip())
                       for b in page.get_text('blocks') if b[6] == 0]
        captions = [(r, re.match(r'^(?:Figure|Fig\.)\s*(\d+)\s*[:.]', t, re.I)) for r,t in text_blocks]
        captions = [(r,m.group(1)) for r,m in captions if m]
        figures = []
        for rect in sorted(groups, key=lambda r:(r.y0,r.x0)):
            if rect.width < 45 or rect.height < 24 or rect.get_area() < 1800:
                continue
            caption = next(((r,n) for r,n in captions if r.y0 >= rect.y0 and -80 <= r.y0-rect.y1 <= 45
                            and min(rect.x1,r.x1)>max(rect.x0,r.x0)), None)
            if caption:
                rect.y1 = min(rect.y1,caption[0].y0-2)
                if caption[0].width < page.rect.width*.6:
                    rect.x0 = max(rect.x0,caption[0].x0-5)
                    rect.x1 = min(rect.x1,caption[0].x1+5)
            # Decorative borders may join a diagram to a whole-page background.
            # In that case use the contained image cluster instead of covering body text.
            if any(len(t)>180 and (rect & r).get_area() > r.get_area()*.5 for r,t in text_blocks):
                contained = [r for r in image_rects if rect.contains(r) and r.get_area()>12]
                if not contained:
                    continue
                rect = fitz.Rect(contained[0])
                for r in contained[1:]:
                    rect |= r
                if rect.width < 45 or rect.height < 24:
                    continue
            rect = (rect + (-3,-3,3,3)) & page.rect
            if caption:
                rect.y1 = min(rect.y1,caption[0].y0-2)
            # Draw-path bounds can include invisible control points or shadows.
            # Trim their blank margins using a tiny raster probe, while the final
            # image itself remains SVG at its original vector quality.
            probe = page.get_pixmap(matrix=fitz.Matrix(1,1),clip=rect,alpha=False)
            samples, stride = probe.samples, probe.stride
            points = [(x,y) for y in range(probe.height) for x in range(probe.width)
                      if min(samples[y*stride+x*3:y*stride+x*3+3]) < 235]
            if points:
                bounds = fitz.Rect(probe.x+min(x for x,y in points)-3,probe.y+min(y for x,y in points)-3,
                                   probe.x+max(x for x,y in points)+4,probe.y+max(y for x,y in points)+4)
                rect &= bounds
            figures.append({'id':len(figures), 'bbox':[round(v,2) for v in rect],
                            'label':f'图 {caption[1]}' if caption else f'图像 {len(figures)+1}'})
        return figures


def export_pdf(folder, pages, output):
    with PDF_LOCK:
        doc = fitz.open()
        for p in pages:
            path = Path(folder)/f'zh-{p["number"]}.pdf'
            if not p['translated'] or not path.exists():
                raise ValueError('全文翻译完成后才能导出完整中文 PDF。')
            with fitz.open(path) as src:
                doc.insert_pdf(src)
        doc.set_metadata({'title': 'Paper Desk Chinese translation', 'subject': 'AI Chinese translation; check against the original.'})
        temp = Path(output).with_suffix('.tmp.pdf')
        doc.save(temp, garbage=4, deflate=True)
        doc.close()
        temp.replace(output)
