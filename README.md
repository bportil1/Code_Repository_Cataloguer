# Codebase Catalog

A lightweight bookkeeping tool that creates a self-contained interactive HTML index of a Python repository.

It catalogs directly visible repository structure:

- directories and files
- Python modules
- imports as written
- classes, functions, and methods
- signatures, docstrings, decorators, bases, and line locations
- simple names mentioned inside definitions
- internal module imports and external package names

It does not attempt runtime tracing, correctness checking, complexity scoring, or architectural evaluation.

## Run

```bash
python codebase_catalog.py /path/to/project
```

The root `.gitignore` is applied automatically. Choose an output and add any extra exclusions:

```bash
python codebase_catalog.py /path/to/project \
  --output project_catalog.html \
  --exclude results \
  --exclude checkpoints \
  --open
```

Explicit `--exclude` values are added to the built-in exclusions and the root `.gitignore` rules. To intentionally catalog ignored files, pass `--no-gitignore`.

The generated HTML is self-contained and can be opened directly without a server.
