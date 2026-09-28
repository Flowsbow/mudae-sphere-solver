# mudae-sphere-solver

A Discord bot that recommends moves in Mudae's `$oc` sphere minigame and shows the
expected-value numbers behind each recommendation.

## Status

Phase 1, in progress: `$oc` solver with the board typed in by hand.

## `$oc` rules as modeled

- 5×5 board, 5 clicks, each click reveals only the cell clicked.
- 1 red, never in the center.
- 2 orange touching red on a side.
- 3 yellow anywhere on red's diagonals.
- 4 green anywhere in red's row or column.
- Teal on every other cell in red's row, column, or diagonals; blue everywhere else.

Exactly 16,800 boards satisfy these rules. `tests/test_oc_rules.py` checks that the
solver generates each of them once and nothing else.

## Model assumption

Mudae's rules say where spheres can go, not how likely each board is. This solver
assumes each of the 24 non-center cells is equally likely to hold red, and that every
legal arrangement of the other spheres is equally likely once red is placed. This has
not been checked against game data, so every recommendation is conditional on it.

## Development

```
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
pytest
ruff format . && ruff check .
```
