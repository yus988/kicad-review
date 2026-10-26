"""The example designs through KiCad (skipped when kicad-cli is not found), and the helpers that need no KiCad.
python -m unittest discover tests"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'src'))     # run from a clone without installing
from kicad_review import kicad_paths as kp  # noqa: E402
from kicad_review import kireview as kr  # noqa: E402
from kicad_review import renumber_review as rr  # noqa: E402

EX = os.path.join(ROOT, 'examples')
BIN = kp.default_bin()


def have_kicad():
    try:
        return subprocess.run([kp.cli(BIN), 'version'], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class RenumberTest(unittest.TestCase):
    def test_text(self):
        m = {'R35': 'R10', 'R36': 'R11', 'R37': 'R12', 'C2': 'C9', 'Q1': 'Q4'}
        self.assertEqual(rr.renumber_text('R35~R37, C2, Q1A, C20, XR35', m), 'R10~R12, C9, Q4A, C20, XR35')

    def test_file(self):
        d = tempfile.mkdtemp()
        try:
            rev, mp = os.path.join(d, 'r.json'), os.path.join(d, 'm.json')
            with open(rev, 'w', encoding='utf-8') as f:
                json.dump({'rev': 3, 'items': {'comp:R33': {'status': ''}, 'net:/Net-(U6-EN)': {}, 'group:g1': {}},
                           'groups': [{'id': 'g1', 'title': 'R33 and U6', 'keys': ['comp:R33'], 'rationale': 'U6'}]}, f)
            with open(mp, 'w', encoding='utf-8') as f:
                json.dump({'R33': 'R15', 'U6': 'U3'}, f)
            rr.main([rev, mp])
            with open(rev, encoding='utf-8') as f:
                out = json.load(f)
            self.assertEqual(sorted(out['items']), ['comp:R15', 'group:g1', 'net:/Net-(U3-EN)'])
            self.assertEqual((out['groups'][0]['title'], out['groups'][0]['keys'], out['rev']), ('R15 and U3', ['comp:R15'], 4))
        finally:
            shutil.rmtree(d)


class PathsTest(unittest.TestCase):
    def test_bin_dir(self):
        b = os.path.join('x', 'bin')
        self.assertEqual(os.path.basename(kp.cli(b)), 'kicad-cli.exe' if os.name == 'nt' else 'kicad-cli')
        self.assertEqual(kp._version_key('C:/Program Files/KiCad/10.0/bin'), [10, 0])
        self.assertGreater(kp._version_key('/K/10.0/bin'), kp._version_key('/K/9.0/bin'))


@unittest.skipUnless(have_kicad(), 'KiCad (kicad-cli) not found: set KICAD_BIN to run these')
class ExampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = tempfile.mkdtemp()
        cls.app = kr.App(cls.data, BIN, 0)

    @classmethod
    def tearDownClass(cls):
        if cls.app.board:
            cls.app.board.stop()
        shutil.rmtree(cls.data, ignore_errors=True)

    def test_schematic_diff(self):
        st = self.app.open_sch(os.path.join(EX, 'blinky_v1'), os.path.join(EX, 'blinky_v2'))
        keys = {it['key'] for it in st['items']}
        for k in ('comp:R2', 'comp:D2', 'field:R1', 'field:C1', 'net:/LED1_A', 'net:/STATUS_A'):
            self.assertIn(k, keys)
        self.assertFalse(any(k.startswith('comp:') and k[5:] in ('R1', 'C1', 'D1', 'J1') for k in keys))
        st = self.app.open_sch(os.path.join(EX, 'blinky_v2'), None)                  # one design: every part
        self.assertEqual(sorted(it['key'] for it in st['items']),
                         ['comp:C1', 'comp:D1', 'comp:D2', 'comp:J1', 'comp:R1', 'comp:R2'])

    def test_board_export(self):
        b = self.app.open_board(os.path.join(EX, 'blinky_v2', 'blinky_v2.kicad_pcb'))
        self.assertIn('F.Cu', b['layers'] if isinstance(b['layers'][0], str) else [x['name'] for x in b['layers']])
        self.assertEqual(len(b['dump']['pads']), 12)
        self.assertFalse(os.path.exists(os.path.join(EX, 'blinky_v2', 'blinky_v2-F_Cu.svg')))  # the project is not written to


if __name__ == '__main__':
    unittest.main()
