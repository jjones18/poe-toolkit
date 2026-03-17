---
description: Version management for POE Toolkit
globs: **/*
alwaysApply: true
---

# POE Toolkit Versioning

## Version Location

The app version is defined in a single place:

- **File:** `src/utils/__init__.py`
- **Variable:** `APP_VERSION`
- **Format:** Semantic versioning (MAJOR.MINOR.PATCH)

This version is displayed in the sidebar of the main UI (`src/ui/main_window.py`).

## Version Bump Rules

**Every commit that changes application behavior MUST include a version bump.**

- **PATCH** (e.g. 1.1.0 -> 1.1.1): Bug fixes, small tweaks, config changes, refactors
- **MINOR** (e.g. 1.1.0 -> 1.2.0): New features, new tools, significant enhancements
- **MAJOR** (e.g. 1.0.0 -> 2.0.0): Breaking changes, major rewrites

When committing changes:
1. Read the current version from `src/utils/__init__.py`
2. Bump the appropriate version component
3. Update `APP_VERSION` in `src/utils/__init__.py`
4. Include the version bump in the same commit as the changes

## What Does NOT Require a Version Bump

- Changes only to documentation (README, comments)
- Changes only to `.gitignore`, `.cursor/rules/`, or other tooling config
- Changes only to `dust_cache.json`, `config/config.json`, or other data files
