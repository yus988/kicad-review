/* talkpage client. Elements marked data-talk="<id>" get status buttons and a comment thread kept by the talkpage
   server (talkpage.py, in <page>.talk.json beside the page); the agent's replies appear in place. Elements marked
   data-copy get a copy button. Loaded from the server at /_talk/talkpage.js; see README.md. The text is English or
   Japanese by the page's <html lang> (else the browser's language). */
(function () {
  'use strict';
  var API = '/_talk/api/';
  var html = document.documentElement;
  var page = html.getAttribute('data-talk-page') || decodeURIComponent(location.pathname).replace(/^\/+/, '');
  if (!page || /\/$/.test(page)) page += 'index.html';
  var TONES = { OK: 'ok', '了承': 'ok', '済': 'ok', '完了': 'ok', NG: 'ng', '要修正': 'ng',
                '飛ばし': 'skip', 'スキップ': 'skip', '対象外': 'skip' };
  var TEXT = {
    en: {
      'presence.listening': 'Agent: listening',
      'presence.listening.title': 'Statuses and comments reach the agent right away',
      'presence.working': 'Agent: working',
      'presence.working.title': 'The agent is working on what it received. What you write now is saved and reaches it when it listens again',
      'presence.absent': 'Agent: not waiting',
      'presence.absent.title': 'What you write is saved and reaches the agent when it starts waiting',
      'presence.down': 'Server offline',
      'presence.down.title': 'Cannot reach the talkpage server. What you write now is not saved',
      'mark.new': 'New reply',
      'mark.wait': 'Unread by agent',
      'mark.read': 'Read by agent',
      'mark.err': 'Not saved',
      'mark.wait.title': 'The agent has not read what you wrote yet',
      'comment': 'Comment',
      'comment.ph': 'Comment (Ctrl+Enter sends)',
      'send': 'Send',
      'who.agent': 'Agent',
      'who.user': 'You',
      'cleared': 'cleared the status',
      'dock.unread': 'New replies {n}',
      'dock.unread.title': 'Go to an item with a new reply from the agent',
      'dock.waiting': 'Unread by agent {n}',
      'dock.waiting.title': 'Go to an item the agent has not read yet',
      'dock.progress': 'Done {done} / {all}',
      'dock.progress.title': 'Items with a status / items that take one',
      'paren': ' ({x})',
      'list.failed': 'Could not load the items: {msg}',
      'copy': 'Copy',
      'copied': 'Copied',
      'copy.failed': 'Copy failed'
    },
    ja: {
      'presence.listening': 'エージェント 受付中',
      'presence.listening.title': 'チェックとコメントは、すぐエージェントに届きます',
      'presence.working': 'エージェント 対応中',
      'presence.working.title': 'エージェントが届いた書き込みを処理しています。この間の書き込みも保存され、次に受け付けたときに届きます',
      'presence.absent': 'エージェント 待ち受けなし',
      'presence.absent.title': '書き込みは保存されます。エージェントが待ち受けを始めたときに届きます',
      'presence.down': 'サーバー未接続',
      'presence.down.title': 'talkpage のサーバーにつながりません。この間の書き込みは保存されません',
      'mark.new': '新しい返信',
      'mark.wait': 'エージェント未読',
      'mark.read': 'エージェント既読',
      'mark.err': '保存の失敗',
      'mark.wait.title': 'エージェントがまだ読んでいない書き込みがあります',
      'comment': 'コメント',
      'comment.ph': 'コメント（Ctrl+Enter で送信）',
      'send': '送信',
      'who.agent': 'エージェント',
      'who.user': 'あなた',
      'cleared': '状態を解除',
      'dock.unread': '新しい返信 {n}',
      'dock.unread.title': 'エージェントの新しい返信がある項目へ移動',
      'dock.waiting': 'エージェント未読 {n}',
      'dock.waiting.title': 'エージェントがまだ読んでいない項目へ移動',
      'dock.progress': '記入 {done} / {all}',
      'dock.progress.title': '状態を付けた項目 / 状態を付けられる項目',
      'paren': '（{x}）',
      'list.failed': '項目の読み込みの失敗: {msg}',
      'copy': 'コピー',
      'copied': 'コピーしました',
      'copy.failed': 'コピーの失敗'
    }
  };
  var LANG = /^ja\b/i.test(html.getAttribute('lang') || navigator.language || '') ? 'ja' : 'en';
  function tr(key, vars) {
    var s = TEXT[LANG][key] != null ? TEXT[LANG][key] : TEXT.en[key];
    return vars ? s.replace(/\{(\w+)\}/g, function (m, k) { return vars[k] != null ? String(vars[k]) : m; }) : s;
  }
  var PRESENCE = {};
  ['listening', 'working', 'absent', 'down'].forEach(function (p) {
    PRESENCE[p] = [tr('presence.' + p), tr('presence.' + p + '.title')];
  });
  var MARKS = { 'new': tr('mark.new'), wait: tr('mark.wait'), read: tr('mark.read'), err: tr('mark.err') };
  var items = {};          // id -> item as the server keeps it
  var ui = {};             // id -> the item's elements and settings
  var order = [];          // declared ids in document order
  var rev = -1, presence = 'down', downWhy = '', jumpAt = -1, listeners = [], dock = {};
  var baseTitle = document.title;
  var byThread = new Map();
  var io = 'IntersectionObserver' in window ? new IntersectionObserver(function (es) {
    es.forEach(function (e) { var u = byThread.get(e.target); if (u) { u.visible = e.isIntersecting; seen(u); } });
  }) : null;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function button(cls, text) { var b = el('button', cls, text); b.type = 'button'; return b; }
  function up(node, name) { var n = node.closest('[' + name + ']'); return n ? n.getAttribute(name) : null; }
  function list(s) { return s.split(',').map(function (t) { return t.trim(); }).filter(Boolean); }
  function states(s) {
    return list(s == null ? 'OK,NG' : s).map(function (t) {
      var p = t.split(':');
      return { name: p[0], tone: p[1] || TONES[p[0]] || 'ask' };
    });
  }
  function when(t) { return t ? t.slice(5, 16).replace('-', '/') : ''; }
  function json(r) {
    return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || r.status); return d; });
  }
  function post(name, body) {
    return fetch(API + name, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                               body: JSON.stringify(body) }).then(json);
  }

  // text of a message: line breaks kept, `code` and http(s) links, nothing else is markup
  function fmt(text, into) {
    text.split(/(`[^`\n]+`)/).forEach(function (part) {
      if (/^`[^`\n]+`$/.test(part)) { into.appendChild(el('code', null, part.slice(1, -1))); return; }
      part.split(/(https?:\/\/[^\s<>"'）」]+)/).forEach(function (seg) {
        if (!/^https?:\/\//.test(seg)) { into.appendChild(document.createTextNode(seg)); return; }
        var a = el('a', null, seg); a.href = seg; a.target = '_blank'; a.rel = 'noopener'; into.appendChild(a);
      });
    });
  }

  // ---------------------------------------------------------------- items
  function build(node) {
    var id = node.getAttribute('data-talk');
    if (!id || ui[id]) { if (id) console.warn('talkpage: duplicate data-talk id', id); return; }
    var u = ui[id] = {
      id: id, el: node, open: false, shown: -1, visible: false,
      title: node.getAttribute('data-talk-title') || node.innerText.replace(/\s+/g, ' ').trim().slice(0, 120),
      states: states(up(node, 'data-talk-states')), wake: up(node, 'data-talk-wake') || '*', btns: {}
    };
    order.push(id);
    var bar = el('div', 'talk-bar');
    u.states.forEach(function (s) {
      var b = button('talk-st', s.name);
      b.setAttribute('data-tone', s.tone);
      b.setAttribute('aria-pressed', 'false');
      b.addEventListener('click', function () { setStatus(u, s.name); });
      u.btns[s.name] = b;
      bar.appendChild(b);
    });
    u.cbtn = button('talk-cbtn', tr('comment'));
    u.cbtn.setAttribute('aria-expanded', 'false');
    u.count = el('span', 'talk-count');
    u.cbtn.appendChild(u.count);
    u.cbtn.addEventListener('click', function () { openThread(u, !u.open); if (u.open) u.ta.focus(); });
    u.mark = el('span', 'talk-mark');
    bar.appendChild(u.cbtn);
    bar.appendChild(u.mark);
    u.thread = el('div', 'talk-thread');
    u.thread.hidden = true;
    u.list = el('div', 'talk-entries');
    var form = el('div', 'talk-form');
    u.ta = el('textarea');
    u.ta.rows = 2;
    u.ta.placeholder = tr('comment.ph');
    u.send = button('talk-send', tr('send'));
    form.appendChild(u.ta);
    form.appendChild(u.send);
    u.thread.appendChild(u.list);
    u.thread.appendChild(form);
    u.send.addEventListener('click', function () { sendComment(u); });
    u.ta.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.isComposing) { e.preventDefault(); sendComment(u); }
    });
    u.draft = 'talk-draft:' + page + ':' + id;           // an unsent comment survives a reload (this browser only)
    try { u.ta.value = localStorage.getItem(u.draft) || ''; } catch (e) {}
    u.ta.addEventListener('input', function () {
      try { if (u.ta.value) localStorage.setItem(u.draft, u.ta.value); else localStorage.removeItem(u.draft); } catch (e) {}
    });
    var slot = node.querySelector('[data-talk-slot]') || node;
    slot.appendChild(bar);
    slot.appendChild(u.thread);
    byThread.set(u.thread, u);
    if (io) io.observe(u.thread);
    if (u.ta.value) openThread(u, true);
  }

  function setStatus(u, name) {
    var cur = (items[u.id] || {}).status || '';
    var next = cur === name ? '' : name;
    var notify = u.wake === '*' || (u.wake !== 'none' && list(u.wake).some(function (w) { return w === next || w === cur; }));
    paint(u, next);
    post('user', { page: page, id: u.id, title: u.title, status: next, notify: notify })
      .then(take)
      .catch(function (e) { paint(u, cur); fail(u, e); });
  }

  function sendComment(u) {
    var text = u.ta.value.trim();
    if (!text || u.send.disabled) return;
    u.send.disabled = true;
    post('user', { page: page, id: u.id, title: u.title, comment: text })
      .then(function (d) {
        u.ta.value = '';
        try { localStorage.removeItem(u.draft); } catch (e) {}
        take(d);
      })
      .catch(function (e) { fail(u, e); })
      .then(function () { u.send.disabled = false; });
  }

  function fail(u, e) { mark(u, 'err'); u.mark.title = String(e && e.message || e); }

  function mark(u, m) {
    u.mark.textContent = MARKS[m] || '';
    u.mark.setAttribute('data-m', m);
    u.mark.title = m === 'wait' ? tr('mark.wait.title') : '';
  }

  function paint(u, s) {
    Object.keys(u.btns).forEach(function (k) { u.btns[k].setAttribute('aria-pressed', String(k === s)); });
    var st = u.states.filter(function (x) { return x.name === s; })[0];
    if (s) {
      u.el.setAttribute('data-talk-status', s);
      u.el.setAttribute('data-talk-tone', st ? st.tone : TONES[s] || 'ask');
    } else {
      u.el.removeAttribute('data-talk-status');
      u.el.removeAttribute('data-talk-tone');
    }
  }

  function openThread(u, on) {
    u.open = on;
    u.thread.hidden = !on;
    u.cbtn.setAttribute('aria-expanded', String(on));
    seen(u);
  }

  function entry(m) {
    var who = tr(m.who === 'agent' ? 'who.agent' : 'who.user');
    if (!m.text) return el('div', 'talk-ev', when(m.time) + '  ' + who + ': ' + (m.status || tr('cleared')));
    var box = el('div', 'talk-msg talk-' + (m.who === 'agent' ? 'agent' : 'user'));
    box.appendChild(el('span', 'talk-who', who + '  ' + when(m.time)));
    var body = el('div', 'talk-text');
    fmt(m.text, body);
    box.appendChild(body);
    return box;
  }

  function render(id) {
    var u = ui[id];
    if (!u) return;
    var it = items[id] || { status: '', thread: [], user_rev: 0, agent_rev: 0, seen_rev: 0 };
    paint(u, it.status || '');
    var msgs = it.thread.filter(function (m) { return m.text; });
    u.count.textContent = msgs.length ? ' ' + msgs.length : '';
    u.unread = msgs.some(function (m) { return m.who === 'agent' && m.rev > (it.seen_rev || 0); });
    u.waiting = it.user_rev > it.agent_rev;
    mark(u, u.unread ? 'new' : u.waiting ? 'wait' : it.user_rev > 0 ? 'read' : '');
    if (it.thread.length !== u.shown) {
      var first = u.shown < 0;
      u.list.textContent = '';
      it.thread.forEach(function (m) { u.list.appendChild(entry(m)); });
      u.shown = it.thread.length;
      if (first && msgs.length && !u.open) openThread(u, true);   // only on load: a later reply never moves the page
    }
    seen(u);
  }

  // the user has read the agent's messages of an item when its thread is open on screen
  function seen(u) {
    if (!u.unread || !u.open || (io && !u.visible) || document.visibilityState !== 'visible' || u.seenBusy) return;
    u.seenBusy = true;
    post('seen', { page: page, id: u.id }).then(take).catch(function () {}).then(function () { u.seenBusy = false; });
  }

  function take(d) {
    items[d.id] = d;
    render(d.id);
    updateDock();
  }

  // ---------------------------------------------------------------- dock (fixed, bottom right)
  function buildDock() {
    var d = el('div', 'talk-dock');
    d.setAttribute('role', 'status');
    dock.unread = button('talk-jump', '');
    dock.unread.title = tr('dock.unread.title');
    dock.waiting = button('talk-jump', '');
    dock.waiting.title = tr('dock.waiting.title');
    dock.progress = el('span', 'talk-progress');
    dock.progress.title = tr('dock.progress.title');
    dock.presence = el('span', 'talk-presence');
    [dock.unread, dock.waiting, dock.progress, dock.presence].forEach(function (x) { d.appendChild(x); });
    dock.unread.addEventListener('click', function () { jump(function (u) { return u.unread; }, true); });
    dock.waiting.addEventListener('click', function () { jump(function (u) { return u.waiting; }, false); });
    document.body.appendChild(d);
  }

  function updateDock() {
    var n = { unread: 0, waiting: 0, done: 0, all: 0 };
    order.forEach(function (id) {
      var u = ui[id];
      if (u.unread) n.unread++;
      if (u.waiting) n.waiting++;
      if (u.states.length) { n.all++; if (items[id] && items[id].status) n.done++; }
    });
    dock.unread.hidden = !n.unread;
    dock.unread.textContent = tr('dock.unread', { n: n.unread });
    dock.waiting.hidden = !n.waiting;
    dock.waiting.textContent = tr('dock.waiting', { n: n.waiting });
    dock.progress.textContent = n.all ? tr('dock.progress', { done: n.done, all: n.all }) : '';
    var p = PRESENCE[presence] || PRESENCE.absent;
    dock.presence.textContent = p[0];
    dock.presence.title = p[1] + (presence === 'down' && downWhy ? tr('paren', { x: downWhy }) : '');
    dock.presence.setAttribute('data-p', presence);
    document.title = (n.unread ? '(' + n.unread + ') ' : '') + baseTitle;
  }

  function jump(pred, open) {
    var ids = order.filter(function (id) { return pred(ui[id]); });
    if (!ids.length) return;
    var next = ids.filter(function (id) { return order.indexOf(id) > jumpAt; })[0] || ids[0];
    jumpAt = order.indexOf(next);
    var u = ui[next];
    if (open) openThread(u, true);
    u.el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    u.el.classList.remove('talk-flash');
    void u.el.offsetWidth;
    u.el.classList.add('talk-flash');
  }

  // ---------------------------------------------------------------- server state (long poll)
  function apply(d) {
    rev = d.rev;
    presence = d.presence || 'absent';
    Object.keys(d.items || {}).forEach(function (k) { items[k] = d.items[k]; });
    order.forEach(render);
    updateDock();
    listeners.forEach(function (fn) { try { fn(d); } catch (e) { console.error(e); } });
  }

  function loop(first) {
    var q = 'state?page=' + encodeURIComponent(page) +
            (first ? '' : '&rev=' + rev + '&presence=' + presence + '&wait=25');
    fetch(API + q, { cache: 'no-store' }).then(json)
      .then(function (d) { apply(d); loop(false); })
      .catch(function (e) {
        presence = 'down';
        downWhy = e && e.message || '';
        updateDock();
        setTimeout(function () { loop(true); }, 3000);
      });
  }

  // ---------------------------------------------------------------- items declared in JSON
  function lists() {
    var boxes = [].slice.call(document.querySelectorAll('[data-talk-list]'));
    return Promise.all(boxes.map(function (box) {
      var src = box.getAttribute('data-talk-list');
      var inline = box.querySelector('script[type="application/json"]');
      var got = src ? fetch(src, { cache: 'no-store' }).then(json)
                    : Promise.resolve(JSON.parse(inline ? inline.textContent : '[]'));
      return got.then(function (data) {
        (Array.isArray(data) ? data : data.items || []).forEach(function (d) {
          var card = el('div', 'talk-card');
          card.setAttribute('data-talk', d.id);
          card.setAttribute('data-talk-title', d.id + ' ' + (d.title || ''));
          if (d.states != null) card.setAttribute('data-talk-states', d.states);
          if (d.wake != null) card.setAttribute('data-talk-wake', d.wake);
          var head = el('div', 'talk-card-head');
          head.appendChild(el('span', 'talk-card-id', d.id));
          head.appendChild(el('span', 'talk-card-title', d.title || ''));
          card.appendChild(head);
          if (d.html || d.text) {
            var body = el('div', 'talk-card-body');
            if (d.html) body.innerHTML = d.html; else body.textContent = d.text;   // html: written by the page's author
            card.appendChild(body);
          }
          box.appendChild(card);
        });
      }).catch(function (e) { box.appendChild(el('p', 'talk-error', tr('list.failed', { msg: e.message }))); });
    }));
  }

  // ---------------------------------------------------------------- copy buttons
  function copyText(text) {
    function legacy() {
      return new Promise(function (ok, ng) {
        var t = el('textarea');
        t.value = text;
        t.style.position = 'fixed';
        t.style.opacity = '0';
        document.body.appendChild(t);
        t.select();
        try { if (document.execCommand('copy')) ok(); else ng(new Error('copy')); } catch (e) { ng(e); }
        document.body.removeChild(t);
      });
    }
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).catch(legacy);
    return legacy();
  }

  function copies() {
    document.querySelectorAll('[data-copy]').forEach(function (box) {
      if (box.querySelector('.talk-copy-btn')) return;
      var fixed = box.getAttribute('data-copy') || null;
      var src = fixed ? null : box.querySelector('code, pre');
      if (!fixed && !src) fixed = box.textContent.trim();
      var b = button('talk-copy-btn', tr('copy'));
      var note = el('span', 'talk-copied');
      note.setAttribute('aria-live', 'polite');
      box.classList.add('talk-copy');
      box.appendChild(b);
      box.appendChild(note);
      b.addEventListener('click', function () {
        copyText(fixed != null ? fixed : src.textContent).then(function () {
          note.textContent = tr('copied');
          clearTimeout(note.timer);
          note.timer = setTimeout(function () { note.textContent = ''; }, 1500);
        }, function () { note.textContent = tr('copy.failed'); });
      });
    });
  }

  // ---------------------------------------------------------------- start, and the API for pages of their own
  window.TalkPage = {
    page: page,
    items: function () { return items; },
    on: function (fn) { listeners.push(fn); },
    user: function (id, body) {
      return post('user', Object.assign({ page: page, id: id }, body)).then(function (d) { take(d); return d; });
    },
    seen: function (id) { return post('seen', { page: page, id: id }).then(function (d) { take(d); return d; }); }
  };

  function start() {
    lists().then(function () {
      document.querySelectorAll('[data-talk]').forEach(build);
      copies();
      buildDock();
      updateDock();
      loop(true);
    });
  }
  document.addEventListener('visibilitychange', function () { order.forEach(function (id) { seen(ui[id]); }); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
