# Research Team Demo

This flagship example runs a complete deterministic multi-agent research
workflow with Agent OS messaging primitives. A planner delegates work to three
research agents, a synthesizer builds a report, and a critic returns a final
quality score.

No API keys, external services, or LLM calls are required.

## Why this matters

The demo is a compact reference for developers building multi-agent systems.
It makes each workflow boundary visible: typed payloads are serialized, routed
through IPC, reconstructed by the next agent, and exposed as final demo state
for testing.

## Architecture

```text
ResearchTeamSupervisor
|
|-- PlannerAgent
|-- ResearchBenefitsAgent
|-- ResearchRisksAgent
|-- ResearchMarketAgent
|-- SynthesizerAgent
`-- CriticAgent
```

## Agent OS capabilities demonstrated

- Deterministic multi-agent workflow execution
- Structured Agent OS IPC messaging
- Serializable dataclass contracts
- Fan-out from one planner to specialized workers
- Fan-in from research agents to a synthesizer
- Final workflow state that is easy to test

## Current status

- Step 1: skeleton and placeholder agents completed
- Step 2: message contracts and deterministic demo data completed
- Step 3: Planner-to-research IPC implemented
- Step 4: Research-to-synthesizer IPC implemented
- Step 5: Synthesizer-to-critic report IPC implemented
- Step 6: Critic review and workflow completion implemented

## Expected output

```text
[SUPERVISOR] Research Team Started
[Planner] Sending assignment: Benefits -> ResearchBenefitsAgent
[Planner] Sending assignment: Risks -> ResearchRisksAgent
[Planner] Sending assignment: Market Trends -> ResearchMarketAgent
[Research-Benefits] Produced 3 findings
[Research-Risks] Produced 3 findings
[Research-Market] Produced 3 findings
[Synthesizer] All research results received
[Synthesizer] Created synthesized report
[Critic] Quality score: 8.7/10
[SUPERVISOR] Workflow Complete
[SUPERVISOR] Final Score: 8.7/10
```

## Deterministic demo data

This demo uses hardcoded research data so every run is fast, repeatable, and
safe to use offline. Shared message contracts keep the IPC workflow explicit.

## How to run

From the repository root:

```powershell
python -m examples.research_team.research_team
```
