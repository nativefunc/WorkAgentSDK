---
name: release-notes
description: Write release notes from the commit history and suggest the next version number following semantic versioning. Use when the user asks for release notes, a changelog, or to decide a version number.
---

# Writing release notes

1. Sort the commits into three groups: new features, fixes, and other.
2. Rewrite each one as a single user-facing sentence, without internal module names.
3. Run `python3 scripts/next_version.py <current version> <has new features: yes/no> <has breaking changes: yes/no>` to get the next version number. If the current version is unknown, treat it as 1.0.0.
4. Output in the following format:

```
## <version>

### New features
- ……

### Fixes
- ……
```
