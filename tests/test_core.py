import sys
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymupdf as fitz
from pdf_engine import normalize_url, public_addresses, extract_pdf, translated_page, export_pdf, PDFLinks, render_svg, extract_figures


class ImportTests(unittest.TestCase):
    def test_normalize_paper_identifiers(self):
        self.assertEqual(normalize_url('2608.17584v1'), 'https://arxiv.org/pdf/2608.17584v1')
        self.assertEqual(normalize_url('https://arxiv.org/abs/2608.17584'), 'https://arxiv.org/pdf/2608.17584')
        self.assertEqual(normalize_url('10.1000/xyz'), 'https://doi.org/10.1000/xyz')
        for bad in ['file:///etc/passwd', 'javascript:alert(1)', 'https://user:secret@example.com/p.pdf', 'not a link']:
            with self.assertRaises(ValueError):
                normalize_url(bad)

    def test_private_and_mixed_dns_are_blocked(self):
        for addresses in [['127.0.0.1'], ['10.1.2.3'], ['::1'], ['169.254.169.254'], ['93.184.216.34','192.168.1.2']]:
            with patch('socket.getaddrinfo', return_value=[(2,1,6,'',(a,443)) for a in addresses]):
                with self.assertRaises(ValueError):
                    public_addresses('example.test',443)

    def test_publisher_metadata(self):
        p=PDFLinks();p.feed('<meta name="citation_pdf_url" content="/paper.pdf"><a href="/download.pdf?x=1">PDF</a>')
        self.assertEqual(p.meta,['/paper.pdf']);self.assertEqual(p.links,['/download.pdf?x=1'])


class PDFTests(unittest.TestCase):
    def test_translation_retains_geometry_and_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);original=folder/'original.pdf'
            doc=fitz.open();page=doc.new_page(width=595,height=842)
            page.insert_text((60,80),'Research motivation and results',fontsize=18)
            page.insert_textbox(fitz.Rect(60,110,530,240),'A robot should respond to changing requests during execution. We test this system on 164 cases and report a success rate of 91.5 percent.',fontsize=12)
            page.insert_text((60,300),'91.5%',fontsize=13)
            page.draw_rect(fitz.Rect(60,350,530,500),color=(.1,.5,.2),fill=(.8,.95,.8))
            doc.save(original);doc.close()
            title,pages=extract_pdf(original);self.assertIn('Research',title)
            for b in pages[0]['blocks']:
                if b['translate']:
                    b['zh']='研究动机与结果' if b['fontSize']>15 else '机器人应在执行期间响应变化的请求。我们在 164 个案例中测试该系统，成功率为 91.5%。'
            warnings=translated_page(original,pages[0],folder/'zh-1.pdf')
            self.assertFalse(warnings)
            with fitz.open(folder/'zh-1.pdf') as result:
                text=result[0].get_text();self.assertIn('研究',text);self.assertIn('91.5',text)
                self.assertEqual(result[0].rect.width,595);self.assertTrue(result[0].get_drawings())
            with self.assertRaises(ValueError):export_pdf(folder,pages,folder/'full.pdf')
            pages[0]['translated']=True;export_pdf(folder,pages,folder/'full.pdf')
            with fitz.open(folder/'full.pdf') as final:self.assertEqual(len(final),1)
            # The browser must get scalable outlines, including Chinese glyphs.
            render_svg(folder/'zh-1.pdf',1,folder/'page.svg')
            svg=ET.fromstring((folder/'page.svg').read_text())
            self.assertEqual(svg.attrib['viewBox'],'0 0 595 842')
            self.assertTrue(list(svg.iter('{http://www.w3.org/2000/svg}path')))
            self.assertFalse(list(svg.iter('{http://www.w3.org/2000/svg}text')))
            figures=extract_figures(original,1)
            self.assertEqual(len(figures),1)
            self.assertLess(figures[0]['bbox'][0],60)
            self.assertGreater(figures[0]['bbox'][3],500)
            render_svg(original,1,folder/'figure.svg',figures[0]['bbox'])
            crop=ET.fromstring((folder/'figure.svg').read_text())
            self.assertLess(float(crop.attrib['height']),200)

    def test_scanned_page_is_explicit_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'scan.pdf';doc=fitz.open();doc.new_page();doc.save(path);doc.close()
            with self.assertRaisesRegex(ValueError,'OCR'):extract_pdf(path)


if __name__=='__main__':unittest.main()
