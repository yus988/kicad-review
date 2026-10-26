"""Review files of kicad-review, kept by talkpage's Store: the item model, the statuses and the older formats.

One file per review: <data>/reviews/<board stem>.json for a board (page key board:<stem>) and
<data>/reviews/sch/<slug>.json for schematics (page key sch:<slug>). An item is a talkpage item (status, thread,
user_rev / agent_rev / seen_rev) plus the review fields below; a schematic file also keeps groups, show_diff and
sheet_pairs at the top level. Status, severity and owner are stored as English codes (STATUSES, SEVERITIES, OWNERS);
the Japanese words of earlier versions are read as their codes wherever a value comes in (files, the page, the
agent's reply and fields, put). Files written by kireview 1 / kidiff (status_rev, 未確認, OK / NG) are converted when
read; they are written back in this format on the next change.
"""
import json
import os
import re

import talkpage as tp

SEVERITIES = ('must', 'should', 'could', 'info')
OWNERS = ('human', 'agent', 'tbd')
# '' = not reviewed. The page offers fixed / please fix (fix) / OK (ok); question and self-fix come from older reviews
# and stay readable
STATUSES = ('', 'ok', 'fix', 'fixed', 'question', 'self-fix')
ASKING = ('fix', 'question')             # a status that waits for the agent
CODES = {'status': STATUSES, 'severity': SEVERITIES, 'owner': OWNERS}
# the Japanese values of earlier versions, and kireview 1 / kidiff's 未確認 / OK / NG
ALIASES = {
    'status': {'未確認': '', 'このまま': 'ok', '修正を依頼': 'fix', '修正済み': 'fixed', '質問': 'question',
               '自分で修正': 'self-fix', 'OK': 'ok', 'NG': 'fix'},
    'severity': {'必須': 'must', '推奨': 'should', '任意': 'could', '情報': 'info'},
    'owner': {'人': 'human', 'エージェント': 'agent', '未定': 'tbd'},
}
SIDE_KEY = re.compile(r'^(F|B|In\d+)$')
BOARD_ID = re.compile(r'^[\w.-]+$')
# board items: ask / ideal / background are the three sections (依頼 / 理想 / 経緯), signal the line's kind, current and
# routing cautions for a routing request; text / action are the older pair
BOARD_FIELDS = ('title', 'severity', 'owner', 'sides', 'x', 'y', 'r', 'w', 'h', 'refs', 'pins', 'spots', 'ask', 'signal',
                'ideal', 'background', 'figures', 'text', 'action', 'near', 'status')
# fields the agent can add to a schematic item (any change, part or group): its intent and, for a finding, the same
# request sections as a board item
SCH_FIELDS = ('rationale', 'severity', 'owner', 'ask', 'signal', 'ideal', 'background', 'figures')


def norm_value(kind, v):
    """A status / severity / owner value (kind) from a file, the page or the agent: its code for a Japanese word or a
    code in other letter case, else unchanged (the check then refuses it)."""
    if v is None:
        return None
    v = str(v).strip()
    if v in ALIASES[kind]:
        return ALIASES[kind][v]
    return v.lower() if v.lower() in CODES[kind] else v


def norm_status(st):
    return norm_value('status', st)


def norm_fields(fields):
    """severity / owner of the agent's fields (a dict, changed in place) as codes."""
    if isinstance(fields, dict):
        for k in ('severity', 'owner'):
            if k in fields:
                fields[k] = norm_value(k, fields[k])
    return fields


def one_of(kind):
    codes = ', '.join('""' if c == '' else c for c in CODES[kind])
    return '%s must be one of %s (the Japanese names of earlier versions are accepted too)' % (kind, codes)


def check_status(st):
    if st is not None and st not in STATUSES:
        raise ValueError(one_of('status'))


def migrate(d):
    """Values as codes; items written by kireview 1 or kidiff: talkpage revisions from the thread and status_rev /
    agent_rev."""
    for it in d.get('items', {}).values():
        it['status'] = norm_status(it.get('status') or '')
        norm_fields(it)
        for m in it.get('thread') or []:            # the status changes of the thread
            if 'status' in m:
                m['status'] = norm_status(m['status'] or '')
        if 'user_rev' in it:
            continue
        th = it.setdefault('thread', [])
        last_agent = max([i for i, m in enumerate(th) if m.get('who') == 'agent'] or [-1])
        asked = it['status'] in ASKING and it.get('status_rev', 0) > it.get('agent_rev', 0)
        talked = bool(th) and th[-1].get('who') == 'user'
        for i, m in enumerate(th):
            m['rev'] = 1 if i > last_agent and m.get('who') == 'user' else 0
        it['user_rev'] = 1 if talked or asked else 0
        it['agent_rev'] = 0
        it['seen_rev'] = 0
        it.pop('status_rev', None)


class ReviewStore(tp.Store):
    """talkpage's Store for one review file; kind is 'board' or 'sch'."""

    def __init__(self, path, page, kind):
        self.kind = kind
        super().__init__(path, page)

    def load(self):
        if not os.path.isfile(self.path):
            return
        with open(self.path, encoding='utf-8') as f:
            d = json.load(f)
        d.setdefault('items', {})
        migrate(d)
        for it in d['items'].values():
            tp.upgrade(it)
        d['rev'] = max(int(d.get('rev') or 0), 1)
        d['page'] = self.page
        self.data, self.mtime = d, os.path.getmtime(self.path)

    def touch(self):
        """Save a change made to self.data (a new revision, so the pages update)."""
        self._next()
        self.save()

    def view(self):
        v = super().view()
        if self.kind == 'sch':
            v['groups'] = self.data.get('groups', [])
        return v


# ---------------------------------------------------------------- board items
def check_board_item(it):
    if not str(it.get('title') or '').strip():
        raise ValueError('title is required')
    if it.get('severity') not in SEVERITIES:
        raise ValueError(one_of('severity'))
    if it.get('owner') not in OWNERS:
        raise ValueError(one_of('owner'))
    check_status(it.get('status'))
    sides = it.get('sides')
    if not isinstance(sides, list) or not sides or not all(isinstance(s, str) and SIDE_KEY.match(s) for s in sides):
        raise ValueError('sides: a non-empty list of "F", "B", "In1", "In2", ...')
    for k in ('x', 'y'):
        if not isinstance(it.get(k), (int, float)):
            raise ValueError('%s (board mm) is required' % k)
    for k in ('refs', 'pins', 'spots', 'figures'):
        if not isinstance(it.get(k, []), list):
            raise ValueError('%s is a list' % k)
    if not all(isinstance(sp, dict) and all(isinstance(sp.get(k), (int, float)) for k in ('x', 'y'))
               for sp in it.get('spots', [])):
        raise ValueError('spots: a list of {x, y, label?, r?} (board mm)')


def put_board_item(store, body):
    """Create or replace a board item (the agent's POST /api/board/item); status, thread and revisions are kept."""
    iid = str(body.get('id') or '').strip()
    if not BOARD_ID.match(iid):
        raise ValueError('id: letters, digits, _ . - only')
    old = store.data['items'].get(iid) or {}
    it = {'severity': 'info', 'owner': 'tbd', 'refs': [], 'status': old.get('status', ''),
          'thread': old.get('thread', []), 'user_rev': old.get('user_rev', 0), 'agent_rev': old.get('agent_rev', 0),
          'seen_rev': old.get('seen_rev', 0)}
    it.update({k: body[k] for k in BOARD_FIELDS if k in body})
    it['status'] = norm_status(it['status'])
    norm_fields(it)
    if 'r' not in it and 'w' not in it:
        it['r'] = 1.0
    check_board_item(it)
    store.data['items'][iid] = it
    store.touch()
    return dict(it, id=iid, rev=store.data['rev'])


def check_fields(kind, fields, merged=None):
    """Fields the agent sends with a reply (severity / owner already as codes, norm_fields): board items are checked as
    a whole (merged), schematic items by name."""
    if fields is None:
        return
    if not isinstance(fields, dict):
        raise ValueError('fields: a JSON object')
    allowed = BOARD_FIELDS if kind == 'board' else SCH_FIELDS
    bad = [k for k in fields if k not in allowed or k == 'status']
    if bad:
        raise ValueError('fields not allowed here: %s (allowed: %s)' % (', '.join(bad), ', '.join(allowed)))
    if kind == 'board':
        check_board_item(dict(merged or {}, **fields))
    else:
        if 'severity' in fields and fields['severity'] not in SEVERITIES:
            raise ValueError(one_of('severity'))
        if 'owner' in fields and fields['owner'] not in OWNERS:
            raise ValueError(one_of('owner'))
        if 'figures' in fields and not isinstance(fields['figures'], list):
            raise ValueError('figures is a list')


# ---------------------------------------------------------------- schematic groups and settings
def set_group(store, gid, title, keys, rationale):
    """Create or replace a group of schematic items reviewed as one (key group:<id>); its status and thread stay."""
    if not title or not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
        raise ValueError('title and a non-empty keys list are required')
    groups = store.data.setdefault('groups', [])
    if not gid:
        n = 1
        while any(g['id'] == 'g%d' % n for g in groups):
            n += 1
        gid = 'g%d' % n
    if not re.match(r'^[\w.-]+$', gid):
        raise ValueError('group id: letters, digits, _ . - only')
    g = {'id': gid, 'title': title.strip(), 'keys': keys, 'rationale': (rationale or '').strip()}
    i = next((n for n, o in enumerate(groups) if o['id'] == gid), None)
    if i is None:
        groups.append(g)
    else:
        groups[i] = g
    store.touch()
    return dict(g, rev=store.data['rev'])


def delete_group(store, gid):
    groups = store.data.setdefault('groups', [])
    if not any(g['id'] == gid for g in groups):
        raise ValueError('no such group: %s' % gid)
    store.data['groups'] = [g for g in groups if g['id'] != gid]
    store.touch()
    return {'deleted': gid, 'rev': store.data['rev']}


def seed_rationale(store, seed):
    """--rationale: {item key: intent}; an intent already written is kept."""
    changed = False
    for key, text in (seed or {}).items():
        it = store.item(key, create=True)
        if text and not it.get('rationale'):
            it['rationale'] = str(text)
            changed = True
    if changed:
        store.touch()
