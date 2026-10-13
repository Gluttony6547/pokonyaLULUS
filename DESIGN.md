# DESIGN.md

Direction for the Sinyal IDX dashboard. `antislop.md` is the filter applied on
top of this; this file is the identity it filters.

## Design read

Reading this as: a data-dense market research dashboard for retail investors
and thesis examiners, in a **trading ledger** visual language, dial
**ENERGY 1 / RHYTHM 2 / MOTION 1**.

- **ENERGY 1**: the numbers are the loudest thing on the page. No glow, no
  welcome animation, no marketing voice.
- **RHYTHM 2**: the signal panel is dense and tabular, the surrounding panels
  are airy. Sections deliberately differ in composition rather than repeating
  one card grid.
- **MOTION 1**: hover and focus states only. Nothing moves on its own, because
  a dashboard a user stares at for minutes should not animate at them.

## Audience and job

The reader opens the page to answer one question: *what does the model say
about this ticker right now, and how fresh is the data behind it?*

That makes the five horizon rows one panel and the data-freshness line the
first thing above them. Everything else on the page is supporting evidence the
reader can visit on the way down: the price context behind the input window,
then the history, then the models.

## Identity

A ledger, not a SaaS landing page: warm paper base, hairline rules instead of
floating cards, tabular numerals in every numeric column. The one identity motif
is the **signal chip**, a rectangular label whose tint and text colour carry the
only non-neutral colour in the layout. Colour is reserved for the signal, which
is the one thing the product actually asserts.

## Palette

Two core colours plus one accent, with neutrals uncounted:

| Role | Light | Dark |
|---|---|---|
| Base (paper) | `#F4F2ED` | `#101215` |
| Surface | `#FFFFFF` | `#171A1E` |
| Ink | `#14161A` | `#E9EAEC` |
| Muted ink | `#565C66` | `#A0A6AE` |
| Rule | `#DCD7CC` | `#262B31` |
| Accent (interactive only) | `#8A4200` | `#E0A05A` |

Signal colours are semantic and appear only on signal chips:

| Signal | Light text / tint | Dark text / tint |
|---|---|---|
| BUY | `#0F5B32` / `#E3F0E6` | `#6ED39B` / `#132A1F` |
| HOLD | `#4C535F` / `#E9E7E1` | `#B7BEC8` / `#1F2429` |
| SELL | `#9B1C1C` / `#F7E4E2` | `#F08C86` / `#2C1718` |

Reason: amber accent is distinct from both signal colours, so the interactive
layer never reads as a recommendation.

## Typography

IBM Plex Sans, one family for the whole interface. It was designed for
technical documentation, holds up at 13 to 15 px in dense tables, and its
tabular figures make numeric columns align without a second monospace face.
Numbers use `font-variant-numeric: tabular-nums`. Body copy is 15 to 16 px;
nothing is set below 12 px, and nothing that carries meaning is set below 13 px.

## Layout reasons, one line each

- **Signal table, not signal cards**: five horizons compared side by side is a
  comparison task, and rows align where cards cannot.
- **Ticker rail as buttons**: ten tickers is a small set, and a rail keeps the
  selection and the result in one viewport.
- **One chart, not a chart per horizon**: the close series and its 20-session
  average answer whether the input window sits in a trend, which is context for
  reading the signal. No other chart answers a question the reader has.
- **Hairline rules instead of shadows**: elevation would imply a modal layer
  that does not exist. Rules separate without floating.
- **Disclaimer pinned in the footer and in the signal panel**: the product is
  decision support, and that has to be true everywhere the signal appears.

## What is deliberately absent

Testimonial and logo sections, a feature grid, pricing, an FAQ, marketing copy,
invented statistics, avatars, decorative icons, spinners without labels, and a
"trusted by" strip. The product has none of that content, so the page has none
of those sections.
