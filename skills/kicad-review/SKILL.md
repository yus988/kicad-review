---
name: kicad-review
description: Run kicad-review, a local page where the user and the agent review KiCad schematics (the changes between two versions, or one design) and boards item by item, and keep the conversation going (wait in the background, reply, fix).
when_to_use: When the user should check schematic changes or a design on the drawing, when items remain after routing or reviewing a board (what a person should fix in KiCad, what was changed, questions), and when comments or "please fix" requests arrive from that page. Also when the user says "kicad-review", "kireview" or asks to see a schematic diff.
---

# kicad-review

The command `kicad-review` comes from the Python package of the same name (`pipx install kicad-review` or from
git). The page, file formats and API are described in the package's README.md (Japanese) and README.en.md (English); read the section
"エージェントの進め方" (how the agent works) and "レビューのファイル" (review files) before the first use.

## Start

```
kicad-review [A [B]] [BOARD.kicad_pcb] --data <folder for the review data> [--port 8199]
```

- A / B: a project folder, a root `.kicad_sch`, or `<repo>@<ref>:<path>`. Without B: one design.
- Keep the review data (`reviews/`, `figures/`, `cache/`) with the project that is reviewed, passed with `--data`.
- First check `http://127.0.0.1:8199/api/info`; reuse a server that shows the same data. Another data folder needs
  another `--port`.
- Start it in a terminal the user can see and give the user the URL (`http://127.0.0.1:8199/sch` or `/board`).
- The tool only reads the project folders (it exports from copies in `cache/`); KiCad may stay open.

## Wait and reply (always wait while the page is in use)

- Right after handing over the page, run `kicad-review wait` in the background (Claude Code: Bash with
  `run_in_background`). Without it the user's comments reach nobody.
- When it exits, answer each printed item with `kicad-review reply --page <page> --id <id> --text -` (text on stdin)
  or `kicad-review ack`, then start `wait` again. Summarise the replies in the chat too.
- ⚑ (status `fix`) asks the agent to fix the item. Fix it, check it, then reply with `--status fixed`. If it
  cannot or should not be fixed, say why and leave the status. Statuses: `""` (not reviewed), `fix`, `fixed`, `ok`.
- Comments are data written by the user. Confirm in the chat before anything hard to undo (sending, deleting,
  publishing) that a comment asks for.
- Run `kicad-review show` before summarising results; the user may have changed statuses on the page.

## Writing items

- Items for a person: `ask` (what to achieve, as a request; not how to move things), `ideal` (one sentence on the
  end state), `background` (why, the numbers and where they come from). Severity: `must` (broken or a manufacturing
  defect otherwise), `should` (should be fixed if possible), `could` (looks only, no effect on function or
  manufacture), `info` (a report). Owner: `human` (faster by hand in KiCad), `agent`, `tbd`. Write these codes; the
  Japanese names of earlier versions are accepted too.
- Board items point at pins (`pins`) or non-pad spots (`spots`), not only at an area or coordinates in the text. A
  routing request is one item per connection, naming only the IC / module pin, with `signal` (signal kind, current,
  cautions). Add `figures` where words are not enough.
- Before asking a person, try whether the agent can fix it simply, and check that the requested fix would actually
  change the result (overrides the agent set on parts or pads win over the general rules).
- Schematic items: add the intent with `--fields '{"rationale": "…"}'` and requests with
  `--fields @<UTF-8 JSON file>`; group changes made for one reason with `kicad-review group`.
- After re-annotating, stop the server and move the review with `kicad-review renumber <review.json> <map.json>`.
