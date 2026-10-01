"""The board: the page over the facts layer's facts and the inference
layer's answer. It is the only presentation code, and no layer imports it.

    board.py    the board's server: the roster and facts endpoints, and
                the handler that routes to them, to serve.py's and to the
                pages
    serve.py    the board's routes over the engine - the board, the
                catalog and /health - the admission that solves one board
                at a time, and each client's lane, where a newer board
                supersedes one still solving
    pages.py    the board's HTML - the page shell, styled like the game's
                hero select, and the math page - and the static files they
                load
    static/     what the browser loads: the stylesheet, the scripts, the
                display font and its licence, and math.html
"""
