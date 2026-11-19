import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zotero_client import ZoteroClient, ZoteroError, normalize_catalog, library_path, item_key


def row(key, **data):
    return {'key': key, 'data': {'key': key, **data}}


class ZoteroTests(unittest.TestCase):
    def test_catalog_keeps_pdf_parent_and_does_not_expose_paths_or_notes(self):
        article = row('PARENT01', itemType='journalArticle', title='<b>Paper</b>', date='2026-01-01',
                      creators=[{'firstName': 'A', 'lastName': 'Chen'}], collections=['COLLECT1'], tags=[{'tag': 'robot'}])
        pdf = row('ATTACH01', itemType='attachment', contentType='application/pdf', parentItem='PARENT01',
                  filename='paper.pdf', path='/private/document.pdf')
        standalone = row('STAND001', itemType='attachment', contentType='application/pdf', filename='solo.pdf')
        note = row('NOTE0001', itemType='note', note='private note')
        c = normalize_catalog([article, pdf, standalone, note], [pdf, standalone], [])
        self.assertEqual([i['key'] for i in c['items']], ['PARENT01', 'STAND001'])
        self.assertEqual(c['items'][0]['pdfs'][0]['key'], 'ATTACH01')
        self.assertEqual(c['items'][0]['authors'], 'A Chen')
        self.assertEqual(c['items'][1]['pdfs'][0]['key'], 'STAND001')
        self.assertNotIn('/private', str(c)); self.assertNotIn('private note', str(c))

    def test_routes_reject_arbitrary_paths(self):
        for bad in ['../../etc/passwd', 'group:1/../../', 'http://example.com', 'group:0']:
            with self.assertRaises(ZoteroError): library_path(bad)
        for bad in [None, '../secret', 'file:///x', 'ABC']:
            with self.assertRaises(ZoteroError): item_key(bad)
        self.assertEqual(library_path('group:123'), '/groups/123')

    def test_pagination_and_version_changes_are_not_lost(self):
        z = ZoteroClient()
        with patch.object(z, 'request', side_effect=[([{'key':'a'}], {'Total-Results':'2','Last-Modified-Version':'3'}),
                                                    ([{'key':'b'}], {'Total-Results':'2','Last-Modified-Version':'4'})]) as request:
            rows, versions = z.all_rows('/users/0/items', 'instance')
        self.assertEqual(len(rows), 2); self.assertEqual(versions, {'3','4'})
        self.assertEqual(request.call_args_list[1].args[1]['start'], 1)

    def test_only_selected_pdf_can_be_read_and_missing_download_is_actionable(self):
        z = ZoteroClient()
        parent = row('PARENT01', title='Research')
        pdf = row('ATTACH01', itemType='attachment', parentItem='PARENT01', contentType='application/pdf', linkMode='imported_file')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '中文 空格.pdf'; path.write_bytes(b'%PDF-1.7\nfixture')
            responses = [(parent, {}), (pdf, {}), (path.as_uri().encode(), {})]
            with patch.object(z, 'identity', return_value='server'), patch.object(z, 'request', side_effect=responses):
                data, name, ref = z.read_pdf('user','PARENT01','ATTACH01','server',1024)
            self.assertTrue(data.startswith(b'%PDF')); self.assertEqual(name, path.name)
            self.assertEqual(ref['itemKey'], 'PARENT01'); self.assertNotIn('path', ref)
            path.unlink()
            with patch.object(z, 'identity', return_value='server'), patch.object(z, 'request', side_effect=responses):
                with self.assertRaisesRegex(ZoteroError, '完成下载'):
                    z.read_pdf('user','PARENT01','ATTACH01','server',1024)
        wrong = row('ATTACH01', itemType='attachment', parentItem='OTHER001', contentType='application/pdf')
        with patch.object(z, 'identity', return_value='server'), patch.object(z, 'request', side_effect=[(parent,{}),(wrong,{})]) as request:
            with self.assertRaisesRegex(ZoteroError, '不属于'):
                z.read_pdf('user','PARENT01','ATTACH01','server',1024)
            self.assertEqual(request.call_count, 2)

    def test_library_switch_never_uses_another_database_attachment(self):
        z = ZoteroClient()
        with patch.object(z, 'identity', return_value='new-server'), patch.object(z, 'request') as request:
            with self.assertRaisesRegex(ZoteroError, '已切换'):
                z.read_pdf('user','PARENT01','ATTACH01','old-server',1024)
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
