# Filtering

The **Filters** dock narrows what you see without touching the data. Two things are filtered:

- the **curves already drawn in a graph** -- a **Trace filter** hides curves; it never adds one, never recomputes and never edits a result;
- optionally the **Data Pool tree**, so only matching measurements and channels are listed (**Filter Data Pool**).

The Evaluation table follows the Trace filter ([Respect Trace filter](topic:evaluation/intro)).

![Filters dock and Configure Filters dialog](configure_filters.en.png)

## Filter cards

What the dock shows is one **Filter card**: a named tab with a list of columns. The checked values behind it are its **Filter selection**.

- **Global** -- one selection shared by every graph. It offers values from the whole Data Pool and the Result Pool, so one click changes all open graphs.
- **Local** -- one selection per graph. It offers only what the graph in focus draws and filters only that graph.
- **+** adds your own card (a Local one by default). A custom Local card belongs to the graph that was in focus; its tab is visible only while that graph is in focus. The checkbox **Global** next to it, or the right-click menu (*Make Global* / *Make Local*, *Rename&hellip;*, *Duplicate*, *Delete*), changes scope. The two fixed tabs cannot change scope or be deleted.

Exactly one card is in effect at a time, for all graphs. Click a tab to switch. If the card in effect is a custom Local card of a graph you leave, the dock falls back to *Local*, and returns to the custom card when you come back to that graph. Cards and selections are saved with the project.

## What a card offers

A fresh card has **one column: Channel**. Everything else you add with **&#9881; Configure Filters&hellip;**:

| Group | Columns |
|---|---|
| Identity | Channel, Direction, Channel type ([Supported formats](topic:import/formats)), File name, Data Pool label, [Result set](topic:results/intro) |
| Raw metadata | fields read from the measurement files |
| Excel metadata | fields from the metadata spreadsheet ([Metadata from Excel](topic:import/metadata)) |
| Calculated | Analysis type (spectrum, order cut, ...), Order, Parameter set |

Raw and Excel fields appear there only after you tick **Use as Filter** for them in *Metadata and Filter Settings* ([Metadata from Excel](topic:import/metadata)). Every row shows how many distinct values the column has now, *(N)*; a column with one value, or a different value on every measurement, is greyed ("cannot narrow anything down") but stays selectable.

In *Configure Filters* you also choose each column's **position**, how it is drawn, how many **columns side by side** the card uses (1 to 4) and **Default**. A column marked *Default* is added to every new graph's card on top of Channel. **Auto apply** shows each change on the graph in focus while you make it; Cancel restores the card.

Drawing: **Checkbox list**, **Multi-select** (a button with a pick list) or **Range (min..max)**. A numeric or date field is always a range; to pick its values from a list, change its Type to Text in *Metadata and Filter Settings* ([Metadata from Excel](topic:import/metadata)). A list longer than 12 rows scrolls inside its box.

A **Parameter Set** (see [Result Pool](topic:results/intro)) is a group of curves computed with the same settings, numbered *Parameter Set 1, 2, ...* (the order is not part of the settings -- it is its own column). Hover a value for the settings it stands for.

## How a curve is judged

A curve stays visible only if **every column** lets it through, and a column lets it through when the curve's value is **checked** (any of the checked values will do). Rules in detail:

1. **A box you unchecked hides, a value never offered does not.** A mask hides only what the card showed a checkbox for and you unchecked. A channel dropped onto the graph after you last looked, or a column the card does not have, hides nothing. When a wider set of values appears, only the *new* values are ticked for you; a value you deliberately unchecked stays unchecked.
2. **Unchecking everything in an offered column hides every curve**, because no value is allowed.
3. **(Empty)** appears in a column when some curve has no value there (a time-domain curve has no Order, a curve without a source has no metadata). Uncheck it to hide those curves.
4. **Order** is compared with a tolerance (relative 10<sup>&minus;5</sup>), so 2.3 typed by you matches 2.3 stored as a float.
5. **Range** hides a curve only when you have moved the range and the curve's value lies outside it. An untouched range hides nothing, and a curve with no value for that field passes -- a range is a statement only about curves it can judge. For a channel-level field the curve's own channel is read.
6. A value whose curves are all hidden by **other** columns anyway is shown greyed: a click on it would change nothing.

## Filter Data Pool and Show all

- **Filter Data Pool** narrows the Data Pool tree to measurements and channels matching the card. Here the rule is a *positive list*, so a column counts only when it really narrows: all values checked, or none, means no constraint. While it is on, the pool's own measurements also contribute values, so you can filter before anything is computed.
- **Show all** switches every mask on every graph and the pool narrowing off at once, and greys the cards. Your checked values are kept; untick it and the filters are back.
