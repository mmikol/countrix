/* the playbook tab: the groups, the cards and the weight sliders; loaded
   before board.js, which calls into it. */
/* a heuristic's weight is the user's to set: a slider under its card, 0 to 10
   to the hundredth (0.25, 9.99), with a number box for the exact figure,
   starting at the weight the file infers; a setting rides with every board
   request (weights=id:value) and never touches the file. Every heuristic has
   a weight to set, on a metric or scored; a constraint is never weighted.
   The Meta slider is one more row of the same kind: meta.md's meta, which
   scales the whole default engine, sent as weights=meta:value. */
function weightRow(h, label) {
  var set = st.weights.hasOwnProperty(h.id), v = set ? st.weights[h.id] : h.weight;
  return "<div class='wrow' data-id='" + esc(h.id) + "' data-inferred='" + h.weight + "'>" +
    "<span class='wlbl'>" + (label || 'weight') + "</span><input type='range' min='0' max='10' step='0.01' value='" + v + "' aria-label='weight of " + esc(h.name) + "'>" +
    "<input type='number' class='wval' min='0' max='10' step='0.01' value='" + v + "' aria-label='exact weight of " + esc(h.name) + "'>" +
    "<span class='wbreak'></span>" +
    "<button class='wreset' " + (set ? '' : 'disabled') + ">reset</button></div>";
}
function clampWeight(x, max) { x = Math.round(+x * 100) / 100; return isNaN(x) ? null : Math.min(max || 10, Math.max(0, x)); }
/* the swap cost: meta.md's swap, in share points of blue's span, 0 to
   SWAP_MAX - what a swap of one of blue's picks must gain before the board
   suggests it; a slider like the weights', sent as weights=swap:value */
var SWAP = 'swap';
function costRow(m) {
  var set = st.weights.hasOwnProperty(SWAP), v = set ? st.weights[SWAP] : m.swap;
  return "<div class='wrow' data-id='" + SWAP + "' data-inferred='" + m.swap + "' data-max='" + SWAP_MAX + "'>" +
    "<span class='wlbl'>swap cost</span><input type='range' min='0' max='" + SWAP_MAX + "' step='0.5' value='" + v + "' aria-label='the swap cost'>" +
    "<input type='number' class='wval' min='0' max='" + SWAP_MAX + "' step='0.5' value='" + v + "' aria-label='the exact swap cost'>" +
    "<span class='wbreak'></span>" +
    "<button class='wreset' " + (set ? '' : 'disabled') + ">reset</button></div>";
}
function setWeight(id, value, inferred) {
  if (value === null || value === inferred) delete st.weights[id]; else st.weights[id] = value;
  save(); refresh();
}
/* the playbook, one group per kind in the equation's order - constraints,
   heuristics, assumptions - each headed with its count, an empty group saying
   so; a card's left edge carries its kind's colour */
var KINDS = [['constraint', 'constraints'], ['heuristic', 'heuristics'], ['assumption', 'assumptions']];
/* the catalog, fetched and drawn; a request that fails draws the failure */
function loadPlaybook() {
  fetch('/api/strategies').then(function (r) { return r.json(); }).then(renderPlaybook,
    function () { renderPlaybook(null); });
}
/* a slider setting whose heuristic the catalog no longer holds - renamed,
   removed, or a draft or a constraint now - has no row to clear it from, and
   would ride with every request: it is dropped. Only a catalog that answered
   prunes; the meta's row is always there */
var META = 'meta';
function weighs(h) { return h.form === 'heuristic' || h.form === 'scored'; }
function pruneWeights(d) {
  var live = {};
  live[META] = true;
  live[SWAP] = true;
  d.strategies.forEach(function (h) { if (weighs(h)) live[h.id] = true; });
  var stale = Object.keys(st.weights).filter(function (id) { return !live[id]; });
  stale.forEach(function (id) { delete st.weights[id]; });
  if (stale.length) save();
}
function renderPlaybook(d) {
  if (!d || !d.strategies || !d.meta) { el('playbook').innerHTML = "<div class='warnbox'>" + esc(d && d.error ? d.error : 'the strategies are not answering') + '</div>'; return; }
  pruneWeights(d);
  /* anchors first: the meta, then one per group with its count, so a long
     playbook is a click from any kind; each scrolls its group into view */
  var out = "<nav class='pbnav'><button class='engine' data-group='pb-engine'>the meta</button>" + KINDS.map(function (k) {
    var n = d.strategies.filter(function (h) { return h.kind === k[0]; }).length;
    return "<button class='" + k[0] + "' data-group='pb-" + k[0] + "'>" + k[1] + " <span class='n'>" + n + '</span></button>';
  }).join('') + '</nav>';
  /* the default engine first, as the equation adds it first: meta.md's dials,
     its prose and the Meta slider over the whole of it */
  var m = d.meta;
  out += "<section class='pbgroup engine' id='pb-engine'><h3>the meta</h3><div class='hcards'><div class='hcard engine'>" +
    mathLink('/math#default-engine', 'the default engine, on the math page') +
    "<span class='kind engine'>engine</span><b>The meta</b><div class='meta'>" +
    esc('meta.md · meta ' + m.meta + ' × (rate ' + m.rate + ' · synergy ' + m.synergy + ' · counter ' + m.counter + ') · swap cost ' + m.swap) +
    '</div>' + prose(m.body) + weightRow({ id: META, name: 'the meta', weight: m.meta }, 'meta') + costRow(m) + '</div></div></section>';
  KINDS.forEach(function (k) {
    /* by name inside a kind: a rule is looked up by what it is called, not by
       where the catalog puts it. The catalog's own order is the scoring order
       and is left alone - the terms sum in it, and the sum is bit-reproducible. */
    var these = d.strategies.filter(function (h) { return h.kind === k[0]; })
      .slice().sort(function (a, b) {
        var x = (a.name || a.id).toLowerCase(), y = (b.name || b.id).toLowerCase();
        return x < y ? -1 : x > y ? 1 : 0;
      });
    out += "<section class='pbgroup " + k[0] + "' id='pb-" + k[0] + "'><h3>" + k[1] + " <span class='n'>" + these.length + '</span></h3>';
    out += these.length ? "<div class='hcards'>" + these.map(card).join('') + '</div>' : "<p class='legend none'>none</p>";
    out += '</section>';
  });
  el('playbook').innerHTML = out;
  el('playbook').querySelectorAll('.pbnav button').forEach(function (b) {
    b.onclick = function () { el(b.getAttribute('data-group')).scrollIntoView({ behavior: 'smooth', block: 'start' }); };
  });
  el('playbook').querySelectorAll('.wrow').forEach(function (row) {
    var id = row.getAttribute('data-id'), inferred = +row.getAttribute('data-inferred'), max = +(row.getAttribute('data-max') || 10);
    var range = row.querySelector('input[type=range]'), val = row.querySelector('.wval'), reset = row.querySelector('.wreset');
    var commit = function (x) { x = clampWeight(x, max); if (x === null) return; range.value = x; val.value = x; reset.disabled = x === inferred; setWeight(id, x, inferred); };
    range.oninput = function () { val.value = range.value; };
    range.onchange = function () { commit(range.value); };
    val.onchange = function () { commit(val.value); };
    reset.onclick = function () { range.value = inferred; val.value = inferred; reset.disabled = true; setWeight(id, null, inferred); };
  });
  function card(h) {
    var meta = h.form === 'heuristic' ? h.direction + ' ' + h.metric + ' · weight ' + h.weight + (h.need ? ' · need' : '') + (h.when ? ' · when ' + h.when : '')
             : h.form === 'limit' ? 'require ' + h.require + ' · always holds'
             : h.form === 'scored' ? [h.when ? 'when ' + h.when : '', h.bonus ? 'bonus ' + h.bonus : '', h.penalty ? 'penalty ' + h.penalty : ''].filter(Boolean).join(' · ') + ' · weight ' + h.weight
             : h.form === 'draft' ? 'draft - name, kind and prose only; not scored'
             : h.form === 'assumption' ? 'assumption - taken as given, shown, not scored'
             : h.form;
    var params = Object.keys(h.params || {}).map(function (k) { return k + '=' + h.params[k]; }).join(', ');
    return "<div class='hcard " + h.kind + "'>" + mathLink('/registry#' + esc(h.id), 'this rule, worked out on the strategy registry') +
      "<span class='kind " + h.kind + "'>" + h.kind + '</span><b>' + esc(h.name) + "</b><div class='meta'>" + esc(meta) + (params ? ' · params ' + esc(params) : '') + '</div>' + prose(h.body) +
      (weighs(h) ? weightRow(h) : '') + '</div>';
  }
}
/* a card's math: a strategy's entry on the registry page (/registry#id), the
   meta's section of the math page */
function mathLink(href, title) {
  return "<a class='reglink' href='" + href + "' title='" + title + "'>its math</a>";
}
/* a file's prose as paragraphs, less its title line: the card names it */
function prose(body) {
  return body.replace(/^#[^\n]*\n/, '').split(/\n\s*\n/).map(function (p) { return '<p>' + esc(p.replace(/\s+/g, ' ')) + '</p>'; }).join('');
}
