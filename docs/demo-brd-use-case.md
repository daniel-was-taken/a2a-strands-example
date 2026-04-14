# Demo: Fetch Records and Create a BRD

This is the demo script for the staged A2A use case in the repository.

## Problem Statement

The use case is: a user wants to fetch real records from a data source and turn that evidence into a
business requirements document.

The hard part is not just retrieval. The system needs to:

- fetch trustworthy evidence from the data source
- separate confirmed facts from assumptions
- pause for a human to validate the evidence before the document is drafted
- produce a mixed-audience BRD with explicit gaps and risks

## What the Framework Does to Fix It

The implemented flow is staged on purpose.

1. The orchestrator detects a combined fetch + BRD request.
2. The Database Agent fetches data and returns a structured evidence summary.
3. The conversation pauses in `awaiting_brd_confirmation`.
4. A human confirms the evidence.
5. The BRD Specialist drafts the document.
6. The Graph Reviewer reviews and improves the draft.
7. The final BRD is returned in the same conversation.

That structure reduces unsupported claims and makes the human approval point visible during the demo.

## Demo Setup

```bash
source .venv/bin/activate
python run_system.py
```

Open `http://localhost:8000`.

## Demo Script in the UI

1. Create a new conversation.
2. Send this prompt:

```text
Fetch records and create a BRD for onboarding issues.
```

After sending the prompt:

1. Show that the system does not draft the BRD immediately.
2. Point out that the conversation status is waiting for evidence confirmation.
3. Review the evidence summary in the UI.
4. Click `Confirm & Draft BRD`.
5. Show the returned BRD with these sections:
   - Problem Statement
   - Scope and Exclusions
   - Functional Requirements
   - Assumptions and Constraints
   - Risks and Open Questions

## Demo Script Over the API

Create a conversation:

```bash
curl -X POST http://localhost:8000/conversations
```

Send the combined fetch + BRD request:

```bash
curl -X POST http://localhost:8000/conversations/<id>/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "Fetch records and create a BRD for onboarding issues"}'
```

What to highlight in the response:

- `status` is `awaiting_brd_confirmation`
- `pending_brd_request` is populated
- `evidence_summary` is populated

Confirm the evidence and draft the BRD:

```bash
curl -X POST http://localhost:8000/conversations/<id>/confirm-evidence
```

What to highlight in the response:

- `status` returns to `active`
- `pending_brd_request` is cleared
- `evidence_summary` is cleared
- the final message contains the BRD headings

## What Counts as a Successful Demo

The demo has addressed the problem if you can show all of the following:

- evidence is fetched before document drafting starts
- the human confirmation step is explicit
- the BRD is generated only after evidence confirmation
- the output uses the required BRD sections
- missing data and open questions are called out instead of invented

## Suggested Demo Narrative

Use this structure when speaking through the demo:

1. Problem: users need one workflow that can fetch data and turn it into a usable BRD.
2. Fix: the framework splits retrieval, human validation, drafting, and review into separate stages.
3. Proof: the conversation visibly pauses after fetch, then resumes into BRD generation only after confirmation.

## Near-Term Improvements

- add a `refine evidence` path instead of only confirm or cancel
- surface configured agents in the UI for stronger demo visibility
- add a live integration test for the full fetch -> confirm -> BRD flow
