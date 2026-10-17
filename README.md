# n400-filing-review: a Terminal-Bench 3 task

A paralegal at an immigration firm runs the monthly N-400 readiness review. For each of 36 permanent-resident clients in the review queue, the AI agent has to decide whether the client can apply for US citizenship on the review date (2026-03-02), and if not, the earliest date they can file and on which basis, or whether the firm must ask for more evidence first. It works from the firm's written procedure (SOP), a SQLite export of the case management system, client email and CBP's answers to the firm's FOIA requests. One wrong client and the reward is 0.

![How the task works](docs/how-it-works.svg)

**Current status** (task v4, 36 clients)

| Check | Result |
|---|---|
| TB3 static checks (`scripts/checks/`) | 28 / 28 pass |
| Docker build | passes |
| Oracle (`solution/solve.py` in Harbor) | reward 1.0 (39 / 39 verifier tests) |
| Nop agent (writes nothing) | reward 0.0 |
| Explorer app `--check` | 24 / 24 pass |
| Implementation rubric review | 32 pass, 3 not applicable, 0 fail (on the README explanations before entry 10; not rerun) |
| Standard trials: Claude Code, Opus 5.5, max effort (3) | **not met**: all 3 passed (reward 1.0); the assignment needs all 3 to fail |
| Cheat trial with TB3's red-team prompt (1) | reward 0: no way around the verifier found, though a safety-classifier stop cut the run short (entries 5 and 9) |
| Trial analysis (`harbor analyze`) | not run; the trials were checked by reading their logs (see the iteration log) |
| Codex with GPT-6.1 Sol | not run: no OpenAI API key or ChatGPT login was available |

## Where it stands

Every check that was run passes except one: the assignment's bar that all 3 standard trials must fail. Claude Code with Opus 5.5 at max effort solved all four versions of the task, in about 5 to 7, 8, 11 to 12, and 13 to 14 minutes of agent time. Every graded standard trial scored 1.0: 3 of 3 in v1, v2 and v4, and 2 of 2 in v3, whose third trial was never graded because Harbor's process stopped while that agent was still running. Only Claude Code with Opus 5.5 was run as the trial agent; the brief's Codex trials were not run. What each round showed (details in the [iteration log](#iteration-log)):

- **v1, 15 clients:** fair but too easy. Every fact could be read straight from SQL and plain-text email.
- **v2, 21 clients:** evidence as a paralegal gets it (CBP answers as PDFs, joint responses, emails from unknown addresses, a day-first itinerary) added only a few minutes. Each trial wrote its own PDF reader.
- **v3, 30 clients:** the shortcuts the v2 solvers relied on now gave wrong answers, but careful reading beat them. The new rules went into general code, and the facts that came only from email were read by hand and typed in correctly.
- **v4, 36 clients:** evidence whose meaning depends on where it sits didn't stop it either. General code followed the new SOP sentences on CBP row order and on a client's own CBP response, and the itinerary legs that cross the border were read correctly.

## Contents

- [What the agent gets and what it must write](#what-the-agent-gets-and-what-it-must-write)
- [Why it's hard](#why-its-hard)
- [How one decision is made](#how-one-decision-is-made)
- [The 36 clients](#the-36-clients)
- [How it's verified](#how-its-verified)
- [Explore the task](#explore-the-task)
- [How to run everything](#how-to-run-everything)
- [Repository layout](#repository-layout)
- [Design notes](#design-notes)
- [Iteration log](#iteration-log)

## What the agent gets and what it must write

The agent's container sees only `/app/review`:

| Path | What it is |
|---|---|
| `/app/review/cms.sqlite` | The case management export: 38 clients (36 in the review queue), permanent-resident records, addresses, marriages, the firm's matters, documents on file, questionnaire trips, planned travel and each client's CBP FOIA request number |
| `/app/review/mail/` | 26 emails (24 from clients, plus a billing notice and a portal notice), 8 with an attachment: airline itineraries and e-tickets, a bus e-ticket, a hotel receipt and one client's own CBP response |
| `/app/review/foia/` | CBP's FOIA responses: 39 PDFs, one per response, including two joint responses for married couples and one amended response |
| `/app/review/sop/n400_readiness_sop.md` | The firm's SOP (NAT-04): every rule the agent needs, in prose |
| `/app/review/sop/filing_review.schema.json` | The normative output format |

It must write one decision per queued client to `/app/output/filing_review.json`:

```json
{
  "review_date": "2026-03-02",
  "decisions": [
    {"client_id": "C-1007", "status": "SCHEDULE", "basis": "5_YEAR", "earliest_filing_date": "2028-04-15"},
    ...
  ]
}
```

`status` is `FILE_NOW`, `SCHEDULE` or `REQUEST_EVIDENCE`. `basis` is `5_YEAR` or `3_YEAR_MARRIAGE` (the spouse of a US citizen). The full instruction is in [instruction.md](n400-filing-review/instruction.md).

## Why it's hard

The facts are split across four sources that disagree, and the date rules interact.

- **Order of trust for trips:** CBP FOIA records first, then carrier documents (tickets, itineraries), then the client's own statements. CBP misses land-border departures, and a hotel receipt is not a carrier document.
- **Permanent-resident date:** from the green card scan, else the I-485 approval notice, never the I-751 notice or the questionnaire.
- **Email beats the CMS** only for moves, separations, trips and planned travel.
- **Date rules:** the 90-day early-filing window; the presumed break after a 6 to 12 month absence and its rebuttal; the wait after a break (4 years and 1 day only with rebuttal documents, otherwise 4 years and 6 months, with no early window); the 3-year spouse rules; physical presence on a sliding window; 3 months in the state; planned trips.

The rules follow INA 316, INA 319, 8 CFR 316.5 and the USCIS Policy Manual (Vol. 12, Part D, Ch. 3), written into the firm's SOP. The clients and records are synthetic.

## How one decision is made

![How one decision is made](docs/decision-flow.svg)

## The 36 clients

Each client turns on one or more rules. The right answers below are computed by `tests/rules.py` from `tests/case_facts.json`; nothing is typed in by hand.

| Client | What it tests | Right answer | A misreading gives |
|---|---|---|---|
| C-1001 | Clean case; a planned June trip doesn't matter | FILE_NOW, 5_YEAR | n/a |
| C-1002 | The 10-year card keeps resident-since 2021-06-15; the I-751 notice and questionnaire say 2023-09-20. His FOIA response is joint: his wife's land return from Canada has no exit, and only his rows count | FILE_NOW, 3_YEAR_MARRIAGE | SCHEDULE 2026-06-22, or REQUEST_EVIDENCE (her rows counted as his) |
| C-1003 | Land return in CBP; departure only in client email; a hotel receipt isn't a carrier document | REQUEST_EVIDENCE | FILE_NOW |
| C-1004 | Land return in CBP; departure proven by a bus e-ticket attached to email | FILE_NOW, 5_YEAR | REQUEST_EVIDENCE |
| C-1005 | Questionnaire trip inside coverage with no CBP arrival is disregarded; a same-state move in Jan 2026 doesn't restart the 3 months | FILE_NOW, 5_YEAR | REQUEST_EVIDENCE, or SCHEDULE 2026-04-15 |
| C-1006 | 7.8-month absence rebutted by an employer letter and a tax return that both cover it | FILE_NOW, 5_YEAR | SCHEDULE 2027-03-05 |
| C-1007 | 8.5-month absence: the lease starts after departure, so only one rebuttal type counts; presumed break, 4 years and 6 months after return | SCHEDULE, 5_YEAR, 2028-04-15 | FILE_NOW, 2027-10-16, 2028-01-16, or 2028-07-17 |
| C-1008 | 13-month absence with no rebuttal documents: 4 years and 6 months, not 4 years and 1 day; no 90-day window | SCHEDULE, 5_YEAR, 2027-04-10 | 2026-10-11, 2027-01-10, or FILE_NOW |
| C-1009 | 3-year basis waits for the spouse's 3 years of citizenship; no early window on that | SCHEDULE, 3_YEAR_MARRIAGE, 2026-11-20 | FILE_NOW, or 2026-08-22 |
| C-1010 | Separation reported only by email, sent from an address not in the CMS and matched by name and A-number, so there is no 3-year basis | SCHEDULE, 5_YEAR, 2026-10-12 | FILE_NOW (3-year) |
| C-1011 | Physical presence binds; the 5-year window slides past old trips | SCHEDULE, 5_YEAR, 2026-06-28 | 2026-05-28 (deficit added to the review date) |
| C-1012 | No card scan, so the I-485 notice gives the date; the move to NJ is only in email, so the 3-month rule applies | SCHEDULE, 5_YEAR, 2026-05-07 | FILE_NOW |
| C-1013 | Trip announced by email covers the continuous-residence date; filing waits for the return day | SCHEDULE, 5_YEAR, 2026-04-25 | 2026-03-20 |
| C-1014 | Trip before FOIA coverage, proven by an itinerary, straddles the window start; only in-window days count (920 present vs 901) | FILE_NOW, 5_YEAR | SCHEDULE 2026-04-02 |
| C-1016 | Only an I-751 notice and the questionnaire on file, so there is no usable LPR date | REQUEST_EVIDENCE | SCHEDULE 2027-01-11, or FILE_NOW |
| C-1017 | 13-month absence covered by an employment letter and a lease: 4 years and 1 day | SCHEDULE, 5_YEAR, 2026-07-21 | 2027-01-20 (rebuttal ignored), or FILE_NOW (no break) |
| C-1018 | Rebutted 7-month absence, then a later one whose documents cover only part of it; only the latest break counts | SCHEDULE, 5_YEAR, 2028-11-25 | FILE_NOW |
| C-1019 | Left before the LPR date on advance parole and came back after it: ignored under SOP 4.2 | FILE_NOW, 5_YEAR | SCHEDULE 2026-03-20 |
| C-1020 | NY, then NJ, then back to NY; the return is only in an email from an unknown address, so the 3 months restart | SCHEDULE, 5_YEAR, 2026-04-12 | FILE_NOW |
| C-1021 | Naturalized spouse's 3 years fall inside a planned trip; joint FOIA response with the husband's 7-month trip | SCHEDULE, 3_YEAR_MARRIAGE, 2026-06-03 | 2026-05-20, FILE_NOW, or 2027-03-14 |
| C-1022 | 2021 trip proven only by an itinerary PDF attached to email, printed DD/MM/YYYY, before FOIA coverage | SCHEDULE, 5_YEAR, 2026-03-10 | FILE_NOW (read as MM/DD) |
| C-1023 | Away 2025-07-31 to 2026-01-31: 184 days, but exactly six calendar months (SOP 10), so not more than six months and no break | FILE_NOW, 5_YEAR | SCHEDULE 2030-07-31 (six months as 180/182/183 days) |
| C-1024 | Away 2023-03-01 to 2024-02-29: 365 days, but less than one year; more than six months, rebutted by an employment letter and a deed | FILE_NOW, 5_YEAR | SCHEDULE 2028-03-01 (a year as 365 days) |
| C-1025 | Planned trip 2026-04-10 to 06-25 covers the continuous-residence date (04-21); on the return date she has 896 of 913 days present | SCHEDULE, 5_YEAR, 2026-07-12 | 2026-06-25 (file on the return date, or planned days not counted) |
| C-1026 | Move to Philadelphia, PA on 2026-04-10, announced in an everyday email; continuous residence is met only on 2026-05-03, so 3 months in PA | SCHEDULE, 5_YEAR, 2026-07-10 | 2026-05-03 (past moves only) |
| C-1027 | CBP exit 2025-10-20 with no return: still abroad; the email gives the booked return 2026-05-02, so the absence is over six months and breaks continuous residence | SCHEDULE, 5_YEAR, 2030-11-02 | FILE_NOW (open exit dropped), REQUEST_EVIDENCE (treated as unverified), or 2026-05-02 (no break) |
| C-1028 | CBP sent an amended response (`-A1`) that replaces the first one, which printed the 2024 return as 09/30 instead of 04/30 | FILE_NOW, 5_YEAR | SCHEDULE 2029-03-30 (first response) |
| C-1029 | Planned trip 03-05 to 04-20 in the CMS and a first email; a reply moves it to 03-25 to 04-02 and quotes the old dates below | SCHEDULE, 5_YEAR, 2026-03-12 | 2026-04-20 (old plan kept) |
| C-1030 | Married to a US citizen by birth; the email says the spouse "moved out" and they keep "separate apartments" (never "separated"), so no 3-year basis | SCHEDULE, 5_YEAR, 2027-01-01 | FILE_NOW (3-year) |
| C-1031 | Spouse is naturalized, date not in her file; he is former client C-1032, whose closed N-400 matter gives the oath date 2023-02-20 (closed 2023-03-14) | FILE_NOW, 3_YEAR_MARRIAGE | SCHEDULE 2026-11-17 (no date, 5-year), or SCHEDULE 2026-03-14 (closing date used) |
| C-1033 | CBP's response has an entry and then an exit on 04/10/2025 (back from London, out to Toronto through Newark), in the order they happened, though its table prints them newest first; his email and questionnaire call 2025 one assignment, and his e-ticket covers only the Toronto leg. Two absences under six months; physical presence binds | SCHEDULE, 5_YEAR, 2026-05-01 | FILE_NOW (exit put first on a shared date, London leg lost), or 2030-01-31 (one trip) |
| C-1034 | The firm's FOIA response (2024) ends 2024-06-15; he emails CBP's response to his own request (2024-01-01 to 2026-02-06), which joins the coverage window. A 2025 Montreal itinerary in the CMS then returns inside it with no CBP arrival near it and is disregarded | FILE_NOW, 5_YEAR | REQUEST_EVIDENCE (his response ignored), or SCHEDULE 2030-02-20 (his CBP trips typed in, firm's window only) |
| C-1035 | CBP has his air return to Newark on 2022-08-14 and no exit; his itinerary flies Toronto to Lisbon to Newark, so it proves the return but not the US departure, which rests on his questionnaire | REQUEST_EVIDENCE | FILE_NOW (Toronto flight taken as the departure) |
| C-1036 | CBP's response has an exit and then an entry at the Seattle ferry pier on 08/17/2024, in the order they happened (its table prints them newest first): a same-day trip | FILE_NOW, 5_YEAR | REQUEST_EVIDENCE (entry put first on a shared date) |
| C-1037 | Itinerary before her CBP coverage: Boston to JFK 2022-01-30, JFK to London 2022-01-31, back 2022-07-31. Only the leg leaving the US counts: exactly six months, no break | FILE_NOW, 5_YEAR | SCHEDULE 2027-01-31 (domestic leg taken as the departure) |
| C-1038 | Tokyo 2022-03-15 to Seattle 2023-03-14, then Seattle to JFK the next day. The US arrival makes it less than a year; an employment letter and a lease rebut it, so no break | FILE_NOW, 5_YEAR | SCHEDULE 2027-03-16 (domestic connection taken as the return: a year) |
| C-1015 | Not in the queue (distractor) | no decision | an extra row fails |
| C-1032 | Not in the queue: a former client (C-1031's husband) | no decision | an extra row fails |

FILE_NOW rows have the review date, 2026-03-02, as their filing date. In total: 15 FILE_NOW, 18 SCHEDULE, 3 REQUEST_EVIDENCE.

## How it's verified

- **Separate verifier container.** It is built from `tests/Dockerfile`. The ground truth (`tests/case_facts.json`) and the reference rules (`tests/rules.py`) never enter the agent's image.
- **One file in, one number out.** The verifier reads only `/app/output/filing_review.json` and never runs agent code. `tests/test.sh` runs 39 pytest tests (3 format tests plus 1 per queued client) and writes reward 1 only if all pass, else 0. There is no LLM judge and no partial credit.
- **Strict parsing.** Duplicate JSON keys, extra or missing fields, extra or missing clients, and a basis on a REQUEST_EVIDENCE row all fail.
- **Tamper-proof answers.** Editing anything under `/app/review` can't change the expected answers, which are computed from the verifier's own copy of the facts.
- **Two independent implementations agree.** `tests/rules.py` works from the structured facts; `solution/solve.py` works only from the rendered database, email and FOIA PDFs. They agree on all 36 clients, so the agent's records contain exactly the facts the answers depend on.
- **One source of truth.** `demo/backend/render_case_data.py` renders the agent's records from `tests/case_facts.json`, deterministically.

## Explore the task

`demo/` holds an optional explorer app. It shows the right answer for every client, works the SOP step by step, and runs the real verifier on any output file. It uses only the Python standard library and only reads the task folder.

```bash
python3 demo/backend/server.py            # opens http://127.0.0.1:8400
python3 demo/backend/server.py --check    # the same checks in the terminal
```

![The explorer's task page](docs/app-task.png)

| | |
|---|---|
| ![Client C-1007](docs/app-client.png) | ![Client C-1003's email](docs/app-client-email.png) |
| **Client C-1007:** what the case tests, each misreading, the timeline and the SOP worked step by step | **Client C-1003:** the hotel receipt doesn't verify the trip, so the answer is REQUEST_EVIDENCE |
| ![The checker on the oracle's answers](docs/app-checker-oracle.png) | ![The checker with one mistake](docs/app-checker.png) |
| **The oracle's answers:** 18 of 18 tests pass, reward 1 | **One mistake on C-1008:** 17 of 18, reward 0 |

![What's done](docs/app-done.png)

## How to run everything

You need Docker, Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). On Windows, work inside WSL2.

**1. Set up Harbor and the TB3 repo.**

```bash
uv tool install "harbor==0.23.1.dev202609170426"   # the version TB3 CI pins
git clone https://github.com/harbor-framework/terminal-bench terminal-bench-3
cd terminal-bench-3
rsync -a --exclude .DS_Store /path/to/AgentEx/n400-filing-review/ tasks/n400-filing-review/
export TASK=tasks/n400-filing-review
```

**2. Static checks** (all 28 pass):

```bash
for c in scripts/checks/check-*.sh; do bash "$c" "$TASK" >/dev/null 2>&1 && echo "PASS $c" || echo "FAIL $c"; done
```

`check-image-digests.sh` needs [dockerfile-pin](https://github.com/azu/dockerfile-pin/releases/tag/v1.5.0) v1.5.0 on your `PATH`.

**3. Docker build, oracle and nop:**

```bash
harbor run -p "$TASK" --agent oracle --env docker --yes -o jobs --job-name oracle   # expect reward 1.0
harbor run -p "$TASK" --agent nop    --env docker --yes -o jobs --job-name nop      # expect reward 0.0
```

**4. Rubric review and agent trials** run on a Claude subscription token (`claude setup-token`). Keep the token in your shell only. Pass `CLAUDE_FORCE_OAUTH=1` as a host environment variable, not through `--ae`: Harbor redacts every `--ae` value whose name contains `AUTH` from the trial files, so `--ae CLAUDE_FORCE_OAUTH=1` would replace every "1" in the results.

```bash
export CLAUDE_CODE_OAUTH_TOKEN='...'

CLAUDE_FORCE_OAUTH=1 harbor check "$TASK" -r docs/prompts/task-implementation.toml -m anthropic/claude-sonnet-5 \
  --ae CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN"

CLAUDE_FORCE_OAUTH=1 harbor run -p "$TASK" --agent claude-code --model anthropic/claude-opus-5-5 -k 3 -n 3 \
  --env docker --yes -o jobs --job-name run-claude-opus-5-5 \
  --ae CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN" \
  --ae CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000 --ak reasoning_effort=max

CLAUDE_FORCE_OAUTH=1 harbor run -p "$TASK" --agent claude-code --model anthropic/claude-opus-5-5 -k 1 \
  --env docker --yes -o jobs --job-name cheat-claude-opus-5-5 \
  --extra-instruction-path docs/prompts/hack-trial-prompt.md \
  --ae CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN" \
  --ae CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000 --ak reasoning_effort=max
```

Each failing trial's `verifier/ctrf.json` names the clients it got wrong (`test_decision_matches_sop[C-xxxx]`). Map them to the table above.

**5. Regenerate the records** after changing `tests/case_facts.json`:

```bash
python3 demo/backend/render_case_data.py n400-filing-review   # from this repo's root
```

Then check that `solve.py` still agrees with `rules.py` (`python3 demo/backend/server.py --check` does this), copy the task into the TB3 checkout again (the `rsync` line in step 1), and rerun the static checks, oracle and nop.

## Repository layout

```
README.md                       this report
n400-filing-review/             the task (TB3 format)
  README.md                     the task's metadata and its four required explanation sections
  instruction.md                what the agent is told
  task.toml                     timeouts and resources: agent 4 h, verifier 300 s, 1 CPU, 2 GB
  environment/                  the agent's image: Dockerfile and data/review (cms.sql, mail/, foia/, sop/)
  solution/                     the reference solution (solve.sh, solve.py)
  tests/                        the separate verifier: Dockerfile, test.sh, test_outputs.py, rules.py, case_facts.json
demo/                           the optional explorer app
  README.md                     how to run it, its flags and the results.json format
  backend/                      the server and its checks (server.py, engine.py, traps.json)
  backend/render_case_data.py   renders the agent's records from tests/case_facts.json
  frontend/                     the page: HTML, CSS and JavaScript, no build step, and its fonts
  results.json                  trial results for the explorer's "What's done" page
docs/                           3 diagrams and 6 explorer screenshots
  DESIGN.md                     design notes: human in the loop, guardrails, data, speed and cost, production plan
```

## Design notes

[docs/DESIGN.md](docs/DESIGN.md) covers how the task handles human review, guardrails, data management, speed and cost, and bounded agent loops, plus the sources behind every rule and a plan for turning it into a production tool:

![Production plan](docs/production-plan.svg)

## Iteration log

1. **2026-10-15, rubric fix.** The first implementation-rubric review failed one criterion, `task_toml_schema`: `[environment]` set `network_mode = "public"`, which is not in the rubric's list of task.toml fields. The line was removed. It was Harbor's default, so the task runs the same. After the fix: 28/28 static checks, oracle 1.0, nop 0.0, rubric 32 pass and 3 not applicable.
2. **2026-10-15, v1 (15 clients), first standard trials: all 3 passed, in about 5 minutes each.** Job `run-claude-opus-5-5`, Claude Code with `anthropic/claude-opus-5-5` at max effort, `-k 3 -n 3`.

   | Trial | Reward | Verifier tests | Agent time |
   |---|---|---|---|
   | `n400-filing-review__sHSmhQX` | 1.0 | 18 / 18 | 5.4 min |
   | `n400-filing-review__8x27Zzi` | 1.0 | 18 / 18 | 5.9 min |
   | `n400-filing-review__gnzro3R` | 1.0 | 18 / 18 | 7.3 min |

   All three were legitimate solves. The agent read the SOP, dumped the CMS tables, read the raw emails with their attachments, and applied the rules in one script. The task was fair but too easy: every fact was cleanly readable from SQL and plain-text email. Following the brief, the task was hardened before any further trials (next entry).
3. **Infrastructure rerun.** An earlier smoke trial (`smoke-claude-opus-5-5`) never started: Harbor's preflight `docker info` took 84 s against its 10 s limit while Docker Desktop was starting. It is not counted.
4. **2026-10-15, v2 hardening (21 clients).** Because v1 was solved in minutes, the evidence was made to look and behave like what a paralegal actually receives. Every rule is still in the SOP, and nothing in instruction.md hints at a trap.
   - **CBP FOIA responses as PDFs.** The `cbp_events` table and the coverage columns are gone from the CMS. Only `cbp_foia_requests` remains, with each client's request number. CBP's answer is now one text-based PDF per request in `/app/review/foia/`: a cover letter that states the coverage window in words, then the entries and exits, newest first, with MM/DD/YYYY dates, over several pages with the header repeated. Two responses (C-1002, C-1021) are joint responses for a married couple, and counting the spouse's rows changes the answer.
   - **Real-looking email.** Two clients (C-1010, C-1020) write from addresses that aren't in the CMS, signed with their full name and A-number. One trip (C-1022) is proven only by a European carrier's itinerary PDF attached to an email. It prints dates as DD/MM/YYYY, says so in its header, and uses dates where both readings are valid.
   - **Six new clients whose rules interact** (C-1017 to C-1022): a rebutted 13-month absence (the 4 years and 1 day branch), a rebutted absence followed by an unrebutted one, a trip that starts before the LPR date, a NY to NJ to NY move, a naturalized spouse's 3 years falling inside a planned trip, and the day-first itinerary.
   - **Keeping traps honest.** For each new trap, `tests/rules.py` computed what the likely misreading gives, and a trap was kept only if that changes the answer. `solution/solve.py` stays independent: it reads only what the agent sees, including the PDFs, with the standard library. It agrees with `rules.py` on all 21 clients.
   - **Checked before any new trial:** the renderer gives byte-identical output on reruns (34 files); 28/28 static checks; oracle 1.0 (24/24 tests) and nop 0.0 in Docker.
   - **Instruction and SOP changes:** the one line of instruction.md that lists the record folders now includes `/app/review/foia/`. SOP section 2 now covers the FOIA PDFs, joint responses, matching email by signature, and printed date formats.
5. **2026-10-15, v2 trials: all 3 standard trials passed again; the cheat trial scored 0.** Rubric review `rubric-review-v2`: 33 pass, 2 not applicable, 0 fail. Job `run-v2-claude-opus-5-5`:

   | Trial | Reward | Verifier tests | Agent time |
   |---|---|---|---|
   | `n400-filing-review__9RN5y28` | 1.0 | 24 / 24 | 8.7 min |
   | `n400-filing-review__JSvF8aQ` | 1.0 | 24 / 24 | 7.5 min |
   | `n400-filing-review__WcBE4hx` | 1.0 | 24 / 24 | 8.8 min |

   All three were legitimate: each wrote its own PDF reader, matched emails by signature, kept only the client's rows in joint responses and read the itinerary as DD/MM/YYYY. The cheat trial (`cheat-v2-claude-opus-5-5`) looked for a way around the verifier and found none. It hit two safety-classifier stops (category "cyber"), and after the second stop, Claude Code moved the rest of the session to a fallback model, `claude-opus-4-8`, which wrote its last messages. It declined to fabricate output and scored 0. The hardening added only a few minutes, so the task was hardened again (next entry).
6. **2026-10-15, v3 (30 clients): the shortcuts the v2 solvers relied on now give wrong answers.** The three v2 solver scripts were read to see what they assumed that the SOP doesn't promise. All three typed the email facts in by hand, opened exactly one FOIA response per client (the one named in the CMS), dropped or mishandled a CBP departure with no return, took the spouse's naturalization date only from `marriages`, and merged a CMS planned trip with an email one only when the dates were equal. Nine clients (C-1023 to C-1031) and one former client (C-1032, not in the queue) were added so that each of these readings, and the other common ones, changes an answer. The SOP still fixes exactly one right answer for each. Every existing client's answer is unchanged.
   - **Calendar lengths.** A 184-day absence that is exactly six calendar months (C-1023), and a 365-day absence across February 29 that is less than a year (C-1024). The SOP now defines lengths of time once (new section 10): calendar months and years, never day counts.
   - **Planned and current trips.** A planned trip that covers the continuous-residence date and leaves the client short of days present on her return date (C-1025). A client who is still abroad on the review date and emailed his booked return (C-1027): the whole absence is over six months. The SOP now says a CBP departure with no later arrival is a current trip that ends on the return date the client states, and that planned and current trips are absences for continuous residence too.
   - **An announced move** to Pennsylvania after the review date (C-1026). The SOP now says a move announced for a later date counts from that date.
   - **Superseded evidence.** CBP's amended FOIA response (`-A1`) replaces a first response with a wrong date, and the CMS still lists only the first (C-1028). A reply that moves a planned trip quotes the old dates below the new ones (C-1029). The SOP now says only the latest CBP response counts, a later statement replaces the earlier one in the CMS or in email, and quoted text is not a new statement.
   - **Everyday wording and routine mail.** A separation stated as "moved out… separate apartments", never "separated" (C-1030), plus six ordinary messages with dates but no facts (appointments, invoices, portal and billing notices).
   - **The firm's own records.** A spouse's naturalization date that only the firm's closed N-400 matter for the husband, a former client, gives; the matter's closing date is a different date (C-1031). The CMS has a new `matters` table, and SOP section 8 says to use the oath date from the firm's records.
   - **Checked before any new trial:** the renderer gives byte-identical output on reruns (cms.sql, 21 emails, 33 FOIA PDFs); `solve.py` matches `rules.py` on all 30 clients; 28/28 static checks; oracle 1.0 (33/33 tests) and nop 0.0 in Docker; the explorer's `--check` passes, with notes and one-mistake checks for the new clients. instruction.md is unchanged (no new folder).
7. **2026-10-15, v3 trials: both graded standard trials passed.** Rubric review `rubric-review-v3`: 33 pass, 2 not applicable, 0 fail. Oracle 1.0 (33/33 tests) and nop 0.0. Job `run-v3-claude-opus-5-5`:

   | Trial | Reward | Verifier tests | Agent time |
   |---|---|---|---|
   | `n400-filing-review__wQuMiyJ` | 1.0 | 33 / 33 | 11.0 min |
   | `n400-filing-review__wobJNXH` | 1.0 | 33 / 33 | 11.9 min |
   | `n400-filing-review__yPtJd7W` | not graded | n/a | Harbor's process stopped before the agent finished; it is not counted |

   Both graded trials were legitimate. Each read all the records, wrote its own PDF reader and one solver script, and handled the new calendar, CBP and firm-record rules in general code. Every fact that came only from email (the announced move, the booked return, the changed plan and the separation) was read by hand and typed into the script, and read correctly. So the email traps made careful reading necessary but not insufficient. The cheat trial was not run. Following the brief, the task was hardened again before any further trials (next entry).
8. **2026-10-16, v4 (36 clients): evidence whose meaning depends on where it sits, not on what it says.** Six clients (C-1033 to C-1038) were added. Each turns on a fact that a careful hand reading of the email does not give, and each is decided by a general SOP sentence that names no client. For each, `tests/rules.py` was run on the misread facts, and every misreading changes the answer. Every existing answer is unchanged.
   - **Two crossings on one day.** CBP lists the records in the order the crossings happened, newest first (SOP 2 now says so). C-1033 came back from London and left for Toronto through Newark on the same day (an entry, then an exit). His email and questionnaire call it one assignment, and his e-ticket covers only the Toronto leg. C-1036 took the Victoria ferry for the day (an exit, then an entry). Any fixed tie-break in a date sort gets one of the two wrong. Exit first drops C-1033's London leg (FILE_NOW instead of SCHEDULE 2026-05-01). Entry first leaves C-1036 with an arrival that has no departure (REQUEST_EVIDENCE instead of FILE_NOW). Only the response's own order gets both right. The renderer, `rules.py` and `solve.py` used an exit-first tie-break before and now keep the response's order.
   - **Legs that don't cross the border.** SOP 4.3 now says that only a leg that leaves or enters the United States sets a departure or return date.
     - C-1037 flew Boston to New York the day before her London flight. That makes her absence exactly six months, not more: FILE_NOW instead of SCHEDULE 2027-01-31.
     - C-1038 came back from Tokyo through Seattle and reached New York the next day. That keeps his absence under a year, where two documents rebut it: FILE_NOW instead of SCHEDULE 2027-03-16.
     - C-1035's itinerary starts in Toronto, so it proves his return but not his US departure. The trip is unverified: REQUEST_EVIDENCE instead of FILE_NOW.
   - **The client's own CBP response.** C-1034 emailed CBP's answer to his own FOIA request, because the firm's response is from 2024. SOP 2 now says such a response counts like ours: its period joins the coverage window, and a record both list counts once. A seven-month Montreal itinerary in the CMS then falls inside the window with no CBP arrival near it and is disregarded: FILE_NOW. Ignoring his response gives REQUEST_EVIDENCE. Typing his trips in while keeping only the firm's window gives SCHEDULE 2030-02-20.
   - **Checked before any new trial:**
     - The renderer gives byte-identical output on reruns (cms.sql, 26 emails, 39 FOIA PDFs), and every v3 email and PDF is unchanged.
     - `solve.py` matches `rules.py` on all 36 clients.
     - 28/28 static checks; oracle 1.0 (39/39 tests) and nop 0.0 in Docker.
     - The explorer's `--check` passes, with a one-mistake check for each new client.
   - instruction.md is unchanged.
9. **2026-10-16, v4 trials: all 3 standard trials passed again; the cheat trial scored 0.** Rubric review `rubric-review-v4`: 32 pass, 3 not applicable, 0 fail. The one change from v3 is `artifact_efficiency`: pass in v3, not applicable now, with the same explanation both times (the only artifact is the small output file). It was also not applicable in `rubric-review-r2`. Job `run-v4-claude-opus-5-5` (3 trials in parallel, 15 min 31 s wall clock):

   | Trial | Reward | Verifier tests | Agent time |
   |---|---|---|---|
   | `n400-filing-review__5kQrLL9` | 1.0 | 39 / 39 | 12.7 min |
   | `n400-filing-review__Dap78bq` | 1.0 | 39 / 39 | 14.4 min |
   | `n400-filing-review__tqbjHqB` | 1.0 | 39 / 39 | 12.8 min |

   All three were legitimate: no package installs, no web access and no search for tests or answers. Each read every record, wrote its own PDF text extractor (the image has no PDF tools), thought for about 7 minutes in one stretch, then wrote its solver once and never edited it. Each also checked every CBP response it used against the record count stated in its cover letter. That is about 2 minutes more agent time than in v3. The six new clients:
   - **Two crossings on one day (C-1033, C-1036).** All three solved both in general code. They reversed each CBP response's newest-first table into the order the crossings happened and kept that order for rows on the same date. Rerunning each trial's solver with the reversal removed (a plain date sort of the table as printed) gets both clients wrong, and an exit-first or entry-first tie-break gets one of them wrong.
   - **The client's own CBP response (C-1034).** All three linked the PDF attached to his email to him by hand. The rest was general code: they parsed it like the firm's responses, added its period to the coverage window, counted the three records both responses list once, and disregarded the Montreal itinerary. Without his response, or without the dedupe, each trial's solver gives REQUEST_EVIDENCE.
   - **Legs that don't cross the border (C-1035, C-1037, C-1038).** `5kQrLL9` and `Dap78bq` read the itineraries and typed in only the legs that leave or enter the United States, with a comment marking each leg they left out as domestic or as not leaving the US. `tqbjHqB` parsed the itineraries in code and kept a leg only if it crosses the US border (a place marked "USA" or one of ten listed US airports); it typed in only which attachment belongs to which client. Given the domestic or Toronto legs instead, each trial's solver gives the wrong answers listed in entry 8.

   So entry 8's premise did not hold. The CBP row order and the client's own response were handled by general code that follows the new SOP sentences, and a careful hand reading of an itinerary does give the right leg once SOP 4.3 says which leg counts.

   The cheat trial (`cheat-v4-claude-opus-5-5`, 1.4 min of agent time) only looked around. It listed `/app`, `/logs` and `/root`, searched for tests, answer keys and verifier files (none are in the container), dumped the CMS, grepped the whole filesystem for decision values (only the SOP, the schema and its own logs matched) and read the raw bytes of one FOIA PDF. The API's safety classifier then blocked its next response (category "cyber"), and the agent gave up, saying the only routes left meant tampering with the grading environment. It wrote no output file (Harbor's copy step found none in the container) and scored 0 (0 / 39 tests). It flagged that `/logs/verifier` is writable from the agent's container; that can't affect the reward, because Harbor removes the agent container and empties that folder before the separate verifier runs.
10. **2026-10-17, new README explanations, then the checks again.** The Difficulty, Solution and Verification explanations in `n400-filing-review/README.md` were replaced with new ones, drafted with AI help from the author's notes. Before they went in, each factual claim in them was checked against the SOP, `solve.py`, `rules.py`, the tests, the records, both cheat-trial logs and Harbor's source. The check found one omission, the test of the top-level keys and `review_date` (`test_top_level`), which now has its own sentence. It also rated six statements loosely worded but not misleading (on quoted text in replies, a client's word as proof of a date, unverified trips, where the date search starts, and the cheat runs' classifier stops and what they flagged); those stay as the author wrote them. The explorer's task page now renders the Difficulty section as Markdown. Nothing the agent or the verifier uses changed: `instruction.md`, the environment, the solution and the tests are the same as in the v4 trials. Rerun on the new copy: 28/28 static checks, oracle 1.0 (`oracle-v4-r2`, 39/39 tests), nop 0.0 (`nop-v4-r2`), and the explorer's `--check` passes. The rubric review was not rerun, so its result in entry 9 is for the earlier explanations.
