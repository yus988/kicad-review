"""Board side of kicad-review: export a KiCad PCB for the review page and find what is at a point.

The board is copied to <data>/cache/board/<stem>/<hash>/ and kicad-cli exports one SVG per layer from the copy: copper
without zone fills (tracks, pads and vias stay readable), and the copper with the fills a second time, drawn faintly
under it in the page. kireview_dump.py (run with KiCad's python) lists footprints and pads. The project folder is
only read. When the board file changes (saved in KiCad) the export runs again in the background (Board.watch).
The 3D view's model (GLB, kicad-cli pcb export glb) takes seconds to minutes, so it is not part of the export above:
it is made in the background once the board has stayed unchanged for SETTLE_S, or when the page asks for it
(Board.model3d).
The review items live in kireview_store (reviews/<stem>.json); kireview.py serves the routes.
"""
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import threading
import time

from . import kicad_paths as kp
from .i18n import t

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP = os.path.join(HERE, 'kireview_dump.py')
EXTRA_LAYERS = ('F.Silkscreen', 'B.Silkscreen', 'Edge.Cuts', 'F.Courtyard', 'B.Courtyard')
CROP_MARGIN = 2.0             # mm around the board outline kept in the layer SVGs
NEAR_PAD_MM = 1.5             # a click this close to a pad names the pad
WATCH_S = 2.0
CACHE_KEEP = 2                # current export and the one before
SETTLE_S = 30                 # the board unchanged this long (s): its 3D model is exported in the background
EXPORT_V = 2                  # cache format: an export of another version is made again
# the 3D model: the parts' models (STEP in place of VRML of the same name, as KiCad's 3D viewer) on the board with its
# copper, silkscreen and soldermask
GLB_OPTS = ('--subst-models', '--include-tracks', '--include-pads', '--include-zones', '--include-silkscreen',
            '--include-soldermask')


# ---------------------------------------------------------------- export
def strip_fills(t):
    """Drop every (filled_polygon ...) so zones plot unfilled: tracks, pads and vias stay readable."""
    out, i = [], 0
    while True:
        j = t.find('(filled_polygon', i)
        if j < 0:
            return ''.join(out) + t[i:]
        out.append(t[i:j])
        d, k = 0, j
        while True:
            c = t[k]
            d += c == '('
            d -= c == ')'
            k += 1
            if d == 0:
                break
        i = k


def _rmtree(path):
    def onerror(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def run(cmd, cwd, low=False):
    """Run a KiCad program; its output (stdout, stderr). low: below normal priority (the 3D export, which may run in
    the background while KiCad is in use)."""
    kw = {}
    if low and os.name == 'nt':
        kw['creationflags'] = subprocess.BELOW_NORMAL_PRIORITY_CLASS
    elif low:
        kw['preexec_fn'] = lambda: os.nice(10)
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, **kw)
    except FileNotFoundError:
        raise RuntimeError('%s not found: install KiCad 10, or pass --kicad-bin <folder of kicad-cli> '
                           '(or set KICAD_BIN / KICAD_PYTHON)' % cmd[0])
    if r.returncode:
        raise RuntimeError('%s failed (%d): %s' % (os.path.basename(cmd[0]), r.returncode,
                                                   (r.stderr or r.stdout).decode('utf-8', 'replace')[-800:]))
    return (r.stdout + b'\n' + r.stderr).decode('utf-8', 'replace')


def crop_svg(path, box):
    """Shrink the page of a layer SVG to box (board mm) and drop a full-page background rect, if any.

    With --page-size-mode 1 the SVG page is the board's page: viewBox units per mm = viewBox width / width in mm
    (1 in KiCad 10) and the page origin is the board origin, so board mm map to user units by that factor alone."""
    with open(path, encoding='utf-8') as f:
        svg = f.read()
    m = re.search(r'width="([\d.]+)mm" height="([\d.]+)mm" viewBox="([\d.\-]+) ([\d.\-]+) ([\d.]+) ([\d.]+)"', svg)
    if not m:
        raise RuntimeError('unexpected SVG header: %s' % path)
    wmm, hmm, vx, vy, vw, vh = (float(v) for v in m.groups())
    k = vw / wmm
    x0, y0, x1, y1 = box

    def bg(r):
        a = dict(re.findall(r'(\w+)="([^"]*)"', r.group(0)))
        full = abs(float(a.get('width', 0)) - vw) < 0.01 and abs(float(a.get('height', 0)) - vh) < 0.01
        return '' if full else r.group(0)
    svg = re.sub(r'<rect[^>]*/>', bg, svg)
    svg = svg[:m.start()] + 'width="%.4fmm" height="%.4fmm" viewBox="%.4f %.4f %.4f %.4f"' % (
        x1 - x0, y1 - y0, vx + x0 * k, vy + y0 * k, (x1 - x0) * k, (y1 - y0) * k) + svg[m.end():]
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(svg)


def export(board, data, kicad_bin):
    """Copy, dump and plot the board into <data>/cache/board/<stem>/<hash>/ unless that export exists. Returns its
    meta: crop box, layer SVG files (zone fills stripped) and fills (copper layers with their zone fills)."""
    stem = os.path.splitext(os.path.basename(board))[0]
    with open(board, 'rb') as f:
        raw = f.read()
    h = hashlib.sha1(raw).hexdigest()[:12]
    base = os.path.join(data, 'cache', 'board', stem)
    d = os.path.join(base, h)
    meta_path = os.path.join(d, 'meta.json')
    if os.path.isfile(meta_path):
        with open(meta_path, encoding='utf-8') as f:
            meta = json.load(f)
        if meta.get('v') == EXPORT_V:
            return meta
    if os.path.isdir(d):
        _rmtree(d)
    os.makedirs(os.path.join(d, 'svg'))
    os.makedirs(os.path.join(d, 'fill'))
    copy = os.path.join(d, stem + '.kicad_pcb')
    with open(copy, 'w', encoding='utf-8', newline='') as f:
        f.write(strip_fills(raw.decode('utf-8')))
    filled = os.path.join(d, 'fill', stem + '.kicad_pcb')          # as saved: zones with their fills
    with open(filled, 'wb') as f:
        f.write(raw)
    pro = os.path.splitext(board)[0] + '.kicad_pro'
    if os.path.isfile(pro):
        shutil.copy2(pro, os.path.join(d, stem + '.kicad_pro'))
    py = kp.python(kicad_bin)
    run([py, DUMP, copy, os.path.join(d, 'dump.json')], d)
    with open(os.path.join(d, 'dump.json'), encoding='utf-8') as f:
        dump = json.load(f)
    layers = dump['layers'] + list(EXTRA_LAYERS)
    cli = kp.cli(kicad_bin)
    opts = ['--exclude-drawing-sheet', '--page-size-mode', '1', '--drill-shape-opt', '2']
    run([cli, 'pcb', 'export', 'svg', '--mode-multi', '-l', ','.join(layers), '-o', os.path.join(d, 'svg')] + opts + [copy], d)
    run([cli, 'pcb', 'export', 'svg', '--mode-multi', '-l', ','.join(dump['layers']), '-o', os.path.join(d, 'fill')]
        + opts + [filled], d)
    bb = dump['bbox'] or _parts_box(dump)
    crop = [bb[0] - CROP_MARGIN, bb[1] - CROP_MARGIN, bb[2] + CROP_MARGIN, bb[3] + CROP_MARGIN]
    files, fills = {}, {}
    for name in layers:
        fn = '%s-%s.svg' % (stem, name.replace('.', '_'))
        for sub, out in (('svg', files), ('fill', fills)):
            fp = os.path.join(d, sub, fn)
            if os.path.isfile(fp):
                crop_svg(fp, crop)
                out[name] = fn
    os.remove(filled)
    meta = {'v': EXPORT_V, 'hash': h, 'board': board.replace('\\', '/'), 'time': time.time(), 'crop': crop,
            'files': files, 'fills': fills}
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False)
    # keep this export and the newest other one (the cache holds only files written here, no links)
    old = sorted((os.path.getmtime(os.path.join(base, n, 'meta.json')) if os.path.isfile(os.path.join(base, n, 'meta.json')) else 0, n)
                 for n in os.listdir(base) if n != h and os.path.isdir(os.path.join(base, n)))
    for _, n in old[:max(0, len(old) - (CACHE_KEEP - 1))]:
        try:
            _rmtree(os.path.join(base, n))
        except OSError:     # a file of it is open (its 3D model being sent): the next export removes it
            pass
    return meta


def missing_models(log):
    """The parts whose 3D model kicad-cli could not add, from its output ("Could not add 3D model for J3." and the
    line after, mostly "File not found: <path>"): [{ref, file}] or [{ref, why}]."""
    out, lines = [], log.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r'\s*Could not add 3D model for (.+?)\.?\s*$', ln)
        if not m:
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ''
        f = re.match(r'File not found:\s*(.*)$', nxt)
        out.append({'ref': m.group(1), 'file': f.group(1)} if f else {'ref': m.group(1), 'why': nxt})
    return out


def export_3d(board, data, d, kicad_bin, h):
    """The board with its parts' 3D models as one GLB, <d>/board.glb (d: the export folder of version h), and what
    could not be added (<d>/3d.json). kicad-cli reads a copy made in <data>/cache/3d-tmp/ (the project folder is only
    read; the copy is outside the export folders, which a newer export may remove meanwhile), run in the project
    folder with KIPRJMOD set to it, so models given by ${KIPRJMOD} or by a path relative to the project are found.
    Returns the state for Board.model3d; 'stale' when the board was saved again since version h."""
    with open(board, 'rb') as f:
        raw = f.read()
    if hashlib.sha1(raw).hexdigest()[:12] != h:
        return {'state': 'stale'}
    stem = os.path.splitext(os.path.basename(board))[0]
    tmp = os.path.join(data, 'cache', '3d-tmp', '%s-%s' % (stem, h))
    if os.path.isdir(tmp):
        _rmtree(tmp)
    os.makedirs(tmp)
    try:
        copy = os.path.join(tmp, stem + '.kicad_pcb')
        with open(copy, 'wb') as f:
            f.write(raw)
        pro = os.path.splitext(board)[0] + '.kicad_pro'
        if os.path.isfile(pro):
            shutil.copy2(pro, os.path.join(tmp, stem + '.kicad_pro'))
        proj = os.path.dirname(os.path.abspath(board))
        out = os.path.join(tmp, 'board.glb')
        log = run([kp.cli(kicad_bin), 'pcb', 'export', 'glb', *GLB_OPTS, '-D', 'KIPRJMOD=' + proj, '-f', '-o', out,
                   copy], proj, low=True)
        if not os.path.isfile(os.path.join(d, 'meta.json')):
            return {'state': 'stale'}               # a newer export removed this version's folder meanwhile
        os.replace(out, os.path.join(d, 'board.glb'))
        with open(os.path.join(d, '3d.json'), 'w', encoding='utf-8') as f:
            json.dump({'missing': missing_models(log), 'time': time.time()}, f, ensure_ascii=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return read_3d(d, h)


def read_3d(d, h):
    """The 3D model of export folder d, made before: the state for Board.model3d, or None."""
    try:
        with open(os.path.join(d, '3d.json'), encoding='utf-8') as f:
            info = json.load(f)
    except (OSError, ValueError):
        return None
    if not os.path.isfile(os.path.join(d, 'board.glb')):
        return None
    return {'state': 'ready', 'url': '/board/3d/%s/board.glb' % h, 'missing': info.get('missing', [])}


def _parts_box(dump):
    """Board without an outline: the footprints' extent."""
    bs = [f['bbox'] for f in dump['footprints']] or [[0, 0, 100, 100]]
    return [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)]


def side_layer(side):
    return 'F.Cu' if side == 'F' else 'B.Cu' if side == 'B' else side + '.Cu'


def _inside(poly, x, y):
    c = False
    for i in range(len(poly)):
        (x0, y0), (x1, y1) = poly[i - 1], poly[i]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            c = not c
    return c


def nearest(dump, x, y, side):
    """What was clicked: the nearest pad on that side's copper within NEAR_PAD_MM, else the smallest footprint whose
    box holds the point (that side's first). Returns (ref text, description) or (None, '')."""
    layer = side_layer(side)
    best = None
    for p in dump['pads']:
        if layer not in p['layers']:
            continue
        dist = 0.0 if p.get('poly') and _inside(p['poly'], x, y) else math.hypot(p['x'] - x, p['y'] - y)
        if dist <= NEAR_PAD_MM and (best is None or dist < best[0]):
            best = (dist, p)
    if best:
        p = best[1]
        return '%s.%s' % (p['ref'], p['num']), '%s %s %s' % (p['ref'], p['num'], p['net'] or t('no_net'))
    hits = [f for f in dump['footprints'] if f['bbox'][0] <= x <= f['bbox'][2] and f['bbox'][1] <= y <= f['bbox'][3]]
    if hits:
        f = min(hits, key=lambda f: (f['side'] != side, (f['bbox'][2] - f['bbox'][0]) * (f['bbox'][3] - f['bbox'][1])))
        return f['ref'], '%s (%s) %s' % (f['ref'], f['value'], t('side.F' if f['side'] == 'F' else 'side.B'))
    return None, ''


class Board:
    """The board under review: the last good export, re-exported in a background thread when the file changes.
    prepare_3d: also export the 3D model of a version once it has stayed SETTLE_S, so the 3D view need not wait."""

    def __init__(self, path, data, kicad_bin, prepare_3d=True):
        self.path = os.path.abspath(path)
        self.data = data
        self.kicad_bin = kicad_bin
        self.stem = os.path.splitext(os.path.basename(self.path))[0]
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.meta, self.dump = None, None
        self.status, self.error = 'ok', ''
        self.stamp = None
        self.stopped = threading.Event()
        self.x3d = {}               # export hash -> the state of its 3D model (model3d)
        self.want3d, self.busy3d = None, False   # the version to export next; one kicad-cli at a time
        self.prepare_3d = prepare_3d
        self.settle_at = None       # when the current version's 3D model is due (prepare_3d)

    def _stamp(self):
        st = os.stat(self.path)
        return (st.st_mtime_ns, st.st_size)

    def load(self):
        stamp = self._stamp()
        meta = export(self.path, self.data, self.kicad_bin)
        with open(os.path.join(self.dir(meta['hash']), 'dump.json'), encoding='utf-8') as f:
            dump = json.load(f)
        with self.lock:
            self.meta, self.dump, self.stamp = meta, dump, stamp
            self.status, self.error = 'ok', ''
            self.settle_at = time.time() + SETTLE_S if self.prepare_3d else None

    def dir(self, h):
        return os.path.join(self.data, 'cache', 'board', self.stem, h)

    def watch(self):
        while not self.stopped.is_set():
            forced = self.wake.wait(WATCH_S)
            self.wake.clear()
            if self.stopped.is_set():
                return
            self._prepare_3d()
            try:
                if not forced and self._stamp() == self.stamp:
                    continue
            except OSError:         # the editor is replacing the file: next round
                continue
            with self.lock:
                self.status = 'reloading'
            try:
                self.load()
            except Exception as e:  # keep serving the last good export; the page shows the error
                with self.lock:
                    self.status, self.error = 'error', str(e)
                    try:
                        self.stamp = self._stamp()
                    except OSError:
                        pass

    def _prepare_3d(self):
        """The board has stayed as it is for SETTLE_S since its last export: its 3D model now (model3d does nothing
        when it is there, being made, or failed)."""
        with self.lock:
            due = self.settle_at is not None and time.time() >= self.settle_at
            if due:
                self.settle_at = None
        if due:
            self.model3d()

    def stop(self):
        """Another board was opened: end the watch thread."""
        self.stopped.set()
        self.wake.set()

    def version(self):
        with self.lock:
            return {'version': self.meta['hash'], 'status': self.status, 'error': self.error}

    def info(self):
        with self.lock:
            m, d = self.meta, self.dump
            return {'board': self.path.replace('\\', '/'), 'stem': self.stem, 'version': m['hash'],
                    'status': self.status, 'error': self.error, 'bbox': d['bbox'], 'crop': m['crop'],
                    'copper': d['layers'],
                    'layers': [{'name': n, 'url': '/board/svg/%s/svg/%s' % (m['hash'], fn),
                                'fill': '/board/svg/%s/fill/%s' % (m['hash'], m['fills'][n]) if n in m.get('fills', {}) else None}
                               for n, fn in m['files'].items()],
                    'dump': d}

    def model3d(self, retry=False):
        """The 3D model of the current export: {version, state: ready | exporting | stale | error, url, missing,
        error}. The first ask starts kicad-cli in a thread and the page asks again until it is ready. retry: try
        again after an error. One export runs at a time: saves while one runs leave only the newest version to do
        next (a large board takes a minute or more)."""
        with self.lock:
            h = self.meta['hash']
            st = self.x3d.get(h)
            if st and st['state'] in ('error', 'stale') and retry:
                st = None
            if st is None:
                st = read_3d(self.dir(h), h)
                if st is None:
                    st = {'state': 'exporting'}
                    self.want3d = h
                    if not self.busy3d:
                        self.busy3d = True
                        threading.Thread(target=self._work_3d, daemon=True).start()
                self.x3d[h] = st
            return dict(st, version=h)

    def _work_3d(self):
        while True:
            with self.lock:
                h, self.want3d = self.want3d, None
                if h is None:
                    self.busy3d = False
                    return
            try:
                st = export_3d(self.path, self.data, self.dir(h), self.kicad_bin, h)
            except Exception as e:  # kicad-cli failed, or the folder went with the cache: the page shows it
                st = {'state': 'error', 'error': str(e)}
            with self.lock:
                self.x3d[h] = st
                keep = (self.meta['hash'], self.want3d)                 # older versions: forget
                self.x3d = {k: v for k, v in self.x3d.items() if k in keep}

    def glb_path(self, h):
        if not re.match(r'^[0-9a-f]+$', h):
            return None
        p = os.path.join(self.dir(h), 'board.glb')
        return p if os.path.isfile(p) else None

    def svg_path(self, h, sub, name):
        if (not re.match(r'^[0-9a-f]+$', h) or sub not in ('svg', 'fill') or '/' in name or '\\' in name
                or not name.endswith('.svg')):
            return None
        p = os.path.join(self.dir(h), sub, name)
        return p if os.path.isfile(p) else None
