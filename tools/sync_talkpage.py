r"""Copy talkpage into this repository from a clone of https://github.com/yus988/talkpage (its main source).

  python tools/sync_talkpage.py <talkpage clone>

kicad-review carries a copy of talkpage so that it runs with nothing installed. Change talkpage in its own
repository, commit there, then run this and commit here; do not edit the copied files here. What is copied:
src/talkpage/* -> src/talkpage/, tests/test_talkpage.py -> tests/, sample/index.html -> examples/talkpage-sample/,
README.md / README.en.md -> docs/talkpage.md / docs/talkpage.en.md (links made to work from docs/). The source commit
is written to src/talkpage/SOURCE.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [('src/talkpage/__init__.py', 'src/talkpage/__init__.py'),
         ('src/talkpage/__main__.py', 'src/talkpage/__main__.py'),
         ('src/talkpage/talkpage.js', 'src/talkpage/talkpage.js'),
         ('src/talkpage/talkpage.css', 'src/talkpage/talkpage.css'),
         ('tests/test_talkpage.py', 'tests/test_talkpage.py'),
         ('sample/index.html', 'examples/talkpage-sample/index.html')]
DOCS = [('README.md', 'docs/talkpage.md',
         '> kicad-review に同梱の talkpage の説明（[talkpage](https://github.com/yus988/talkpage) の README の写し）。'
         'kicad-review を入れると、コマンド `talkpage` も入る。\n\n'),
        ('README.en.md', 'docs/talkpage.en.md',
         '> The talkpage bundled with kicad-review (a copy of the README of '
         '[talkpage](https://github.com/yus988/talkpage)). Installing kicad-review also installs the command '
         '`talkpage`.\n\n')]
LINKS = [('(README.en.md)', '(talkpage.en.md)'), ('(README.md)', '(talkpage.md)'),
         ('(sample/index.html)', '(../examples/talkpage-sample/index.html)'), ('(LICENSE)', '(../LICENSE)')]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = os.path.abspath(sys.argv[1])
    if not os.path.isfile(os.path.join(src, 'src', 'talkpage', '__init__.py')):
        sys.exit('not a talkpage clone: ' + src)
    git = ['git', '-C', src]
    if subprocess.run(git + ['status', '--porcelain'], capture_output=True, text=True).stdout.strip():
        sys.exit('the talkpage clone has uncommitted changes; commit them there first')
    rev = subprocess.run(git + ['rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    for a, b in FILES:
        os.makedirs(os.path.dirname(os.path.join(HERE, b)), exist_ok=True)
        shutil.copyfile(os.path.join(src, a), os.path.join(HERE, b))
    for a, b, head in DOCS:
        with open(os.path.join(src, a), encoding='utf-8') as f:
            text = f.read()
        for old, new in LINKS:
            text = text.replace(old, new)
        title, _, rest = text.partition('\n\n')
        with open(os.path.join(HERE, b), 'w', encoding='utf-8', newline='\n') as f:
            f.write(title + '\n\n' + head + rest)
    with open(os.path.join(HERE, 'src', 'talkpage', 'SOURCE'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('https://github.com/yus988/talkpage %s\n' % rev)
    print('talkpage %s copied; review with git diff and commit' % rev[:7])


if __name__ == '__main__':
    main()
