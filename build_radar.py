#!/usr/bin/env python3
"""
Validasi blips.json hasil AI agent terhadap components.json, lalu hasilkan radar.json
(format Thoughtworks Build Your Own Radar).

Format blips.json:
    {
      "blips": [
        {"name": "Spring Boot", "quadrant": "Languages & Frameworks", "ring": "Adopt",
         "alasan": "...", "yakin": "sedang",
         "components": ["pkg:maven/org.springframework.boot/spring-boot", "..."]}
      ],
      "dikecualikan": [
        {"alasan": "Paket OS dari base image", "components": ["pkg:deb/ubuntu/adduser", "..."]}
      ]
    }

Aturan:
    - setiap id di components.json harus muncul TEPAT SATU KALI, di sebuah blip atau di dikecualikan
    - id yang tidak ada di components.json ditolak
    - nama blip unik, quadrant dan ring dari daftar yang diizinkan
    - kunci selain yang tercantum ditolak

Deskripsi blip dirangkai dari data (project, versi, modul) ditambah alasan dari agent,
sehingga angka dan nama di deskripsi tidak berasal dari tebakan AI.

Exit code 0 bila valid, 1 bila ada kesalahan.

Contoh:
    python3 build_radar.py --check
    python3 build_radar.py --out radar.json
"""
import argparse
import json
import sys
from collections import Counter

QUADRANTS = ["Languages & Frameworks", "Platforms", "Tools", "Techniques"]
RINGS = ["Adopt", "Trial", "Assess", "Hold"]
CONFIDENCE = ["tinggi", "sedang", "rendah"]
BLIP_KEYS = {"name", "quadrant", "ring", "alasan", "yakin", "components"}
EXCL_KEYS = {"alasan", "components"}
MAX_ALASAN = 400
MAX_BLIPS_WARN = 40


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        sys.exit(f"{what} tidak ditemukan: {path}")
    except json.JSONDecodeError as e:
        sys.exit(f"{what} bukan JSON valid ({path}): {e}")


def check_components(entry, tag, known, assigned, errors):
    comps = entry.get("components")
    if not isinstance(comps, list) or not comps:
        errors.append(f"{tag}: components harus berupa daftar tidak kosong")
        return []
    ok = []
    for cid in comps:
        if not isinstance(cid, str) or cid not in known:
            errors.append(f"{tag}: id tidak ada di components.json: {cid!r}")
        elif cid in assigned:
            errors.append(f"{tag}: id sudah dipakai di '{assigned[cid]}': {cid}")
        else:
            assigned[cid] = tag
            ok.append(cid)
    return ok


def validate(data, known):
    errors, assigned = [], {}
    if not isinstance(data, dict) or set(data) != {"blips", "dikecualikan"}:
        return ["blips.json harus berupa objek dengan tepat dua kunci: blips dan dikecualikan"], assigned
    if not isinstance(data["blips"], list) or not isinstance(data["dikecualikan"], list):
        return ["blips dan dikecualikan harus berupa array"], assigned

    names = set()
    for i, b in enumerate(data["blips"], 1):
        tag = f"blip #{i}"
        if not isinstance(b, dict):
            errors.append(f"{tag}: harus berupa objek")
            continue
        if isinstance(b.get("name"), str):
            tag = f"blip #{i} ({b['name']})"
        extra, missing = set(b) - BLIP_KEYS, BLIP_KEYS - set(b)
        if extra:
            errors.append(f"{tag}: kunci tidak dikenal: {sorted(extra)}")
        if missing:
            errors.append(f"{tag}: kunci wajib hilang: {sorted(missing)}")
            continue
        name = b["name"]
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{tag}: name kosong")
        elif name.strip().lower() in names:
            errors.append(f"{tag}: nama blip kembar")
        else:
            names.add(name.strip().lower())
        if b["quadrant"] not in QUADRANTS:
            errors.append(f"{tag}: quadrant '{b['quadrant']}' tidak valid")
        if b["ring"] not in RINGS:
            errors.append(f"{tag}: ring '{b['ring']}' tidak valid")
        if b["yakin"] not in CONFIDENCE:
            errors.append(f"{tag}: yakin '{b['yakin']}' tidak valid")
        alasan = b["alasan"]
        if not isinstance(alasan, str) or not alasan.strip():
            errors.append(f"{tag}: alasan kosong")
        elif len(alasan) > MAX_ALASAN:
            errors.append(f"{tag}: alasan lebih dari {MAX_ALASAN} karakter")
        check_components(b, tag, known, assigned, errors)

    for i, e in enumerate(data["dikecualikan"], 1):
        tag = f"dikecualikan #{i}"
        if not isinstance(e, dict):
            errors.append(f"{tag}: harus berupa objek")
            continue
        extra, missing = set(e) - EXCL_KEYS, EXCL_KEYS - set(e)
        if extra:
            errors.append(f"{tag}: kunci tidak dikenal: {sorted(extra)}")
        if missing:
            errors.append(f"{tag}: kunci wajib hilang: {sorted(missing)}")
            continue
        if not isinstance(e["alasan"], str) or not e["alasan"].strip():
            errors.append(f"{tag}: alasan kosong")
        check_components(e, tag, known, assigned, errors)

    unassigned = sorted(set(known) - set(assigned))
    if unassigned:
        shown = ", ".join(unassigned[:30])
        errors.append(f"{len(unassigned)} component belum dimasukkan ke blip maupun dikecualikan: "
                      f"{shown}{' ...' if len(unassigned) > 30 else ''}")
    return errors, assigned


def describe(blip, known):
    rows = [known[c] for c in blip["components"]]
    projects = sorted({p for r in rows for p in r.get("projects", [])})
    versions = sorted({v for r in rows for v in r.get("versions", [])})
    names = sorted({r["name"] for r in rows})

    text = f"Dipakai di {len(projects)} project"
    text += f" ({', '.join(projects)})." if len(projects) <= 6 else "."
    if 0 < len(versions) <= 3:
        text += f" Versi: {', '.join(versions)}."
    if len(names) > 1:
        text += f" Modul: {', '.join(names[:8])}{f' dan {len(names) - 8} lainnya' if len(names) > 8 else ''}."
    return f"{text} {blip['alasan'].strip()}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--blips", default="blips.json")
    ap.add_argument("--components", default="dump/components.json")
    ap.add_argument("--out", default="radar.json")
    ap.add_argument("--check", action="store_true", help="Hanya validasi, jangan tulis radar.json")
    args = ap.parse_args()

    data = read_json(args.blips, "blips.json")
    rows = read_json(args.components, "components.json")
    known = {r["id"]: r for r in rows}

    errors, assigned = validate(data, known)
    if errors:
        print(f"{len(errors)} kesalahan pada {args.blips}:", file=sys.stderr)
        for e in errors[:50]:
            print(f"  - {e}", file=sys.stderr)
        if len(errors) > 50:
            print(f"  ... dan {len(errors) - 50} lainnya", file=sys.stderr)
        sys.exit(1)

    blips = data["blips"]
    excluded = sum(len(e["components"]) for e in data["dikecualikan"])
    print(f"Valid: {len(blips)} blip dari {len(known)} component unik ({excluded} dikecualikan)", file=sys.stderr)
    print("Per quadrant: " + ", ".join(f"{k} {v}" for k, v in Counter(b["quadrant"] for b in blips).most_common()),
          file=sys.stderr)
    print("Per ring: " + ", ".join(f"{k} {v}" for k, v in Counter(b["ring"] for b in blips).most_common()),
          file=sys.stderr)
    low = [b["name"] for b in blips if b["yakin"] == "rendah"]
    if low:
        print(f"Keyakinan rendah ({len(low)}): {', '.join(low)}", file=sys.stderr)
    if len(blips) > MAX_BLIPS_WARN:
        print(f"PERINGATAN: {len(blips)} blip, radar sulit dibaca bila lebih dari {MAX_BLIPS_WARN}.", file=sys.stderr)

    if args.check:
        return

    radar = [{"name": b["name"].strip(), "ring": b["ring"], "quadrant": b["quadrant"],
              "isNew": "FALSE", "description": describe(b, known)}
             for b in sorted(blips, key=lambda x: x["name"].lower())]
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(radar, f, indent=2, ensure_ascii=False)
    print(f"Ditulis: {len(radar)} blip -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
