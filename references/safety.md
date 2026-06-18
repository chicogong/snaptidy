# Safety and recovery

Load this reference before any operation that can move files, edit metadata,
import media, change Photos.app, or send items to Trash.

## Non-negotiable rules

1. Never implement or invoke permanent deletion.
2. Never modify files or databases inside `.photoslibrary` or `.photolibrary`
   packages directly.
3. Generate and review a plan before a state-changing operation.
4. Obtain explicit user confirmation for the exact plan and operation mode.
5. Preserve CSV audit logs and report their paths.
6. Verify backups before metadata repair, conversion, rename, or bulk movement.
7. Keep Live Photo components together and exclude unreliable iCloud
   placeholders from hash-based decisions.

Use `scan_photos_library.py` for read-only Photos.app indexing. Use the supported
Photos APIs through SnapTidy for Photos.app changes so its database remains
consistent.

## Operation classes

### Read-only

Scanning, duplicate detection, previews, reports, statistics, and dry runs do
not intentionally change source media. Store their outputs outside the source
tree. These operations do not require move confirmation once the source path is
known.

### Reversible writes

Normal folder moves performed by `apply_move_plan.py --mode move` create a JSON
undo record in an `undo_records/` directory. The record expires after 30 days.
Reverse the latest eligible move with:

```bash
python3 scripts/apply_move_plan.py --plan /path/to/move_plan.csv --undo
```

EXIF edits create backups by default. Keep backups until the result is verified.
Do not use `--no-backup` unless the user explicitly accepts the reduced safety.

### Special recovery

Trash operations do not use SnapTidy's JSON undo records:

- Recover `--mode trash` operations with Finder > Put Back.
- Recover `--mode photos-trash` operations from Photos.app > Recently Deleted
  while the system retention window still applies.

Never tell a user to run `--undo` for either Trash mode.

## Confirmation thresholds

- For 1–9 moves, present the summary and request `[Y/n]` confirmation.
- For 10 or more moves, require the user to type `yes`.
- A previous request to scan, preview, or generate a plan is not approval to
  apply that plan.

The confirmation summary must include the number of actions, total bytes,
source, destination, operation mode, iCloud exclusions, Live Photo handling,
and the applicable recovery mechanism.

## Source-specific checks

- Normal folders: reject system directories and warn when source and target
  overlap unexpectedly.
- Photos.app: request Full Disk Access when required; never traverse the library
  package with the normal folder scanner.
- iCloud-optimized sources: use warn, skip, or download handling before dedup;
  do not trust placeholder hashes.
- External drives and Android devices: confirm the mount remains available
  through scanning and import.
- Shared albums: treat them as read-only; import into a regular album and let
  the user perform any supported manual shared-album step.

## Completion report

Report whether the operation was read-only or state-changing, the successful,
skipped, and failed counts, the audit and undo-record paths, and the exact
recovery action. Never imply that a generated plan was applied.
