/* the board: TEAM and BANS are set by the page before this loads, and
   comps.js and playbook.js before it */
var el = function (id) { return document.getElementById(id); };
/* an empty board, and every field's default: a board saved before a field
   existed takes it from here. It is a function because Object.assign copies
   array references, and one shared object would take the next ban pushed */
function blank() { return { map: '', stage: '', red: [], blue: [], bans: [], side: '', weights: {} }; }
var ROSTER = null, st = blank();
var SHAPES = null;   /* the (tank, damage, support) triples the queue and the playbook allow, from the board */
var ROLES = ['tank', 'damage', 'support'];
try { var saved = JSON.parse(localStorage.getItem('owdb-board2'));
      if (saved && saved.red && saved.blue) st = Object.assign(blank(), saved); } catch (e) {}
var TABS = ['comps', 'facts', 'playbook'];   /* the panels; the first is the default */
var bansOpen = false;                        /* the ban picker starts collapsed */

function currentMap() { return ROSTER ? ROSTER.maps.filter(function (x) { return x.name === st.map; })[0] : null; }

/* text for markup and for either kind of quoted attribute: a map named King's
   Row must not close a single-quoted title */
function esc(s) { return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
function save() { try { localStorage.setItem('owdb-board2', JSON.stringify(st)); } catch (e) {} }
function hero(name) { return ROSTER.byName[name]; }
function portrait(h) {
  var initials = h.name.split(/[\s:.]+/).map(function (w) { return w[0]; }).join('').slice(0, 2);
  return h.portrait
    ? "<img src='" + esc(h.portrait) + "' alt='' loading='lazy' onerror=\"this.style.display='none';this.nextSibling.style.display='flex'\"><span class='ph' style='display:none'>" + esc(initials) + '</span>'
    : "<span class='ph'>" + esc(initials) + '</span>';
}

/* --- the rosters: one tile renderer for red, blue and the ban picker ------ */
var SILHOUETTE = "<svg class='sil' viewBox='0 0 48 64' aria-hidden='true'><circle cx='24' cy='23' r='10'/>" +
  "<path d='M7 64c0-14 7.5-23 17-23s17 9 17 23z'/></svg>";

function tile(h, team) {
  if (h.status === 'announced') return soonTile(h);
  return "<div class='tile' data-team='" + team + "' data-h=\"" + esc(h.name) + "\" title=\"" + esc(h.name + ' - ' + h.subrole) + "\">" +
    portrait(h) + "<span class='nm'>" + esc(h.name) + '</span></div>';
}
/* an announced hero: the same tile in its role column, dimmed, tagged, with
   no data-h and no data-team - the click handler and the state never see it */
function soonTile(h) {
  return "<div class='tile soon' title=\"" + esc(h.name + ' - announced, not yet playable' + (h.release_date ? ' (releases ' + h.release_date + ')' : '') + ' - ' + h.subrole) + "\">" +
    (h.portrait ? portrait(h) : SILHOUETTE) + "<span class='tag'>coming soon</span><span class='nm'>" + esc(h.name) + '</span></div>';
}
function rosterHTML(team) {
  var cols = '';
  ROLES.forEach(function (role) {
    var icon = ROSTER.role_icons[role] ? "<img src='" + esc(ROSTER.role_icons[role]) + "' alt=''>" : '';
    cols += "<div class='rolecol'><h4>" + icon + role + "</h4><div class='grid'>";
    ROSTER.heroes.filter(function (h) { return h.role === role; }).forEach(function (h) { cols += tile(h, team); });
    cols += '</div></div>';
  });
  return cols;
}

/* a team's six slots, empty until paint draws its row: a slot carries its
   team, and data-h, the hero it shows, which is all a click reads - the row
   is drawn in role order, so a slot's place names no pick */
function buildTeam(team) {
  var slots = '';
  for (var i = 0; i < TEAM; i++) slots += "<div class='slot' data-team='" + team + "'></div>";
  el(team + 'slots').innerHTML = slots;
  el(team + 'roster').innerHTML = rosterHTML(team);
}
function buildBanPicker() { el('banroster').innerHTML = rosterHTML('ban'); }

/* how many of a role a team may hold, given what it holds of the others. Blue's
   is the most any legal shape seats, null when the board has not said what is
   legal. Red's is the queue's tank limit alone: the playbook's limits are
   blue's, and red's picks are never ruled out */
function roleCap(team, role) {
  if (team === 'red') return role === 'tank' ? TANKS : null;
  if (!SHAPES || !SHAPES.length) return null;
  var have = roleCounts(team), cap = -1;
  SHAPES.forEach(function (shape) {
    for (var i = 0; i < ROLES.length; i++) if (ROLES[i] !== role && shape[i] < have[ROLES[i]]) return;
    cap = Math.max(cap, shape[ROLES.indexOf(role)]);
  });
  return cap < 0 ? null : cap;
}
function roleCounts(team) {
  var have = { tank: 0, damage: 0, support: 0 };
  st[team].forEach(function (n) { var h = hero(n); if (h && have.hasOwnProperty(h.role)) have[h.role]++; });
  return have;
}
function toggle(team, name) {
  if (st.bans.indexOf(name) >= 0) { flash(name + ' is banned this match'); return; }
  var arr = st[team], at = arr.indexOf(name);
  if (at >= 0) arr.splice(at, 1);
  else if (arr.length >= TEAM) { flash(team + ' already has ' + TEAM); return; }
  else {
    var h = hero(name), cap = h ? roleCap(team, h.role) : null;
    if (cap !== null && roleCounts(team)[h.role] >= cap) {
      flash('the queue allows at most ' + cap + ' ' + h.role + (cap === 1 ? '' : 's')); return;
    }
    arr.push(name);
  }
  save(); paint(); refresh();
}

function toggleBan(name) {
  var at = st.bans.indexOf(name);
  if (at >= 0) st.bans.splice(at, 1);
  else if (st.bans.length < BANS) {
    st.bans.push(name);
    ['red', 'blue'].forEach(function (team) {          /* a banned hero cannot be picked */
      var i = st[team].indexOf(name); if (i >= 0) st[team].splice(i, 1);
    });
  } else { flash(BANS + ' bans already'); return; }
  save(); paint(); refresh();
}

/* the bans bar: a header (count and small portraits, click to open), the five
   slots, and the same portrait grid the rosters use - a click bans, a click on
   a banned tile or its slot un-bans */
function paintBans() {
  var slots = '', mini = '';
  st.bans.forEach(function (name) {
    var h = hero(name) || { name: name, portrait: '' };
    slots += "<div class='slot full' data-ban=\"" + esc(name) + "\" title='click to unban'>" + portrait(h) + "<span class='nm'>" + esc(name) + '</span></div>';
    mini += "<span class='banchip' data-ban=\"" + esc(name) + "\" title='click to unban'>" +
      (h.portrait ? "<img src='" + esc(h.portrait) + "' alt=''>" : '') + '<b>✕</b>' + esc(name) + '</span>';
  });
  for (var i = st.bans.length; i < BANS; i++) slots += "<div class='slot'><span class='idx'>" + (i < 4 ? (i < 2 ? 'red' : 'blue') : 'lobby') + '</span></div>';
  el('banslots').innerHTML = slots;
  el('banmini').innerHTML = mini;
  el('bancount').textContent = st.bans.length + '/' + BANS;
  var tiles = el('banroster').querySelectorAll('.tile[data-h]');
  for (var t = 0; t < tiles.length; t++) {
    var n = tiles[t].getAttribute('data-h');
    tiles[t].className = 'tile' + (st.bans.indexOf(n) >= 0 ? ' banned' : '') +
      (st.red.indexOf(n) >= 0 ? ' inred' : '') + (st.blue.indexOf(n) >= 0 ? ' inblue' : '');
  }
  el('bans').className = 'bans' + (bansOpen ? ' open' : '') + (st.bans.length >= BANS ? ' maxed' : '');
}

/* a filled slot's tooltip: the reason the board gives its hero - blue's fill
   or six, red's likely six - and none while no board has answered */
function pickReason(team, name) {
  var d = INF, r = !d || d.error ? null : team === 'blue' ? (d.fill || d.current) : d.expected;
  var p = r && r.picks ? r.picks.filter(function (x) { return x.hero === name; })[0] : null;
  return p ? p.why : '';
}

function paint() {
  if (!ROSTER) return;                  /* the slots and rosters are built when the roster loads */
  paintBans();
  var rows = paintRows();
  ['red', 'blue'].forEach(function (team) {
    var other = team === 'red' ? 'blue' : 'red';
    var have = roleCounts(team), capped = {}, caps = {};
    ROLES.forEach(function (role) { caps[role] = roleCap(team, role); capped[role] = caps[role] !== null && have[role] >= caps[role]; });
    var tiles = el(team + 'roster').querySelectorAll('.tile[data-h]');   /* the announced card keeps its own class */
    for (var t = 0; t < tiles.length; t++) {
      var n = tiles[t].getAttribute('data-h'), hh = hero(n), on = st[team].indexOf(n) >= 0;
      tiles[t].className = 'tile' + (on ? ' on' : '') + (st[other].indexOf(n) >= 0 ? ' other' : '') +
        (st.bans.indexOf(n) >= 0 ? ' banned' : '') + (!on && hh && capped[hh.role] ? ' capped' : '');
    }
  });
  paintSwaps(rows.blue);
  el('mapsel').value = st.map;
  var m = currentMap();
  paintStagePicker(m);
  var sided = !!(m && m.sided);
  if (!sided) st.side = '';
  el('mode').textContent = m ? m.mode + (m.style ? ' · rewards ' + m.style : '') +
    (sided ? (st.side ? ' · blue ' + (st.side === 'attack' ? 'attacks' : 'defends') : '') : ' · no sides') : 'map unknown';
  el('sideseg').className = 'sideseg' + (sided ? ' show' : '');
  var sb = el('sideseg').querySelectorAll('button');
  for (var s = 0; s < sb.length; s++) sb[s].className = sb[s].getAttribute('data-side') === st.side ? 'on' : '';
}

document.addEventListener('click', function (e) {
  var near = function (sel) { return e.target.closest(sel); };
  var sideBtn = near('[data-side]');
  if (sideBtn) { var sd = sideBtn.getAttribute('data-side'); st.side = st.side === sd ? '' : sd; save(); paint(); refresh(); return; }
  var clear = near('[data-clear]');                   /* a team's clear button: that team's picks only */
  if (clear) { st[clear.getAttribute('data-clear')] = []; save(); paint(); refresh(); return; }
  var ban = near('[data-ban]');                       /* a ban slot or a header chip: un-ban */
  if (ban) { toggleBan(ban.getAttribute('data-ban')); return; }
  if (near('#banhead')) { bansOpen = !bansOpen; paintBans(); return; }
  var swap = near('[data-swap-in]');                  /* a suggested swap: that pick is traded in place */
  if (swap) { takeSwap(swap.getAttribute('data-swap-out'), swap.getAttribute('data-swap-in')); return; }
  var hit = near('[data-h][data-team]');              /* a roster tile, a team slot, or a picker tile */
  if (hit) {
    var team = hit.getAttribute('data-team'), name = hit.getAttribute('data-h');
    if (team === 'ban') toggleBan(name); else toggle(team, name);
    return;
  }
  var tab = near('nav.tabs button');
  if (tab) showTab(tab.getAttribute('data-tab'));
});

var flashTimer = null;
function flash(msg) { el('flash').textContent = msg; clearTimeout(flashTimer);
  flashTimer = setTimeout(function () { el('flash').textContent = ''; }, 3000); }

function qs() {
  var q = [];
  if (st.map) q.push('map=' + encodeURIComponent(st.map));
  if (st.stage) q.push('stage=' + encodeURIComponent(st.stage));
  st.red.forEach(function (h) { q.push('red=' + encodeURIComponent(h)); });
  st.blue.forEach(function (h) { q.push('blue=' + encodeURIComponent(h)); });
  st.bans.forEach(function (h) { q.push('bans=' + encodeURIComponent(h)); });
  if (st.side) q.push('side=' + st.side);
  Object.keys(st.weights).sort().forEach(function (id) { q.push('weights=' + encodeURIComponent(id + ':' + st.weights[id])); });
  return q.join('&');
}

var pending = null, seq = 0, FACTS = null, INF = null;
var STALE = false;         /* the last refresh failed: the next focus or reconnect retries it */
var solve = null;          /* the board request in flight, aborted when a newer one is sent */
var redKey = null;         /* the map, bans and red picks red's likely six was drawn for */
/* this page's name on its board requests: the server stops a board this page
   has moved past, and serves every other page's in its own lane */
var CLIENT = Math.random().toString(36).slice(2, 10);
/* one switch for every figure the solver owns */
function solving(on) {
  document.body.classList.toggle('solving', !!on);
  ['bluescore', 'redscore'].forEach(function (id) {
    var node = el(id);
    if (on) { if (node.textContent !== '…') node.dataset.was = node.textContent; node.textContent = '…'; }
    else if (node.textContent === '…' && node.dataset.was !== undefined) { node.textContent = node.dataset.was; }
  });
  if (on) el('momentum').innerHTML = "<span class='lbl'>fight odds</span><span class='legend searching'>solving…</span>";
  ['plan', 'blueslots', 'redslots', 'blueswaps', 'stageplan'].forEach(function (id) {
    el(id).classList.toggle('waiting', !!on);
  });
}

/* the facts tab when its request fails: the reason in place of the rows, so
   the last board's facts never stand in for this one's */
function factsFailed(why) {
  FACTS = null;
  el('factbody').innerHTML = "<tr><td class='src'>" + esc(why) + '</td></tr>';
  el('factsn').textContent = '';
}

/* the comps tab when no board came back: the page says so everywhere the
   board would have answered, and keeps nothing of the last one */
function boardFailed() {
  STALE = true; redKey = null;
  solving(false);
  INF = null; paint();
  el('inf-blue').innerHTML = "<div class='warnbox'>the board is not answering</div>";
  el('inf-red').innerHTML = ''; el('plan').innerHTML = '';
  el('stageplan').innerHTML = ''; el('blueswaps').innerHTML = '';
  el('momentum').innerHTML = "<span class='lbl'>fight odds</span><span class='legend'>the board is not answering</span>";
  ['bluescore', 'redscore'].forEach(function (id) { el(id).textContent = ''; el(id).title = ''; });
}

function refresh() {
  if (!ROSTER) return;                  /* nothing is drawn before the roster loads */
  clearTimeout(pending);
  pending = setTimeout(function () {
    var mine = ++seq, q = qs();
    fetch('/api/facts?' + q).then(function (r) { return r.json(); }).then(function (d) {
      if (mine !== seq) return;
      if (d.error) { factsFailed(d.error); return; }
      FACTS = d; renderFacts();
    }).catch(function () {
      if (mine !== seq) return;
      STALE = true; factsFailed('the board is not answering');
    });
    /* the search is seconds of work, so everything it feeds says so until it
       lands: the two seats, the scores, the plan and the filled slots. Without
       this the board shows the last board's numbers while it thinks, which
       reads as an answer. Red's likely six changes only with the map, the
       bans and red's own picks, so a blue pick, a side or a stage leaves it
       standing */
    solving(true);
    el('inf-blue').innerHTML = "<p class='legend searching'>searching…</p>";
    var key = [st.map].concat(st.bans, ['red'], st.red).join('|');
    if (key !== redKey) el('inf-red').innerHTML = "<p class='legend searching'>searching…</p>";
    if (solve) solve.abort();           /* the older request; this one's arrival stops its board */
    solve = new AbortController();
    fetch('/api/board?' + q + (q ? '&' : '') + 'client=' + CLIENT, { signal: solve.signal })
      .then(function (r) { return r.json(); }).then(function (d) {
        if (mine !== seq) return;
        solving(false);
        STALE = !!d.error; redKey = d.error ? null : key;
        INF = d; renderInf();
      }).catch(function () {
        if (mine !== seq) return;       /* an aborted request is an older one */
        boardFailed();
      });
  }, 200);
}
/* a failed refresh is tried again when the page comes back into view or the
   network comes back */
['online', 'focus'].forEach(function (ev) { window.addEventListener(ev, function () { if (STALE) refresh(); }); });

var SCOPES = ['meta', 'bans', 'map', 'hero', 'team', 'matchup'];
var scopeOn = { meta: true, bans: true, map: true, hero: true, team: true, matchup: true };
function renderFacts() {
  if (!FACTS) return;
  var f = el('filter').value.toLowerCase(), out = '', last = null, shown = 0;
  FACTS.facts.forEach(function (x) {
    if (!scopeOn[x.scope]) return;
    if (f && (x.id + ' ' + x.key + ' ' + x.subject + ' ' + x.text).toLowerCase().indexOf(f) < 0) return;
    shown++;
    var head = x.scope === 'hero' ? (x.team + ' · ' + x.subject) : x.scope === 'team' ? (x.subject + ' team') : x.scope;
    if (head !== last) { out += "<tr class='h'><td colspan='3' class='head'>" + esc(head) + '</td></tr>'; last = head; }
    var cls = (x.team || '') + (x.warn ? ' warn' : '') + (x.source.indexOf('derived:') === 0 ? ' derived' : '');
    out += "<tr class='" + cls + "'><td class='tag'>[" + x.id + "]</td><td class='text'>" + esc(x.text) + "</td><td class='src'>" + esc(x.source) + '</td></tr>';
  });
  el('factbody').innerHTML = out || "<tr><td class='src'>nothing matches</td></tr>";
  var total = FACTS.facts.length;   /* the total lives in the panel, beside the filter */
  el('factsn').textContent = shown === total ? commas(total) + ' facts' : commas(shown) + ' of ' + commas(total) + ' facts';
}

/* the two team rows: each team's picks and, in its open slots, the board's
   suggestions, a click from locking. Blue's are the solver's: the optimal six
   before any pick, then the fill - the best six that keeps the locked ones -
   and while a board solves the board in hand's, around the picks as they
   stand: the optimal's where it answered no blue pick, so a first pick taken
   from its role's first slot stays there, and one from a role's second moves
   to the first, as a role's picks lead it. Red's are its likely six around its picks: for each
   open slot the hero with the highest pick score, drawn only for the red
   picks the board in hand answered. A suggested tile shows the hero alone;
   its reason and pick score ride in the hover title. Each row keeps the
   shape of the six the board in hand drew for its team (shapeOf). Returns
   each row as drawn (lineup) */
function paintRows() {
  var d = INF, ok = !!d && !d.error;
  var asked = ok && d.current ? d.current.blue || [] : [];   /* the blue picks the board in hand answered */
  var src = !ok ? null : st.blue.length && asked.length ? d.fill : d.blue;
  var sw = answered() ? d.swaps : null;         /* the swaps' empty slots show the fill's heroes */
  var free = function (p) { return st.blue.indexOf(p.hero) < 0; };
  var open = sw && sw.open && sw.open.length ? sw.open.filter(free)
           : src && src.picks ? src.picks.filter(function (p) { return !p.locked && free(p); }) : [];
  var likely = redAnswered() ? d.expected.picks.filter(function (p) {
    return !p.locked && st.red.indexOf(p.hero) < 0; }) : [];
  var six = src || (asked.length ? d.current : null);       /* blue's six in hand: its fill, else its picks */
  return { blue: paintRow('blue', lineup('blue', open, shapeOf(six))),
           red: paintRow('red', lineup('red', likely, shapeOf(ok ? d.expected : null))) };
}

/* the slots each role holds in a six the board in hand drew, in ROLES order:
   its heroes' roles counted; null with no six in hand */
function shapeOf(six) {
  if (!six || !six.picks) return null;
  return ROLES.map(function (role) { return six.picks.filter(function (p) { return p.role === role; }).length; });
}

/* a team's six as its row draws it: its picks and the suggestions for its
   open slots together, tanks first, then damage, then supports (ROLES), so a
   glance tells what the team fields. Within a role the team's own picks come
   first, in pick order, then the suggestions in the board's order, then empty
   slots (null) up to the role's slots in `shape`, the six in hand's; a hero
   of no known role goes last. So while a board solves a pick, a clear or a
   suggestion gone in one role moves no other role's slots, unless it changes
   how many slots a role holds: a red pick past a role's slots, or its clear,
   shifts red's picks a slot until the board lands, since only red's likely
   six says which role gives a slot up. Past six, a role over its slots takes the last
   empty slots, then the last suggestions. Only the drawing moves: st.blue and
   st.red keep the order picked, which the board is asked in. An entry is a
   pick, `at` its place among the team's picks, or a suggestion, `p` the
   board's entry */
function lineup(team, suggested, shape) {
  var rank = function (name, p) {
    var h = hero(name), r = ROLES.indexOf(h ? h.role : p ? p.role : '');
    return r < 0 ? ROLES.length : r;
  };
  var picks = st[team].map(function (name, at) { return { name: name, at: at }; });
  var open = suggested.map(function (p) { return { name: p.hero, p: p }; });
  var row = [];
  for (var r = 0; r <= ROLES.length; r++) {
    var mine = picks.filter(function (x) { return rank(x.name) === r; });
    var room = Math.max(shape && r < ROLES.length ? shape[r] : 0, mine.length);
    var role = mine.concat(open.filter(function (x) { return rank(x.name, x.p) === r; })).slice(0, room);
    while (role.length < room) role.push(null);
    row = row.concat(role);
  }
  for (var k = row.length - 1; row.length > TEAM && k >= 0; k--) if (!row[k]) row.splice(k, 1);
  for (k = row.length - 1; row.length > TEAM && k >= 0; k--) if (row[k].p) row.splice(k, 1);
  return row;
}

/* `team`'s slots show `row`: a pick solid, its tooltip the reason this board
   gives it; a suggestion dashed, a click from locking, with no number - its
   place would skip around the picks (2, 4, 6) and read as an order the board
   does not give; an empty slot numbered among the empty slots, 1 up, so the
   last number counts them */
function paintRow(team, row) {
  var slots = el(team + 'slots').children, empty = 0;
  for (var i = 0; i < TEAM; i++) {
    var x = row[i], s = slots[i];
    if (!x) { s.className = 'slot'; s.removeAttribute('data-h'); s.title = ''; s.innerHTML = "<span class='idx'>" + (++empty) + '</span>'; continue; }
    var h = hero(x.name) || { name: x.name, portrait: x.p ? x.p.portrait : '' };
    s.className = x.p ? 'slot suggested' : 'slot full'; s.setAttribute('data-h', x.name);
    s.title = x.p ? x.p.why : pickReason(team, x.name);
    s.innerHTML = portrait(h) + "<span class='nm'>" + esc(x.name) + '</span>';
  }
  return row;
}

/* the swaps above blue's picks: the board's one joint answer (swaps) - the
   incoming hero's portrait over the pick it replaces, wherever blue's row
   (`row`, lineup) draws that pick: the entry whose place among the picks is
   the pair's `at`. A click takes that swap, and the caption is the board's
   verdict. Taking one leaves the rest the board's answer from the new picks.
   Nothing is drawn for red */
function paintSwaps(row) {
  var d = INF, sw = answered() ? d.swaps : null, box = el('blueswaps');
  var pairs = sw && sw.pairs ? sw.pairs : [];
  if (!pairs.length) {                   /* a kept six says nothing */
    box.innerHTML = '';
    return;
  }
  var cells = '';
  for (var i = 0; i < TEAM; i++) {
    var x = row[i], p = x && !x.p ? pairs.filter(function (y) { return y.at === x.at; })[0] : null;
    if (!p) { cells += "<div class='swapcell'></div>"; continue; }
    var h = hero(p.in) || { name: p.in, portrait: p.portrait };
    cells += "<div class='swapcell' data-swap-in=\"" + esc(p.in) + "\" data-swap-out=\"" + esc(p.out) +
      "\" title=\"" + esc('swap ' + p.out + ' for ' + p.in + ' - ' + p.why) + "\">" + portrait(h) + '</div>';
  }
  box.innerHTML = "<div class='swapcap'>" + esc(sw.verdict) + '</div>' + cells;
}
function takeSwap(out, into) {
  var at = st.blue.indexOf(out);
  if (at < 0 || st.blue.indexOf(into) >= 0) return;
  if (st.bans.indexOf(into) >= 0) { flash(into + ' is banned this match'); return; }
  st.blue.splice(at, 1);                             /* the role cap, as a pick is checked */
  var h = hero(into), cap = h ? roleCap('blue', h.role) : null;
  if (cap !== null && roleCounts('blue')[h.role] >= cap) {
    st.blue.splice(at, 0, out);
    flash('the queue allows at most ' + cap + ' ' + h.role + (cap === 1 ? '' : 's')); return;
  }
  st.blue.splice(at, 0, into);
  save(); paint(); refresh();
}
/* whether the board in hand answered blue's picks as they stand, in the
   order sent: its swaps and the slots it fills are drawn only for those
   picks, and a local change hides them until the next board lands */
function answered() {
  var d = INF, asked = d && !d.error && d.current ? d.current.blue || [] : null;
  return !!asked && asked.length === st.blue.length &&
    asked.every(function (n, i) { return st.blue[i] === n; });
}
/* the same for red: the likely six the board in hand drew around red's picks */
function redAnswered() {
  var d = INF, asked = d && !d.error && d.expected ? d.expected.locked || [] : null;
  return !!asked && asked.length === st.red.length &&
    asked.every(function (n, i) { return st.red[i] === n; });
}
/* the stage picker: the map's stages in play order after the whole map,
   hidden on a map without stages; a stage the map does not list is dropped */
var stagesFor = null;       /* the map the stage picker's options were built for */
function paintStagePicker(m) {
  var names = m && m.stages ? m.stages : [], sel = el('stagesel');
  if (names.indexOf(st.stage) < 0) st.stage = '';
  sel.style.display = names.length ? '' : 'none';
  if (stagesFor !== st.map) {            /* rebuilt on a new map alone: an open picker stays open */
    stagesFor = st.map;
    sel.innerHTML = names.length ? "<option value=''>WHOLE MAP</option>" + names.map(function (n) {
      return "<option value=\"" + esc(n) + "\">" + esc(n) + '</option>'; }).join('') : '';
  }
  sel.value = st.stage;
}

function showTab(name) {
  if (TABS.indexOf(name) < 0) name = TABS[0];   /* an unknown or stale saved tab lands on comps */
  document.querySelectorAll('nav.tabs button').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-tab') === name); });
  document.querySelectorAll('.panel').forEach(function (p) { p.classList.toggle('active', p.id === 'tab-' + name); });
  try { localStorage.setItem('owdb-tab', name); } catch (e) {}
}

/* the board once the roster has loaded: every tile, slot and control hangs off it */
function start(d) {
  ROSTER = d; ROSTER.byName = {};
  d.heroes.forEach(function (h) { ROSTER.byName[h.name] = h; });
  el('mapsel').innerHTML = "<option value=''>MAP UNKNOWN / ANY</option>" + d.maps.map(function (m) { return "<option value=\"" + esc(m.name) + "\">" + esc(m.name) + '</option>'; }).join('');
  var known = function (h) { return !!ROSTER.byName[h]; };   /* the roster is the only source of a name in state */
  st.red = st.red.filter(known); st.blue = st.blue.filter(known); st.bans = st.bans.filter(known);
  if (!d.maps.some(function (m) { return m.name === st.map; })) st.map = '';
  buildTeam('red'); buildTeam('blue'); buildBanPicker(); paint();
  var w = el('vintage'), newer = d.newer_patches || [];     /* the patches, or nothing: boot's failure note goes */
  w.style.display = newer.length ? 'block' : 'none';
  w.textContent = newer.length ? newer.length + ' patch(es) since the rates were captured (newest ' + newer[0].name + ') - run pull_rates' : '';
  el('mapsel').onchange = function () { st.map = this.value; st.stage = ''; save(); paint(); refresh(); };
  el('stagesel').onchange = function () { st.stage = this.value; save(); paint(); refresh(); };
  el('filter').oninput = renderFacts;
  var chips = el('chips'); chips.innerHTML = SCOPES.map(function (s) { return "<button class='chip on' data-scope='" + s + "'>" + s + '</button>'; }).join('');
  chips.onclick = function (e) { var c = e.target.closest('.chip'); if (!c) return; var s = c.getAttribute('data-scope');
    scopeOn[s] = !scopeOn[s]; c.classList.toggle('on', scopeOn[s]); renderFacts(); };
  loadPlaybook();
  showTab((function () { try { return localStorage.getItem('owdb-tab'); } catch (e) { return null; } })());
  el('clearall').onclick = function () {   /* back to nothing: map, side, bans, both teams - the weights stay */
    st = Object.assign(blank(), { weights: st.weights }); save(); paint(); refresh();
  };
  refresh();
}

/* the roster, asked for until it comes: a failure says so in the warning box
   and tries again, waiting twice as long each time up to half a minute */
var bootWait = 1000;
function boot() {
  fetch('/api/roster').then(function (r) {
    return r.json().then(function (d) {
      if (!r.ok || d.error || !d.heroes) throw new Error(d.error || 'HTTP ' + r.status);
      return d;
    });
  }).then(start, function (e) {
    var w = el('vintage');
    w.style.display = 'block';
    w.textContent = 'the board is not answering (' + (e && e.message ? e.message : e) + ') - trying again in ' + Math.round(bootWait / 1000) + 's';
    setTimeout(boot, bootWait);
    bootWait = Math.min(bootWait * 2, 30000);
  });
}
boot();
