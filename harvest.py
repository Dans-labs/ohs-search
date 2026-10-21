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
import html
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
        {"name": "dataset_citation", "type": "string", "index": False, "optional": True},
        {"name": "file_id", "type": "string", "index": False},
        {"name": "file_checksum", "type": "string", "index": False},
        {"name": "published_at", "type": "int64", "sort": True},
        {"name": "published_year", "type": "int32", "facet": True},
        # --- descriptive
        {"name": "title", "type": "string", "sort": True},
        {"name": "subtitle", "type": "string", "optional": True},
        {"name": "description", "type": "string", "optional": True},
        # --- people
        {"name": "interviewee", "type": "string", "facet": True, "optional": True},
        {"name": "interviewer", "type": "string[]", "facet": True, "optional": True},
        {"name": "interpreter", "type": "string[]", "facet": True, "optional": True},
        {"name": "others", "type": "string[]", "facet": True, "optional": True},
        {"name": "recorded_by", "type": "string[]", "facet": True, "optional": True},
        {"name": "recorded_by_affiliation", "type": "string[]", "facet": True, "optional": True},
        {"name": "recorded_by_consent", "type": "string[]", "facet": True, "optional": True},
        {"name": "authors", "type": "string[]", "facet": True, "optional": True},
        {"name": "author_affiliations", "type": "string[]", "facet": True, "optional": True},
        {"name": "author_orcids", "type": "string[]", "facet": True, "optional": True},
        # --- interview
        {"name": "interview_location", "type": "string[]", "facet": True, "optional": True},
        {"name": "interview_location_uri", "type": "string[]", "index": False, "optional": True},
        {"name": "interview_location_geo", "type": "geopoint[]", "optional": True},
        {"name": "interview_date", "type": "int64", "sort": True, "optional": True},
        {"name": "interview_date_end", "type": "int64", "sort": True, "optional": True},
        {"name": "interview_year", "type": "int32", "facet": True, "optional": True},
        {"name": "language_interview", "type": "string[]", "facet": True, "optional": True},
        {"name": "language_interview_code", "type": "string[]", "facet": True, "optional": True},
        {"name": "recording_format", "type": "string[]", "facet": True, "optional": True},
        {"name": "recording_equipment", "type": "string", "facet": True, "optional": True},
        {"name": "transcript_machine", "type": "string", "facet": True, "optional": True},
        # --- subject
        {"name": "subject_keywords", "type": "string[]", "facet": True, "optional": True},
        {"name": "subject_keywords_aat", "type": "string[]", "facet": True, "optional": True},
        {"name": "subject_keywords_wikidata", "type": "string[]", "facet": True, "optional": True},
        {"name": "subject_keywords_freetext", "type": "string[]", "facet": True, "optional": True},
        {"name": "subject_keyword_uri", "type": "string[]", "index": False, "optional": True},
        {"name": "subject_locations", "type": "string[]", "facet": True, "optional": True},
        {"name": "subject_location_uri", "type": "string[]", "index": False, "optional": True},
        {"name": "subject_locations_geo", "type": "geopoint[]", "optional": True},
        {"name": "subject_locations_pt", "type": "string[]", "facet": True, "optional": True},
        {"name": "subject_year_start", "type": "int32", "facet": True, "optional": True},
        {"name": "subject_year_end", "type": "int32", "facet": True, "optional": True},
        # --- relations
        {"name": "audience", "type": "string[]", "facet": True, "optional": True},
        {"name": "audience_uri", "type": "string[]", "index": False, "optional": True},
        {"name": "collections", "type": "string[]", "facet": True, "optional": True},
        {"name": "collections_uri", "type": "string[]", "index": False, "optional": True},
        {"name": "relation_type", "type": "string[]", "facet": True, "optional": True},
        {"name": "relation_item", "type": "string[]", "optional": True},
        {"name": "relation_reference", "type": "string[]", "optional": True},
        # --- administrative / rights
        {"name": "language_metadata", "type": "string", "facet": True, "optional": True},
        {"name": "language_metadata_code", "type": "string", "facet": True, "optional": True},
        {"name": "contact_email", "type": "string", "index": False, "optional": True},
        {"name": "contact_name", "type": "string", "facet": True, "optional": True},
        {"name": "contact_affiliation", "type": "string", "facet": True, "optional": True},
        {"name": "depositor", "type": "string", "index": False, "optional": True},
        {"name": "date_available", "type": "string", "optional": True},
        {"name": "publisher", "type": "string", "facet": True, "optional": True},
        {"name": "publisher_ror", "type": "string", "index": False, "optional": True},
        {"name": "publisher_country", "type": "string", "facet": True, "optional": True},
        {"name": "rightsholder", "type": "string", "facet": True, "optional": True},
        {"name": "rightsholder_ror", "type": "string", "index": False, "optional": True},
        {"name": "rightsholder_country", "type": "string", "facet": True, "optional": True},
        {"name": "licence", "type": "string", "facet": True, "optional": True},
        {"name": "licence_url", "type": "string", "index": False, "optional": True},
        {"name": "contains_personal_data", "type": "bool", "facet": True, "optional": True},
        {"name": "grants", "type": "string[]", "facet": True, "optional": True},
        {"name": "grant_agencies", "type": "string[]", "facet": True, "optional": True},
        {"name": "grant_numbers", "type": "string[]", "optional": True},
        # --- attached files listed in the form metadata (non-private ones)
        {"name": "attachment_names", "type": "string[]", "optional": True},
        {"name": "attachment_types", "type": "string[]", "facet": True, "optional": True},
        {"name": "attachment_roles", "type": "string[]", "facet": True, "optional": True},
        {"name": "attachment_count", "type": "int32", "sort": True, "optional": True},
        {"name": "attachment_size", "type": "int64", "sort": True, "optional": True},
        # Complete parsed metadata file kept for display, not indexed
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


def as_list(v):
    if v is None or v == "":
        return []
    return v if isinstance(v, list) else [v]


def values(v):
    """The 'value' part of {label,value} dicts (codes, URIs)."""
    return [str(x["value"]).strip() for x in as_list(v)
            if isinstance(x, dict) and x.get("value")]


def uris(v):
    return [x for x in values(v) if x.startswith("http")]


def uri(v):
    u = uris(v)
    return u[0] if u else ""


def person(p):
    """'First Last' from {x_first_name, x_last_name}; tolerant of other shapes."""
    if isinstance(p, dict):
        first = last = ""
        for k, val in p.items():
            if k.endswith("first_name"):
                first = str(val or "").strip()
            elif k.endswith("last_name"):
                last = str(val or "").strip()
        if first or last:
            return " ".join(x for x in (first, last) if x)
        return " ".join(str(val).strip() for k, val in p.items()
                        if isinstance(val, str) and val.strip() and "consent" not in k)
    return str(p or "").strip()


def people(v):
    return [n for n in (person(p) for p in as_list(v)) if n]


def dmy_dates(s):
    """All DD-MM-YYYY [HH:MM] dates in a string -> unix timestamps (UTC)."""
    out = []
    for d, mo, y, hh, mm in re.findall(
            r"(\d{1,2})-(\d{1,2})-(\d{4})(?:[ T]+(\d{1,2}):(\d{2}))?", s or ""):
        try:
            out.append(int(datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0),
                                    tzinfo=timezone.utc).timestamp()))
        except ValueError:
            pass
    return out


def geopoints(v):
    """Locations carry coordinates as ["lon","lat"] strings; Typesense wants [lat, lon]."""
    out = []
    for x in as_list(v):
        c = x.get("coordinates") if isinstance(x, dict) else None
        try:
            lon, lat = float(c[0]), float(c[1])
        except (TypeError, ValueError, IndexError):
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            out.append([lat, lon])
    return out


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


def _flat_to_nested(f):
    """Files exported as a flat {"id", "metadata": {...}} -> the nested layout."""
    g = f.get
    return {
        "data": {
            "ohs": {k: g(k) for k in ("interviewee", "interviewer", "interpreter", "others") if g(k)},
            **{k: g(k) for k in ("interview_location", "interview_date_time", "recorded_by",
                                 "recording_format", "recording_equipment", "transcript_machine")},
        },
        "citation": {k: g(k) for k in ("title", "subtitle", "description", "publisher", "author", "grant")},
        "coverage": {
            "subject_keywords": [*as_list(g("subject_keywords_aat")),
                                 *as_list(g("subject_keywords_wikidata")),
                                 *as_list(g("subject_keywords_freetext"))],
            "subject_location": g("subject_location"),
            "subject_date_time": g("subject_date_time"),
        },
        "relations": {k: g(k) for k in ("audience", "collections", "relation")},
        "administrative": {k: g(k) for k in ("language_interview", "language_metadata", "contact_email")},
        "rights": {k: g(k) for k in ("rightsholder", "licence_type", "personal_data")},
    }


def _form_root(meta):
    """
    Return the nested dict that holds data/citation/coverage/rights/... Files come in
      * nested:  {"data": {...}, "citation": {...}, ...}
      * wrapped: {"data": {"data": ..., "citation": ...}}
      * flat:    {"id": ..., "metadata": {"interviewee": ..., "title": ..., ...}}
    """
    inner = meta.get("data")
    if isinstance(inner, dict) and "citation" in inner and "citation" not in meta:
        return inner
    if isinstance(meta.get("metadata"), dict) and "citation" not in meta:
        return _flat_to_nested(meta["metadata"])
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

    # "key": [ <whitespace> }   -> list that was opened but never filled/closed
    if stripped[:1] == "}" and stack and stack[-1] == "[":
        return head + "]" + rest

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


def _repair_all(dec, text):
    """Escape stray quotes, then fix structure one decoder error at a time."""
    text = _escape_stray_quotes(_fix_extra_content(text))
    for _ in range(50):
        try:
            obj, end = dec.raw_decode(text)
            return obj, end, text
        except json.JSONDecodeError as e:
            fixed = _repair_structure(text, e)
            if fixed is None:
                lo = max(0, e.pos - 100)
                raise ValueError(
                    f"{e.msg} at char {e.pos}; near: {text[lo:e.pos + 100]!r}") from None
            text = fixed
    raise ValueError("gave up after 50 structural repairs")


def _tail_members(dec, tail):
    """Some files close the root object too early: '... } , "file-metadata": [...] }'."""
    t = tail.lstrip(", \t\r\n")
    if not t.startswith('"'):
        return {}
    try:
        obj, _ = dec.raw_decode("{" + t)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


def parse_lenient(text, label_=""):
    """
    Parse JSON that may be slightly broken. Tolerates:
      * raw control characters (newlines/tabs) inside strings
      * unescaped double quotes inside strings
      * lists that were opened but never closed, trailing/missing commas, missing closers
      * members after the root object was closed early (kept, e.g. "file-metadata")
    If the file cannot be repaired as a whole, the (optional) "file-metadata"
    section is cut off and the rest is repaired.
    """
    dec = json.JSONDecoder(strict=False)
    text = text.lstrip("\ufeff \t\r\n")
    original = text
    notes = []
    try:
        obj, end = dec.raw_decode(text)
    except json.JSONDecodeError:
        notes.append("repaired")
        try:
            obj, end, text = _repair_all(dec, original)
        except ValueError as first_err:
            cut = _cut_file_metadata(original)
            if cut == original:
                raise
            try:
                obj, end, text = _repair_all(dec, cut)
                notes.append("file-metadata dropped")
            except ValueError:
                raise first_err from None
    tail = text[end:].strip()
    if tail.strip("} \t\r\n,"):
        extra = _tail_members(dec, tail)
        if extra and isinstance(obj, dict):
            for k, v in extra.items():
                obj.setdefault(k, v)
        else:
            log.warning("%s: ignoring %d chars of trailing data", label_, len(tail))
    if notes:
        log.warning("%s: metadata file was not valid JSON; %s", label_, ", ".join(notes))
    return obj


def fetch_metadata(session, item):
    r = session.get(item["url"], timeout=60)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")
    return parse_lenient(text, item["dataset_persistent_id"])


_TYPES = {f["name"]: f["type"] for f in SCHEMA["fields"]}


def _coerce(doc):
    """Force every value to the schema type (the forms are not consistent:
    a subtitle can be a string or a list), and unescape HTML entities (&amp;)."""
    out = {}
    for k, v in doc.items():
        t = _TYPES.get(k)
        if k == "raw" or t is None or v is None:
            out[k] = v
            continue
        if t == "string":
            if isinstance(v, (list, tuple)):
                v = ", ".join(labels(v))
            elif isinstance(v, dict):
                v = label(v)
            v = html.unescape(str(v)).strip()
        elif t == "string[]":
            v = [html.unescape(x) for x in labels(as_list(v))]
        elif t in ("int32", "int64"):
            try:
                v = int(v)
            except (TypeError, ValueError):
                v = None
        out[k] = v
    return out


def _is_true(v):
    return v is True or str(v).strip().lower() == "true"


def build_doc(item, meta):
    m = _form_root(meta)
    data = m.get("data") or {}
    cit = m.get("citation") or {}
    cov = m.get("coverage") or {}
    rel = m.get("relations") or {}
    adm = m.get("administrative") or {}
    rights = m.get("rights") or {}
    ohs = data.get("ohs") or m.get("ohs") or {}   # "ohs" sits under "data" or beside "citation"

    def pick(key):
        """Interview fields sit in "data" in some forms and in "ohs" in others."""
        for src in (data, ohs):
            if src.get(key) not in (None, "", [], {}):
                return src[key]
        return None

    # --- people
    interviewee = "; ".join(people(ohs.get("interviewee") or data.get("interviewee")))
    interviewer = people(ohs.get("interviewer") or data.get("interviewer"))
    interpreter = people(ohs.get("interpreter") or data.get("interpreter"))
    others = people(ohs.get("others") or data.get("others"))

    rec = [r for r in as_list(pick("recorded_by")) if isinstance(r, dict)]
    recorded_by = [n for n in (person(r) for r in rec) if n]
    rec_aff = sorted({str(r.get("recorded_by_affiliation")).strip() for r in rec
                      if r.get("recorded_by_affiliation")})
    rec_consent = sorted({str(r.get("recorded_by_consent")).strip() for r in rec
                          if r.get("recorded_by_consent")})

    authors, author_aff, author_orcids = [], [], []
    for a in as_list(cit.get("author")):
        if not isinstance(a, dict):
            continue
        nm = a.get("name") or {}
        n = label(nm) if isinstance(nm, dict) else str(nm).strip()
        if n:
            authors.append(n)
        if a.get("affiliation"):
            author_aff.append(text_of(a["affiliation"]))
        if isinstance(nm, dict):
            val = str(nm.get("value") or "")
            orcid = nm.get("id") if "orcid" in str(nm.get("idLabel", "")).lower() else None
            if not orcid and "orcid.org/" in val:
                orcid = val.rsplit("/", 1)[-1]
            if orcid:
                author_orcids.append(str(orcid))

    # --- dates
    idates = [t for e in as_list(pick("interview_date_time")) if isinstance(e, dict)
              for v in e.values() if isinstance(v, str) for t in dmy_dates(v)]
    interview_ts = min(idates) if idates else None
    interview_end = max(idates) if idates else None
    interview_year = (datetime.fromtimestamp(interview_ts, timezone.utc).year
                      if interview_ts else None)

    sdt = " ".join(str(v) for e in as_list(cov.get("subject_date_time")) if isinstance(e, dict)
                   for v in e.values() if isinstance(v, str))
    y0, y1 = parse_year_range(sdt)

    # --- keywords, split by vocabulary (works for the flat and the merged layout)
    kws = as_list(cov.get("subject_keywords"))
    aat, wiki, free = [], [], []
    for x in kws:
        lab = label(x)
        val = str(x.get("value") or "") if isinstance(x, dict) else ""
        if not lab:
            continue
        if "vocab.getty.edu" in val:
            aat.append(lab)
        elif "wikidata.org" in val:
            wiki.append(lab)
        else:
            free.append(lab)

    # --- misc
    published = ts(item["published_at"])
    pd = rights.get("personal_data")
    personal = None if pd is None else str(pd).endswith("true")

    grant_list = [g for g in as_list(cit.get("grant")) if isinstance(g, dict)]
    grants = [" ".join(filter(None, [g.get("grant_agency"), g.get("grant_number")]))
              for g in grant_list]

    relations = [r for r in as_list(rel.get("relation")) if isinstance(r, dict)]

    contact = adm.get("contact") if isinstance(adm.get("contact"), dict) else {}
    # older forms have a single "language" (the metadata language); the
    # language_interview / language_metadata split was added later
    lang_m = adm.get("language_metadata") or adm.get("language")

    pub, rh = cit.get("publisher"), rights.get("rightsholder")
    lic = rights.get("licence_type")

    files = None
    for cand in (m.get("file-metadata"), meta.get("file-metadata"),
                 (meta.get("metadata") or {}).get("file-metadata")):
        if cand is not None:
            files = [f for f in as_list(cand) if isinstance(f, dict) and not _is_true(f.get("private"))]
            break

    pid = item["dataset_persistent_id"].replace("doi:", "")

    subject_locations_pt = [
        f"{lat}|{lng}|{name}"
        for name, (lat, lng) in zip(m.get("subject_locations"), m.get("subject_locations_geo"))
    ]
        
    doc = {
        # Dataverse
        "id": str(item["dataset_id"]),
        "doi": pid,
        "dataset_name": item["dataset_name"],
        "dataset_url": f"https://doi.org/{pid}",
        "dataset_citation": item.get("dataset_citation"),
        "file_id": str(item["file_id"]),
        "file_checksum": item["checksum"]["value"],
        "published_at": published,
        "published_year": datetime.fromtimestamp(published, timezone.utc).year,
        # descriptive
        "title": cit.get("title") or item["dataset_name"],
        "subtitle": cit.get("subtitle"),
        "description": cit.get("description"),
        # people
        "interviewee": interviewee,
        "interviewer": interviewer,
        "interpreter": interpreter,
        "others": others,
        "recorded_by": recorded_by,
        "recorded_by_affiliation": rec_aff,
        "recorded_by_consent": rec_consent,
        "authors": authors,
        "author_affiliations": author_aff,
        "author_orcids": author_orcids,
        # interview
        "interview_location": labels(pick("interview_location")),
        "interview_location_uri": uris(pick("interview_location")),
        "interview_location_geo": geopoints(pick("interview_location")),
        "interview_date": interview_ts,
        "interview_date_end": interview_end,
        "interview_year": interview_year,
        "language_interview": labels(adm.get("language_interview")),
        "language_interview_code": values(adm.get("language_interview")),
        "recording_format": labels(pick("recording_format")),
        "recording_equipment": text_of(pick("recording_equipment")),
        "transcript_machine": text_of(pick("transcript_machine")),
        # subject
        "subject_keywords": labels(kws),
        "subject_keywords_aat": aat,
        "subject_keywords_wikidata": wiki,
        "subject_keywords_freetext": free,
        "subject_keyword_uri": uris(kws),
        "subject_locations": labels(cov.get("subject_location")),
        "subject_location_uri": uris(cov.get("subject_location")),
        "subject_locations_geo": geopoints(cov.get("subject_location")),
        "subject_locations_pt": subject_locations_pt,
        "subject_year_start": y0,
        "subject_year_end": y1,
        # relations
        "audience": labels(rel.get("audience")),
        "audience_uri": uris(rel.get("audience")),
        "collections": labels(rel.get("collections")),
        "collections_uri": uris(rel.get("collections")),
        "relation_type": [str(r["relation_type"]) for r in relations if r.get("relation_type")],
        "relation_item": [str(r["relation_item"]) for r in relations if r.get("relation_item")],
        "relation_reference": [str(r["relation_reference"]) for r in relations
                               if r.get("relation_reference")],
        # administrative / rights
        "language_metadata": label(lang_m),
        "language_metadata_code": (lang_m.get("value") if isinstance(lang_m, dict) else None),
        "contact_email": adm.get("contact_email") or contact.get("contact_email"),
        "contact_name": contact.get("contact_name"),
        "contact_affiliation": contact.get("contact_affiliation"),
        "depositor": cit.get("depositor"),
        "date_available": adm.get("date_available"),
        "publisher": label(pub),
        "publisher_ror": uri(pub),
        "publisher_country": (pub.get("extraContent") if isinstance(pub, dict) else None),
        "rightsholder": label(rh),
        "rightsholder_ror": uri(rh),
        "rightsholder_country": (rh.get("extraContent") if isinstance(rh, dict) else None),
        "licence": label(lic),
        "licence_url": uri(lic),
        "contains_personal_data": personal,
        "grants": [g for g in grants if g],
        "grant_agencies": [str(g["grant_agency"]) for g in grant_list if g.get("grant_agency")],
        "grant_numbers": [str(g["grant_number"]) for g in grant_list if g.get("grant_number")],
        # attached files
        "attachment_names": [str(f["name"]) for f in files or [] if f.get("name")],
        "attachment_types": sorted({str(f["mimetype"]) for f in files or [] if f.get("mimetype")}),
        "attachment_roles": sorted({label(f["role"]) for f in files or [] if f.get("role")}),
        "attachment_count": None if files is None else len(files),
        "attachment_size": (sum(int(f["size"]) for f in files if str(f.get("size", "")).isdigit())
                            if files and any(str(f.get("size", "")).isdigit() for f in files) else None),
        # everything, as parsed
        "raw": json.dumps(meta, ensure_ascii=False),
    }
    return clean(_coerce(doc))


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