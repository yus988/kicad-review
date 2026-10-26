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

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')
sys.path.insert(0, SRC)     # run from a clone without installing
from kicad_review import kireview as kr  # noqa: E402
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
        h = {'Content-Type': 'application/json'} if body is not None else {}
        h.update(headers or {})
        r = urllib.request.Request('http://127.0.0.1:%d%s' % (self.port, path),
                                   json.dumps(body).encode() if body is not None else None, h, method=method)
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


if __name__ == '__main__':
    unittest.main()
