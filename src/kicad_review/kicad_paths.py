"""Where KiCad's programs are: kicad-cli, the python that can import pcbnew, and eeschema.

bin_dir is --kicad-bin (or $KICAD_BIN): the folder that holds kicad-cli. Without it the usual install places are
searched (Windows: the newest %ProgramFiles%\\KiCad\\<version>\\bin; macOS: /Applications/KiCad/KiCad.app; Linux and
others: kicad-cli and eeschema on PATH and the system python3). $KICAD_PYTHON names the python with pcbnew directly.
"""
import glob
import os
import re
import shutil
import sys

MAC_APP = '/Applications/KiCad/KiCad.app'


def _version_key(path):
    m = re.search(r'[\\/](\d+(?:\.\d+)*)[\\/]bin$', path)
    return [int(t) for t in m.group(1).split('.')] if m else [0]


def default_bin():
    """The KiCad bin folder found on this PC, or None (then kicad-cli is looked up on PATH)."""
    env = os.environ.get('KICAD_BIN')
    if env:
        return env
    if os.name == 'nt':
        roots = {os.environ.get(k) for k in ('ProgramFiles', 'ProgramW6432')} | {'C:/Program Files'}
        found = [os.path.dirname(p) for r in roots if r
                 for p in glob.glob(os.path.join(r, 'KiCad', '*', 'bin', 'kicad-cli.exe'))]
        return max(found, key=_version_key) if found else None
    if sys.platform == 'darwin' and os.path.isfile(os.path.join(MAC_APP, 'Contents', 'MacOS', 'kicad-cli')):
        return os.path.join(MAC_APP, 'Contents', 'MacOS')
    return None


def _exe(name):
    return name + '.exe' if os.name == 'nt' else name


def _in(bin_dir, name):
    if bin_dir:
        return os.path.join(bin_dir, _exe(name))
    return shutil.which(name) or name          # a missing program fails when it is run, with its name


def cli(bin_dir):
    return _in(bin_dir, 'kicad-cli')


def python(bin_dir):
    """The python that imports pcbnew: KiCad's own on Windows and macOS, the system python3 on Linux."""
    env = os.environ.get('KICAD_PYTHON')
    if env:
        return env
    if os.name == 'nt' and bin_dir:
        return os.path.join(bin_dir, 'python.exe')
    if sys.platform == 'darwin' and bin_dir:
        app = os.path.dirname(os.path.dirname(os.path.abspath(bin_dir)))       # <KiCad.app>/Contents/MacOS
        return os.path.join(app, 'Contents', 'Frameworks', 'Python.framework', 'Versions', 'Current', 'bin',
                            'python3')
    return '/usr/bin/python3' if os.path.isfile('/usr/bin/python3') else (shutil.which('python3') or 'python3')


def eeschema(bin_dir):
    if sys.platform == 'darwin' and bin_dir:
        app = os.path.dirname(os.path.dirname(os.path.abspath(bin_dir)))
        return os.path.join(app, 'Contents', 'Applications', 'eeschema.app', 'Contents', 'MacOS', 'eeschema')
    return _in(bin_dir, 'eeschema')
