"""Text the server makes (schematic item titles and details, git version names, what is at a board point), in English
and Japanese. kireview.py sets the language once at startup (--lang); the item keys (comp:R1, net:..., ...) never
depend on it. The page text is in i18n.js. Every key is in both tables (tests/test_i18n.py checks it)."""

LANGS = ('en', 'ja')
LANG = 'en'

MSG = {
    'en': {
        # git / folder versions (kireview_sch.folder_state, snapshot)
        'git.outside': 'Latest (working folder, not in git)',
        'git.latest': 'Latest (working folder)',
        'git.dirty': 'Latest (working folder: commit of {last} + uncommitted changes)',
        'git.clean': 'Latest (working folder = commit of {last})',
        'git.at': '{name}  as of {when} ({sha})',
        'folder.disp': '{name}  {state}',
        # schematic items
        'field.Value': 'Value',
        'field.Footprint': 'Footprint',
        'field.Datasheet': 'Datasheet',
        'field.Description': 'Description',
        'field.Symbol': 'Symbol',
        'field.Sheet': 'Sheet',
        'field.dnp': 'DNP',
        'field.exclude_from_bom': 'Excluded from BOM',
        'field.exclude_from_board': 'Excluded from board',
        'renumber.title': 'Re-annotation: {n} parts',
        'renumber.detail': 'The same parts (same UUID) are matched from the A reference to the B reference '
                           '(the A drawing keeps the old references).',
        'sheet.renamed': 'Sheet renamed: {a} → {b}',
        'sheet.renamed.detail': 'Sheets that hold mostly the same parts are paired (the sheet of a part is not counted '
                                'as a change)',
        'sheet.removed': 'Sheet removed: {s}',
        'sheet.added': 'Sheet added: {s}',
        'comp.added': '{ref} added  {value}',
        'comp.removed': '{ref} removed  {value}',
        'comp.changed': '{ref} changed  {value}',
        'conn': 'Connections: {pins}',
        'none': '(none)',
        'no_pin': '(no pin)',
        'pin.line': 'Pin {pins}: {a} → {b}',
        'pin.moved': '{ref} connections changed  {value}',
        'label.power': 'Power symbol',
        'label.global': 'Global label',
        'label.hierarchical': 'Hierarchical label',
        'label.replaced_from': ' (replaced; before: {kind})',
        'label.replaced': ' (replaced)',
        'label.members': 'Connected parts: {parts}',
        'label.member': '{ref} {value}  pin {pins}',
        'label.changed': 'Label changed: {a} → {b}',
        'net.renamed': 'Net renamed: {a} → {b}',
        'net.removed': 'Net removed: {a}',
        'net.added': 'Net added: {b}',
        'part.old': ' (was {ref})',
        'need_a': 'Please choose A',
        # board: what is at a point
        'no_net': '(no net)',
        'side.F': 'front',
        'side.B': 'back',
    },
    'ja': {
        'git.outside': '最新（今のフォルダ。git 管理外）',
        'git.latest': '最新（今のフォルダ）',
        'git.dirty': '最新（今のフォルダ。{last} の記録 ＋ 未記録の変更あり）',
        'git.clean': '最新（今のフォルダ ＝ {last} の記録）',
        'git.at': '{name}　{when} 時点（{sha}）',
        'folder.disp': '{name}　{state}',
        'field.Value': '値',
        'field.Footprint': 'フットプリント',
        'field.Datasheet': 'データシート',
        'field.Description': '説明',
        'field.Symbol': 'シンボル',
        'field.Sheet': 'シート',
        'field.dnp': 'DNP',
        'field.exclude_from_bom': 'BOM 除外',
        'field.exclude_from_board': '基板除外',
        'renumber.title': '番号の付け直し: {n} 個',
        'renumber.detail': '同じ部品（UUID が同じ）を A の番号 → B の番号で対応づけて比べています（A の図の番号は旧番号のまま）。',
        'sheet.renamed': 'シート名変更: {a} → {b}',
        'sheet.renamed.detail': '同じ部品が多いシートを同じものとして並べる（部品の所属シートは変更として数えない）',
        'sheet.removed': 'シート削除: {s}',
        'sheet.added': 'シート追加: {s}',
        'comp.added': '{ref} 追加  {value}',
        'comp.removed': '{ref} 削除  {value}',
        'comp.changed': '{ref} 変更  {value}',
        'conn': '接続: {pins}',
        'none': '(なし)',
        'no_pin': '(ピンなし)',
        'pin.line': 'ピン {pins}: {a} → {b}',
        'pin.moved': '{ref} 接続変更  {value}',
        'label.power': '電源シンボル',
        'label.global': 'グローバルラベル',
        'label.hierarchical': '階層ラベル',
        'label.replaced_from': '（{kind} から置き換え）',
        'label.replaced': '（置き換え）',
        'label.members': 'つながる部品: {parts}',
        'label.member': '{ref} {value}  ピン {pins}',
        'label.changed': 'ラベル変更: {a} → {b}',
        'net.renamed': 'ネット名変更: {a} → {b}',
        'net.removed': 'ネット削除: {a}',
        'net.added': 'ネット追加: {b}',
        'part.old': '（旧 {ref}）',
        'need_a': 'A を指定してください',
        'no_net': '(ネットなし)',
        'side.F': '表',
        'side.B': '裏',
    },
}


def set_lang(lang):
    global LANG
    LANG = lang if lang in LANGS else 'en'


def t(key, **kw):
    """The text of key in the current language, with {name} filled from kw."""
    s = MSG[LANG].get(key)
    if s is None:
        s = MSG['en'][key]
    return s.format(**kw) if kw else s
