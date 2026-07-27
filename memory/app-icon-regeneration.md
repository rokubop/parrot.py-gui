---
name: app-icon-regeneration
description: The logo's master, the macOS tile geometry and colors, and which platform gets which variant - so an icon tweak is a re-run, not a re-derivation
type: reference
---

Master art: `gui/assets/parrot.png`, 1024x1024 RGBA, transparent, nothing
touching the edges. Keep exports downscale-only from Roku's Clip Studio
source.

- **macOS** (`parrot-tile.png` → `parrot.icns` via `iconutil`): head on a
  rounded card at Apple's grid - 824x824 tile centered in 1024, corner radius
  186, head at 78% of the tile nudged 10 px down, vertical gradient dark
  slate `#23262b` → `#17191d`. Apple's own apps follow the 824 grid; many
  third-party apps draw larger, so "matches the dock" depends on the
  neighbours - compare against Finder, not against whatever is loudest.
  A free-form mark renders oversized in the dock (tried first, reverted).
- **Windows/Linux**: the bare head; `parrot.ico` carries 16-256 px.
- Runtime pick is per-platform in `gui/app.py` (`ICON_PATH`).
- Sizes are Lanczos downscales; iconset names `icon_<pt>x<pt>[@2x].png` for
  pt in 16/32/128/256/512.
