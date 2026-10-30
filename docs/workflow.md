# From schematic to order: an example workflow

[日本語](workflow.ja.md) · [README](../README.en.md)

How the author builds boards with KiCad and a coding agent (Claude Code). It is the author's own preference and will
differ between projects. kicad-review is used in steps 2 and 6, and can be used in step 4.

| # | Step | Who | kicad-review |
|---|---|---|---|
| 1 | Circuit design | a person or the agent | |
| 2 | Schematic review | person and agent | **schematic** (`/sch`) |
| 3 | BOM check | the agent, checked by a person | |
| 4 | Outline and key placement | a person, closely involved | board (`/board`), optional |
| 5 | Autorouting | the agent | |
| 6 | Board review | person and agent, in rounds | **board** (`/board`) |
| 7 | Deciding it is ready to order | a person | |
| 8 | Fab outputs | the agent | |
| 9 | Bulk buying of parts (optional) | the agent; a person decides | |
| 10 | Cart and order | the agent; a person places the order | |

## 1. Circuit design

A person or the agent. Check each part against the reference circuit in its datasheet.

## 2. Schematic review (kicad-review, schematic)

Review one schematic, or the changes from the previous version. The agent writes down why each change was made; you
check it on the drawing and ask questions or ask for fixes, until nothing is left. To compare with an earlier version
or another board, use side by side, overlay or flip.

## 3. BOM check

**Always before moving to the board.** Check that every part can be bought from the assembler (e.g. JLCPCB: stock,
basic or extended part) and that part numbers and footprints match. Note an alternative for parts with little stock.
Finding a missing part after placement means placing again.

## 4. Outline and key placement

Place the board outline, the parts that face the outside (connectors, switches, displays) and the power / high-current
ICs (motor drivers, chargers, power switches) first. The agent can do it, but **a person should be closely involved and
review it**: moving them later means routing again. Decide where the high-current ICs go with the same weight as the
connectors (far apart means long, wide traces). Placement checks can be listed on the board page too.

## 5. Autorouting

Let the agent route with [Freerouting](https://github.com/freerouting/freerouting) or similar. Depending on the board,
it can take hours.

## 6. Board review (kicad-review, board)

The agent lists what is left on the board (what it changed, what is faster to fix by hand in KiCad, questions). You
check, comment or press "please fix", the agent fixes, you check again, in rounds.

**What a person does faster:** an autorouter cannot push other traces aside or nudge parts to squeeze a trace in. Fix
those by hand in KiCad. Have the agent write each item as a goal ("connect these two pads", "make this trace 0.5 mm or
wider"), not as step-by-step instructions.

## 7. Deciding it is ready to order

The hardest step, and it depends a lot on the project. The criteria below are one example: what the author checked or
had fixed again and again in the last review rounds of two small boards (a radio module, a motor driver and a battery
charger on each).

## 8. Fab outputs

Let the agent export the Gerbers, the BOM and the placement file. The BOM was checked in step 3; check the exported
files only.

## 9. Bulk buying of parts (optional)

If you plan more boards like this one, compare whether buying parts in bulk is cheaper, and buy in bulk if it is.

## 10. Cart and order

An agent that drives a browser (e.g. Claude in Chrome) can upload the files and fill the cart at the assembler. A
person does the final check and places the order.

---

## Pre-order criteria (an example)

### Must hold

- DRC: no violations and no unconnected items; check what the exclusions are
- No mismatch with the schematic
- Traces that carry current are wide enough from end to end, and short, without changing width along the way; where a
  trace must be narrower, list it with the reason for a person to see
- Where a high-current trace changes layers, count the vias (decide how much current one via carries)
- GND: no islands (every GND pad joins one pour or via network); thermal reliefs balanced so a part does not tombstone
- If you use teardrops, they were regenerated after the last edit
- No courtyard overlaps; finally look in 3D that no part bodies touch
- No copper (traces, pours, vias) in a radio module's antenna keep-out
- With an enclosure: check fit and clearances against its 3D model (optional)

### What the agent tended to miss

Found by a person, not by the agent, on the author's boards:

- **A trace that only grazes a pad.** DRC counts it as connected, but the contact is narrower than the trace
- **A GND island handed to a person as "no room for a via"** that rotating the part would have fixed. Have the agent
  try rotating or nudging two-pin parts before asking
- **Courtyard overlaps set to "ignore".** DRC passed while a resistor sat on the body of the next FET
- **One via for a high-current layer change**
- **A power trace whose width changed several times along the way**
- **Numeric rules with no source**, made up by the agent (part spacing), then handed to a person where they could not
  be met. Have the agent state where a rule comes from (datasheet, fab rules, your instruction)
- **A fix asked of a person that the agent's own override cancelled:** pads forced to solid connection, so clearing
  around them did not make thermal reliefs
- **Hard to catch by machine:** pointless detours, needless crossings of motor outputs, placement misses (a
  high-current IC far from its connector). A person looks for these

### Fab outputs

- Check the rotation and position of every part in the assembler's preview
- Keep stock text for order notes (cut-outs in front of connectors that overhang the board edge, assembly notes) and
  read it against the real assembly steps

---

## Other people's experience

- [From half-wired schematic to fab-ready Gerbers in one afternoon (KiCad 10 + MCP)](https://chronara.io/dev-news/carrier-board-rev1-kicad-mcp)
  — 4 layers, 171 parts; placement by hand, wiring, Freerouting runs and outputs by the agent
- [KiCad MCP: Design a PCB with Claude Code in KiCad 10](https://jlcpcb.com/blog/kicad-mcp-how-to-design-a-pcb-with-claude-code)
  — clean ERC / DRC does not mean correct; compare the netlist with the intent before ordering
- [What Routing 314 Nets Taught Me About AI-Assisted PCB Design](https://tinycomputers.io/posts/what-routing-314-nets-taught-me-about-ai-assisted-pcb-design.md)
  — six hours on autorouter clearances; trust the fab's DFM check
- [PCB_Layout_with_AGENT_in_KiCAD](https://github.com/haohao-0725/PCB_Layout_with_AGENT_in_KiCAD) — print the
  placement 1:1 before routing
- [kicad-happy](https://github.com/aklofas/kicad-happy), [kicad-skills](https://github.com/jvanderberg/kicad-skills) —
  agent skills for analysis, BOM and pre-order checks
