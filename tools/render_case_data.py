#!/usr/bin/env python3
"""Render the agent-facing records for n400-filing-review from tests/case_facts.json.

Writes environment/data/review/cms.sql (the CMS export as SQL text; the agent image
builds cms.sqlite from it) and environment/data/review/mail/*.eml (client email with
attachments). Fields used only by the verifier ("facts", "in_queue", "_note") are not
rendered. Output is deterministic: running it twice gives byte-identical files.

Usage: python3 tools/render_case_data.py tasks/n400-filing-review
"""
import email.policy
import json
import sys
from datetime import datetime
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
CREATE TABLE cbp_foia (client_id TEXT PRIMARY KEY, request_no TEXT, coverage_from TEXT NOT NULL, coverage_to TEXT NOT NULL, received_on TEXT);
CREATE TABLE cbp_events (event_id INTEGER PRIMARY KEY, client_id TEXT NOT NULL, event_date TEXT NOT NULL, event_type TEXT NOT NULL, port TEXT, mode TEXT NOT NULL);
CREATE TABLE documents (doc_id TEXT PRIMARY KEY, client_id TEXT NOT NULL, doc_type TEXT NOT NULL, issuer TEXT, depart_date TEXT, return_date TEXT, covers_from TEXT, covers_to TEXT, received_on TEXT);
CREATE TABLE questionnaire_trips (trip_id INTEGER PRIMARY KEY, client_id TEXT NOT NULL, depart_date TEXT, return_date TEXT, destination TEXT, answered_on TEXT);
CREATE TABLE planned_travel (plan_id INTEGER PRIMARY KEY, client_id TEXT NOT NULL, depart_date TEXT NOT NULL, return_date TEXT NOT NULL, destination TEXT, recorded_on TEXT);
"""
PARALEGALS = ["J. Whitford", "M. Osei", "R. Delgado"]


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
    n = {"lpr": 0, "addr": 0, "event": 0, "trip": 0, "plan": 0}
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
        out.append(insert("cbp_foia", {"client_id": cid, **c["cbp_foia"]}))
        for e in sorted(c["cbp_events"], key=lambda e: (e["date"], e["type"] != "DEPARTURE")):
            n["event"] += 1
            out.append(insert("cbp_events", {"event_id": n["event"], "client_id": cid, "event_date": e["date"],
                                             "event_type": e["type"], "port": e["port"], "mode": e["mode"]}))
        for x in c["documents"]:
            out.append(insert("documents", {"doc_id": x["doc_id"], "client_id": cid, **{k: v for k, v in x.items() if k != "doc_id"}}))
        for t in c["questionnaire_trips"]:
            n["trip"] += 1
            out.append(insert("questionnaire_trips", {"trip_id": n["trip"], "client_id": cid, **t}))
        for p in c["planned_travel"]:
            n["plan"] += 1
            out.append(insert("planned_travel", {"plan_id": n["plan"], "client_id": cid, **p}))
    return "\n".join(out) + "\n"


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
        msg.add_attachment(a["text"], subtype="plain", filename=a["filename"])
    if msg.is_multipart():
        msg.set_boundary(f"=={stem}==")
    return msg.as_bytes(policy=email.policy.default)


def main(task_dir):
    task = Path(task_dir)
    facts = json.loads((task / "tests" / "case_facts.json").read_text(encoding="utf-8"))
    review = task / "environment" / "data" / "review"
    mail = review / "mail"
    mail.mkdir(parents=True, exist_ok=True)
    for old in mail.glob("*.eml"):
        old.unlink()
    (review / "cms.sql").write_text(render_sql(facts), encoding="utf-8")
    count = 0
    for c in facts["clients"]:
        for e in c["emails"]:
            (mail / e["file"]).write_bytes(render_email(e))
            count += 1
    print(f"wrote {review / 'cms.sql'} and {count} emails in {mail}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
