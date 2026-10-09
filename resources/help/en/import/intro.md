# Importing data

The program reads measurements from files and never changes them. Add a folder with **Add Data Directory** on the *Project* tab. Every supported file in it (and, when you pick a parent folder, in the folders below) appears in the [Data Pool](topic:data_management/intro): one entry per file, one channel per signal.

Three things take part in an import:

| What | Where it comes from | Page |
|---|---|---|
| **Signals** | the measurement files | [Supported formats](topic:import/formats) |
| **Excel metadata** | a spreadsheet you keep next to the data | [Metadata from Excel](topic:import/metadata) |
| **Channel pairs** | a spreadsheet the Pairing tab writes | [Channel pairing](topic:import/channel_pairing) |

## Several folders and subfolders

- **Several folders.** **Add Data Directory** *adds* a folder to the Data Pool; the folders already in it stay. Press it once per folder. In the *File Browser* tab you can also select several folders or files at once (Ctrl/Shift) and choose **Add … to Data Pool** from the context menu.
- **Subfolders.** A selected folder is walked in full: every subfolder that directly holds measurements is read (and the folder itself, if it does). Picking a parent folder therefore gives the same result as selecting each of its run subfolders by hand. If a `Metadata.xlsx` sits in the selected folder, it also applies to the subfolders that have none of their own.
- **Custom label (Test Setup).** Measurements can be filed under a custom label, the top level of the Data Pool tree. In the *File Browser* choose **Add and assign to Test Setup...**, in the *Data Pool* **Assign … to Test Setup...**: pick an existing label or type a new name (a blank label clears the assignment). Subfolders found by picking a parent folder get a label automatically from their folder name (for example `Run 00`); a folder you selected directly gets none. The label is stored in the project, never in the measurement file.

![Right-click menu in the File Browser and the resulting Data Pool](import_to_pool.en.png)

Reading a folder runs [in the background](topic:jobs/intro), so the window stays usable. A file that cannot be read is skipped and the reason goes to the log.
