# Vendored: cm-chessboard

Vendored (no build step — native ES modules) for the GUI solver board.

- **Source:** https://github.com/shaack/cm-chessboard
- **Version:** 8.12.12
- **Code license:** MIT — © Stefan Haack (see `LICENSE`).

## Pieces

Only the **standard** piece set is vendored (`assets/pieces/standard.svg`):

- **Wikimedia "standard" SVG chess pieces** (Colin M.L. Burnett / Cburnett),
  licensed **CC BY-SA 3.0** — https://commons.wikimedia.org/wiki/Category:SVG_chess_pieces/Standard
  This is the same piece artwork python-chess renders on the `/review` board.

The bundled **staunty** set is **CC BY-NC-SA 4.0** (NonCommercial) and was deliberately
**not vendored** to keep this repository free of NonCommercial assets.

## Not vendored
Build/source artifacts (`*.scss`, `*.sketch`), the staunty sprite, and `examples/`,
`test/` from the upstream package.
