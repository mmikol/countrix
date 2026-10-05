# The user guide

How a player or a team uses Countrix, task by task, in plain words:
installing and starting it, the board step by step, its three tabs, the
registry, the math page and the study, tuning the playbook, the data,
troubleshooting, questions, and the credits and licences. It is a site
built with [MkDocs](https://www.mkdocs.org) and the
[Material](https://squidfunk.github.io/mkdocs-material/) theme.

| file | what it is |
| --- | --- |
| `mkdocs.yml` | the site: its name, theme, palettes, navigation and the strict checks |
| `docs/` | the pages, one markdown file each, starting at [docs/index.md](docs/index.md) |
| `docs/img/` | the screenshots, listed in [docs/img/README.md](docs/img/README.md) with the board each one is taken on |
| `docs/css/countrix.css` | the board's colours on the theme |
| `docs/js/iframe-worker.js` | the shim that runs the search from pages opened straight from the disk, with its MIT licence |
| `requirements.txt` | MkDocs and Material, pinned |

From the repo root, in a venv of the guide's own, which git ignores:

```bash
python3.12 -m venv user-guide/.venv
user-guide/.venv/bin/pip install -r user-guide/requirements.txt
user-guide/.venv/bin/mkdocs serve -f user-guide/mkdocs.yml            # http://127.0.0.1:8000, rebuilt on each save
user-guide/.venv/bin/mkdocs build --strict -f user-guide/mkdocs.yml   # the site, in user-guide/site/
```

The build is strict: a page left out of the navigation, a broken link or
a broken anchor fails it, and CI runs it on every push to `main` and
every pull request. `user-guide/site/` is ignored by git. The built
pages open straight from the disk too, search included:
`user-guide/site/index.html`. Material prints a notice about MkDocs 2.0
on every run: the pins hold MkDocs at 1.6, and `NO_MKDOCS_2_WARNING=true`
quiets it, as CI sets it.

The guide describes the board as the code on `main` behaves. A change to
what a player sees changes its page here in the same commit.
