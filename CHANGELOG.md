# Changelog

What changed in Spectra, written for users. Rules for writing it: [docs/agents/release.md](docs/agents/release.md).

## 0.2.2 - 2026-10-23

- Simcenter Testlab `.ldsf` version 21, 24-bit data format as input is supported.
- Settings has Display prefix and decimals per unit, with a live Preview; axes, Cursor Box and evaluation table follow them.
- Tracked analysis takes Min and Max RPM. Start and End in seconds in Free Run.
- Tracking gives one point per speed, so plateaus and dips no longer cause zigzag curves. The Hysteresis setting is gone and Sweep offers only Up and Down.
  ![One point per speed, the first crossing](docs/site/img/whats_new_0_2_2.png)
- Folder added to the Data Pool gets its own Label after the folder name.
- A tab restored with a project keeps the settings it was saved with.
- Highlight also marks the legend row.
- Curve legends are named consistently.
- Bug fixes.


## 0.2.1 - 2026-10-18

- Simcenter Testlab `.ldsf` time recordings with 32-bit float samples can be opened.
- The project keeps its computed graph tabs on Save and when Spectra closes, so reopening it shows them without recomputing.
- Minor bug fixes.


## 0.2.0 - 2026-10-14

- Workflow tab is now a block canvas: drag, wire and arrange blocks, undo / redo, and run all chains or one with Run Chain.
  ![Workflow canvas with blocks](docs/site/img/whats_new_0_2_0.png)
- New Settings window (gear icon) replaces the Settings tab, with search, Apply / Revert and Reset All; Run Benchmark moved to the Project tab.
- Project, cache and settings files from much older versions are no longer read; old results are recomputed.
- New Theme setting (Dark / Light) switches the whole application look after restart.
- Graph curves use a new 12-colour palette and stay smooth with many curves.
- Data Pool asks whether MASTA, processed and ANSYS amplitudes are RMS or Peak, so curves are no longer off by √2.
- MASTA workbooks with one sheet per order (H1, H4.79, …) are now read sheet by sheet; ANSYS harmonic-response CSV files can be added as a first-order curve.
- Fixed: opening a project no longer marks it as unsaved, and starting an Update no longer shows "Not responding".

## 0.1.2 - 2026-10-08

- New Cursor on the Tools tab: hover a graph and read the values of the curve in a box right.
- Cursor Settings let you choose and order the fields the box shows.
- Highlight thickens the curve under the mouse and dims the others; Pin freezes the box in place.
- New built-in Help window with a quick start and a full reference, in English and Czech.
  ![Help quick start and the Cursor](docs/site/img/whats_new_0_1_2.png)
- Minor bug fixes.

## 0.1.1 - 2026-10-05

- Opening a project that is already open now brings its existing window to the front instead of opening a second one.

## 0.1.0 - 2026-10-05

- First public alpha: spectra, spectrograms, order tracking and trending across large sets of measurements.
