# Canvas controls

The Workflow editor uses one visual style for the **Block Pool**, workflow tabs, canvas, **Properties** and status line. Blocks, ports, wires and text are drawn directly by Qt at the screen's DPI. Zoom changes the view; moving a block changes its saved position. Open [Workflow block diagram](topic:workflow/intro) for Input selections, saving results and chain execution.

## Shortcuts and mouse gestures

| Control | Gesture | Effect |
| --- | --- | --- |
| Workflow tabs | Click a tab | Open that workflow; each has separate undo history. |
| Canvas | Mouse wheel | Zoom around the pointer. |
| Canvas background | Left-button drag | Pan. |
| Canvas | Middle-button drag | Pan. |
| Block | Left click | Select and show Properties. |
| Block | Ctrl+click | Select multiple blocks. |
| Block | Left-button drag | Move; wires follow. |
| Block | Double-click | Focus Properties. |
| Block Pool row | Drag onto canvas | Add an unconnected block at the pointer, with default settings. |
| Block Pool row | Double-click | Add with compatible auto-wire from the selected block. |
| Selection | Drag onto an Input block | Change that Input's selection immediately. |
| Output port | Drag to an input port | Connect; replace the wire if the input is occupied. |
| Wire drag | Escape | Cancel. |
| Wire | Click, then Delete; or right-click → Delete wires | Disconnect selected wires. |
| Selected blocks | Delete; or right-click → Delete blocks | Remove blocks, their wires and positions. |
| Block | Right-click → Run Chain | Run its connected chain; also available in the ribbon. |
| Editor / Properties | Ctrl+Z / Ctrl+Y; or Undo / Redo toolbar buttons | Restore committed workflow edits; unapplied form values are replaced. |
| Project | Ctrl+S | Save the current workflow and layout with the project. |

## Wiring and marks

Input ports are on the **left**, output ports on the **right**. Hover over a port for its name, data kind and required/optional status. Grey inputs cannot accept the wire being dragged. Incompatible kinds and cycles are refused with a reason below the canvas. One output can feed several inputs; each input has one wire.

The **tacho · from measurement** port takes its channel from Properties; new wires cannot attach to it. Existing imported tacho wires can still be deleted. An Input shows its Selection or **Whole Data Pool**. A **red outline** means validation rejected the block (including a chain with several Inputs); its tooltip explains why. A **💾** badge means the output will be saved; its tooltip gives the result set name. Selection uses a light grey outline; an invalid selected block keeps its red outline.

The status line summarizes readiness. **Run** executes all runnable chains sequentially in the background and reports refused chains; **Run Chain** executes the selected block's connected chain. Each runnable chain needs one Input with a resolvable selection and at least one Save block. See [Running chains](topic:workflow/intro).
