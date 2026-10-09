# Selections

A **Selection** names a set of measurements and channels by their values in the current [Data Pool](topic:data_management/intro). Use it to draw the same subset again without picking its channels individually. A query Selection is evaluated again against the pool when it is used, so it can include matching measurements added later.

## Create a Selection

Open **Selections** in the Explorer and press **Create Selection**. Give the Selection a name, then use the checkboxes in the grid to choose which measurements and channels match. Each displayed column is one condition: values checked within a column are alternatives, while restrictions in different columns apply together. In a new Selection, leave every value checked in a column to keep that column open to new values in future measurements. The **(Empty)** value lets you include measurements where that field has no value.

For example, in the help demo choose only `Healthy` in Condition and `Motor_HSG` and `Bearing_HSG` in Channel. Both chosen channels from Healthy measurements match; Damaged measurements and the sound-pressure channel do not.

![The Selection editor with the example rule and its live count](selection_editor.en.png)

The grid starts with the available channel, identity and categorical metadata columns. Press **Configure…** to choose which columns the editor displays; this column configuration is shared by Selection editors in the project. Result-set, order, analysis-type and Parameter Set columns (see [Filtering](topic:filtering/intro)) are not offered here. The grid shows a live count of matching measurements and distinct channel names/directions, rather than a count of every channel occurrence across all files. For example, the same two channels in eight measurements still count as two channels here. The **OK** button becomes available when the name is valid and at least one measurement matches. Press **Cancel** to close without saving the Selection.

## Edit, rename or delete

Right-click a Selection in the list to choose **Edit…**, **Rename…** or **Delete…**. Editing changes its checked values; its name is fixed in the editor. Renaming is a separate action. A name must be unique and cannot be **Whole Data Pool**, which is reserved for the entire pool.

Before deleting, the program asks you to confirm. If a workflow refers to that Selection, the confirmation lists the affected workflows; after deletion they show **Not ready** until their input is set to an available Selection. Renaming a Selection also updates workflow inputs that refer to its old name.

Selections belong to the [project](topic:general/projects). Save the project to keep changes for the next time you open it.

## Draw a Selection in a graph

Double-click a Selection in the **Selections** list to open its channels in a new workspace tab. You can also drag it onto an open [graph](topic:graphs/intro) to add those channels there. The Selection is resolved against the current Data Pool when you draw it. If it has no channel available to draw, nothing is added. For more than 50 channel occurrences across the measurements, confirm that you want to draw them all.

The graph receives the resolved channels; it does not stay linked to the Selection. Editing the Selection later does not change channels already drawn in a graph.

> **Selection** here means a saved Measurement selection. It is different from a **Filter selection**, which controls which existing graph curves are visible. See [Filtering](topic:filtering/intro).
