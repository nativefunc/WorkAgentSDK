import sys

current, has_feature, breaking = sys.argv[1], sys.argv[2] == "yes", sys.argv[3] == "yes"
major, minor, patch = (int(part) for part in current.split("."))

if breaking:
    print(f"{major + 1}.0.0")
elif has_feature:
    print(f"{major}.{minor + 1}.0")
else:
    print(f"{major}.{minor}.{patch + 1}")
