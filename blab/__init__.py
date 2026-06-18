"""Error-analysis layer for Chess Blunder Lab.

Pure-logic helpers built on top of the analysis in ``blunder_lab.py``: classifying
each flagged move into a named blunder category, aggregating an error profile, and
(later milestones) assembling lessons, a puzzle database, an AI writer, and a
spaced-repetition store. Modules here depend only on ``python-chess`` and the
standard library so they stay unit-testable without an engine or network.
"""
