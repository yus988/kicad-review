"""Tests of kicad-review's review store and the server's checks (no KiCad needed). python -m unittest discover tests"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')
sys.path.insert(0, SRC)     # run from a clone without installing
from kicad_review import kireview as kr  # noqa: E402
from kicad_review import kireview_sch as kc  # noqa: E402
from kicad_review import kireview_store as ks  # noqa: E402

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)


BOARD_ITEM = {'title': 't', 'severity': 'should', 'owner': 'human', 'sides': ['F'], 'x': 1, 'y': 2, 'r': 1.0, 'refs': []}


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_board_v1(self):
        # kireview 1 wrote Japanese values: they are read as the codes
        p = os.path.join(self.dir, 'b.json')
        write(p, {'board': 'x', 'rev': 40, 'items': {
            'C1': dict(BOARD_ITEM, status='修正を依頼', status_rev=39, agent_rev=30, thread=[
                {'who': 'user', 'text': 'q', 'time': 't'}, {'who': 'agent', 'text': 'a', 'time': 't'}]),
            'C2': dict(BOARD_ITEM, status='修正済み', status_rev=10, agent_rev=12, thread=[]),
            'C3': dict(BOARD_ITEM, status='未確認', agent_rev=5, thread=[
                {'who': 'agent', 'text': 'a', 'time': 't'}, {'who': 'user', 'text': 'why', 'time': 't'}]),
            'C4': dict(BOARD_ITEM, status='修正を依頼', status_rev=3, agent_rev=8, thread=[])}})
        s = ks.ReviewStore(p, 'board:b', 'board')
        waiting = {x['id']: x for x in s.waiting_items()}
        self.assertEqual(sorted(waiting), ['C1', 'C3'])          # asked after the last reply / a comment unanswered
        self.assertEqual([m['text'] for m in waiting['C3']['new']], ['why'])
        self.assertEqual({k: v['status'] for k, v in s.data['items'].items()},
                         {'C1': 'fix', 'C2': 'fixed', 'C3': '', 'C4': 'fix'})
        self.assertNotIn('status_rev', s.data['items']['C1'])
        it = s.agent('C1', reply='done')
        self.assertGreater(it['agent_rev'], 40)
        self.assertEqual(ks.ReviewStore(p, 'board:b', 'board').data['items']['C1']['thread'][-1]['text'], 'done')

    def test_sch_kidiff(self):
        p = os.path.join(self.dir, 's.json')
        write(p, {'rev': 7, 'show_diff': False, 'groups': [{'id': 'g1', 'title': 'G', 'keys': ['comp:R1'], 'rationale': 'r'}],
                  'items': {'comp:R1': {'status': 'OK', 'rationale': 'x', 'thread': []},
                            'net:/A B/Net-(U1-EN)': {'status': 'NG', 'rationale': '', 'thread': [
                                {'who': 'user', 'text': 'fix', 'time': 't'}]},
                            'group:g1': {'status': '質問', 'rationale': '', 'thread': []}}})
        s = ks.ReviewStore(p, 'sch:s', 'sch')
        st = {k: v['status'] for k, v in s.data['items'].items()}
        self.assertEqual(st, {'comp:R1': 'ok', 'net:/A B/Net-(U1-EN)': 'fix', 'group:g1': 'question'})
        self.assertEqual([x['id'] for x in s.waiting_items()], ['net:/A B/Net-(U1-EN)'])
        self.assertEqual(s.view()['groups'][0]['id'], 'g1')
        s.user('comp:R1', status='')
        again = ks.ReviewStore(p, 'sch:s', 'sch')
        self.assertEqual((again.data['show_diff'], again.data['items']['comp:R1']['status']), (False, ''))

    def test_japanese_values_read_as_codes(self):
        p = os.path.join(self.dir, 'j.json')
        write(p, {'rev': 5, 'items': {
            'B1': dict(BOARD_ITEM, severity='必須', owner='エージェント', status='修正済み', user_rev=2, agent_rev=3,
                       seen_rev=0, thread=[{'who': 'user', 'status': '修正を依頼', 'time': 't', 'rev': 2},
                                           {'who': 'agent', 'status': '修正済み', 'time': 't', 'rev': 3}]),
            'B2': dict(BOARD_ITEM, severity='任意', owner='未定', status='このまま', user_rev=0, agent_rev=0, seen_rev=0,
                       thread=[]),
            'B3': dict(BOARD_ITEM, severity='情報', owner='人', status='自分で修正', user_rev=0, agent_rev=0, seen_rev=0,
                       thread=[])}})
        s = ks.ReviewStore(p, 'board:j', 'board')
        got = {k: (v['severity'], v['owner'], v['status']) for k, v in s.data['items'].items()}
        self.assertEqual(got, {'B1': ('must', 'agent', 'fixed'), 'B2': ('could', 'tbd', 'ok'),
                               'B3': ('info', 'human', 'self-fix')})
        self.assertEqual([m['status'] for m in s.data['items']['B1']['thread']], ['fix', 'fixed'])
        s.touch()                                                        # written back with the codes
        with open(p, encoding='utf-8') as f:
            saved = json.load(f)
        self.assertEqual(saved['items']['B2']['severity'], 'could')
        self.assertEqual(saved['items']['B1']['thread'][0]['status'], 'fix')

    def test_aliases(self):
        self.assertEqual([ks.norm_status(v) for v in ('修正を依頼', 'このまま', '修正済み', '未確認', 'OK', 'NG', 'Fixed', '')],
                         ['fix', 'ok', 'fixed', '', 'ok', 'fix', 'fixed', ''])
        self.assertEqual(ks.norm_fields({'severity': '推奨', 'owner': 'エージェント', 'ask': 'a'}),
                         {'severity': 'should', 'owner': 'agent', 'ask': 'a'})
        with self.assertRaises(ValueError) as cm:
            ks.check_status('NG?')
        self.assertIn('ok, fix, fixed', str(cm.exception))

    def test_put_board_item_keeps_thread(self):
        s = ks.ReviewStore(os.path.join(self.dir, 'n.json'), 'board:n', 'board')
        ks.put_board_item(s, dict(BOARD_ITEM, id='H1'))
        s.user('H1', comment='hm')
        it = ks.put_board_item(s, dict(BOARD_ITEM, id='H1', title='t2', status='未確認', severity='推奨', owner='人'))
        self.assertEqual((it['title'], it['status'], it['thread'][0]['text']), ('t2', '', 'hm'))
        self.assertEqual((it['severity'], it['owner']), ('should', 'human'))          # Japanese names: the codes
        self.assertEqual(ks.put_board_item(s, {'id': 'H3', 'title': 'x', 'sides': ['B'], 'x': 0, 'y': 0})['severity'], 'info')
        self.assertTrue(it['user_rev'] > it['agent_rev'])
        for bad in ({'severity': 'x'}, {'sides': []}, {'spots': [{'x': 1}]}, {'id': 'a b'}):
            with self.assertRaises(ValueError):
                ks.put_board_item(s, dict(dict(BOARD_ITEM, id='H2'), **bad))


class ServerTest(unittest.TestCase):
    """The talkpage routes through kireview's checks, with a board review loaded without KiCad."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.app = kr.App(cls.dir, 'none', 0)
        cls.store = cls.app.store('board', 'b')
        ks.put_board_item(cls.store, dict(BOARD_ITEM, id='H1'))
        kr.Handler.app = cls.app
        cls.srv = kr.tp.Server(('127.0.0.1', 0), kr.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls.dir)

    def req(self, path, body=None, headers=None, method=None):
        """(code, body) of a request sent like the page does (our Origin); headers: None removes one."""
        h = {'Origin': 'http://127.0.0.1:%d' % self.port}
        if body is not None:
            h['Content-Type'] = 'application/json'
        h.update(headers or {})
        r = urllib.request.Request('http://127.0.0.1:%d%s' % (self.port, path),
                                   json.dumps(body).encode() if body is not None else None,
                                   {k: v for k, v in h.items() if v is not None}, method=method)
        try:
            with OPENER.open(r, timeout=10) as resp:
                data = resp.read()
                return resp.status, json.loads(data) if 'json' in resp.headers['Content-Type'] else data
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'{}')

    def test_talk_checks(self):
        page = 'board:b'
        self.assertEqual(self.req('/_talk/api/user', {'page': page, 'id': 'H1', 'status': 'ok'})[0], 200)
        self.assertEqual(self.req('/_talk/api/pending')[1]['items'], [])            # OK does not wake the agent
        code, it = self.req('/_talk/api/user', {'page': page, 'id': 'H1', 'status': '修正を依頼', 'title': 'other'})
        self.assertEqual((code, it['title'], it['status']), (200, 't', 'fix'))    # its own title; the Japanese name: fix
        self.assertEqual([x['id'] for x in self.req('/_talk/api/pending')[1]['items']], ['H1'])
        self.assertEqual(self.req('/_talk/api/user', {'page': page, 'id': 'H1', 'status': 'NG?'})[0], 400)
        self.assertEqual(self.req('/_talk/api/user', {'page': page, 'id': 'H9', 'comment': 'x'})[0], 400)
        self.assertEqual(self.req('/_talk/api/agent', {'page': 'board', 'id': 'H1', 'reply': 'ok',
                                                       'fields': {'severity': 'x'}})[0], 400)
        code, it = self.req('/_talk/api/agent', {'page': 'board', 'id': 'H1', 'reply': '直しました', 'status': '修正済み',
                                                 'fields': {'severity': '必須', 'owner': 'エージェント'}})
        self.assertEqual((code, it['status'], it['severity'], it['owner']), (200, 'fixed', 'must', 'agent'))
        code, it = self.req('/_talk/api/agent', {'page': 'board', 'id': 'H1', 'status': 'fixed', 'fields': {'owner': 'human'}})
        self.assertEqual((code, it['owner']), (200, 'human'))
        self.assertEqual(self.req('/_talk/api/pending')[1]['items'], [])
        self.assertEqual(self.req('/api/info', headers={'Host': 'evil.example:%d' % self.port})[0], 403)
        self.assertEqual(self.req('/api/board/item?id=H1', headers={'Origin': 'https://evil.example'}, method='DELETE')[0], 403)
        self.assertEqual(self.req('/api/board/item?id=H1', headers={'Origin': None}, method='DELETE')[0], 403)
        self.assertEqual(self.req('/_talk/api/user', {'page': page, 'id': 'H1', 'comment': 'x'}, {'Origin': None})[0], 403)

    def test_git_and_folder_reads(self):
        """/api/refs runs git and /api/projects walks the folder of the query: our pages and clients only."""
        q = '/api/projects?dir=' + urllib.request.quote(self.dir)
        self.assertEqual(self.req(q)[0], 200)
        self.assertEqual(self.req(q, headers={'Origin': None, 'Sec-Fetch-Site': 'same-origin'})[0], 200)
        self.assertEqual(self.req(q, headers={'Origin': None})[0], 403)
        self.assertEqual(self.req(q, headers={'Origin': None, 'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'no-cors',
                                              'Sec-Fetch-Dest': 'image'})[0], 403)
        self.assertEqual(self.req('/api/refs?path=' + urllib.request.quote(self.dir), headers={'Origin': None})[0], 403)
        self.assertEqual(self.req('/api/info', headers={'Origin': None})[0], 200)       # plain reads stay open

    def test_routes_without_targets(self):
        self.assertEqual(self.req('/api/sch/state')[1], {'empty': True})
        self.assertEqual(self.req('/api/info')[1]['sch'], None)
        self.assertEqual(self.req('/api/sch/group', {'title': 'x', 'keys': ['a']})[0], 400)
        self.assertEqual(self.req('/figures/../x.svg')[0], 404)
        code, body = self.req('/sch')
        self.assertEqual(code, 200)
        self.assertIn(b'<html lang="en">', body)                                  # the server's language
        self.assertIn(b'/i18n.js', body)
        self.assertEqual(self.req('/i18n.js')[0], 200)
        self.assertEqual(self.req('/api/info')[1]['lang'], 'en')
        self.app.lang = 'ja'
        try:
            self.assertIn(b'<html lang="ja">', self.req('/board')[1])
        finally:
            self.app.lang = 'en'
        self.assertEqual(self.req('/sch/svg/a/x.svg?cell=0_0')[0], 404)            # no schematic open
        self.assertEqual(self.req('/api/datasheet-url?u=https%3A%2F%2Fexample.com%2Fa.pdf')[0], 404)   # links of a schematic only
        self.assertEqual(self.req('/api/datasheet-url?u=x', headers={'Origin': None})[0], 403)      # it fetches: our pages only
        self.assertEqual(self.req('/datasheet')[0], 200)
        self.assertEqual(self.req('/api/sch/area', {'sheet': '/', 'side': 'a', 'box': [0, 0, 1, 1], 'comment': 'x'})[0], 400)


class AreaTest(unittest.TestCase):
    """An area question (Ctrl+drag on the schematic page): what is in the box, the item and its title."""
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.diff = kc.Diff.__new__(kc.Diff)
        self.diff.sides = {'a': {'sheets': {'/': {}, '/power/': {}}, 'pos': {
            'R12': {'sheet': '/power/', 'box': [10, 10, 12, 14]},
            'U3': {'sheet': '/power/', 'box': [20, 8, 30, 20]},
            'C5': {'sheet': '/power/', 'box': [29, 19, 31, 23]},       # reaches into the box at its corner
            'R2': {'sheet': '/power/', 'box': [10, 10, 12, 14]},
            'R9': {'sheet': '/power/', 'box': [50, 50, 52, 54]},       # outside
            'U1': {'sheet': '/', 'box': [10, 10, 20, 20]}},            # another sheet
            'net': {'pin_net': {('U3', '1'): 'Net-(U3-FB)', ('U3', '2'): '+5V', ('R12', '1'): 'GND',
                                ('R9', '1'): 'OTHER', ('C5', '1'): '+5V'}}}}

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_contents(self):
        refs, nets = self.diff.area_contents('a', '/power/', [9, 9, 29.5, 19.5])
        self.assertEqual(refs, ['C5', 'R2', 'R12', 'U3'])                 # in reference order
        self.assertEqual(nets, ['+5V', 'GND', 'Net-(U3-FB)'])             # named nets first
        with self.assertRaises(ValueError):
            self.diff.area_contents('a', '/nope/', [0, 0, 1, 1])

    def test_stale(self):
        """Diff.stale: a folder side whose files changed or went since it was loaded."""
        p = os.path.join(self.dir, 'a.kicad_sch')
        with open(p, 'w', encoding='utf-8') as f:
            f.write('(kicad_sch)')
        st = os.stat(p)
        self.diff.sides['a']['info'] = {'folder': self.dir, 'stamp': [['a.kicad_sch', st.st_mtime_ns, st.st_size]]}
        self.assertFalse(self.diff.stale())
        with open(p, 'a', encoding='utf-8') as f:
            f.write('\n')                                                # saved again
        self.assertTrue(self.diff.stale())
        self.diff.sides['a']['info'] = {'folder': self.dir, 'stamp': [['gone.kicad_sch', 1, 1]]}
        self.assertTrue(self.diff.stale())
        self.diff.sides['a']['info'] = {'folder': self.dir}               # a git side: a fixed version
        self.assertFalse(self.diff.stale())

    def test_item(self):
        s = ks.ReviewStore(os.path.join(self.dir, 'r.json'), 'sch:x', 'sch')
        refs = ['C1', 'C2', 'C3', 'R1', 'R2', 'R3', 'R4', 'R5', 'TP1', 'U2', 'Q1']
        iid = ks.new_area(s, '/power/', 'a', [1.234, 2, 3, 4], refs, ['GND'], 'power')
        self.assertEqual(iid, 'area:1')
        it = s.data['items'][iid]
        self.assertEqual((it['sheet'], it['side'], it['box'], it['refs']), ('/power/', 'a', [1.23, 2, 3, 4], refs))
        self.assertTrue(it['title'].startswith('Area 1 (power: U2 Q1 R1'))  # the main parts first
        self.assertIn(' and 3 more', it['title'])
        self.assertEqual(ks.new_area(s, '/', 'a', [0, 0, 1, 1], [], [], '/'), 'area:2')
        self.assertEqual(s.data['items']['area:2']['title'], 'Area 2 (/)')
        ks.delete_area(s, 'area:1')
        self.assertNotIn('area:1', s.data['items'])
        with self.assertRaises(ValueError):
            ks.delete_area(s, 'comp:R1')


# a sheet of 200 x 130 mm: cells of 4 x 3 (kc.TILE_MM 64), each 50 x 43.33 mm
SHEET = '''<?xml version="1.0" standalone="no"?>
 <!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<svg xmlns:svg="http://www.w3.org/2000/svg" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
  version="1.1" width="200mm" height="130mm" viewBox="0.0000 0.0000 200.0000 130.0000">
<title>the sheet</title>
<desc>made by a test</desc>
<g style="fill:none; stroke:#840000; stroke-width:0.2; stroke-linecap:round;">
<path id="p1" d="M10 10
L20 10
" />
<path id="long" d="M10 20 L190 20" />
<path id="edge" d="M49.8 30 L49.8 32" />
</g>
<g id="teal" style="fill:none; stroke:#006464; stroke-width:0.1524;">
<g transform="rotate(-90 120 100)">
<text id="t" x="120" y="100" textLength="4" font-size="1.7" text-anchor="start" opacity="0">A&amp;B</text>
</g>
<g class="stroked-text"><desc>A&amp;B</desc>
<path id="t1" d="m118 98 l1 -2 h1 v1 c1 1 2 2 3 3" />
</g>
</g>
<g style="fill:#009600; stroke:none;"><circle id="dot" cx="160" cy="86.9" r="0.5" /></g>
<g style="fill:none; stroke:#000000; stroke-width:0.2;"><path id="arc" d="M170 120 A3 3 0 1 1 171 120" /></g>
<g transform="translate(0 0) scale(1 1)">
</g>
</svg>
'''


class CellTest(unittest.TestCase):
    """kireview_sch.split_sheet: a sheet SVG served as a grid of cells."""
    @classmethod
    def setUpClass(cls):
        cls.cols, cls.rows, cls.cells = kc.split_sheet(SHEET.encode('utf-8'))
        cls.trees = [ET.fromstring(c) for c in cls.cells]       # every cell is an SVG of its own

    def where(self, eid):
        return {(k % self.cols, k // self.cols) for k, t in enumerate(self.trees) if t.find(".//*[@id='%s']" % eid) is not None}

    def test_grid_and_view_boxes(self):
        self.assertEqual((self.cols, self.rows), (4, 3))
        self.assertEqual(kc.tile_spec([0, 0, 200, 130]), {'cols': 4, 'rows': 3, 'overlap': kc.TILE_OVERLAP_MM})
        ov = kc.TILE_OVERLAP_MM
        vb = [float(v) for v in self.trees[1 * 4 + 2].get('viewBox').split()]   # column 2, row 1
        for got, want in zip(vb, [100 - ov, 130 / 3 - ov, 50 + 2 * ov, 130 / 3 + 2 * ov]):
            self.assertAlmostEqual(got, want, places=3)

    def test_elements_in_the_cells_they_reach(self):
        self.assertEqual(self.where('p1'), {(0, 0)})
        self.assertEqual(self.where('long'), {(0, 0), (1, 0), (2, 0), (3, 0)})
        self.assertEqual(self.where('edge'), {(0, 0), (1, 0)})            # 0.2 mm from the edge: in the overlap
        self.assertEqual(self.where('dot'), {(3, 1), (3, 2)})             # on the row edge at 86.67 mm
        self.assertEqual(self.where('t'), {(2, 2)})                       # the rotated text: its box turned
        self.assertEqual(self.where('t1'), {(2, 2)})                      # relative commands and a curve
        self.assertIn((3, 2), self.where('arc'))

    def test_groups_and_text_kept(self):
        t = self.trees[2 * 4 + 2]
        self.assertIsNone(t.find('{http://www.w3.org/2000/svg}title'))  # the sheet's own title is left out
        g = t.find(".//*[@class='stroked-text']")
        self.assertEqual(g.find('{http://www.w3.org/2000/svg}desc').text, 'A&B')   # desc goes with its group
        self.assertEqual(t.find(".//*[@id='t']").text, 'A&B')
        self.assertIn(g, list(t.find(".//*[@id='teal']")))                # inside its style group
        self.assertIn('stroke:#006464', t.find(".//*[@id='teal']").get('style'))
        self.assertFalse(len(self.trees[1 * 4 + 0]))                      # nothing reaches column 0, row 1

    def test_path_box(self):
        self.assertEqual(kc.path_box('M10 10\nL20 5\n'), [10, 5, 20, 10])
        self.assertEqual(kc.path_box('m1 1 l2 0 v3 h-5 z'), [-2, 1, 3, 4])
        self.assertEqual(kc.path_box('M0 0 C 5 -5 10 5 10 0'), [0, -5, 10, 5])   # control points included
        b = kc.path_box('M10 10 A2 2 0 1 1 11 10')
        self.assertLessEqual(b[0], 9)
        self.assertGreaterEqual(b[3], 12)
        self.assertIsNone(kc.path_box('M1 1 X 2 2'))

    def test_sheet_cell(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, 's.svg')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(SHEET)
            self.assertEqual(kc.sheet_cell(p, 0, 0), self.cells[0])
            self.assertIsNone(kc.sheet_cell(p, 4, 0))
            self.assertIsNone(kc.sheet_cell(p, 0, 3))
        finally:
            shutil.rmtree(d)


class DatasheetFetchTest(unittest.TestCase):
    """kireview_sch.fetch_datasheet: a PDF given as a web link is fetched once and kept; anything else is not."""
    @classmethod
    def setUpClass(cls):
        import http.server

        class Site(http.server.BaseHTTPRequestHandler):
            hits = []

            def do_GET(self):
                Site.hits.append(self.path)
                body, ctype = (b'%PDF-1.4\n%test\n', 'application/pdf') if self.path.endswith('.pdf') else \
                    (b'<html>a product page</html>', 'text/html')
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        cls.site = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Site)
        cls.hits = Site.hits
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()
        cls.base = 'http://127.0.0.1:%d/' % cls.site.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.site.shutdown()

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_pdf_kept(self):
        p = kc.fetch_datasheet(self.base + 'a.pdf', self.dir)
        with open(p, 'rb') as f:
            self.assertTrue(f.read().startswith(b'%PDF-'))
        n = len(self.hits)
        self.assertEqual(kc.fetch_datasheet(self.base + 'a.pdf', self.dir), p)   # from the folder the next time
        self.assertEqual(len(self.hits), n)

    def test_not_pdf(self):
        self.assertIsNone(kc.fetch_datasheet(self.base + 'page', self.dir))
        n = len(self.hits)
        self.assertIsNone(kc.fetch_datasheet(self.base + 'page', self.dir))      # not asked again for a while
        self.assertEqual(len(self.hits), n)
        self.assertIsNone(kc.fetch_datasheet('http://127.0.0.1:1/x.pdf', self.dir))   # nothing there


if __name__ == '__main__':
    unittest.main()
