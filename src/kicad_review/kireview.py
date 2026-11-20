"""kicad-review: review KiCad 10 schematics and boards with a coding agent, on one local page.

  kicad-review [A [B]] [BOARD.kicad_pcb] [--board BOARD] [--data DIR] [--port 8199] [--no-open]
               [--kicad-bin DIR] [--rationale FILE] [--no-diff] [--lang en|ja] [--no-reload]
  kicad-review wait | reply | ack | show ...      (talkpage's commands on this server; see README.md)
  kicad-review put --file items.json              (board items, POST /api/board/item each)
  kicad-review group --file groups.json           (schematic groups, POST /api/sch/group each)
  kicad-review renumber REVIEW.json MAP.json      (carry a schematic review over a re-annotation; server stopped)

A / B: the schematic to review (a project folder, a root .kicad_sch or <repo>@<ref>:<path>); with B the changes from
A to B are listed. BOARD: a .kicad_pcb to review. Either can be chosen in the page too. /sch is the schematic page,
/board the board page. <data> (default: the current folder) holds reviews/ (the review notes), cache/ and figures/.
--lang: the language of the pages and of the text the server makes (default: $KICAD_REVIEW_LANG, else the OS
language: ja when it is Japanese, else en).
The server runs under a small watcher (supervise): when its own Python files change, it starts again with the new code
and opens the schematic and board that were open (--no-reload: one process, no watching). Page files (HTML, JS, CSS)
are read at each request anyway: a page shows "Reload page" for them.
The work is done in kireview_sch.py, kireview_board.py and kireview_store.py; the comment threads, the agent's wait
and replies are talkpage's (the talkpage package, routes /_talk/api/).
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser

from . import __version__

from . import i18n
from . import kicad_paths as kp
from . import kireview_board as kb
from . import kireview_sch as kc
from . import kireview_store as ks

tp = ks.tp
HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8199
PAGES = {'/sch': 'sch.html', '/board': 'board.html', '/datasheet': 'datasheet.html'}
STATIC = {'/i18n.js': 'text/javascript', '/review.js': 'text/javascript', '/board3d.js': 'text/javascript',
          '/review.css': 'text/css'}
FIGURE_TYPES = {'.svg': 'image/svg+xml', '.png': 'image/png', '.webp': 'image/webp', '.jpg': 'image/jpeg'}
TALK_CMDS = ('wait', 'reply', 'ack', 'show')
NAME = re.compile(r'^[\w.@+-]+$')     # review names (board stems, schematic slugs) and figure files
REVIEW_KEY = re.compile(r'^(sch|board):[\w.@+-]+$')   # page key of a review store
RESTART_CODE = 3                 # the server's exit status when its code changed: the watcher starts it again
CHILD_ENV = 'KICAD_REVIEW_CHILD'  # in the server the watcher runs: "1", "restart" after a code change
START_S = 30                     # a server started again that fails sooner did not start with the new code
WATCHER_ENV = 'KICAD_REVIEW_WATCHER'   # the watcher's pid, in the server it runs


def page_stamp():
    """The newest file time of the page files, so an open page can tell that a newer page is there."""
    t = 0
    for n in list(PAGES.values()) + [p.lstrip('/') for p in STATIC]:
        try:
            t = max(t, int(os.path.getmtime(os.path.join(HERE, n))))
        except OSError:
            pass
    return t


class App:
    """What the server holds: the review stores (talkpage's Talk), the board and the schematic under review. lang
    ('en' / 'ja') is the language of the pages and of the server's text (i18n, set here once)."""

    def __init__(self, data, kicad_bin, port, seed=None, lang='en'):
        self.data, self.kicad_bin, self.port = data, kicad_bin, port
        self.lang = lang if lang in i18n.LANGS else 'en'
        i18n.set_lang(self.lang)
        self.talk = tp.Talk(None, port, self.lang)
        self.cond = self.talk.cond
        self.board, self.board_store, self.sch = None, None, None
        self.seed = seed
        self.open_lock = threading.Lock()
        self.restarting = False        # the code changed: serve() ends with RESTART_CODE
        kc.CACHE = os.path.join(data, 'cache', 'sch')

    # ------------------------------------------------------------ stores and targets
    def store(self, kind, name):
        page = '%s:%s' % (kind, name)
        sub = ('sch',) if kind == 'sch' else ()
        path = os.path.join(self.data, 'reviews', *sub, name + '.json')
        with self.cond:
            s = self.talk.stores.get(page)
            if s is None:
                s = self.talk.stores[page] = ks.ReviewStore(path, page, kind)
            s.fresh()
            return s

    def sch_store(self, slug):
        s = self.store('sch', slug)
        if self.seed:                       # --rationale is for the pair given on the command line only
            with self.cond:
                ks.seed_rationale(s, self.seed)
                self.cond.notify_all()
            self.seed = None
        return s

    def open_board(self, path):
        path = os.path.abspath(str(path or ''))
        if not path.endswith('.kicad_pcb') or not os.path.isfile(path):
            raise ValueError('not a .kicad_pcb file: %s' % path)
        with self.open_lock:
            b = kb.Board(path, self.data, self.kicad_bin)
            b.load()                        # the export: a few seconds for a new version of the file
            s = self.store('board', b.stem)
            with self.cond:
                s.data['board'] = b.path.replace('\\', '/')
                old, self.board, self.board_store = self.board, b, s
                self.cond.notify_all()
            if old:
                old.stop()
            threading.Thread(target=b.watch, daemon=True).start()
        self.save_open()
        return self.board_info()

    def open_sch(self, a, b):
        if self.sch is None:
            d = kc.Diff(a, b or None, self.kicad_bin, self.sch_store, self.cond)
            st = d.load()
            self.sch = d
        else:
            st = self.sch.compare(a, b)
        self.save_open()
        return st

    # ------------------------------------------------------------ what is open, for a start after a code change
    def open_file(self):
        return os.path.join(self.data, 'cache', 'open-%d.json' % self.port)

    def save_open(self):
        """The schematic sides and the board that are open (also those chosen in the page), per port."""
        d = {'sch': [self.sch.specs['a'], self.sch.specs['b']] if self.sch else None,
             'board': self.board.path if self.board else None}
        try:
            os.makedirs(os.path.dirname(self.open_file()), exist_ok=True)
            with open(self.open_file(), 'w', encoding='utf-8') as f:
                json.dump(d, f, ensure_ascii=False)
        except OSError:
            pass

    def load_open(self):
        try:
            with open(self.open_file(), encoding='utf-8') as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def board_info(self):
        if not self.board:
            return {'empty': True, 'hint': self.sch.board_hint() if self.sch else None}
        return dict(self.board.info(), review={'page': self.board_store.page,
                                               'file': self.board_store.path.replace('\\', '/')})

    def info(self):
        with self.cond:
            presence = self.talk.presence()
        st = self.sch.state if self.sch else None
        sch = None
        if st:
            sd, old = st['sides'], self.sch.stale_sides()
            sch = {'page': st['review']['page'], 'single': st['single'], 'stale': bool(old), 'old': old,
                   'vers': {k: s.get('ver') for k, s in sd.items() if s},
                   'title': sd['a']['short'] if st['single'] else sd['a']['short'] + ' → ' + sd['b']['short']}
        board = {'page': self.board_store.page, 'stem': self.board.stem,
                 'path': self.board.path.replace('\\', '/')} if self.board else None
        return {'tool': 'kireview', 'port': self.port, 'lang': self.lang, 'data': self.data.replace('\\', '/'), 'presence': presence,
                'page_stamp': page_stamp(), 'sch': sch, 'board': board,
                'board_hint': self.sch.board_hint() if self.sch and not self.board else None}

    # ------------------------------------------------------------ talkpage routes: checks before the store
    def check_talk(self, path, body):
        """/_talk/api/user and /agent: the item must belong to the review, the status and fields must be ours."""
        if path not in ('/_talk/api/user', '/_talk/api/agent') or not isinstance(body, dict):
            return
        page = body.get('page')
        with self.cond:
            # a review key (sch:<slug>, board:<stem>) the server does not hold: a page left open across a restart on
            # a renamed folder. talkpage would read it as a path of an .html page and say so; say what happened instead
            if path == '/_talk/api/user' and isinstance(page, str) and REVIEW_KEY.match(page) and page not in self.talk.stores:
                raise ValueError(i18n.t('review.gone', page=page))
            s = self.talk.store(page, loose=path == '/_talk/api/agent')
        if not isinstance(s, ks.ReviewStore):
            raise ValueError('not a review: %s' % s.page)
        body['page'] = s.page
        if body.get('status') is not None:
            body['status'] = ks.norm_status(body['status'])
            ks.check_status(body['status'])
        iid = body.get('id')
        if s.kind == 'board':
            if iid not in s.data['items']:
                raise ValueError('unknown item: %s (board items are made with POST /api/board/item)' % iid)
            ks.check_fields('board', ks.norm_fields(body.get('fields')), s.data['items'][iid])
            body.pop('title', None)         # a board item's title is its own
        else:
            if not isinstance(iid, str) or not (iid in s.data['items'] or self.sch and self.sch.is_known(s, iid)):
                raise ValueError('unknown item key: %s' % iid)
            ks.check_fields('sch', ks.norm_fields(body.get('fields')))
        if path == '/_talk/api/user':      # a status alone wakes the agent only when it asks for something
            body['notify'] = body.get('status') in ks.ASKING

    # ------------------------------------------------------------ routes: (code, body[, content type[, cacheable]])
    def get(self, path, q):
        def one(k, d=''):
            return (q.get(k) or [d])[0]
        if path == '/api/info':
            return 200, self.info()
        if path == '/api/board':
            return 200, self.board_info()
        if path == '/api/board/version':
            return (200, self.board.version()) if self.board else (200, {'version': None})
        if path.startswith('/board/svg/'):
            parts = path.split('/')                          # /board/svg/<hash>/<svg|fill>/<file>
            p = self.board.svg_path(parts[3], parts[4], parts[5]) if self.board and len(parts) == 6 else None
            return self._file(p, 'image/svg+xml', True)     # the URL carries the content hash
        if path.startswith('/board/3d/'):
            parts = path.split('/')                          # /board/3d/<hash>/board.glb
            p = self.board.glb_path(parts[3]) if self.board and len(parts) == 5 and parts[4] == 'board.glb' else None
            return self._file(p, 'model/gltf-binary', True)
        if path.startswith('/figures/'):                     # <data>/figures/<review name>/<file>
            parts = [urllib.parse.unquote(x) for x in path.split('/')]
            ok = len(parts) == 4 and NAME.match(parts[2]) and NAME.match(parts[3])
            ctype = FIGURE_TYPES.get(os.path.splitext(parts[-1])[1].lower())
            return self._file(os.path.join(self.data, 'figures', parts[2], parts[3]) if ok and ctype else None, ctype)
        if path == '/api/sch/state':
            return 200, self.sch.state if self.sch else {'empty': True}
        if path.startswith('/sch/svg/'):
            parts = path.split('/')                          # /sch/svg/<a|b>/<file>[?tone=red][&cell=<col>_<row>]
            p = self.sch.svg_path(parts[3], parts[4]) if self.sch and len(parts) == 5 else None
            cell = re.match(r'^(\d+)_(\d+)$', one('cell'))
            if not p or one('cell') and not cell:
                return 404, {'error': 'not found'}
            if cell:                                         # one cell of the sheet (kireview_sch.split_sheet)
                body = kc.sheet_cell(p, int(cell.group(1)), int(cell.group(2)))
                if body is None:
                    return 404, {'error': 'not found'}
            else:
                with open(p, 'rb') as f:
                    body = f.read()
            if one('tone') in kc.TONES:
                body = kc.recolour(body, kc.TONES[one('tone')])
            return 200, body, 'image/svg+xml', True          # the URL carries ?v=<load time>
        if path.startswith('/api/datasheet/'):
            parts = path.split('/')
            p = self.sch.datasheet(parts[3], urllib.parse.unquote(parts[4])) if self.sch and len(parts) == 5 else None
            return self._file(p, kc.DATASHEET_TYPES.get(os.path.splitext(p or '')[1].lower(), 'application/octet-stream'))
        if path == '/api/datasheet-url':
            return self.datasheet_url(one('u').strip(), one('probe') == '1')
        if path == '/api/projects':
            return 200, kc.list_projects(one('dir'))
        if path == '/api/refs':
            return 200, kc.list_refs(one('path'))
        return None

    def datasheet_url(self, u, probe=False):
        """A datasheet given as a web link of the loaded schematic (no other link) as a PDF from here
        (kc.fetch_datasheet), for the datasheet tab's frame; 404 when the link gives none. With probe, only whether
        there is one ({pdf}): the tab then shows the link itself, as many makers' sites refuse to be shown inside
        another page and the browser tells the page nothing when it refuses."""
        if not self.sch or u not in self.sch.datasheet_urls():
            return 404, {'error': 'not a datasheet link of the loaded schematic'}
        p = kc.fetch_datasheet(u, os.path.join(self.data, 'cache', 'datasheets'))
        if probe:
            return 200, {'pdf': bool(p)}
        return self._file(p, 'application/pdf', True)

    @staticmethod
    def _file(p, ctype, cache=False):
        if not p or not ctype or not os.path.isfile(p):
            return 404, {'error': 'not found'}
        with open(p, 'rb') as f:
            return 200, f.read(), ctype, cache

    def _need(self, what):
        if what == 'board' and not self.board:
            raise ValueError('no board is open (POST /api/board/open {path})')
        if what == 'sch' and not self.sch:
            raise ValueError('no schematic is open (POST /api/sch/compare {a, b})')

    def post(self, path, body):
        if not isinstance(body, dict):
            raise ValueError('a JSON object is expected')
        if path == '/api/board/open':
            return 200, self.open_board(body.get('path'))
        if path == '/api/sch/compare':
            return 200, self.open_sch((body.get('a') or '').strip(), (body.get('b') or '').strip())
        if path.startswith('/api/board/'):
            self._need('board')
            if path == '/api/board/reload':
                self.board.wake.set()
                return 200, {'status': 'reloading'}
            if path == '/api/board/3d':                       # the 3D view's model: its state, made when first asked
                return 200, self.board.model3d(bool(body.get('retry')))
            with self.cond:
                if path == '/api/board/item':
                    out = ks.put_board_item(self.board_store, body)
                elif path == '/api/board/new':
                    out = self.board_new(body)
                else:
                    return None
                self.cond.notify_all()
            return 200, out
        if path.startswith('/api/sch/'):
            self._need('sch')
            if path == '/api/sch/reload':
                return 200, self.sch.load()
            if path == '/api/sch/show-diff':
                return 200, self.sch.set_show_diff(body.get('on'))
            if path == '/api/sch/sheet-pair':
                return 200, self.sch.set_sheet_pair(body.get('a') or '', body.get('b') or '')
            if path == '/api/sch/open':
                return 200, self.sch.open_kicad(body.get('side'))
            if path == '/api/sch/area':
                with self.cond:
                    out = self.sch_area(body)
                    self.cond.notify_all()
                return 200, out
            if path == '/api/sch/group':
                with self.cond:
                    out = ks.set_group(self.sch.store, body.get('id'), body.get('title') or '', body.get('keys'),
                                       body.get('rationale'))
                    self.cond.notify_all()
                return 200, out
        return None

    def delete(self, path, q):
        one = (q.get('id') or [''])[0]
        if path == '/api/board/item':
            self._need('board')
            with self.cond:
                s = self.board_store
                if one not in s.data['items']:
                    raise ValueError('unknown item id: %s' % one)
                del s.data['items'][one]
                s.touch()
                self.cond.notify_all()
                return 200, {'deleted': one, 'rev': s.data['rev']}
        if path == '/api/sch/group':
            self._need('sch')
            with self.cond:
                out = ks.delete_group(self.sch.store, one)
                self.cond.notify_all()
            return 200, out
        if path == '/api/sch/area':
            self._need('sch')
            with self.cond:
                out = ks.delete_area(self.sch.store, one)
                self.cond.notify_all()
            return 200, out
        return None

    def sch_area(self, body):
        """A question the user asks about an area of a sheet: item area:<n> (ks.new_area) with the user's comment.
        Callers hold cond."""
        sheet, side, box = body.get('sheet'), body.get('side'), body.get('box')
        comment = (body.get('comment') or '').strip()
        if side not in ('a', 'b'):
            raise ValueError('side: "a" or "b"')
        if not isinstance(sheet, str):
            raise ValueError('sheet: a sheet path ("/", "/power/", ...)')
        if not (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)):
            raise ValueError('box: [x0, y0, x1, y1] in sheet mm')
        if not comment:
            raise ValueError('comment is required')
        box = [min(box[0], box[2]), min(box[1], box[3]), max(box[0], box[2]), max(box[1], box[3])]
        refs, nets = self.sch.area_contents(side, sheet, box)
        label = sheet.strip('/').split('/')[-1] or '/'
        s = self.sch.store
        iid = ks.new_area(s, sheet, side, box, refs, nets, label)
        it = s.user(iid, comment=comment)
        self.talk.last_user_at = time.time()
        return dict(it, id=iid, rev=s.data['rev'])

    def board_new(self, body):
        """A question the user asks at a point of the board: item Q<n>, refs = what is there. Callers hold cond."""
        x, y, side, comment = body.get('x'), body.get('y'), body.get('side'), (body.get('comment') or '').strip()
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            raise ValueError('x and y (board mm) are required')
        if not isinstance(side, str) or not ks.SIDE_KEY.match(side):
            raise ValueError('side: "F", "B", "In1", ...')
        if not comment:
            raise ValueError('comment is required')
        ref, near = kb.nearest(self.board.info()['dump'], x, y, side)
        s = self.board_store
        n = 1
        while 'Q%d' % n in s.data['items']:
            n += 1
        iid = 'Q%d' % n
        first = comment.splitlines()[0]
        s.data['items'][iid] = {'title': first[:60] + ('…' if len(first) > 60 else ''), 'severity': 'info',
                                'owner': 'tbd', 'sides': [side], 'x': round(x, 3), 'y': round(y, 3), 'r': 1.0,
                                'refs': [ref] if ref else [], 'near': near, 'status': '', 'thread': [],
                                'user_rev': 0, 'agent_rev': 0, 'seen_rev': 0}
        it = s.user(iid, comment=comment)
        self.talk.last_user_at = time.time()
        return dict(it, id=iid, rev=s.data['rev'])


# ---------------------------------------------------------------- HTTP server
class Handler(tp.Handler):
    """talkpage's handler (127.0.0.1 only, own pages only, JSON POSTs) with the review routes."""
    app = None
    server_version = 'kireview/2'
    API = ('/_talk/api/', '/api/')

    def _acts(self, path, q):
        """Also the GETs that run git or walk folders at a path from the query, and the one that fetches a datasheet."""
        return super()._acts(path, q) or path in ('/api/refs', '/api/projects', '/api/datasheet-url')

    def _send(self, code, body, ctype='application/json', cache=False, headers=None):
        if not isinstance(body, bytes):
            body = tp.dump(body)
        text = ctype.startswith('text/') or ctype.endswith(('json', 'javascript'))
        self.send_response(code)
        self.send_header('Content-Type', ctype + ('; charset=utf-8' if text else ''))
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'max-age=86400' if cache else 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _run(self, fn):
        try:
            super()._run(fn)
        except RuntimeError as e:          # kicad-cli or git failed
            self._send(500, {'error': str(e)})

    def do_DELETE(self):
        self._run(self._delete)

    def _get(self):
        path, _, query = self.path.partition('?')
        if path == '/':
            target = '/board' if self.app.board and not self.app.sch else '/sch'
            return self._send(302, b'', 'text/plain', headers={'Location': target})
        name = PAGES.get(path) or (path.lstrip('/') if path in STATIC else None)
        if name:
            with open(os.path.join(HERE, name), 'rb') as f:
                body = f.read()
            if path in PAGES:                  # the page in the server's language (i18n.js reads <html lang>)
                body = body.replace(b'<html lang="ja">', b'<html lang="%s">' % self.app.lang.encode(), 1)
            return self._send(200, body, 'text/html' if path in PAGES else STATIC[path])
        q = urllib.parse.parse_qs(query)
        r = self.app.talk.get(path, q) if path.startswith('/_talk/api/') else self.app.get(path, q)
        self._send(*r) if r else self._send(404, {'error': 'not found'})

    def _body(self):
        if not (self.headers.get('Content-Type') or '').lower().startswith('application/json'):
            return None
        n = int(self.headers.get('Content-Length') or 0)
        if n > 1000000:
            raise ValueError('body too large')
        return json.loads(self.rfile.read(n).decode('utf-8')) if n else {}

    def _post(self):
        body = self._body()
        if body is None:
            return self._send(415, {'error': 'Content-Type: application/json'})
        path = self.path.partition('?')[0]
        if path.startswith('/_talk/api/'):
            self.app.check_talk(path, body)
            r = self.app.talk.post(path, body)
        else:
            r = self.app.post(path, body)
        self._send(*r) if r else self._send(404, {'error': 'not found'})

    def _delete(self):
        path, _, query = self.path.partition('?')
        r = self.app.delete(path, urllib.parse.parse_qs(query))
        self._send(*r) if r else self._send(404, {'error': 'not found'})


# ---------------------------------------------------------------- command line
def cmd_post_each(a, route):
    """put / group: POST each object of a JSON file (an object or a list of them) to the running server."""
    with open(a.file, encoding='utf-8') as f:
        data = json.load(f)
    for obj in data if isinstance(data, list) else [data]:
        r = tp.call(a, route, obj)
        print('kireview: %s %s  rev %s' % (route, r.get('id'), r.get('rev')))


def serve(args):
    data = os.path.abspath(args.data)
    pcbs = [t for t in args.targets if t.lower().endswith('.kicad_pcb')]
    schs = [t for t in args.targets if t not in pcbs]
    if len(pcbs) + bool(args.board) > 1 or len(schs) > 2:
        raise SystemExit('kireview: at most one board and two schematics (A, B)')
    seed = None
    if args.rationale:
        with open(args.rationale, encoding='utf-8') as f:
            seed = json.load(f)
    restart = os.environ.get(CHILD_ENV) == 'restart'
    app = App(data, args.kicad_bin, args.port, None if restart else seed,
              args.lang or tp.default_lang('KICAD_REVIEW_LANG'))
    Handler.app = app
    try:
        srv = tp.Server(('127.0.0.1', args.port), Handler)
    except OSError as e:
        raise SystemExit('kireview: cannot listen on 127.0.0.1:%d (%s). Another kireview? '
                         'http://127.0.0.1:%d/api/info tells what it shows.' % (args.port, e, args.port))
    board = args.board or (pcbs[0] if pcbs else None)
    if restart:                      # started again after a code change: what was open, also what the page chose
        last = app.load_open()
        schs = [s for s in (last.get('sch') or []) if s]
        board = last.get('board')
    if schs:
        print('kireview: exporting the schematic ...', flush=True)
        try:
            st = app.open_sch(schs[0], schs[1] if len(schs) > 1 else None)
            if args.no_diff and not st['single'] and not restart:
                st = app.sch.set_show_diff(False)
            print('kireview: schematic %d items, %d sheets, review %s' % (len(st['items']), len(st['sheets']),
                                                                           st['review']['file']), flush=True)
        except (ValueError, RuntimeError, OSError) as e:
            if not restart:
                raise
            print('kireview: the schematic did not open again (%s); choose it in the page' % e, flush=True)
    if board:
        print('kireview: exporting the board ...', flush=True)
        try:
            b = app.open_board(board)
            print('kireview: board %d layers, %d pads, review %s' % (len(b['layers']), len(b['dump']['pads']),
                                                                     b['review']['file']), flush=True)
        except (ValueError, RuntimeError, OSError) as e:
            if not restart:
                raise
            print('kireview: the board did not open again (%s); choose it in the page' % e, flush=True)
    url = 'http://127.0.0.1:%d/' % args.port
    page = 'board' if board and not schs else 'sch'
    print('kireview: %s%s  (Ctrl-C to stop; the agent waits with: kicad-review wait%s)'
          % (url, page, '' if args.port == PORT else ' --port %d' % args.port), flush=True)
    if not args.no_open and not restart:
        webbrowser.open(url + page)
    if os.environ.get(CHILD_ENV):    # under the watcher: watch the code, and stop when the watcher is gone
        threading.Thread(target=watch_code, args=(srv, app), daemon=True).start()
        threading.Thread(target=end_with_watcher, daemon=True).start()
    try:
        srv.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    if app.restarting:
        sys.exit(RESTART_CODE)


# ---------------------------------------------------------------- start again on a code change
def code_files():
    """The Python files of the server: kicad_review and the talkpage package it uses."""
    out = []
    for pkg in (HERE, os.path.dirname(os.path.abspath(tp.__file__))):
        out += glob.glob(os.path.join(pkg, '*.py'))
    return out


def code_stamp():
    out = {}
    for p in code_files():
        try:
            out[p] = os.stat(p).st_mtime_ns
        except OSError:
            pass
    return out


def wait_code_change(seen):
    """Wait until the code differs from seen (an edit of several files is let settle for a second); the new stamp."""
    while True:
        time.sleep(1)
        now = code_stamp()
        if now != seen:
            time.sleep(1)
            return code_stamp()


def watch_code(srv, app):
    """In the server: when its Python files change and all of them compile, stop with RESTART_CODE (the watcher then
    starts the new code). A change that does not compile is reported, and the next change is waited for."""
    seen = code_stamp()
    while True:
        now = wait_code_change(seen)
        changed = sorted(os.path.basename(p) for p in set(now) | set(seen) if now.get(p) != seen.get(p))
        seen = now
        bad = []
        for p in now:
            try:
                with open(p, encoding='utf-8') as f:
                    compile(f.read(), p, 'exec')
            except (SyntaxError, ValueError, OSError) as e:
                bad.append('%s: %s' % (os.path.basename(p), e))
        if bad:
            print('kicad-review: not started again, the code does not compile: ' + '; '.join(bad), flush=True)
            continue
        print('kicad-review: %s changed, starting the server again ...' % ', '.join(changed), flush=True)
        app.restarting = True
        srv.shutdown()
        return


def end_with_watcher():
    """In the server: when the watcher (its parent, WATCHER_ENV) is gone (stopped, killed), the server stops too. Not by
    a read on a pipe from the watcher: on Windows a pending read blocks every new subprocess (kicad-cli, git)."""
    try:
        pid = int(os.environ.get(WATCHER_ENV) or 0)
    except ValueError:
        return
    if not pid:
        return
    if os.name == 'nt':
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x00100000, False, pid)        # SYNCHRONIZE, opened now: a reused pid cannot fool it
        if not h:
            os._exit(0)
        k32.WaitForSingleObject(h, 0xFFFFFFFF)            # until the watcher ends
    else:
        while os.getppid() == pid:
            time.sleep(1)
    os._exit(0)


def supervise(argv):
    """The watcher: run the server (python -m kicad_review argv) as a child and start it again when it exits with
    RESTART_CODE. If the new code then fails within START_S, wait for the next change of the code; a server stopped
    later (killed, crashed) ends the watcher too. Ctrl-C stops both."""
    src = os.path.dirname(HERE)       # the folder holding kicad_review and talkpage (a clone's src, or site-packages)
    env = dict(os.environ, **{CHILD_ENV: '1', WATCHER_ENV: str(os.getpid())})
    env['PYTHONPATH'] = src + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    restarted = False
    while True:
        started = time.time()
        child = subprocess.Popen([sys.executable, '-m', 'kicad_review'] + argv, env=env, stdin=subprocess.DEVNULL)
        try:
            code = child.wait()
        except KeyboardInterrupt:     # the console's Ctrl-C reaches the server too
            try:
                child.wait(timeout=10)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                child.kill()
            return 0
        if code == RESTART_CODE or restarted and code != 0 and time.time() - started < START_S:
            if code != RESTART_CODE:
                print('kicad-review: the server did not start with the new code (exit %d); '
                      'it starts again when the code changes' % code, flush=True)
                try:
                    wait_code_change(code_stamp())
                except KeyboardInterrupt:
                    return 0
            restarted = True
            env[CHILD_ENV] = 'restart'
            continue
        return code


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if len(sys.argv) > 1 and sys.argv[1] in TALK_CMDS:
        sys.argv = ['kicad-review', '--port', str(PORT)] + sys.argv[1:]
        return tp.main()
    if len(sys.argv) > 1 and sys.argv[1] == 'renumber':
        from . import renumber_review
        return renumber_review.main(sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] in ('put', 'group'):
        p = argparse.ArgumentParser(prog='kicad-review ' + sys.argv[1])
        p.add_argument('--file', required=True, help='JSON: one object or a list of them')
        p.add_argument('--port', type=int, default=PORT)
        a = p.parse_args(sys.argv[2:])
        return cmd_post_each(a, '/api/board/item' if sys.argv[1] == 'put' else '/api/sch/group')
    p = argparse.ArgumentParser(prog='kicad-review', description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('targets', nargs='*', help='schematic A [B] (folder, .kicad_sch, <repo>@<ref>:<path>) and / or a .kicad_pcb')
    p.add_argument('--board', help='the .kicad_pcb to review')
    p.add_argument('--data', default='.', help='folder for reviews/, cache/ and figures/ (default: current folder)')
    p.add_argument('--port', type=int, default=PORT)
    p.add_argument('--no-open', action='store_true', help='do not open the page in the browser')
    p.add_argument('--kicad-bin', default=kp.default_bin(),
                   help='folder of kicad-cli (default: $KICAD_BIN or the usual install place; see kicad_paths.py)')
    p.add_argument('--rationale', help='JSON file {item key: intent} to seed the schematic review (kept if already set)')
    p.add_argument('--version', action='version', version='kicad-review ' + __version__)
    p.add_argument('--no-diff', action='store_true', help='two schematics: only put them side by side (saved in the review)')
    p.add_argument('--lang', choices=i18n.LANGS,
                   help='language of the pages (default: $KICAD_REVIEW_LANG, else ja for a Japanese OS, else en)')
    p.add_argument('--no-reload', action='store_true',
                   help='one process: do not start the server again when its Python files change')
    args = p.parse_args()
    if args.no_reload or os.environ.get(CHILD_ENV):
        return serve(args)
    sys.exit(supervise(sys.argv[1:]))


if __name__ == '__main__':
    main()
