# PythonAnywhere deployment notes

Use the repository root **`wsgi.py`** as the WSGI entry. It respects **`TABLETTRACKER_ROOT`**: set that environment variable to your clone path if the file is not at the project root, instead of hardcoding paths in a copy-pasted WSGI file.

Example snippet for a hosted WSGI config:

```python
import os
os.environ.setdefault("TABLETTRACKER_ROOT", "/home/yourusername/TabletTracker")
```

Then import the app from `wsgi` at the repo root (or paste the contents of root `wsgi.py`).

## Historical copies

`WSGI_FIX_NOW.py` and `WSGI_COMPLETE.py` in this folder are older PythonAnywhere-oriented copies that used a fixed home-directory path. They are kept for reference only; new deployments should use root `wsgi.py` and `TABLETTRACKER_ROOT`.
