# Pitch composition validation

## Browser acceptance

The static deck was checked in the Codex in-app browser on 3 October 2026. All eight slides displayed correctly. Next and arrow-key navigation advanced the staged reveals, and revisiting a slide reset its reveals. Present opened a separate audience tab; slide changes and individual reveals synchronised while notes remained in the presenter view. The official local HyperFrames presenter also reached later scenes successfully.

A retained startup console exception was traced through the debugger to Electron's injected page-annotation code, outside the deck and its player bundles. No error suppression or third-party bundle changes were applied. The deck's own isolated runtime checks passed.

## Composition checks

Checked on 3 October 2026 with HyperFrames 0.8.114 at 1920 × 1080.

All eight slides passed the strict composition checks, with no remaining lint,
runtime, layout, motion or contrast findings. The final frame of each slide was
also inspected for readability, clipping and unintended overlap.

| Slide | Layout sample times | Motion seek samples | Text contrast observations | Result |
| --- | ---: | ---: | ---: | --- |
| Cover | 6 | 241 | 27 | Pass |
| Problem | 9 | 241 | 37 | Pass |
| Shelf | 6 | 241 | 41 | Pass |
| Offers | 6 | 241 | 40 | Pass |
| Processing | 10 | 241 | 62 | Pass |
| Evidence | 6 | 241 | 51 | Pass |
| Forecast | 10 | 241 | 46 | Pass |
| Trial | 6 | 241 | 51 | Pass |
| **Total** | **59** | **1,928** | **355** | **Pass** |

The motion pass checks heading appearance, heading bounds, fragment appearance,
fragment order and fragment bounds. Contrast observations can count the same
text at more than one time. These figures describe the presentation checks,
not tests of the Trace webcam prototype.

## Reproduce the checks

From `docs/pitch`:

```sh
npm run build
node scripts/check-slides.mjs
```

To recheck one slide:

```sh
node scripts/check-slides.mjs --only forecast
```

The script prints its temporary output directory. Each slide gets the complete
HyperFrames JSON report, a motion assertion file and five PNG snapshots. An
aggregate `validation.json` records the source hash, actual sample counts and
results. `--output /path/to/temporary-directory` selects a location explicitly.

## Why slides are checked separately

HyperFrames 0.8.114 derives the ordinary check duration from this deck's first
top-level scene. Running `hyperframes check composition` alone therefore checks
only the first 12 seconds.

The helper creates one temporary fixture per slide. It retains the source CSS,
scene markup, assets and GSAP statements, translating absolute scene and reveal
times to start at zero. It samples entrance states, every presenter fragment
endpoint and the settled slide. HyperFrames also runs its denser motion sweep.

During review, the original forecasting footnote overlapped the footer. The
checker reported a held `content_overlap` error. Shorter copy and a wider text
box resolved it; the revised slide passed without suppressing the finding.
Fixture and asset comparisons confirmed that the other seven retained checks
match the final source. Their only CSS difference is the unused forecasting
footnote rule.

Checked `composition/index.html` SHA-256:

```text
236361dd10abb8ca29c85c40db62be2197fcc1f88acd11e3bd9d1fbec193d4a1
```

## Scope

These are sampled composition checks. The fixtures exclude the standalone
navigation bridge; the separate browser acceptance above covers navigation,
keyboard controls and presenter/audience synchronisation. No MP4 was rendered
as part of this validation.
