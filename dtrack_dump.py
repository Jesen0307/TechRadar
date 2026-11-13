#!/usr/bin/env python3
"""
Fetch ALL components from Dependency-Track, without filtering or grouping.

Output folder (default: dump/):
    projects.json                 list of projects
    components/<project>.json     components per project, exactly as returned by the API
    all-components.json           combined: {"name:version (uuid)": [component, ...]}
    components.json               compact summary for the AI agent: one line per unique component,
                                  without OS packages (deb, apk, rpm) unless --include-os is used
    metrics/<project>.json        (optional --with-metrics) current metrics per project
    findings/<project>.json       (optional --with-findings) vulnerabilities per project

Every components.json line has an "id" (purl without version), for example:
    pkg:maven/org.springframework/spring-core
Components without a purl use "<classifier>:<name>", for example: operating_system:ubuntu

Python 3.8+ standard library only.

Example:
    export DT_KEY="odt_xxxxxxxx"
    python3 dtrack_dump.py --url http://localhost:8082
"""
import argparse
import datetime
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


def api_get(base, path, key, params=None, ctx=None):
    url = f"{base.rstrip('/')}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-Api-Key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
            total = resp.headers.get("X-Total-Count")
            body = resp.read()
            return (json.loads(body) if body else None), (int(total) if total else None)
    except urllib.error.HTTPError as e:
        return {"__error__": f"HTTP {e.code}", "url": url}, None
    except urllib.error.URLError as e:
        sys.exit(f"Cannot connect to {url}: {e.reason}\n  Check --url and the API server port.")


def fetch_all(base, path, key, ctx, page_size=100):
    items, page = [], 1
    while True:
        data, total = api_get(base, path, key, {"pageSize": page_size, "pageNumber": page}, ctx)
        if isinstance(data, dict) and "__error__" in data:
            sys.exit(f"{data['__error__']} on {data['url']}\n"
                     f"  401/403 -> check the API key and its permission (VIEW_PORTFOLIO)")
        if not data:
            break
        items.extend(data)
        if (total is not None and len(items) >= total) or len(data) < page_size:
            break
        page += 1
    return items


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def safe_name(p):
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{p['name']}_{p.get('version') or 'noversion'}")
    return f"{base}_{p['uuid'][:8]}"


def component_id(c):
    purl = c.get("purl") or ""
    if purl.startswith("pkg:"):
        base = purl.split("#", 1)[0].split("?", 1)[0]
        if "@" in base:
            base = base.rsplit("@", 1)[0]
        return base
    return f"{(c.get('classifier') or 'unknown').lower()}:{c.get('name')}"


def component_type(c):
    purl = c.get("purl") or ""
    if purl.startswith("pkg:"):
        return purl[4:].split("/", 1)[0].lower()
    return (c.get("classifier") or "unknown").lower()


def month(ms):
    if not ms:
        return None
    dt = datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m")


OS_TYPES = {"deb", "apk", "rpm"}


def add_compact(agg, comps, project_label, skip_types, dropped):
    for c in comps:
        cid = component_id(c)
        ctype = component_type(c)
        if ctype in skip_types:
            dropped.setdefault(ctype, set()).add(cid)
            continue
        a = agg.get(cid)
        if a is None:
            a = agg[cid] = {"name": c.get("name"), "group": c.get("group") or "",
                            "type": component_type(c), "classifier": c.get("classifier") or "LIBRARY",
                            "versions": set(), "projects": set(), "latest": set(), "pub": 0,
                            "critical": 0, "high": 0, "kev": 0, "policy_fail": 0, "licenses": set()}
        if c.get("version"):
            a["versions"].add(c["version"])
        a["projects"].add(project_label)
        meta = c.get("repositoryMeta") or {}
        if meta.get("latestVersion"):
            a["latest"].add(meta["latestVersion"])
        a["pub"] = max(a["pub"], meta.get("latestVersionPublishedAt") or 0)
        m = c.get("metrics") or {}
        a["critical"] = max(a["critical"], m.get("critical") or 0)
        a["high"] = max(a["high"], m.get("high") or 0)
        a["kev"] = max(a["kev"], m.get("kev") or 0)
        a["policy_fail"] = max(a["policy_fail"], m.get("policyViolationsFail") or 0)
        lic = c.get("resolvedLicense") or {}
        lic_id = lic.get("licenseId") or lic.get("name")
        if lic_id:
            a["licenses"].add(lic_id)


def compact_rows(agg):
    rows = []
    for cid in sorted(agg):
        a = agg[cid]
        row = {"id": cid, "name": a["name"]}
        if a["group"]:
            row["group"] = a["group"]
        row["type"] = a["type"]
        if a["classifier"] != "LIBRARY":
            row["classifier"] = a["classifier"]
        row["versions"] = sorted(a["versions"])
        row["projects"] = sorted(a["projects"])
        if a["latest"]:
            row["latestVersions"] = sorted(a["latest"])
        if a["pub"]:
            row["latestRelease"] = month(a["pub"])
        if a["critical"] or a["high"] or a["kev"] or a["policy_fail"]:
            row["critical"], row["high"] = a["critical"], a["high"]
            row["kev"], row["policyFail"] = a["kev"], a["policy_fail"]
        if a["licenses"]:
            row["licenses"] = sorted(a["licenses"])
        rows.append(row)
    return rows


def write_compact(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n]\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("DT_URL", "http://localhost:8082"),
                    help="Base URL API server (env: DT_URL, default http://localhost:8082)")
    ap.add_argument("--out", default="dump", help="Output folder (default: dump)")
    ap.add_argument("--tag", help="Only projects with this tag")
    ap.add_argument("--include-inactive", action="store_true", help="Include inactive projects")
    ap.add_argument("--include-os", action="store_true",
                    help="Keep OS packages (deb, apk, rpm) in components.json (default: dropped)")
    ap.add_argument("--with-metrics", action="store_true", help="Also fetch current metrics per project")
    ap.add_argument("--with-findings", action="store_true", help="Also fetch vulnerabilities per project")
    ap.add_argument("--insecure", action="store_true", help="Skip TLS certificate validation")
    args = ap.parse_args()
    if not re.match(r"^https?://", args.url or ""):
        sys.exit(f"invalid --url: '{args.url}'. Use a full address, for example: http://localhost:8082")

    key = os.environ.get("DT_KEY")
    if not key:
        sys.exit('Env DT_KEY is not set. Run: export DT_KEY="<api key>"')

    ctx = None
    if args.insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    projects = fetch_all(args.url, "/api/v1/project", key, ctx)
    if not args.include_inactive:
        projects = [p for p in projects if p.get("active", True)]
    if args.tag:
        projects = [p for p in projects
                    if args.tag.lower() in [t.get("name", "").lower() for t in p.get("tags", [])]]
    save(os.path.join(args.out, "projects.json"), projects)
    print(f"{len(projects)} project -> {args.out}/projects.json", file=sys.stderr)

    combined, agg, dropped = {}, {}, {}
    skip_types = set() if args.include_os else OS_TYPES
    for p in projects:
        fname = safe_name(p)
        short = f"{p['name']}:{p.get('version') or '-'}"
        label = f"{short} ({p['uuid']})"

        comps = fetch_all(args.url, f"/api/v1/component/project/{p['uuid']}", key, ctx)
        save(os.path.join(args.out, "components", fname + ".json"), comps)
        combined[label] = comps
        add_compact(agg, comps, short, skip_types, dropped)
        print(f"  {label}: {len(comps)} component", file=sys.stderr)

        if args.with_metrics:
            data, _ = api_get(args.url, f"/api/v1/metrics/project/{p['uuid']}/current", key, None, ctx)
            save(os.path.join(args.out, "metrics", fname + ".json"), data)
        if args.with_findings:
            data, _ = api_get(args.url, f"/api/v1/finding/project/{p['uuid']}", key, None, ctx)
            save(os.path.join(args.out, "findings", fname + ".json"), data)

    save(os.path.join(args.out, "all-components.json"), combined)
    rows = compact_rows(agg)
    write_compact(os.path.join(args.out, "components.json"), rows)
    total = sum(len(v) for v in combined.values())
    print(f"Done: {total} components from {len(combined)} projects -> {args.out}/", file=sys.stderr)
    print(f"Summary for the agent: {len(rows)} unique components -> {args.out}/components.json", file=sys.stderr)
    if dropped:
        parts = ", ".join(f"{t} {len(ids)}" for t, ids in sorted(dropped.items()))
        print(f"OS packages dropped from components.json (unique): {parts}", file=sys.stderr)


if __name__ == "__main__":
    main()
