/* the strategy registry's dialog: a click on a rule - its row in its kind's
   table, or a rule an entry names - opens the rule's entry in the page's
   dialog (#rule_box) over the page, which stays where it was. The entries sit
   hidden under the tables (#rule_entries), and one goes in as a copy of the
   server's node, so the script writes no markup and escapes nothing: the one
   text it sets, the dialog's name, it sets as text.
   The address names the open rule, /registry#<id>: opening one pushes its
   hash, a rule opened from inside the dialog takes the open one's place,
   Back closes it and Forward opens it again over the page where it is now;
   Esc, the close button and the backdrop close it too and take the hash
   away, and nothing moves the page. Arriving at /registry#<id> - the
   playbook tab's 'its math', a shared address - opens it over the page.
   Without the script, or without the dialog, the entries show under the
   tables and the links scroll to them, as the server anchors them. The ids
   the script looks up hold an underscore, as the page's own anchors do, so
   no rule's id is one and a lookup never finds an entry in its place. */
var el = function (id) { return document.getElementById(id); };
var box = el('rule_box'), shut = el('rule_shut'), pane = el('rule_body'), entries = el('rule_entries');
var RULES = Object.create(null);   /* each rule's entry by its id; no prototype key names one */
var shown = null;                  /* the id of the rule the dialog shows */
var openedBy = null;               /* the link that opened the dialog, which gets the focus back */
var pressed = false;               /* a press began on the backdrop */
var openedAt = 0;                  /* when the dialog last opened, in ms */
/* a double-click's second press, which lands on the backdrop the first
   press's dialog put under it, comes within this many ms */
var SECOND_PRESS = 500;

/* the rule an address's hash or a link's href names, or null: only an
   entry's id, so the page's own anchors - the top, each kind's table - stay
   links that scroll */
function rule(hash) {
  var id = String(hash || '').replace(/^#/, '');
  try { id = decodeURIComponent(id); } catch (e) { return null; }
  return RULES[id] ? id : null;
}

/* the dialog shows the rule's entry from its top, named for a reader that
   reads it aloud, and the focus goes to the dialog itself, whether it opened
   or another rule took the open one's place: Space and the arrow keys
   scroll the entry, and Tab reaches the close button, which Space would
   press */
function show(id) {
  var copy = RULES[id].cloneNode(true), name = copy.querySelector('b');
  pane.replaceChildren(copy);
  box.setAttribute('aria-label', name ? name.textContent : id);
  shown = id;
  if (!box.open) { box.showModal(); openedAt = performance.now(); }
  box.scrollTop = 0;
  box.focus();
}

/* a click on a link to a rule: the dialog opens over the page and the
   address names the rule, so Back closes it; a rule opened from inside the
   dialog replaces the open one's address, so one Back still closes it */
function openRule(id, link) {
  if (box.open) { history.replaceState(history.state, '', '#' + id); show(id); return; }
  openedBy = link;
  history.pushState({ pushed: true }, '', '#' + id);
  show(id);
}

/* the dialog follows the address: Back, Forward or a hash typed in opens
   the rule it names, and an address that names none closes the dialog */
function sync() {
  var id = rule(location.hash);
  if (id) { if (!box.open || id !== shown) show(id); }
  else if (box.open) box.close();
}

/* Back or Forward: the dialog follows the address, and where it shows a rule
   the page stays where it is. The browser puts back the scroll the address
   had when it was last left only after this handler, which would move the
   page behind the dialog, so the page goes back a frame later, before that
   frame is drawn */
function traversed() {
  var x = window.scrollX, y = window.scrollY;
  sync();
  if (box.open) requestAnimationFrame(function () { window.scrollTo(x, y); });
}

/* however the dialog closed - Esc, the close button, the backdrop, Back -
   the address leaves the rule and the focus goes back to the link that
   opened it. A hash this page pushed is undone by going back to the entry
   before it, so the history never holds the page twice; a hash the page
   arrived with is cleared in place. Neither moves the page */
function afterClose() {
  if (rule(location.hash)) {
    if (history.state && history.state.pushed) history.back();
    else history.replaceState(null, '', location.pathname + location.search);
  }
  pane.replaceChildren();
  shown = null;
  if (openedBy) openedBy.focus({ preventScroll: true });
  openedBy = null;
}

/* whether a pointer lands on the backdrop: on the dialog, outside its box */
function outside(e) {
  var r = box.getBoundingClientRect();
  return e.target === box &&
    (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom);
}

function start() {
  /* each entry gives its id up to the script, so the copy the dialog shows
     never repeats it, and the browser's own jump to an address's entry - on
     arrival, or a hash typed in - finds none and leaves the page where it
     was under the dialog */
  document.querySelectorAll('.hcard[id]').forEach(function (card) {
    RULES[card.id] = card;
    card.removeAttribute('id');
  });
  document.addEventListener('click', function (e) {
    /* a click meant for a new tab or window stays the browser's */
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var link = e.target.closest ? e.target.closest('a[href^="#"]') : null;
    var id = link ? rule(link.getAttribute('href')) : null;
    if (!id) return;               /* /math, the sources and a section's anchor stay links */
    e.preventDefault();
    openRule(id, link);
  });
  shut.addEventListener('click', function () { box.close(); });
  /* a press and its release on the backdrop close it; a selection dragged
     out of the entry does not, nor the second press of the double-click
     that opened it */
  box.addEventListener('pointerdown', function (e) {
    pressed = outside(e) && performance.now() - openedAt > SECOND_PRESS;
  });
  box.addEventListener('click', function (e) {
    if (pressed && outside(e)) box.close();
    pressed = false;
  });
  box.addEventListener('close', afterClose);
  window.addEventListener('popstate', traversed);
  window.addEventListener('hashchange', sync);
  sync();
}
/* a browser without the dialog shows the entries under the tables, as a page
   without the script does, and the links scroll to them */
if (box && box.showModal) start();
else if (entries) entries.style.display = 'block';
