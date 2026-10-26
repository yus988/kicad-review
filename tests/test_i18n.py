"""The English and Japanese text tables have the same keys, the pages use only keys that exist, and the language
helper. python -m unittest discover tests"""
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SRC = os.path.join(ROOT, 'src')
sys.path.insert(0, SRC)     # run from a clone without installing
import talkpage as tp  # noqa: E402
from kicad_review import i18n  # noqa: E402

KR = os.path.join(SRC, 'kicad_review')


def read(*parts):
    with open(os.path.join(*parts), encoding='utf-8') as f:
        return f.read()


def js_table(src, lang):
    """Keys of the `<lang>: { 'key': '...', ... }` block of a JS text table (one entry per line)."""
    m = re.search(r"^\s*%s: \{\n(.*?)\n\s*\}" % lang, src, re.S | re.M)
    if not m:
        raise AssertionError('no %s table' % lang)
    return re.findall(r"^\s*'([^']+)':", m.group(1), re.M)


class TablesTest(unittest.TestCase):
    def check_pair(self, en, ja):
        self.assertTrue(en)
        self.assertEqual(len(en), len(set(en)), 'duplicate keys')
        self.assertEqual(sorted(set(en) - set(ja)), [], 'missing in ja')
        self.assertEqual(sorted(set(ja) - set(en)), [], 'missing in en')

    def test_page_table(self):
        src = read(KR, 'i18n.js')
        self.check_pair(js_table(src, 'en'), js_table(src, 'ja'))

    def test_talkpage_table(self):
        src = read(SRC, 'talkpage', 'talkpage.js')
        self.check_pair(js_table(src, 'en'), js_table(src, 'ja'))

    def test_server_tables(self):
        self.check_pair(list(i18n.MSG['en']), list(i18n.MSG['ja']))
        self.check_pair(list(tp.LISTING['en']), list(tp.LISTING['ja']))

    def test_pages_use_known_keys(self):
        known = set(js_table(read(KR, 'i18n.js'), 'en'))
        used = set()
        for name in ('sch.html', 'board.html', 'review.js'):
            src = read(KR, name)
            used |= set(re.findall(r"\bt\('([\w.-]+)'\s*[,)]", src))
            used |= set(re.findall(r'data-i18n(?:-title|-placeholder)?="([\w.-]+)"', src))
            # keys made from codes: 'st.btn.' + c and the like
            for prefix, codes in (('st.btn.', ('fixed', 'fix', 'ok')), ('st.title.', ('fixed', 'fix', 'ok')),
                                  ('st.name.', ('open', 'ok', 'fix', 'fixed', 'question', 'self-fix')),
                                  ('st.line.', ('open', 'ok', 'fix', 'fixed', 'question', 'self-fix')),
                                  ('sev.', ('must', 'should', 'could', 'info')), ('owner.', ('human', 'agent', 'tbd')),
                                  ('presence.', ('listening', 'working', 'absent', 'down')),
                                  ('dock.side.', ('left', 'right', 'top', 'bottom')), ('side.', ('F', 'B')),
                                  ('kind.', ('comp_added', 'comp_removed', 'comp_changed', 'pin_moved', 'group',
                                             'label_changed', 'sheet_renamed'))):
                if "'%s' +" % prefix in src:
                    used |= {prefix + c for c in codes}
        self.assertEqual(sorted(used - known), [])

    def test_server_text(self):
        try:
            i18n.set_lang('ja')
            self.assertEqual(i18n.t('comp.added', ref='R2', value='1k'), 'R2 追加  1k')
            i18n.set_lang('xx')
            self.assertEqual(i18n.t('comp.added', ref='R2', value='1k'), 'R2 added  1k')
        finally:
            i18n.set_lang('en')


class LangTest(unittest.TestCase):
    def test_env_override(self):
        for v, want in (('ja', 'ja'), ('en', 'en'), ('ja_JP.UTF-8', 'ja'), ('EN', 'en')):
            with mock.patch.dict(os.environ, {'KR_TEST_LANG': v}):
                self.assertEqual(tp.default_lang('KR_TEST_LANG'), want)

    def test_os_default(self):
        with mock.patch.dict(os.environ, {'KR_TEST_LANG': ''}):
            self.assertIn(tp.default_lang('KR_TEST_LANG'), ('en', 'ja'))
            with mock.patch('locale.getlocale', return_value=('Japanese_Japan', '932')):
                self.assertEqual(tp.default_lang('KR_TEST_LANG'), 'ja')


if __name__ == '__main__':
    unittest.main()
