---
name: windows-torch-before-qt
description: On Windows, torch must be imported before Qt or c10.dll fails to load (WinError 1114) - gui/__main__ preloads it
type: project
---

On Windows, importing Qt before torch makes torch fail to load `c10.dll` with
`WinError 1114` (a DLL initialization routine failed). `gui/__main__.py`
therefore **preloads torch before Qt on Windows**, costing about a second of
startup.

**Why it matters more than it looks:** this did not present as a crash on
startup. It silently broke GUI training and model inspection in the Windows venv
- the failure only appeared when something actually tried to touch a model, on
one platform, so it is easy to reintroduce from a Mac and not notice.

**How to apply:** Do not reorder or "tidy" the imports in `gui/__main__.py`.
Anything that ends up importing Qt at module scope earlier in the startup path
needs checking on Windows specifically - offscreen smoke tests on macOS will not
catch it.

Related: [[cross-pc-workflow]]
