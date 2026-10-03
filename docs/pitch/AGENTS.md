# Trace HyperFrames pitch

This folder contains a navigable eight-slide presentation. Read the installed HyperFrames slideshow and core skills before changing composition code.

## Source and build

- Edit `scripts/build-composition.mjs` for copy, layout and seekable motion.
- Edit `speaker-notes.json` for spoken notes and evidence URLs.
- Run `npm run build` to regenerate `composition/index.html` and the root browser entrypoint.
- `scripts/build-wrapper.mjs` keeps both slideshow manifests in sync.
- Keep the official player bundles unmodified. The standalone compatibility bridge lives in `composition/standalone.js`.

## Validation and handoff

- `npm run check` builds and validates every slide through isolated, timed fixtures. A plain `hyperframes check composition` checks only the first top-level scene with this CLI.
- Check actual keyboard navigation, fragment reveals and presenter/audience synchronisation in the browser after integration changes.
- `npm run dev` starts the HyperFrames presenter on port 4325.
- `npm run serve` starts the static deck on port 4326.
- Do not run a linear MP4 render against the multi-scene deck; the current CLI would export only the first scene.
- Use the shared Present control and editable notes, without custom replacements.

## Content boundaries

Use natural UK English. Keep facts consistent with the repository. Captures have the camera off and no shopper observations. The test figures refer to the recorded software review on 3 October 2026. Physical gaze accuracy remains unverified. Forecasting, saved history and external data integrations remain proposed work. Do not imply product, purchase, identity or demographic recognition.

The cover is a concept illustration. Preserve asset provenance and dependency notices. Publish only the explicitly selected static files through the Pages workflow; the webcam app and API remain local.
