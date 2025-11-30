# PoE API Limitations

This document tracks known limitations of the Path of Exile API that affect this tool's functionality.

## Unique Collection Stash Tab (UniqueStash)

**Date Discovered:** 2024-11-30

**Issue:** The PoE stash API (`/character-window/get-stash-items`) does **NOT return items** from Unique Collection stash tabs.

**Technical Details:**
- When fetching a UniqueStash tab, the API returns:
  - `items: []` (empty array)
  - `uniqueLayout: {}` (empty object)
- The tab metadata correctly identifies `type: "UniqueStash"`
- Opening the tab in-game does NOT sync the data to the API
- This appears to be a fundamental API limitation, not a sync issue

**Investigation Log:**
1. Initial symptom: Scanning Unique Collection tab returned 0 items
2. Debug showed API response has `items` key but empty array
3. Checked if tab needs to be "loaded" in-game first - no effect
4. Saved raw API response - confirmed `uniqueLayout` and `items` both empty
5. Conclusion: UniqueStash tabs are not supported by legacy stash API

**Workaround:** 
Users must move unique items to regular/quad stash tabs before scanning.

**Code Reference:**
- `scanner.py`: `UNSUPPORTED_TAB_TYPES` set contains `'UniqueStash'`
- Scanner automatically skips these tabs with a log message

---

## Future Notes

If GGG updates the API or provides an alternative endpoint for special stash tabs, 
the `UNSUPPORTED_TAB_TYPES` set in `scanner.py` can be updated to re-enable support.

The OAuth-based API may have different behavior - worth investigating if OAuth 
authentication is implemented in the future.

