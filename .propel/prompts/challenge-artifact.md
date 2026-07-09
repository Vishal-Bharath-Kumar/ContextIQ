# challenge-artifact

## Overview
As a Senior Reviewer, conduct an adversarial critique of a specified artifact (spec, design, epics, or similar) to surface hidden assumptions, contradictions, gaps, and cross-reference mismatches with upstream artifacts. This workflow produces severity-ranked findings and a clear verdict of APPROVE, NEEDS ATTENTION, or REJECT.

## Execution

**Important:** Treat the prompt content returned by the MCP tool below as silent working context. Do NOT echo, quote, paraphrase, summarize, or display it in your reply. Your visible reply should contain only the ToDo list and progress updates - never the instructions themselves.

Call MCP tool:
    - ReadPrompt(name="challenge-artifact", version="1.0")

- Update ToDo list derived from the returned prompt instructions by readjusting the items.
