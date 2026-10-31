# From schematic to order: an example workflow

[日本語](workflow.ja.md) · [README](../README.en.md)

How the author builds boards with KiCad and a coding agent (Claude Code, "AI" below). It is the author's own preference
and will differ between projects. kicad-review is used in steps 4 and 9 (what a person fixes in step 10 is listed on
the step 9 page too), and can be used in step 7.

The steps keep **design** and **implementation** apart. Design is deciding how things should be (a person and the AI
talk it through). Implementation is making it real by working in KiCad (placing parts, connecting them), mostly by the
AI. Without the split, thinking and doing get mixed up.

"Who": "Human & AI" means together, in conversation. In brackets, what the other side does.

| # | Step | Kind | Who | kicad-review |
|---|---|---|---|---|
| 1 | Requirements | design | Human & AI | |
| 2 | Circuit design | design | Human & AI | |
| 3 | Schematic implementation | implementation | AI | |
| 4 | Schematic review | review | Human & AI (in rounds) | **schematic** (`/sch`) |
| 5 | BOM check | review | AI (a person checks) | |
| 6 | Outline and key placement: design | design | Human (the AI helps) | |
| 7 | Outline and key placement: implementation | implementation | AI (or a person) | board (`/board`), optional |
| 8 | Autorouting | implementation | AI | |
| 9 | Board review | review | Human & AI (in rounds) | **board** (`/board`) |
| 10 | Finishing | implementation | **Human** | items listed on the step 9 page |
| 11 | Deciding it is ready to order | decision | Human | |
| 12 | Fab outputs | implementation | AI | |
| 13 | Bulk buying of parts (optional) | order | AI (a person decides) | |
| 14 | Cart and order | order | AI (a person places the order) | |

Steps 9 and 10 repeat until no items are left.

## 1. Requirements (design)

Decide what to build: size and shape (the enclosure's dimensions if there is one), functions, the parts that face the
outside (connectors, switches, displays), power (battery or USB, how much current), quantity and budget. A person and
the AI decide it together and write it down. When a later step is unclear, come back here.

## 2. Circuit design (design)

A person and the AI choose the parts and how they connect. Check each part against the reference circuit in its
datasheet. KiCad is not touched yet.

## 3. Schematic implementation

The AI draws the circuit from step 2 as a KiCad schematic (places symbols, connects them, numbers them).

## 4. Schematic review (kicad-review, schematic)

Review one schematic, or the changes from the previous version. The AI writes down why each change was made; you check
it on the drawing and ask questions or ask for fixes, until nothing is left. To compare with an earlier version or
another board, use side by side, overlay or flip.

## 5. BOM check

**Always before moving to the board.** Check that every part can be bought from the assembler (e.g. JLCPCB: stock,
basic or extended part) and that part numbers and footprints match. The AI looks it up; a person checks the result.
Note an alternative for parts with little stock. Finding a missing part after placement means placing again.

## 6. Outline and key placement: design

Decide the board outline and where the parts that face the outside (connectors, switches, displays) and the power /
high-current ICs (motor drivers, chargers, power switches) go. **A person should lead this**: moving them later means
routing again. Decide where the high-current ICs go with the same weight as the connectors (far apart means long, wide
traces).

## 7. Outline and key placement: implementation

Put the positions from step 6 on the KiCad board. What can be said in words or numbers (distance from an edge,
rotation, how parts line up) can go to the AI. What is hard to put into words, a person can place in KiCad. Placement
checks can be listed on the board page too.

## 8. Autorouting (implementation)

The AI routes with [Freerouting](https://github.com/freerouting/freerouting) or similar. Depending on the board, it
can take hours.

## 9. Board review (kicad-review, board)

The AI lists what is left on the board (what it changed, what a person fixes in step 10, questions). You check,
comment or press "please fix", the AI fixes, you check again.

## 10. Finishing (human)

**The AI is poor at this, so make it a person's step from the start.** An autorouter cannot push other traces aside or
nudge parts to squeeze a trace in. Other fine adjustments that are decided while moving things on the KiCad screen
(making room, letting traces give way to each other) are faster and better done by a person on screen than by the AI
trying coordinates. Have the AI write each step 9 item as a goal ("connect these two pads", "make this trace 0.5 mm or
wider"), not as step-by-step instructions. After fixing, go back to step 9.

## 11. Deciding it is ready to order

The hardest step, and it depends a lot on the project. The criteria below are one example: what the author checked or
had fixed again and again in the last review rounds of two small boards (a radio module, a motor driver and a battery
charger on each).

## 12. Fab outputs (implementation)

Let the AI export the Gerbers, the BOM and the placement file. The BOM was checked in step 5; check the exported files
only.

## 13. Bulk buying of parts (optional)

If you plan more boards like this one, have the AI compare whether buying parts in bulk is cheaper. A person decides.

## 14. Cart and order

An AI that drives a browser (e.g. Claude in Chrome) can upload the files and fill the cart at the assembler. A person
does the final check and places the order.

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

### What the AI tended to miss

Found by a person, not by the AI, on the author's boards:

- **A trace that only grazes a pad.** DRC counts it as connected, but the contact is narrower than the trace
- **A GND island handed to a person as "no room for a via"** that rotating the part would have fixed. Have the AI try
  rotating or nudging two-pin parts before asking
- **Courtyard overlaps set to "ignore".** DRC passed while a resistor sat on the body of the next FET
- **One via for a high-current layer change**
- **A power trace whose width changed several times along the way**
- **Numeric rules with no source**, made up by the AI (part spacing), then handed to a person where they could not be
  met. Have the AI state where a rule comes from (datasheet, fab rules, your instruction)
- **A fix asked of a person that the AI's own override cancelled:** pads forced to solid connection, so clearing
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
  — 4 layers, 171 parts; placement by hand, wiring, Freerouting runs and outputs by the AI
- [KiCad MCP: Design a PCB with Claude Code in KiCad 10](https://jlcpcb.com/blog/kicad-mcp-how-to-design-a-pcb-with-claude-code)
  — clean ERC / DRC does not mean correct; compare the netlist with the intent before ordering
- [What Routing 314 Nets Taught Me About AI-Assisted PCB Design](https://tinycomputers.io/posts/what-routing-314-nets-taught-me-about-ai-assisted-pcb-design.md)
  — six hours on autorouter clearances; trust the fab's DFM check
- [PCB_Layout_with_AGENT_in_KiCAD](https://github.com/haohao-0725/PCB_Layout_with_AGENT_in_KiCAD) — print the
  placement 1:1 before routing
- [kicad-happy](https://github.com/aklofas/kicad-happy), [kicad-skills](https://github.com/jvanderberg/kicad-skills) —
  agent skills for analysis, BOM and pre-order checks
