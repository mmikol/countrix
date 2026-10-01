"""The board's stylesheet against the page: every class it styles is one
the scripts, the shell or the math page names."""

import re

from ui import pages


def test_every_stylesheet_class_is_used_by_the_page():
    """A class in board.css that no script, template or page names is dead
    styling; the rosters, cards and panels are all rendered from these files."""
    css = pages.static_file("board.css")[0].decode()
    selectors, depth, buf = [], 0, ""
    for ch in css:
        if ch == "{":
            if depth == 0:
                selectors.append(buf)
            depth, buf = depth + 1, ""
        elif ch == "}":
            depth, buf = depth - 1, ""
        else:
            buf += ch
    classes = set()
    for selector in selectors:
        if selector.lstrip().startswith("@"):        # an at-rule, not a selector
            continue
        classes.update(re.findall(r"\.([A-Za-z_][\w-]*)", re.sub(r"/\*.*?\*/", "", selector)))
    shell = pages.view_board()
    names = re.findall(r"<script src='/static/([\w.-]+\.js)'>", shell)
    assert names, "the shell loads no script"
    sources = "".join(pages.static_file(name)[0].decode() for name in names)
    sources += shell + pages.view_math()
    assert len(classes) > 50
    assert [c for c in classes if not re.search(r"\b%s\b" % re.escape(c), sources)] == []
