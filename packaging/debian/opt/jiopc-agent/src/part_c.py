# src/part_c.py
"""
Part C — Start Menu & Desktop App Presence (corrected: separate desktop vs menu checks).
Read-only structural integrity check. Launches nothing, needs no root.

Two INDEPENDENT checks per app, per spec:
  1. Desktop shortcut present in the correct ~/Desktop/<folder>/.
  2. Start menu entry present in /usr/share/applications/ or
     ~/.local/share/applications/ with the expected Categories= value.

MISSING   = the app's .desktop cannot be found anywhere (neither desktop nor menu).
MISPLACED = found, but wrong desktop folder OR wrong/absent start menu category.
"""

import time
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

from xdg.DesktopEntry import DesktopEntry


# Start menu / application-menu locations (spec-named for category resolution).
MENU_DIRS = [
    Path("/usr/share/applications/"),
    Path.home() / ".local" / "share" / "applications",
]
# Desktop folders root (Games / Education / Productivity live under here).
DESKTOP_ROOT = Path.home() / "Desktop"


def _normalize(name):
    """Canonical key: lowercase, no spaces, no dots, no .desktop suffix."""
    name = name.lower()
    if name.endswith(".desktop"):
        name = name[: -len(".desktop")]
    return name.replace(" ", "").replace(".", "")


def run_part_c(desktop_apps, log_result):
    desktop_index, menu_index = build_indexes()   # two separate indexes, one scan each
    results = []
    for app in desktop_apps:
        result = check_presence(app, desktop_index, menu_index)
        results.append(result)
        log_result(result)
    return results


def _index_entry(path):
    """Parse one .desktop file into a record; tolerate malformed files."""
    try:
        entry = DesktopEntry(str(path))
        display_name = (entry.getName() or path.stem).strip()
        categories = [c for c in entry.getCategories() if c]
    except Exception:
        display_name = path.stem
        categories = []
    return {
        "display_name": display_name,
        "categories": categories,
        "folder": folder_under_desktop(path),
        "path": str(path),
    }


def build_indexes():
    """
    Build TWO indexes in separate scans:
      desktop_index: keyed name -> [records] for files under ~/Desktop/
      menu_index:    keyed name -> [records] for files under the menu dirs
    Each file is indexed under both its display Name= and its filename stem.
    """
    desktop_index = defaultdict(list)
    menu_index = defaultdict(list)

    # --- Desktop folder scan ---
    if DESKTOP_ROOT.exists():
        for path in DESKTOP_ROOT.rglob("*.desktop"):
            rec = _index_entry(path)
            for key in {_normalize(rec["display_name"]), _normalize(path.stem)}:
                desktop_index[key].append(rec)

    # --- Menu (applications) scan ---
    for root in MENU_DIRS:
        if not root.exists():
            continue
        for path in root.rglob("*.desktop"):
            rec = _index_entry(path)
            for key in {_normalize(rec["display_name"]), _normalize(path.stem)}:
                menu_index[key].append(rec)

    return desktop_index, menu_index


def folder_under_desktop(path):
    """Return the desktop folder name if path lives under ~/Desktop/<folder>/, else None."""
    try:
        rel = path.relative_to(DESKTOP_ROOT)
    except ValueError:
        return None
    parts = rel.parts
    return parts[0] if len(parts) > 1 else None


def check_presence(app, desktop_index, menu_index):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "component": "C",
        "test_name": app["name"],
        "result": "MISSING",
        "duration_ms": 0,
        "detail": "",
    }
    start = time.perf_counter()
    key = _normalize(app["name"])
    expected_folder = app["desktop_folder"]
    expected_category = app["start_menu_category"]

    try:
        desktop_matches = desktop_index.get(key, [])
        menu_matches = menu_index.get(key, [])

        # --- MISSING: not found anywhere (neither desktop shortcut nor menu entry) ---
        if not desktop_matches and not menu_matches:
            entry["result"] = "MISSING"
            entry["detail"] = (
                f".desktop for '{app['name']}' not found on desktop or in any "
                f"applications directory"
            )
            return entry

        reasons = []

        # --- Check 1: desktop shortcut in the correct folder (independent) ---
        if not desktop_matches:
            reasons.append(
                f"no desktop shortcut found; expected in folder '{expected_folder}'"
            )
        else:
            folders_found = {m["folder"] for m in desktop_matches if m["folder"]}
            if expected_folder not in folders_found:
                reasons.append(
                    f"desktop shortcut in folder(s) {sorted(folders_found) or 'root'}, "
                    f"expected '{expected_folder}'"
                )

        # --- Check 2: start menu entry with the correct category (independent) ---
        if not menu_matches:
            reasons.append(
                f"no start menu entry found in applications dirs; "
                f"expected category '{expected_category}'"
            )
        else:
            menu_categories = {c for m in menu_matches for c in m["categories"]}
            if expected_category not in menu_categories:
                reasons.append(
                    f"start menu Categories={sorted(menu_categories) or '[]'} "
                    f"missing expected '{expected_category}'"
                )

        if reasons:
            entry["result"] = "MISPLACED"
            entry["detail"] = "; ".join(reasons)
        else:
            entry["result"] = "PASS"
            entry["detail"] = (
                f"Desktop shortcut in '{expected_folder}' and start menu category "
                f"'{expected_category}' both present"
            )

    except Exception as e:
        entry["result"] = "MISPLACED"
        entry["detail"] = f"Error during presence check: {str(e)[:100]}"
    finally:
        entry["duration_ms"] = round((time.perf_counter() - start) * 1000, 2)

    return entry

