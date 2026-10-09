# Test datasets

**Realize Test Dataset** writes a complete, repeatable synthetic measurement set to a folder you choose. The files are Siemens ASC measurements ([Supported formats](topic:import/formats); to make a single record yourself, see [Generate a signal](topic:generation/signal)), accompanied by an Excel metadata sheet and, for one dataset, a channel pairing sheet. You can use the files to explore the analysis workflow without preparing measurements yourself.

## Choose a dataset

On the *Project* tab, open **Realize Test Dataset** in the *Tools* group. Choose a dataset in **Dataset:**, then choose an output folder. The selector lists dataset IDs; it does not let you pick individual measurements. The whole dataset is written. The current library contains:

| Dataset | What it contains |
|---|---|
| `engine_degradation_v1` | 25 measurements: five runs representing 0 to 20,000 cycles, each with five ramp setups. Six vibration channels cover acceleration and sound pressure, alongside a tacho channel. The signals vary between runs to support comparisons across the degradation sequence. |
| `help_demo_v1` | 8 measurements: Healthy and Damaged runs, each with slow and fast ramps up and down. It has two acceleration channels, one sound-pressure channel, and a tacho channel. Its signals include orders, resonances, sidebands, and a 500–3,000 Hz chirp for exploring plots and analysis settings. |

The first dataset ID is selected by default. The output-folder dialog starts in the current active directory when one is set. Cancel either picker, or decline the confirmation, to leave without starting the job. The confirmation dialog shows how many measurement files will be written and warns that files with matching names will be overwritten.

## Write and add the measurements

1. Choose the dataset and its output folder.
2. Read the overwrite warning and confirm with **Yes**.
3. Wait for the background job to finish. The log reports the written measurement count and the spreadsheet files. If the job stops or a write fails, the output folder may contain files already written; the app reports that the dataset is incomplete and does not roll those files back.
4. To analyse the measurements, add the chosen output folder with **Add Data Directory** ([Importing data](topic:import/intro)). The folder scan finds measurements in its subfolders and reads the dataset's matching metadata. Realizing a dataset does not add it to the current Data Pool automatically.

## The accompanying spreadsheets

`metadata.xlsx` is written at the output folder root. Its **Measurements** sheet has one row per ASC file, keyed by **File Name** (the filename without `.asc`), with setup, ramp, speed, duration, and seed fields. The `help_demo_v1` sheet also has a **Condition** column containing `Healthy` or `Damaged`. When a project-level metadata sheet and this folder sheet both describe a file, the project-level row takes precedence. See [Metadata from Excel](topic:import/metadata) for how Excel metadata is matched to measurements and used in the app.

`help_demo_v1` also writes `channel_pairing.xlsx`, with the example pair `Motor_HSG` and `Bearing_HSG`. Both channels are in this generated ASC dataset; the row is a pairing example, not a claim that one is a simulated measurement. The app reads its active pairing sheet from the folder containing the [project file](topic:general/projects) (`.nvhproject`). If your project is in another folder, copy the generated workbook there to use that mapping. See [Channel pairing](topic:import/channel_pairing).

The dataset files use fixed seeds, so realizing the same library version produces repeatable ASC files. The **engine_degradation_v1** metadata workbook also includes an **Order Map** sheet describing its simulated features and tacho changes. The help demo does not include that sheet.
