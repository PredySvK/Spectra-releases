# Metadata from Excel

A spreadsheet can describe your measurements (rotor state, oil temperature, test number) and every column becomes something you can filter by.

## The sheet

Any sheet with a **File Name** column works. Case, spaces, `_` and `-` in that header do not matter, and the first such sheet wins. One row per measurement. Everything is read as text, so `3000` stays `3000`. A trailing `.0` is dropped and an empty cell means "no value".

The demo `metadata.xlsx` next to `Setup1-Sweep1-1_Processed.unv` (some columns left out):

| File Name | Setup | Spin cycle | Rotor unbalance | Spring | Max speed [rpm] | Spin direction | Oil temp |
|---|---|---|---|---|---|---|---|
| Setup1-Step1-1 | 1 | Step1 | Balanced | 200N | 35000 | Drive | 30 |
| Setup1-Step2-1 | 1 | Step2 | Balanced | 200N | 35000 | Reverse | 30 |
| Setup1-Sweep1-1 | 1 | Sweep1 | Balanced | 200N | 35000 | Drive | 30 |

## Where the sheet lives

1. `metadata.xlsx` in the project folder (it exists once the project is saved) has priority.
2. `Metadata.xlsx` next to the data, or in the folder you picked when the data sits in sub-folders, is used only for files the project sheet does not mention. When both sheets describe the same file, the project one wins.

## Metadata as Filter

Each column becomes a field in **Metadata and Filter Settings** (*Project* tab). The *Type* is guessed from the values. One odd value makes the whole column text.

To filter by a column, tick **Use as Filter** on its row and confirm with **Save & Apply Schema**. The field then appears in the Filters card (add it there with *Configure Filters*, see [Filtering](topic:filtering/intro)): numbers filter as a range, text as a checklist of values. Excel columns start with both **Active** and **Use as Filter** ticked.

![Metadata and Filter Settings](metadata_editor.en.png)

The window has two tabs. *Fields* lists every field; **Active Status** decides whether the field can be shown as a column of the Evaluation table (*Columns…*, see [Evaluation](topic:evaluation/intro)) and has no effect on filtering; **Original Metadata Key** is the column header from your sheet, **Custom Display Label Override** is the name shown in the program, **Type** overrides the guessed type. Level 1 holds the **raw metadata**, what the program reads from the measurement file itself ([Supported formats](topic:import/formats): signal domain, sampling rate, unit and so on); Level 2 holds the columns of your Excel sheet. The *Pairing* tab sets which measured channel belongs to which simulated one: see [Channel pairing](topic:import/channel_pairing).
