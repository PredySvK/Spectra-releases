# Import wizard

A table file (`.xlsx`, `.txt`, `.csv`) is read through an **Import template**: it says where the headings are, which columns are curves and how a channel gets its name, order and metadata from the texts around it. When no template fits your files, the wizard builds one from one or more sample files. The template is stored in your library; the sample files are never changed.

*[Project](topic:general/projects)* tab → **Import Templates…** → **New…** → pick one or more sample files of the same kind. **Edit…** opens the wizard on a sample with the selected template already loaded.

The wizard has four steps, named in the line at the top, and goes forward only when the step is complete. **Next** (Alt+Right) and **< Back** (Alt+Left) move between them; the red line next to the buttons says what is missing. The examples below use a MASTA workbook with order cuts.

## 1. Samples and what it is

![Step 1](wizard_samples.en.png)

- **Add files…** adds more samples. Several samples show what changes between files, and the wizard offers the other files of the same suffix in the folder. A sample of another suffix is refused with the reason.
- **Data kind** says what the curves are: order cut, spectrum, Overall Level, order residual or time signal. The wizard guesses it and names the cell it guessed from.
- **Origin**, **Values** and **Amplitude in the file** are what the file cannot tell, so they start unanswered (red star) and **Next** stays off until you answer them. A wrong answer would change the numbers without any sign. Values *in dB* ask for the reference level; *From the header* is offered only when the amplitude header says Peak, RMS or Peak-to-Peak.
- **Channel type**: *Automatic* follows the unit.
- A time signal also asks where the time comes from (a first column, a fixed sample rate, or a text picked in step 3).

## 2. Table

![Step 2](wizard_table.en.png)

The preview under the settings shows the sheet; the colours are explained under it.

- **Headings**: the heading row is found by the text of its first cell (works when the position differs between files) or by its number. Click a **row number** in the preview to move it; the next click sets the first data row.
- **Sheets**: which sheets are read: all (a sheet without the heading row is skipped), the first N, without the last N, or listed by name. A text file has no sheets but asks for its encoding, delimiter and decimal separator, shown as detected.
- **Columns**: *X/Y pairs*, *Shared X* (one X column, many Y) or *One curve per sheet*. The layout the wizard guesses is marked.
- **Units**: detected in the headings; override X or the amplitude unit when the headings are wrong or missing. A conflict is written in red.

## 3. Texts → roles

![Step 3](wizard_roles.en.png)

Every text around a curve (header cells, the sheet, file and folder name) is split into **chips**. A chip can play a role: **Channel name**, **Axis**, **Order**, or a **Metadata** field. The wizard fills the slots first from how the chips change from channel to channel; the slots show the selected channel.

- **+ Pick** arms a slot, then click a header cell (or the *Sheet* / *File* / *Folder* text above the preview) and choose the chip. Esc stops picking. Without an armed slot, a click offers every role for every chip.
- The name is made of chips in text order: drag a chip to move it, **✕** takes it out, right click splits it. The axis is the locked last chip; if it is also in the name, a warning says so.
- **Order** takes a chip, or one number typed for all channels.
- A chip with a role is marked in its cell by a band in the colour of the role (two roles, two bands).
- The table under the preview shows what the roles make of every channel. Click a row to select that channel; **Problem** says what fails.

## 4. Check and save

![Step 4](wizard_check.en.png)

- **Template name** and **File name pattern** (which files the template reads, e.g. `*.xlsx`). A name of a built-in template is refused.
- The table lists every channel the template reads, with its order, units and number of points.
- **Advanced** holds an optional check for duplicate curves (the same channel and order with equal values after conversion to RMS), with a choice to keep one of them. It runs on the first sample only.
- **Save** writes the template into your library and adds the files with it. A built-in template can only be saved under a new name (**Save as**). When the wizard was opened on a template of the project, the button is **Apply to project**, or **Overwrite** / **Save as new**.

See also: [Importing data](topic:import/intro), [Supported formats](topic:import/formats).
