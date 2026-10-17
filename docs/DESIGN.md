# Design notes: n400-filing-review

This note covers how the task handles the things every agent system has to get right. The short version: the model reads, code decides, and a person gets the cases that can't be proven.

## 1. Human in the loop

- **"Ask for evidence" is a real answer.** For 3 of the 36 clients (C-1003, C-1016 and C-1035), the right decision is to stop and send the case back to the paralegal, because the records can't prove what's needed. An agent that fills the gap with the client's word, or with a hotel receipt, fails.
- **The SOP draws that line in writing:**
  - A client's statement alone never establishes a date (SOP 4.3 and 4.6).
  - With no usable permanent-resident date, the answer is REQUEST_EVIDENCE (SOP 3).
- **A person owned every decision about the task itself.** Every change made after a trial result was my decision, recorded in the iteration log.

## 2. Guardrails

**On the evidence (in the SOP):**

- For trip dates there is a fixed order of trust: CBP FOIA records first, then carrier documents (tickets, itineraries), then the client's own statements.
- A hotel receipt is not proof of travel.
- Client email overrides the case database only for facts the client reports: moves, separations, trips and planned travel. A CBP response that a client sends by email counts like the firm's own.

**On the verifier:**

- It runs in its own container, built from `tests/Dockerfile`.
- The ground truth (`tests/case_facts.json`) and the reference rules (`tests/rules.py`) never enter the agent's image.
- It reads one file, `/app/output/filing_review.json`, and never runs agent code.
- Parsing is strict:
  - duplicate JSON keys and invalid constants are rejected
  - every decision must have exactly the schema's fields
  - there must be exactly one decision per queued client, and no others
- The reward is 0 or 1, never partial.
- Editing anything under `/app/review` can't change the expected answers. They're computed from the verifier's own copy of the facts.

**Against cheating:** the `/cheat` trial runs Terminal-Bench's red-team prompt, which tells the agent to game the verifier instead of solving the task. It must score 0. Results are in [README.md](../README.md).

## 3. Data management

- **One source of truth.** `tests/case_facts.json` holds every fact for 38 clients: 36 in the review queue, plus 2 who aren't in the queue to check that the agent leaves them out. One of them, C-1032, is a former client, C-1031's husband, whose closed N-400 matter gives his oath date.
- **One renderer.** `demo/backend/render_case_data.py` turns that file into what the agent sees:
  - the case database export (`cms.sql`, built into `cms.sqlite` when the image is built)
  - 26 emails, 8 of them with attachments
  - 39 CBP FOIA responses as PDFs

  Rendering is deterministic: running it twice gives byte-identical files.
- **The answer key comes from the same file**, so the data and the answers can't drift apart.
- **Two independent implementations.** `tests/rules.py` works from the structured facts. `solution/solve.py` works only from the rendered database, email and FOIA PDFs, using the Python standard library. They agree on all 36 decisions. The oracle passing in Docker proves the agent's records contain exactly the facts the answers depend on.
- **All synthetic.** Every person, firm and record is made up, and email addresses use example domains.

## 4. Speed and cost

- **Correctness is graded, not speed.** Agents get 14,400 seconds. The verifier runs in well under a second, and the reference solution in about a second.
- **The task rewards the same split I'd use in a real system:** a model for reading messy records, and plain code for rules and date arithmetic, which is instant, exact and testable.
- **The oracle's search is cheap.** It looks for the earliest filing date day by day, but it starts at the latest hard date and stops after 8 years. The hard dates are the continuous-residence date and the marriage dates. The 3 months in the state is checked on each day, because a move the client announces for a later date counts only from that date.
- **Trials run in parallel.** The standard job runs its 3 attempts at once, so the set takes about as long as its slowest trial rather than all 3 in a row: 15 min 31 s for v4.

## 5. One declarative file drives everything

- **The same pattern I use at MIA and in Intake Desk.** At MIA, one YAML file drives the screens, the validation and the document extraction. In Intake Desk, `config/intake.yaml` does the same.
- **Here that file is JSON** (`case_facts.json`), which keeps the verifier image to the standard library plus pytest.
- **The firm's rules are prose on purpose.** They're an SOP memo, not config, because reading a real procedure and applying it exactly is part of the work being tested. In a product I would encode the SOP as config, the way Intake Desk does.
- **Strict by default.** The output format is a normative JSON schema, and the verifier rejects anything outside it: extra fields, extra or missing clients, duplicate keys. In a product I'd hold the config to the same standard: the YAML is schema-checked when the app starts, and a bad config stops the app instead of running on a guess. Intake Desk already fails closed: if a patient-data field doesn't say what every role can see, every page and API call fails until the YAML is fixed.

## 6. Bounded loops: three tries, then a person

- **In this evaluation.** The trial agent, Claude Code with Opus 5.5, gets 3 independent trials per task version, and all 3 must fail, so a failure can't be luck. A trial that ends in an infrastructure error (rate limit, crash, timeout) is logged and never counts as a model failure. The one so far, v3's third trial, wasn't rerun: the other two had passed, so the task moved on to v4.
- **In a production version of this review,** I'd run the agent in a bounded loop. The model reads the records and proposes decisions, code checks every decision against the rules, and any failed check goes back to the model with the exact errors. After 3 attempts the client goes to a paralegal with the errors attached. Every attempt is logged, so a reviewer can see why a case was escalated.

## 7. Sources

- **Where each fact comes from.** Trip dates follow the order of trust in SOP 4.3: CBP FOIA entry and exit records (one PDF per response in `foia/`, named by the request number in `cbp_foia_requests`, with the coverage window on its cover letter, plus the response one client sent by email), then carrier documents (the airline itineraries in the CMS `documents` table, the airline e-tickets attached to 5 emails and the bus e-ticket attached to one; the hotel receipt attached to another email doesn't count), then the client's own statements (questionnaire and email). The other rows in `documents` (5 employment letters, 3 tax returns, 4 leases and a deed) are rebuttal evidence for absences over six months (SOP 5.2 and 5.4). The permanent-resident date comes from the card scan, else the I-485 notice, and never from the I-751 notice or the questionnaire (SOP 3). Client email overrides the CMS only for moves, separations, trips and planned travel, and a CBP response a client sends by email counts like the firm's own (SOP 2).
- **Where each answer comes from.** Every expected decision is computed by `tests/rules.py` from `tests/case_facts.json`. Nothing in the answer key is typed in by hand.
- **The law behind the rules.** INA 316 (the 5-year basis), INA 319 (the 3-year basis for spouses of US citizens), 8 CFR 316.5 (continuous residence and absences) and the [USCIS Policy Manual, Vol. 12, Part D, Ch. 3](https://www.uscis.gov/policy-manual/volume-12-part-d-chapter-3) (the waiting periods after a break), restated as the firm's SOP. The clients and records are synthetic.
- **The benchmark rules followed.** Terminal-Bench 3's contributing guide and task review automation docs, run with Harbor 0.23.1.dev202609170426, the version TB3's CI pins. Xiangkai confirmed that either agent pair is fine, Klavis's brief's or the CI defaults. The trials ran only the Claude half of the brief's pair, Claude Code with Opus 5.5 at max effort. The Codex trials (GPT-6.1 Sol) were not run, because no OpenAI API key or ChatGPT login was available. Sources:
  - [CONTRIBUTING.md](https://github.com/harbor-framework/terminal-bench/blob/main/CONTRIBUTING.md)
  - [docs/TASK_REVIEW_AUTOMATION.md](https://github.com/harbor-framework/terminal-bench/blob/main/docs/TASK_REVIEW_AUTOMATION.md)
  - [.github/harbor-run-defaults.yml](https://github.com/harbor-framework/terminal-bench/blob/main/.github/harbor-run-defaults.yml)
  - [.github/harbor-version](https://github.com/harbor-framework/terminal-bench/blob/main/.github/harbor-version)

## 8. Diagrams

![How the task works](how-it-works.svg)
![How one decision is made](decision-flow.svg)
![Production plan](production-plan.svg)

The explorer app in `demo/` shows the task live: the right answer for every client, the SOP worked step by step, and the real verifier run on any output file. Run it with `python3 demo/backend/server.py`.

![Explorer: the task page](app-task.png)

*The task page: the review queue of 36 clients (the first 15 shown), each with the right answer from the verifier's own rules.*

![Explorer: client C-1007](app-client.png)

*Client C-1007: what the case tests, what each misreading gives, the timeline, the SOP worked step by step, and the records the agent sees.*

![Explorer: client C-1003's email](app-client-email.png)

*Client C-1003 with the email tab open: her email gives the departure date, but the only attachment is a hotel receipt, which isn't a carrier document. The trip stays unverified, so the right answer is REQUEST_EVIDENCE.*

![Explorer: the checker on the oracle's answers](app-checker-oracle.png)

*The checker running the real verifier on the oracle's answers: 39 of 39 tests pass, so the reward is 1.*

![Explorer: the checker](app-checker.png)

*The checker: the oracle's answers with one mistake (for C-1008, using 4 years and 1 day without rebuttal documents) fail 1 of 39 verifier tests, so the reward is 0.*

![Explorer: what's done](app-done.png)

*What's done: the checks the app runs with the task's own code, and where each part of the assignment stands after the v4 trials.*

## 9. From benchmark to production (what I'd build next)

None of this is part of the benchmark task. It's how I'd turn the same design into a real tool for a firm.

1. **Real inputs.** Connect the firm's CMS and intake inbox. Extract facts from CBP FOIA PDFs and uploaded documents, and keep a source quote and page reference with every fact.
2. **Rules as config.** The SOP becomes a versioned YAML file, schema-checked when the app starts. The decision engine stays plain code that reads it, so a rule change is a reviewed config change, not a code change.
3. **Bounded agent loop.** The model extracts, code checks, and failed checks go back to the model with the exact errors, up to 3 attempts. Then the client goes to the paralegal queue.
4. **Human review.** A paralegal approves, edits or overrides every decision before it reaches the client. Overrides need a reason and are logged.
5. **Guardrails.** Role-based masking of A-numbers and addresses, an append-only audit log, no client data in logs, and a model provider contract that rules out training on client data.
6. **Evals in CI.** These 36 clients, plus every real-world miss, become a regression suite that must pass 100% before any rule or prompt change ships.
7. **Speed and cost.** Cache extractions by document hash, process clients in parallel, and use a smaller model for clean documents, keeping the larger one for hard cases.

Proposed rules.yaml (the SOP as config):

```yaml
version: 1
evidence_order: [CBP_FOIA, CARRIER_DOCUMENT, CLIENT_STATEMENT]
not_evidence: [HOTEL_RECEIPT]
match_window_days: 3
lookback_years: 5
early_filing_days: 90
bases:
  five_year: {years: 5, min_days_present: 913}
  three_year_marriage:
    years: 3
    min_days_present: 548
    requires: [married_3_years, spouse_citizen_3_years, no_separation]
absences:
  presumed_break:
    longer_than_months: 6
    rebuttal: {min_distinct_types: 2, must_cover_whole_absence: true,
               types: [US_EMPLOYMENT_LETTER, RESIDENT_TAX_RETURN, US_LEASE_OR_DEED]}
  break:
    at_least_years: 1
  wait_after_break:
    default: {five_year: "4y+6m", three_year: "2y+6m"}
    one_year_rebutted: {five_year: "4y+1d", three_year: "2y+1d"}
    early_filing_window: false
state_residence_months: 3
statuses: [FILE_NOW, SCHEDULE, REQUEST_EVIDENCE]
escalation: {max_model_attempts: 3, queue: paralegal_review}
```
