#!/usr/bin/env python3
"""
Harvest __generated__form-metadata-public.json files from a Dataverse
installation and sync them into a Typesense collection.

Nightly-safe / incremental:
  * one document per dataset (id = Dataverse dataset_id)
  * a document is only re-fetched + upserted when the file checksum changed
  * documents whose dataset no longer shows up in the harvest are deleted
  * safety guard: nothing is deleted if the harvest looks broken/empty

Usage:
  python harvest.py            # incremental sync
  python harvest.py --full     # ignore checksums, re-fetch everything
  python harvest.py --recreate # drop + recreate the collection (schema change)
  python harvest.py --dry-run  # show what would happen
"""
import argparse
import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import requests
import typesense

BASE = os.environ.get("DATAVERSE_BASE", "https://ssh.datastations.nl").rstrip("/")
FILE_NAME = "__generated__form-metadata-public.json"
PER_PAGE = 1000
COLLECTION = "datasets"
FETCH_WORKERS = 8

log = logging.getLogger("harvest")

SCHEMA = {
    "name": COLLECTION,
    "enable_nested_fields": False,
    "fields": [
        # --- from the Dataverse search result
        {"name": "doi", "type": "string", "facet": False},
        {"name": "dataset_name", "type": "string"},
        {"name": "dataset_url", "type": "string", "index": False, "optional": True},
        {"name": "file_id", "type": "string", "index": False},
        {"name": "file_checksum", "type": "string", "index": False},
        {"name": "published_at", "type": "int64", "sort": True},
        {"name": "published_year", "type": "int32", "facet": True},
        # --- from the form-metadata file
        {"name": "title", "type": "string"},
        {"name": "description", "type": "string", "optional": True},
        {"name": "interviewee", "type": "string", "facet": True, "optional": True},
        {"name": "interviewer", "type": "string[]", "facet": True, "optional": True},
        {"name": "interviewer_affiliation", "type": "string[]", "facet": True, "optional": True},
        {"name": "authors", "type": "string[]", "facet": True, "optional": True},
        {"name": "interview_location", "type": "string[]", "facet": True, "optional": True},
        {"name": "interview_date", "type": "int64", "sort": True, "optional": True},
        {"name": "interview_year", "type": "int32", "facet": True, "optional": True},
        {"name": "subject_keywords", "type": "string[]", "facet": True, "optional": True},
        {"name": "subject_locations", "type": "string[]", "facet": True, "optional": True},
        {"name": "subject_year_start", "type": "int32", "facet": True, "optional": True},
        {"name": "subject_year_end", "type": "int32", "facet": True, "optional": True},
        {"name": "audience", "type": "string[]", "facet": True, "optional": True},
        {"name": "collections", "type": "string[]", "facet": True, "optional": True},
        {"name": "language_interview", "type": "string[]", "facet": True, "optional": True},
        {"name": "language_metadata", "type": "string", "facet": True, "optional": True},
        {"name": "publisher", "type": "string", "facet": True, "optional": True},
        {"name": "rightsholder", "type": "string", "facet": True, "optional": True},
        {"name": "licence", "type": "string", "facet": True, "optional": True},
        {"name": "contains_personal_data", "type": "bool", "facet": True, "optional": True},
        {"name": "transcript_machine", "type": "string", "facet": True, "optional": True},
        {"name": "recording_format", "type": "string[]", "facet": True, "optional": True},
        {"name": "recording_equipment", "type": "string", "facet": True, "optional": True},
        {"name": "grants", "type": "string[]", "facet": True, "optional": True},
        {"name": "contact_email", "type": "string", "index": False, "optional": True},
        # Raw metadata kept for display, not indexed
        {"name": "raw", "type": "string", "index": False, "optional": True},
    ],
    "default_sorting_field": "published_at",
}


# ----------------------------------------------------------------- helpers
def client():
    return typesense.Client({
        "nodes": [{
            "host": os.environ.get("TYPESENSE_HOST", "localhost"),
            "port": os.environ.get("TYPESENSE_PORT", "8108"),
            "protocol": os.environ.get("TYPESENSE_PROTOCOL", "http"),
        }],
        "api_key": os.environ["TYPESENSE_API_KEY"],
        "connection_timeout_seconds": 30,
    })


def ts(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def labels(v):
    """Turn a list of {label,value} dicts (or plain strings) into list[str]."""
    out = []
    if isinstance(v, (str, dict)):
        v = [v]
    for x in v or []:
        if isinstance(x, dict):
            s = x.get("label") or x.get("value")
        else:
            s = x
        if s:
            out.append(str(s).strip())
    return out


def label(v):
    if isinstance(v, dict):
        return str(v.get("label") or v.get("value") or "").strip()
    return str(v or "").strip()


def text_of(v):
    """Scalar text from a string, a {label,value} dict, or a list of those."""
    if isinstance(v, (list, tuple)):
        return ", ".join(labels(v))
    return label(v)


def parse_dmy_range(s):
    """'11-01-2025 11-01-2025' (DD-MM-YYYY) -> unix ts of the start date."""
    m = re.search(r"(\d{1,2})-(\d{1,2})-(\d{4})", s or "")
    if not m:
        return None
    d, mo, y = map(int, m.groups())
    try:
        return int(datetime(y, mo, d, tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


def parse_year_range(s):
    ys = [int(x) for x in re.findall(r"\b(\d{4})\b", s or "")]
    if not ys:
        return None, None
    return min(ys), max(ys)


def clean(d):
    """Drop empty values so optional fields stay absent."""
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


# ------------------------------------------------------------ harvesting
def harvest_file_list(session):
    items, start = [], 0
    while True:
        r = session.get(f"{BASE}/api/search", params={
            "q": "*",
            "fq": f'fileName:"{FILE_NAME}"',
            "per_page": PER_PAGE,
            "start": start,
        }, timeout=60)
        r.raise_for_status()
        data = r.json()["data"]
        items.extend(data["items"])
        total = data["total_count"]
        log.info("search: got %d/%d", len(items), total)
        if not data["items"] or len(items) >= total:
            break
        start = len(items)
    return items


def _escape_stray_quotes(text):
    """
    Repair strings containing unescaped double quotes, e.g.
        "extraContent": "Add "Shi Kin Tan" as custom value"
    A quote inside a string only counts as the closing quote if the next
    non-whitespace character is one of  , } ] :  (or end of input).
    Anything else is treated as part of the text and escaped.
    """
    out, in_str, i, n = [], False, 0, len(text)
    while i < n:
        ch = text[i]
        if in_str and ch == "\\" and i + 1 < n:
            out.append(text[i:i + 2])
            i += 2
            continue
        if ch == '"':
            if not in_str:
                in_str = True
                out.append(ch)
            else:
                j = i + 1
                while j < n and text[j] in " \t\r\n":
                    j += 1
                if j >= n or text[j] in ",}]:":
                    in_str = False
                    out.append(ch)
                else:
                    out.append('\\"')
        else:
            out.append(ch)
        i += 1
    return "".join(out)


_EXTRA_CONTENT = re.compile(r'("extraContent"\s*:\s*")Add "(.*?)" as custom value"', re.S)


def _fix_extra_content(text):
    """The form generator writes  "Add "<name>" as custom value"  unescaped."""
    return _EXTRA_CONTENT.sub(
        lambda m: m.group(1) + 'Add \\"' + m.group(2).replace('"', '\\"') + '\\" as custom value"',
        text)


def _form_root(meta):
    """
    Return the dict that holds citation/coverage/rights/... Files come in two
    shapes: the form object itself ({"data": {...}, "citation": {...}, ...}),
    or wrapped one level deeper ({"data": {"data": ..., "citation": ...}}).
    """
    inner = meta.get("data")
    if isinstance(inner, dict) and "citation" in inner and "citation" not in meta:
        return inner
    return meta


_FILE_META = re.compile(r',?\s*"file-metadata"\s*:')
_KEY_AHEAD = re.compile(r'\s*"[^"\n]*"\s*:')


def _cut_file_metadata(text):
    """The trailing "file-metadata" section is not needed and is often broken."""
    m = _FILE_META.search(text)
    return text[:m.start()] if m else text


def _open_stack(text, pos):
    """Containers ('{' / '[') still open at text[pos], string-aware."""
    stack, in_str, i = [], False, 0
    while i < pos:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "{[":
            stack.append(c)
        elif c in "}]" and stack:
            stack.pop()
        i += 1
    return stack


def _repair_structure(text, e):
    """
    One repair step for template-generated JSON bugs, driven by the decoder
    error. Returns new text, or None if this error is not one we know.
      * trailing comma before } or ]            ->  drop the comma
      * list that was never closed ("key": [ <newline> "next_key": ...)
                                                ->  insert ],
      * missing comma between members           ->  insert ,
      * input ends inside open containers       ->  append the closers
    """
    pos = e.pos
    if e.msg.startswith("Illegal trailing comma"):   # Python 3.13+: pos is the comma
        return text[:pos] + text[pos + 1:]
    head, rest = text[:pos], text[pos:]
    stripped = rest.lstrip()

    m = re.search(r",\s*$", head)
    if m and stripped[:1] in ("}", "]"):
        s = m.start()
        return head[:s] + head[s + 1:] + rest

    stack = _open_stack(text, pos)

    if not stripped:
        if not stack:
            return None
        closers = "".join("}" if c == "{" else "]" for c in reversed(stack))
        return head.rstrip() + closers

    if e.msg.startswith("Expecting ',' delimiter"):
        # decoder read  "next_key"  as a list element and stopped at the ':'
        if stripped[:1] == ":" and stack and stack[-1] == "[":
            h = head.rstrip()
            if h.endswith('"'):
                j = len(h) - 2
                while j >= 0 and not (h[j] == '"' and (j == 0 or h[j - 1] != "\\")):
                    j -= 1
                if j >= 0:
                    return h[:j] + "]," + h[j:] + head[len(h):] + rest
        if _KEY_AHEAD.match(rest):
            if stack and stack[-1] == "[":
                return head + "]" + rest
            return head + "," + rest
    return None


def parse_lenient(text, label_=""):
    """
    Parse JSON that may be slightly broken. Tolerates:
      * raw control characters (newlines/tabs) inside strings
      * unescaped double quotes inside strings
      * trailing garbage after the first complete JSON value
    """
    dec = json.JSONDecoder(strict=False)
    text = text.lstrip("﻿ \t\r\n")
    text = _cut_file_metadata(text)
    notes = []
    try:
        obj, end = dec.raw_decode(text)
    except json.JSONDecodeError:
        text = _escape_stray_quotes(_fix_extra_content(text))
        notes.append("quotes")
        for _ in range(50):
            try:
                obj, end = dec.raw_decode(text)
                break
            except json.JSONDecodeError as e:
                fixed = _repair_structure(text, e)
                if fixed is None:
                    lo = max(0, e.pos - 100)
                    raise ValueError(
                        f"{e.msg} at char {e.pos}; near: {text[lo:e.pos + 100]!r}") from None
                text = fixed
                notes.append("structure")
        else:
            raise ValueError("gave up after 50 structural repairs")
    tail = text[end:].strip()
    if tail.strip("} \t\r\n,"):
        log.warning("%s: ignoring %d chars of trailing data", label_, len(tail))
    if notes:
        log.warning("%s: metadata file was not valid JSON; repaired (%s)",
                    label_, ", ".join(dict.fromkeys(notes)))
    return obj


def fetch_metadata(session, item):
    r = session.get(item["url"], timeout=60)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")
    return parse_lenient(text, item["dataset_persistent_id"])


def build_doc(item, meta):
    m = _form_root(meta)
    data = m.get("data", {})
    cit = m.get("citation", {})
    cov = m.get("coverage", {})
    rel = m.get("relations", {})
    adm = m.get("administrative", {})
    rights = m.get("rights", {})

    ie = data.get("ohs", {}).get("interviewee", {})
    interviewee = " ".join(filter(None, [ie.get("interviewee_first_name"),
                                         ie.get("interviewee_last_name")]))
    rec = data.get("recorded_by", []) or []
    interviewer = [" ".join(filter(None, [r.get("recorded_by_first_name"),
                                          r.get("recorded_by_last_name")])) for r in rec]
    interviewer_aff = [r.get("recorded_by_affiliation") for r in rec]

    idt = (data.get("interview_date_time") or [{}])[0].get("interview_date_time_range")
    interview_ts = parse_dmy_range(idt)
    interview_year = (datetime.fromtimestamp(interview_ts, timezone.utc).year
                      if interview_ts else None)

    sdt = (cov.get("subject_date_time") or [{}])[0].get("subject_date_time_range")
    y0, y1 = parse_year_range(sdt)

    published = ts(item["published_at"])
    pd = rights.get("personal_data")
    personal = None if pd is None else str(pd).endswith("true")

    grants = [" ".join(filter(None, [g.get("grant_agency"), g.get("grant_number")]))
              for g in cit.get("grant", []) or []]

    doc = {
        "id": str(item["dataset_id"]),
        "doi": item["dataset_persistent_id"].replace("doi:", ""),
        "dataset_name": item["dataset_name"],
        "dataset_url": f"https://doi.org/{item['dataset_persistent_id'].replace('doi:', '')}",
        "file_id": str(item["file_id"]),
        "file_checksum": item["checksum"]["value"],
        "published_at": published,
        "published_year": datetime.fromtimestamp(published, timezone.utc).year,
        "title": cit.get("title") or item["dataset_name"],
        "description": cit.get("description"),
        "interviewee": interviewee,
        "interviewer": [x for x in interviewer if x],
        "interviewer_affiliation": sorted({x for x in interviewer_aff if x}),
        "authors": [a.get("name", {}).get("label") or a.get("name", {}).get("value")
                    for a in cit.get("author", []) or []],
        "interview_location": labels(data.get("interview_location")),
        "interview_date": interview_ts,
        "interview_year": interview_year,
        "subject_keywords": labels(cov.get("subject_keywords")),
        "subject_locations": labels(cov.get("subject_location")),
        "subject_year_start": y0,
        "subject_year_end": y1,
        "audience": labels(rel.get("audience")),
        "collections": labels(rel.get("collections")),
        "language_interview": labels(adm.get("language_interview")),
        "language_metadata": label(adm.get("language_metadata")),
        "publisher": label(cit.get("publisher")),
        "rightsholder": label(rights.get("rightsholder")),
        "licence": label(rights.get("licence_type")),
        "contains_personal_data": personal,
        "transcript_machine": text_of(data.get("transcript_machine")),
        "recording_format": labels(data.get("recording_format")),
        "recording_equipment": text_of(data.get("recording_equipment")),
        "grants": [g for g in grants if g],
        "contact_email": adm.get("contact_email"),
        "raw": json.dumps(m, ensure_ascii=False),
    }
    doc["authors"] = [a for a in doc["authors"] if a]
    return clean(doc)


# ------------------------------------------------------------------ sync
def _schema_sig(fields):
    return {(f["name"], f["type"], bool(f.get("facet", False))) for f in fields}


def ensure_collection(ts_client, recreate):
    exists = any(c["name"] == COLLECTION for c in ts_client.collections.retrieve())
    if exists and not recreate:
        current = ts_client.collections[COLLECTION].retrieve()
        if _schema_sig(current["fields"]) != _schema_sig(SCHEMA["fields"]):
            log.warning("schema changed; recreating collection (it is rebuilt from the harvest)")
            recreate = True
    if exists and recreate:
        log.warning("dropping collection %s", COLLECTION)
        ts_client.collections[COLLECTION].delete()
        exists = False
    if not exists:
        log.info("creating collection %s", COLLECTION)
        ts_client.collections.create(SCHEMA)


def existing_checksums(ts_client):
    """id -> file_checksum for everything currently indexed."""
    raw = ts_client.collections[COLLECTION].documents.export(
        {"include_fields": "id,file_checksum"})
    out = {}
    for line in raw.splitlines():
        if line.strip():
            d = json.loads(line)
            out[d["id"]] = d.get("file_checksum")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--recreate", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    session = requests.Session()
    session.headers["User-Agent"] = "typesense-dv-harvester/1.0"

    items = harvest_file_list(session)
    if not items:
        log.error("harvest returned 0 files; aborting without touching the index")
        return 1

    # One doc per dataset; if a dataset has several such files keep the newest.
    by_ds = {}
    for it in items:
        k = str(it["dataset_id"])
        if k not in by_ds or it["published_at"] > by_ds[k]["published_at"]:
            by_ds[k] = it

    tsc = client()
    if not args.dry_run:
        ensure_collection(tsc, args.recreate)
        known = existing_checksums(tsc)
    else:
        known = {}

    # Safety: refuse mass-deletion if the harvest shrank drastically.
    stale = [i for i in known if i not in by_ds]
    if known and len(stale) > max(5, 0.5 * len(known)):
        log.error("would delete %d of %d docs; refusing (harvest looks broken)",
                  len(stale), len(known))
        return 1

    todo = [it for k, it in by_ds.items()
            if args.full or known.get(k) != it["checksum"]["value"]]
    log.info("%d datasets harvested, %d new/changed, %d to delete, %d unchanged",
             len(by_ds), len(todo), len(stale), len(by_ds) - len(todo))

    if args.dry_run:
        for it in todo:
            log.info("would upsert %s (%s)", it["dataset_persistent_id"], it["dataset_name"])
        return 0

    docs, failures = [], 0

    def work(it):
        try:
            return build_doc(it, fetch_metadata(session, it))
        except Exception as e:  # keep going; old doc (if any) stays in place
            log.error("failed %s: %s", it["dataset_persistent_id"], e)
            return None

    with ThreadPoolExecutor(FETCH_WORKERS) as ex:
        for d in ex.map(work, todo):
            if d is None:
                failures += 1
            else:
                docs.append(d)

    if docs:
        res = tsc.collections[COLLECTION].documents.import_(
            docs, {"action": "upsert", "batch_size": 200})
        bad = [r for r in res if not r.get("success")]
        for r in bad:
            log.error("import error: %s", r)
        failures += len(bad)

    for doc_id in stale:
        tsc.collections[COLLECTION].documents[doc_id].delete()

    log.info("done: upserted %d, deleted %d, failures %d", len(docs), len(stale), failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())