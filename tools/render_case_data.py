#!/usr/bin/env python3
"""Render the agent-facing records for n400-filing-review from tests/case_facts.json.

Writes, under environment/data/review:
- cms.sql: the CMS export as SQL text (the agent image builds cms.sqlite from it)
- mail/*.eml: client email, attachments included (text files and PDFs)
- foia/<request number>.pdf: one CBP FOIA response per request, as a text-based PDF; when CBP
  amended its response, the first one stays as <request number>.pdf and the amended one is
  <request number>-A1.pdf

Fields used only by the verifier ("facts", "in_queue", "_note", "oath_date", FOIA coverage dates
in the CMS) are not rendered as data. Output is deterministic: no timestamps, fixed object order and
zlib-compressed streams, so running it twice gives byte-identical files. Standard library only.

Usage: python3 tools/render_case_data.py tasks/n400-filing-review
"""
import email.policy
import json
import sys
import zlib
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

DDL = """
CREATE TABLE cms_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE clients (client_id TEXT PRIMARY KEY, full_name TEXT NOT NULL, date_of_birth TEXT, a_number TEXT, email TEXT);
CREATE TABLE review_queue (client_id TEXT PRIMARY KEY REFERENCES clients(client_id), added_on TEXT NOT NULL, paralegal TEXT NOT NULL);
CREATE TABLE lpr_records (record_id INTEGER PRIMARY KEY, client_id TEXT NOT NULL, source TEXT NOT NULL, form TEXT, record_date TEXT NOT NULL, note TEXT);
CREATE TABLE addresses (address_id INTEGER PRIMARY KEY, client_id TEXT NOT NULL, street TEXT, city TEXT, state TEXT NOT NULL, moved_in TEXT NOT NULL, moved_out TEXT);
CREATE TABLE marriages (client_id TEXT PRIMARY KEY, spouse_name TEXT, marriage_date TEXT NOT NULL, spouse_status TEXT NOT NULL, spouse_naturalized_on TEXT, status TEXT NOT NULL);
CREATE TABLE cbp_foia_requests (client_id TEXT PRIMARY KEY, request_no TEXT NOT NULL, received_on TEXT);
CREATE TABLE documents (doc_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, doc_type TEXT NOT NULL, issuer TEXT, depart_date TEXT, return_date TEXT, covers_from TEXT, covers_to TEXT, received_on TEXT);
CREATE TABLE questionnaire_trips (trip_id INTEGER PRIMARY KEY, client_id TEXT NOT NULL, depart_date TEXT, return_date TEXT, destination TEXT, answered_on TEXT);
CREATE TABLE planned_travel (plan_id INTEGER PRIMARY KEY, client_id TEXT NOT NULL, depart_date TEXT NOT NULL, return_date TEXT NOT NULL, destination TEXT, recorded_on TEXT);
CREATE TABLE matters (matter_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, matter_type TEXT NOT NULL, opened_on TEXT NOT NULL, closed_on TEXT, outcome TEXT);
"""
PARALEGALS = ["J. Whitford", "M. Osei", "R. Delgado"]
PORTS = {"JFK": "New York (JFK), NY", "EWR": "Newark (EWR), NJ", "BOS": "Boston (BOS), MA"}
MODES = {"AIR": "Air", "LAND": "Land", "SEA": "Sea"}
ROWS_PER_PAGE = 5


def sql_value(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def insert(table, row):
    cols = ", ".join(row)
    vals = ", ".join(sql_value(v) for v in row.values())
    return f"INSERT INTO {table} ({cols}) VALUES ({vals});"


def render_sql(facts):
    out = [f"-- Calder & Voss Immigration PLLC: CMS export taken {facts['cms_export_date']}.", DDL.strip(), ""]
    out.append(insert("cms_meta", {"key": "export_date", "value": facts["cms_export_date"]}))
    out.append(insert("cms_meta", {"key": "firm", "value": "Calder & Voss Immigration PLLC"}))
    n = {"lpr": 0, "addr": 0, "trip": 0, "plan": 0, "matter": 0}
    queued = 0
    for c in sorted(facts["clients"], key=lambda c: c["client_id"]):
        cid = c["client_id"]
        out.append(insert("clients", {"client_id": cid, "full_name": c["full_name"], "date_of_birth": c["dob"],
                                      "a_number": c["a_number"], "email": c["email"]}))
        if c["in_queue"]:
            out.append(insert("review_queue", {"client_id": cid, "added_on": facts["cms_export_date"],
                                               "paralegal": PARALEGALS[queued % len(PARALEGALS)]}))
            queued += 1
        for r in c["lpr_records"]:
            n["lpr"] += 1
            out.append(insert("lpr_records", {"record_id": n["lpr"], "client_id": cid, "source": r["source"],
                                              "form": r["form"], "record_date": r["record_date"], "note": r["note"]}))
        for a in c["addresses"]:
            n["addr"] += 1
            out.append(insert("addresses", {"address_id": n["addr"], "client_id": cid, **a}))
        if c["marriage"]:
            out.append(insert("marriages", {"client_id": cid, **c["marriage"]}))
        foia = c["cbp_foia"]
        first = foia.get("superseded_response", foia)  # the CMS records the first response only
        out.append(insert("cbp_foia_requests", {"client_id": cid, "request_no": foia["request_no"], "received_on": first["received_on"]}))
        for x in c["documents"]:
            out.append(insert("documents", {"doc_id": x["doc_id"], "client_id": cid, **{k: v for k, v in x.items() if k != "doc_id"}}))
        for t in c["questionnaire_trips"]:
            n["trip"] += 1
            out.append(insert("questionnaire_trips", {"trip_id": n["trip"], "client_id": cid, **t}))
        for p in c["planned_travel"]:
            n["plan"] += 1
            out.append(insert("planned_travel", {"plan_id": n["plan"], "client_id": cid, **p}))
        for m in c["matters"]:
            n["matter"] += 1
            out.append(insert("matters", {"matter_id": f"M-{m['opened_on'][:4]}-{n['matter']:03d}", "client_id": cid,
                                          **{k: v for k, v in m.items() if k != "oath_date"}}))
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- PDF


def pdf_text(s):
    return "(" + s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def pdf_bytes(pages):
    """A minimal text-only PDF. pages: lists of (x, y, font, size, text); font is "R" or "B"."""
    objs = [None, None, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
    kids = []
    for items in pages:
        ops = []
        for x, y, font, size, text in items:
            ops.append(f"BT /F{'2' if font == 'B' else '1'} {size} Tf 1 0 0 1 {x} {y} Tm {pdf_text(text)} Tj ET")
        data = zlib.compress("\n".join(ops).encode("latin-1"), 9)
        objs.append(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream")
        content = len(objs)
        objs.append(None)
        kids.append(len(objs))
        objs[-1] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                    b"/Contents %d 0 R >>" % content)
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def wrap(text, width=92):
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    return lines + [line] if line else lines


def words(iso):
    x = date.fromisoformat(iso)
    return f"{x.strftime('%B')} {x.day}, {x.year}"


def mdy(iso):
    x = date.fromisoformat(iso)
    return f"{x.month:02d}/{x.day:02d}/{x.year}"


def traveler(name):
    first, last = name.rsplit(" ", 1)
    return f"{last.upper()}, {first.upper()}"


def render_foia_pdf(c, first=False):
    """CBP's response to one FOIA request: a cover letter, then the travel records, newest first.
    With first=True, the response that a later amended response replaces."""
    foia = dict(c["cbp_foia"])
    events = c["cbp_events"]
    amended = "superseded_response" in foia
    if first:
        events, foia["received_on"] = foia["superseded_response"]["events"], foia["superseded_response"]["received_on"]
    people = [(c["full_name"], c["dob"], events)]
    if foia.get("joint_traveler"):
        j = foia["joint_traveler"]
        people.append((j["name"], j["dob"], j["events"]))
    rows = []
    for name, dob, events in people:
        for e in events:
            rows.append((e["date"], "Entry" if e["type"] == "ARRIVAL" else "Exit", PORTS.get(e["port"], e["port"]),
                         MODES[e["mode"]], traveler(name), mdy(dob)))
    rows.sort(key=lambda r: (r[0], r[1] == "Entry", r[4]), reverse=True)  # newest first; on one day the entry follows the exit
    subjects = "; ".join(f"{traveler(n)} (date of birth {mdy(b)})" for n, b, _ in people)
    request = foia["request_no"] + ("-A1" if amended and not first else "")
    letter = [
        ("B", 11, "U.S. Customs and Border Protection"), ("R", 10, "FOIA Division"),
        ("R", 10, "90 K Street NE, Washington, DC 20229"), ("R", 10, ""), ("R", 10, words(foia["received_on"])), ("R", 10, ""),
        ("R", 10, "Calder & Voss Immigration PLLC"), ("R", 10, "Attn: N-400 review team"), ("R", 10, ""),
        ("B", 10, f"Re: FOIA request {foia['request_no']}" + (" (amended response)" if request != foia["request_no"] else "")),
        ("R", 10, ""), ("R", 10, "Dear Requester:"), ("R", 10, ""),
    ]
    para = []
    if request != foia["request_no"]:
        para.append(f"This is an amended response to your request. It replaces our response of "
                    f"{words(foia['superseded_response']['received_on'])}, in which one record was listed with an incorrect "
                    f"date. Please disregard that response and rely on the records below.")
    para += [f"This responds to your Freedom of Information Act request for the travel history of {subjects}. "
             f"We searched the records of entries into and exits from the United States from "
             f"{words(foia['coverage_from'])} through {words(foia['coverage_to'])}. The {len(rows)} records we found are "
             f"listed on the following pages, newest first.",
             "Entries into the United States are recorded for every mode of travel. Exits are recorded for air and sea "
             "travel only; departures by land are not recorded."]
    if len(people) > 1:
        para.append("Your request named more than one traveler, so the records for all of them are listed together. "
                    "Each record shows the traveler it belongs to.")
    for p in para:
        letter += [("R", 10, line) for line in wrap(p)] + [("R", 10, "")]
    letter += [("R", 10, "Sincerely,"), ("R", 10, ""), ("R", 10, "FOIA Officer, Office of Privacy and Diversity")]
    chunks = [rows[i:i + ROWS_PER_PAGE] for i in range(0, len(rows), ROWS_PER_PAGE)] or [[]]
    total = 1 + len(chunks)
    footer = lambda n: (72, 40, "R", 8, f"FOIA request {request}  -  page {n} of {total}")
    pages = [[(72, 740 - 15 * i, f, s, t) for i, (f, s, t) in enumerate(letter) if t] + [footer(1)]]
    cols = (72, 135, 210, 330, 370, 505)
    head = ("Date", "Entry or Exit", "Port", "Mode", "Traveler", "Date of birth")
    for n, chunk in enumerate(chunks, 2):
        page = [(72, 740, "B", 11, "Entries and exits, newest first"),
                (72, 722, "R", 9, f"Request {request}. Dates are shown as MM/DD/YYYY.")]
        page += [(x, 696, "B", 9, h) for x, h in zip(cols, head)]
        for i, r in enumerate(chunk):
            page += [(x, 676 - 20 * i, "R", 9, v) for x, v in zip(cols, (mdy(r[0]),) + r[1:])]
        if not chunk:
            page.append((72, 676, "R", 9, "No records were found."))
        pages.append(page + [footer(n)])
    return pdf_bytes(pages)


def render_itinerary_pdf(a):
    """A European carrier's e-ticket itinerary; it prints dates in the format its header states."""
    fmt = lambda iso: date.fromisoformat(iso).strftime("%d/%m/%Y" if a["date_format"] == "DD/MM/YYYY" else "%m/%d/%Y")
    page = [(72, 740, "B", 14, a["carrier"]), (72, 720, "R", 10, "E-ticket itinerary / Itinerario do bilhete eletronico"),
            (72, 696, "R", 10, f"Booking reference: {a['booking']}"), (72, 681, "R", 10, f"Passenger: {a['passenger']}"),
            (72, 657, "B", 10, f"All dates in this document are shown as {a['date_format']}."),
            (72, 627, "B", 9, "Flight"), (126, 627, "B", 9, "Date"), (190, 627, "B", 9, "From"),
            (330, 627, "B", 9, "To"), (470, 627, "B", 9, "Departs"), (520, 627, "B", 9, "Arrives")]
    for i, f in enumerate(a["flights"]):
        y = 607 - 20 * i
        page += [(72, y, "R", 9, f["flight"]), (126, y, "R", 9, fmt(f["date"])), (190, y, "R", 9, f["from"]),
                 (330, y, "R", 9, f["to"]), (470, y, "R", 9, f["dep"]), (520, y, "R", 9, f["arr"])]
    page += [(72, 540, "R", 9, "Times are local. +1 means the next day."),
             (72, 525, "R", 9, "Checked baggage: 1 x 23 kg. Please be at the airport 3 hours before an intercontinental departure.")]
    return pdf_bytes([page])


# --------------------------------------------------------------------------- email


def render_email(e):
    stem = e["file"].rsplit(".", 1)[0]
    msg = EmailMessage()
    msg["From"] = e["from"]
    msg["To"] = e["to"]
    msg["Subject"] = e["subject"]
    msg["Date"] = format_datetime(datetime.fromisoformat(e["date"]))
    msg["Message-ID"] = f"<{stem}@mail.calder-voss.example>"
    msg.set_content(e["body"])
    for a in e["attachments"]:
        if a.get("pdf") == "itinerary":
            msg.add_attachment(render_itinerary_pdf(a), maintype="application", subtype="pdf", filename=a["filename"])
        else:
            msg.add_attachment(a["text"], subtype="plain", filename=a["filename"])
    if msg.is_multipart():
        msg.set_boundary(f"=={stem}==")
    return msg.as_bytes(policy=email.policy.default)


def main(task_dir):
    task = Path(task_dir)
    facts = json.loads((task / "tests" / "case_facts.json").read_text(encoding="utf-8"))
    review = task / "environment" / "data" / "review"
    mail, foia = review / "mail", review / "foia"
    for folder, pattern in ((mail, "*.eml"), (foia, "*.pdf")):
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob(pattern):
            old.unlink()
    (review / "cms.sql").write_text(render_sql(facts), encoding="utf-8")
    n_mail = n_pdf = 0
    for c in facts["clients"]:
        for e in c["emails"]:
            (mail / e["file"]).write_bytes(render_email(e))
            n_mail += 1
        request = c["cbp_foia"]["request_no"]
        if "superseded_response" in c["cbp_foia"]:
            (foia / f"{request}.pdf").write_bytes(render_foia_pdf(c, first=True))
            (foia / f"{request}-A1.pdf").write_bytes(render_foia_pdf(c))
            n_pdf += 2
        else:
            (foia / f"{request}.pdf").write_bytes(render_foia_pdf(c))
            n_pdf += 1
    print(f"wrote {review / 'cms.sql'}, {n_mail} emails in {mail} and {n_pdf} FOIA responses in {foia}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
