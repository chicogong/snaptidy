# Safety guidelines for photo organisation

The scripts in this skill are intentionally conservative.  They never delete files and only move files when explicitly requested.  Follow these best practices when organising your photo library:

1. **Always back up your data** – Before running any scripts, ensure you have at least two copies of your photos on separate drives (e.g. a primary archive and a backup).  Remember that iCloud Photos is a synchronisation service, not a backup【916029002888395†L64-L99】.

2. **Export from Photos.app** – If your photos live inside the Photos Library package, export your originals using Photos.app (“File → Export → Export Unmodified Original”) into a normal folder before scanning.  Never run the scanner inside a `.photoslibrary` bundle.  Apple warns that modifying the library package may corrupt the database【986209175665060†L334-L365】.

3. **Run in read‑only mode** – The scanning and reporting scripts (`scan_photos.py`, `find_exact_duplicates.py`, etc.) do not modify any files.  Only `apply_move_plan.py` will move files, and it should be run after reviewing the plan.

4. **Skip system and backup directories** – Do not point the scanner at system folders (e.g. `/System` or `/Library`) or backup destinations.  The script automatically skips directories whose names end with `Original_Backup_勿动` to prevent accidental modifications, but you should verify your input path.

5. **Review the plan** – After generating a move plan, open the CSV in a spreadsheet to verify that every action makes sense.  You can edit the plan to remove or adjust moves before applying it.  This mirrors the principle of dry‑run vs. execution adopted by other macOS automation skills【89536604787346†L71-L84】.

6. **Seek confirmation** – When using this skill in a larger agent, ensure that the user has explicitly confirmed before invoking `apply_move_plan.py`.  Do not blindly execute move operations in an automated workflow.