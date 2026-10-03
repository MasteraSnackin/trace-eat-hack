# Trace review and completion plan

The scope is the public Trace repository, starting at `fb25455`. The user confirmed that the app must keep its local Python and plain JavaScript setup. The separate Coding workspace is not edited by this review.

The nine supplied Markdown files are task briefs. Their Next.js, Antigravity, Tailwind, Framer Motion and Modal examples are adapted to this codebase. A database, cloud deployment and speculative features are outside this pass. Evidence comes from the actual source, tests and captured browser states; unavailable checks stay marked as unavailable.

## Work sequence

1. Complete: inspect the current app, capture its starting state and reproduce defects.
2. Complete: repair confirmed backend, interface and algorithm issues; independently recheck restart and page-restoration failures.
3. Complete: write the README, architecture and seven review reports, with screenshots and before/after browser recordings.
4. Complete: 68 Python tests, 19 JavaScript tests, model verification, syntax checks and browser validation. This delivery uses the required `[AUTO-HEALED]` commit prefix; the final handoff records publication status.

## Completion status

All nine briefs have corresponding deliverables below. Generic framework and styling prescriptions were adapted to the user's decision to retain the existing setup. The software review is complete; live camera and physical shelf validation remain pending.

The scoped review scores are Visual 9/10, Functional 9/10 and Trust 9/10. Their rubric, evidence and exclusions are in [docs/AUDIT.md](docs/AUDIT.md). An unconditional "Verified & Polished" product label is withheld because no physical accuracy result is available. Live webcam use also awaits the user's permission.

## Brief-to-output map

| Supplied brief | Output and acceptance |
| --- | --- |
| `!)README.md` | `README.md`: requested sections, actual installation and usage, API reference and Mermaid architecture. No invented licence, deployment or contact details. |
| `£)ARCHITECTURE.md` | `ARCHITECTURE.md`: actual components, flows, state, deployment, security, limits and decisions. |
| `1)AUDIT.md` | `docs/AUDIT.md`: current browser evidence, functional checks, findings, corrections and explicit evidence limits. Scores need a stated rubric. |
| `2)DEBUG.md` | `docs/DEBUG.md`: reproducible defects, ranked hypotheses, root causes, fixes and regression results. |
| `3)ERRORHANDING.md` | `docs/ERROR_HANDLING.md`: appropriate validation, recoverable errors, cancellation, cleanup and diagnostics. Irrelevant distributed-system examples are documented as not applicable. |
| `A)DESIGNLEAD.md` | `docs/DESIGN_REVIEW.md`: existing layout, readable state feedback, keyboard access and bounded visual improvements supported by captured evidence. |
| `B)BUILDER.md` | `docs/BUILD_REVIEW.md`: local API and state correctness, with tests for confirmed failures. |
| `C)NERD.md` | `docs/PERFORMANCE.md`: three priority risks, measured baseline, a justified fix and before/after results. |
| `D)RESEARCHER.md` | `docs/RESEARCH.md`: primary sources, algorithm assessment, quick wins, medium efforts, research bets and evidence for the implemented quick win. |

## Acceptance boundaries

- Original input Markdown files and synced project sources remain unchanged.
- No raw camera images, biometric templates, credentials or local environments enter Git.
- The app must not count uncertain or stale observations as current shelf attention.
- Expected failures need useful recovery messages; stale requests must not revive stopped visits.
- Fresh automated checks must pass before publication. Browser, physical webcam and shelf-accuracy checks are reported separately.
- Do not mark the app "Verified & Polished" or assign a passing visual score without the required evidence.
