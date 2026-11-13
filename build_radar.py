#!/usr/bin/env python3
"""
Validate blips.json (written by the AI agent) against components.json and the previous
build, then produce radar.json in the Thoughtworks Build Your Own Radar format.

blips.json format:
    {
      "blips": [
        {"name": "Hibernate ORM", "quadrant": "Languages & Frameworks", "ring": "Adopt",
         "isNew": false, "reason": "...", "confidence": "medium",
         "components": ["pkg:maven/org.hibernate.orm/hibernate-core", "..."]}
      ],
      "excluded": [
        {"reason": "Scan artifact, not a technology", "components": ["application:gradle.lockfile"]}
      ]
    }

Optional blip key "previousName": the name this blip had in the previous build (rename).

Rules:
    - every id in components.json appears EXACTLY ONCE, in a blip or in "excluded"
    - ids that are not in components.json are rejected
    - blip names are unique; quadrant, ring and confidence come from fixed lists
    - isNew must agree with the previous build (blips.previous.json):
        * no previous build: every blip has isNew false (nothing to compare with)
        * name exists in the previous build: isNew false
        * renamed (previousName exists in the previous build): isNew false
        * otherwise: isNew true
    - keys other than those listed are rejected

radar.json description is only the sorted list of modules (component names) of the blip.

Exit code 0 when valid, 1 when there are errors.

Examples:
    python3 build_radar.py --check
    python3 build_radar.py --out radar.json --changes changes.md
"""
import argparse
import json
import os
import sys
from collections import Counter

QUADRANTS = ["Languages & Frameworks", "Platforms", "Tools", "Techniques"]
RINGS = ["Adopt", "Trial", "Assess", "Hold"]
CONFIDENCE = ["high", "medium", "low"]
BLIP_REQUIRED = {"name", "quadrant", "ring", "isNew", "reason", "confidence", "components"}
BLIP_OPTIONAL = {"previousName"}
EXCL_KEYS = {"reason", "components"}
MAX_REASON = 400
MAX_BLIPS_WARN = 40


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        sys.exit(f"{what} not found: {path}")
    except json.JSONDecodeError as e:
        sys.exit(f"{what} is not valid JSON ({path}): {e}")


def load_previous(path):
    if not os.path.exists(path):
        return {}
    data = read_json(path, "previous blips")
    blips = data.get("blips", []) if isinstance(data, dict) else []
    return {b["name"].strip().lower(): b for b in blips if isinstance(b, dict) and isinstance(b.get("name"), str)}


def check_components(entry, tag, known, assigned, errors):
    comps = entry.get("components")
    if not isinstance(comps, list) or not comps:
        errors.append(f"{tag}: components must be a non-empty list")
        return
    for cid in comps:
        if not isinstance(cid, str) or cid not in known:
            errors.append(f"{tag}: id not found in components.json: {cid!r}")
        elif cid in assigned:
            errors.append(f"{tag}: id already used in '{assigned[cid]}': {cid}")
        else:
            assigned[cid] = tag


def check_is_new(b, tag, prev, claimed, errors):
    is_new, prev_name = b["isNew"], b.get("previousName")
    if not isinstance(is_new, bool):
        errors.append(f"{tag}: isNew must be true or false")
        return
    key = b["name"].strip().lower() if isinstance(b["name"], str) else ""
    if not prev:
        if is_new:
            errors.append(f"{tag}: there is no previous build, so isNew must be false")
        if prev_name is not None:
            errors.append(f"{tag}: previousName given but there is no previous build")
        return
    if prev_name is not None:
        pk = str(prev_name).strip().lower()
        if key in prev:
            errors.append(f"{tag}: previousName is only for renamed blips, but this name exists in the previous build")
        elif pk not in prev:
            errors.append(f"{tag}: previousName '{prev_name}' not found in the previous build")
        elif pk in claimed:
            errors.append(f"{tag}: previousName '{prev_name}' already claimed by '{claimed[pk]}'")
        else:
            claimed[pk] = b["name"]
            if is_new:
                errors.append(f"{tag}: a renamed blip must have isNew false")
        return
    if key in prev and is_new:
        errors.append(f"{tag}: exists in the previous build, so isNew must be false")
    if key not in prev and not is_new:
        errors.append(f"{tag}: not in the previous build, so isNew must be true (or set previousName if renamed)")


def validate(data, known, prev):
    errors, assigned = [], {}
    if not isinstance(data, dict) or set(data) != {"blips", "excluded"}:
        return ['blips.json must be an object with exactly two keys: "blips" and "excluded"'], assigned
    if not isinstance(data["blips"], list) or not isinstance(data["excluded"], list):
        return ['"blips" and "excluded" must be arrays'], assigned

    names, claimed = set(), {}
    for i, b in enumerate(data["blips"], 1):
        tag = f"blip #{i}"
        if not isinstance(b, dict):
            errors.append(f"{tag}: must be an object")
            continue
        if isinstance(b.get("name"), str):
            tag = f"blip #{i} ({b['name']})"
        extra = set(b) - BLIP_REQUIRED - BLIP_OPTIONAL
        missing = BLIP_REQUIRED - set(b)
        if extra:
            errors.append(f"{tag}: unknown keys: {sorted(extra)}")
        if missing:
            errors.append(f"{tag}: missing required keys: {sorted(missing)}")
            continue
        name = b["name"]
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{tag}: empty name")
        elif name.strip().lower() in names:
            errors.append(f"{tag}: duplicate blip name")
        else:
            names.add(name.strip().lower())
        if b["quadrant"] not in QUADRANTS:
            errors.append(f"{tag}: invalid quadrant '{b['quadrant']}'")
        if b["ring"] not in RINGS:
            errors.append(f"{tag}: invalid ring '{b['ring']}'")
        if b["confidence"] not in CONFIDENCE:
            errors.append(f"{tag}: invalid confidence '{b['confidence']}'")
        reason = b["reason"]
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{tag}: empty reason")
        elif len(reason) > MAX_REASON:
            errors.append(f"{tag}: reason longer than {MAX_REASON} characters")
        check_is_new(b, tag, prev, claimed, errors)
        check_components(b, tag, known, assigned, errors)

    for i, e in enumerate(data["excluded"], 1):
        tag = f"excluded #{i}"
        if not isinstance(e, dict):
            errors.append(f"{tag}: must be an object")
            continue
        extra, missing = set(e) - EXCL_KEYS, EXCL_KEYS - set(e)
        if extra:
            errors.append(f"{tag}: unknown keys: {sorted(extra)}")
        if missing:
            errors.append(f"{tag}: missing required keys: {sorted(missing)}")
            continue
        if not isinstance(e["reason"], str) or not e["reason"].strip():
            errors.append(f"{tag}: empty reason")
        check_components(e, tag, known, assigned, errors)

    unassigned = sorted(set(known) - set(assigned))
    if unassigned:
        shown = ", ".join(unassigned[:30])
        errors.append(f"{len(unassigned)} components are in neither a blip nor excluded: "
                      f"{shown}{' ...' if len(unassigned) > 30 else ''}")
    return errors, assigned


def modules(blip, known):
    return sorted({known[c]["name"] for c in blip["components"]}, key=str.lower)


def short(cid, known):
    return known[cid]["name"] if cid in known else cid.rsplit("/", 1)[-1]


def diff_report(blips, prev, known):
    cur = {b["name"].strip().lower(): b for b in blips}
    renamed = {str(b["previousName"]).strip().lower(): b["name"] for b in blips if b.get("previousName")}
    lines = []
    if not prev:
        return ["No previous build: this build is the baseline, all blips are marked as not new."]

    new = [b["name"] for b in blips if b["isNew"]]
    removed = [p["name"] for k, p in prev.items() if k not in cur and k not in renamed]
    lines.append(f"New blips ({len(new)}): {', '.join(sorted(new, key=str.lower)) or 'none'}")
    lines.append(f"Removed blips ({len(removed)}): {', '.join(sorted(removed, key=str.lower)) or 'none'}")
    if renamed:
        lines.append("Renamed: " + ", ".join(f"{prev[k]['name']} -> {v}" for k, v in sorted(renamed.items())))

    moves = []
    for b in blips:
        old = prev.get(b["name"].strip().lower()) or prev.get(str(b.get("previousName") or "").strip().lower())
        if not old:
            continue
        if old.get("ring") != b["ring"]:
            moves.append(f"{b['name']}: ring {old.get('ring')} -> {b['ring']}")
        if old.get("quadrant") != b["quadrant"]:
            moves.append(f"{b['name']}: quadrant {old.get('quadrant')} -> {b['quadrant']}")
    lines.append(f"Ring and quadrant changes ({len(moves)}): {'; '.join(moves) or 'none'}")

    mod = []
    for b in blips:
        old = prev.get(b["name"].strip().lower()) or prev.get(str(b.get("previousName") or "").strip().lower())
        if not old or not isinstance(old.get("components"), list):
            continue
        added = sorted(set(b["components"]) - set(old["components"]))
        gone = sorted(set(old["components"]) - set(b["components"]))
        if added or gone:
            part = []
            if added:
                part.append("+" + ", ".join(short(c, known) for c in added[:8]) + (" ..." if len(added) > 8 else ""))
            if gone:
                part.append("-" + ", ".join(short(c, known) for c in gone[:8]) + (" ..." if len(gone) > 8 else ""))
            mod.append(f"{b['name']}: {' '.join(part)}")
    lines.append(f"Module changes ({len(mod)}):")
    lines.extend(f"  - {m}" for m in mod)
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--blips", default="blips.json")
    ap.add_argument("--components", default="dump/components.json")
    ap.add_argument("--previous", default="blips.previous.json")
    ap.add_argument("--out", default="radar.json")
    ap.add_argument("--changes", default="changes.md", help="Where to write the change report")
    ap.add_argument("--check", action="store_true", help="Validate only, do not write any file")
    args = ap.parse_args()

    data = read_json(args.blips, "blips.json")
    rows = read_json(args.components, "components.json")
    known = {r["id"]: r for r in rows}
    prev = load_previous(args.previous)

    errors, _ = validate(data, known, prev)
    if errors:
        print(f"{len(errors)} errors in {args.blips}:", file=sys.stderr)
        for e in errors[:50]:
            print(f"  - {e}", file=sys.stderr)
        if len(errors) > 50:
            print(f"  ... and {len(errors) - 50} more", file=sys.stderr)
        sys.exit(1)

    blips = data["blips"]
    excluded = sum(len(e["components"]) for e in data["excluded"])
    print(f"Valid: {len(blips)} blips from {len(known)} unique components ({excluded} excluded)", file=sys.stderr)
    print("By quadrant: " + ", ".join(f"{k} {v}" for k, v in Counter(b["quadrant"] for b in blips).most_common()),
          file=sys.stderr)
    print("By ring: " + ", ".join(f"{k} {v}" for k, v in Counter(b["ring"] for b in blips).most_common()),
          file=sys.stderr)
    low = [b["name"] for b in blips if b["confidence"] == "low"]
    if low:
        print(f"Low confidence ({len(low)}): {', '.join(low)}", file=sys.stderr)
    if len(blips) > MAX_BLIPS_WARN:
        print(f"WARNING: {len(blips)} blips, the radar is hard to read above {MAX_BLIPS_WARN}.", file=sys.stderr)

    report = diff_report(blips, prev, known)
    print("\n".join(report), file=sys.stderr)

    if args.check:
        return

    radar = [{"name": b["name"].strip(), "ring": b["ring"], "quadrant": b["quadrant"],
              "isNew": "TRUE" if b["isNew"] else "FALSE", "description": ", ".join(modules(b, known))}
             for b in sorted(blips, key=lambda x: x["name"].lower())]
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(radar, f, indent=2, ensure_ascii=False)
    with open(args.changes, "w", encoding="utf-8") as f:
        f.write("# Radar changes since the last build\n\n" + "\n".join(f"- {l}" if not l.startswith("  ") else l
                                                                         for l in report) + "\n")
    print(f"Written: {len(radar)} blips -> {args.out}, change report -> {args.changes}", file=sys.stderr)


if __name__ == "__main__":
    main()
