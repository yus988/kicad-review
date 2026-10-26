"""Carry a schematic review over a re-annotation: item keys, group keys, group titles and reasons get the new part
references (comp:R33 -> comp:R15, pin:U6 -> pin:U3, net:Net-(U6-EN) -> net:Net-(U3-EN)). The comment threads stay
as written. Stop the kicad-review server first (it keeps the review in memory and could write the old one back).

    kicad-review renumber <data>/reviews/sch/<slug>.json map.json

map.json is {old reference: new reference}, e.g. {"R33": "R15", "U6": "U3"} (from your annotation script, or written
by hand from the "renumber" item of the review).
"""
import json
import os
import re
import sys

PREFIX = re.compile(r'^(.*?)(\d+)$')
# a reference in a note (C28, Q1A) or a range of them (R35〜R39)
TOKEN = re.compile(r'(?<![A-Za-z0-9_])([A-Z]+)(\d+)(?:([〜～~])\1(\d+)(?![0-9])|([A-Z]?)(?![A-Za-z0-9]))')


def renumber_text(txt, rmap):
    """Part references written in a text (C28, Q1A, R35〜R39) changed by rmap {old: new}."""
    def rep(mt):
        p, a = mt.group(1), int(mt.group(2))
        if mt.group(3):         # a range: the new numbers, as a range again when they still follow on
            olds = ['%s%d' % (p, i) for i in range(a, int(mt.group(4)) + 1)]
            if not olds or not all(o in rmap for o in olds):
                return mt.group(0)
            nums = sorted(int(PREFIX.match(rmap[o]).group(2)) for o in olds)
            if nums == list(range(nums[0], nums[-1] + 1)):
                return '%s%d%s%s%d' % (p, nums[0], mt.group(3), p, nums[-1])
            return '・'.join('%s%d' % (p, n) for n in nums)
        old = p + mt.group(2)
        return rmap[old] + mt.group(5) if old in rmap else mt.group(0)
    return TOKEN.sub(rep, txt)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        raise SystemExit('usage: kicad-review renumber <review.json> <map.json>')
    path, map_path = argv
    with open(map_path, encoding='utf-8') as f:
        rmap = json.load(f)
    with open(path, encoding='utf-8') as f:
        d = json.load(f)

    def key(k):
        kind, _, rest = k.partition(':')
        return k if kind == 'group' or not rest else kind + ':' + renumber_text(rest, rmap)

    d['items'] = {key(k): v for k, v in d['items'].items()}
    for g in d.get('groups', []):
        g['keys'] = [key(k) for k in g['keys']]
        g['title'] = renumber_text(g['title'], rmap)
        g['rationale'] = renumber_text(g['rationale'], rmap)
    d['rev'] = int(d.get('rev', 0)) + 1
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
        f.write('\n')
    os.replace(tmp, path)
    for g in d.get('groups', []):
        print(g['id'], g['title'], g['keys'])


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()
