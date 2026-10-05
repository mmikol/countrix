"""The board: the page over the facts layer's facts and the inference
layer's answer. It is the only presentation code, and no layer imports it.

    board.py        the board's server: the roster and facts endpoints, and
                    the handler that routes to them, to serve.py's and to
                    the pages
    serve.py        the board's routes over the engine - the board, the
                    catalog and /health - the admission that solves one
                    board at a time, and each client's lane, where a newer
                    board supersedes one still solving
    pages.py        the board's HTML - the page shell, styled like the
                    game's hero select, and the math page - and the static
                    files they load
    registry.py     the strategy registry: each rule of the playbook in
                    force written out - its form, its gate and its formula
                    with its own numbers, the metrics it reads and its
                    sources - from the code
    study.py        the study: the proof that the search is exact, the
                    audit of what is hard-coded, and the study's results
                    from static/study.json once a run is published there,
                    each chart beside its numbers
    charts.py       the study's charts, inline SVG drawn on the server from
                    plain rows: dots, stacked bars, a scatter, a heatmap and
                    a funnel on a log scale
    static/         what the browser loads: the stylesheet, the scripts,
                    the display font and its licence, and the articles the
                    pages render, math.html and study.html
"""
