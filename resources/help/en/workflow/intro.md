# Workflow block diagram

A workflow automates calculations. You chain processing blocks, for example Remove DC → Spectrum, and run them over many measurements at once instead of opening each channel by hand.

- **Inputs:** an **Input** block picks the measurements: the **Whole Data Pool** or a saved **Selection**.
- **Results:** a block with **Save result set** ticked writes its output as a result set into the project's result cache and is marked with a **💾** badge. Blocks that do not save are only intermediate steps. To plot a result, focus a graph and check the set in the **Result Pool** (Explorer); see [Result Pool](topic:results/intro).

![The Workflow tab: Block Pool, block diagram with wires, and Properties](workflow_canvas.en.png)

See [Canvas controls](topic:workflow/canvas) for a complete table of shortcuts, mouse gestures and canvas marks.

On the **Workflow** ribbon tab, create a **New Workflow** or choose one using the tabs above the canvas. Separate connected parts of the diagram are called chains.

Input ports are on the left, output ports on the right. Hover over a port to see its data kind and whether an input is required or optional. Wires show the data flow between blocks. Blocks are automatically placed from left to right. A red border indicates that the workflow is not valid yet; hover over a block for the validation message.

## Running chains

Each **chain** is one connected part of the diagram, with its own Input selection.
Adding a wire between two chains merges them. Chains are derived from the wires;
they have no separate settings. Messages identify them by their canvas order and
Input block identifiers, for example **Chain 2 (input_2)**.

**Run** runs all runnable chains one after another in the background. A chain
that cannot run is reported by name and skipped; the other chains still run.
Each chain needs one Input with a selection and at least one block marked to save.
Chains with several Input blocks are **not supported yet** and are skipped.

Select a block and click **Run Chain** in the ribbon, or **right-click a block →
Run Chain**, to run only its connected chain. The ribbon button is enabled when a
block is selected. Before execution, one **Overwrite / Save as new / Cancel** dialog
covers existing matching result sets across all runnable chains, with candidates
collected per saved block. Cancel stops the whole request; cancelling a running
chain also stops the remaining chains.

## Marks and editing

The **tacho** port is marked **from measurement** because it uses the measurement's tacho channel. New wires cannot connect to it; choose the channel in the block's Properties. Previously saved tacho wires remain visible and can be selected and deleted. An Input block shows its Selection name, or **Whole Data Pool**. A red outline marks a block rejected by validation; hover over it for the reason. A **💾** badge marks a block that saves its output; hover over it to see the result set name.

**Click a wire and press Delete**, or right-click it and choose **Delete wires**, to disconnect it. Select blocks on the canvas and press **Delete**, or right-click and choose **Delete blocks**, to remove them together with their wires and stored positions. Undo with **Ctrl+Z**, redo with **Ctrl+Y**.

## Properties

**Properties** on the right hold the settings of the selected block. An Input block reads the data chosen by a [Selection](topic:selections/intro); a processing block has its parameters and the **Save result set** option, see [Results](topic:results/intro). Confirm block settings with **Apply block settings**; **Ctrl+S** saves them with the project.
