# Contributing to SnapTidy

First off, thanks for taking the time to contribute! 🎉

## Opening an Issue

### Bug Reports

When filing a bug report, please include:

1. **macOS version** (e.g., macOS 14.5 Sonoma)
2. **Python version** (`python3 --version`)
3. **Steps to reproduce** the issue
4. **Expected behavior** vs. **actual behavior**
5. **Full error output** (stack trace if available)

### Feature Requests

When suggesting a feature, please describe:

1. **The problem** you're trying to solve
2. **Your proposed solution**
3. **Alternatives** you've considered

## Development Setup

```bash
# Clone the repository
git clone https://github.com/chicogong/snaptidy.git
cd snaptidy

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Optional: install development dependencies
pip install pytest
```

## Making Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Test your changes (see below)
5. Commit with a clear message (see Commit Guidelines)
6. Push to your fork
7. Open a Pull Request

## Testing

Before submitting a PR, verify your changes:

```bash
# Quick smoke test — scan a small directory
python3 scripts/scan_photos.py --input /tmp/test_photos --output /tmp/test_index.db

# Run the full pipeline on test data
python3 scripts/scan_photos.py --input /tmp/test_photos --output /tmp/test_index.db
python3 scripts/find_exact_duplicates.py --index /tmp/test_index.db --output /tmp/test_dupes.csv
python3 scripts/find_similar_photos.py --index /tmp/test_index.db --output /tmp/test_similar.csv
python3 scripts/generate_move_plan.py --duplicates /tmp/test_dupes.csv --index /tmp/test_index.db --plan /tmp/test_plan.csv --target-root /tmp/test_photos
python3 scripts/generate_preview.py --duplicates /tmp/test_similar.csv --index /tmp/test_index.db --output /tmp/test_preview.html
```

## Commit Guidelines

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add reverse geocoding for GPS metadata
fix: prevent crash when scan finds no photos
docs: update README with new installation method
refactor: extract _compute_entry() from scan loop
test: add edge case tests for Chinese filenames
chore: update dependencies
```

## Code Style

- **Python 3.9+**, PEP 8
- 4-space indent, max line length 120
- CLI scripts use `argparse` with `--input`/`--output` style flags
- All CSV output uses UTF-8 with BOM for Excel compatibility
- No pandas, numpy, or other heavy dependencies unless absolutely necessary
- SQLite is preferred over CSV for output (better performance at scale)

## Safety Rules

When contributing code, you MUST follow these rules:

- **Never implement file deletion** — only move operations
- **Never modify files inside `.photoslibrary`** — use `scan_photos_library.py` (read-only) or `apply_move_plan.py --mode photos-trash` (PyObjC)
- **Always require user confirmation** before any file move operation
- **Log all operations** to a CSV audit trail
- **Commit each entry immediately** when scanning to SQLite (zero data loss)

## Areas Where Help Is Needed

See the [README](README.md#contributing) for a list of areas where contributions are especially welcome.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
