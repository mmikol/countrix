"""The tests, in three folders by what they hold the code to.

    qa/            the repository's text against the house rules: the docs
                   current and every name in them real, the layers' imports,
                   the style, the stylesheet's classes in use
    verification/  the code against its spec, a folder per layer beside the
                   orchestrator's tests: the units, the search against a full
                   enumeration, the database's invariants, the hand-run
                   provers
    validation/    the engine against outcomes, the owner's recorded maps;
                   empty until they exist
    conftest.py    the fixtures every folder shares: the database, its rows,
                   the World and the synthetic one, and a private copy of
                   the reference playbook
    synthetic.py   a World built by hand, so a test works out its expected
                   values with no database
    fixtures/      the reference playbook and the reach record
"""
