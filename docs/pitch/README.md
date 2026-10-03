# Trace animated pitch

[Open the public presentation](https://masterasnackin.github.io/trace-eat-hack/pitch/)

Eight editable HTML slides for the EAT_HACK judges, adapted from the [PowerPoint](../slides/Trace-EAT-HACK-judges-pitch.pptx). The deck keeps the same evidence and roughly two minutes of speaker notes, with animated entrances and staged reveals for the problem, local processing and proposed forecasting.

## Present

Use Next or the right arrow to advance. The problem, processing and forecasting slides reveal one point at a time. Previous or the left arrow returns to the previous slide.

Click **Present**, or press **P**, to open the audience tab. Your original tab shows the current slide, next slide, editable notes and elapsed time. Share the audience tab, so your notes stay private. Browser edits to notes are saved locally; they do not update the repository.

In Google Meet, share the audience **tab**. In Zoom, move that tab into its own window, share that window and keep it at least partly visible so the browser continues drawing it.

## Run locally

The static presentation includes its player scripts and images. From the repository root, serve it with Python:

```sh
python3 -m http.server 4326 --bind 127.0.0.1 --directory docs/pitch
```

Open <http://127.0.0.1:4326/>. Use an HTTP server; opening the HTML directly with `file://` can block communication between the player and its iframe.

For the HyperFrames presenter server, use Node.js 22 or later:

```sh
cd docs/pitch
npm run dev
```

This uses pinned HyperFrames 0.8.114 on port 4325. Its first run may download the CLI. The presentation does not start Trace's webcam app or request camera access.

## Edit and check

Edit slide copy, layout and deterministic motion in `scripts/build-composition.mjs`. Edit spoken notes and source references in `speaker-notes.json`. Then regenerate the composition and public wrapper:

```sh
npm run build
npm run check
```

The generated `composition/index.html` contains the eight HyperFrames scenes and slideshow manifest. The root `index.html` is the runnable browser entrypoint. `scripts/build-wrapper.mjs` keeps its manifest and time bounds in sync with the composition. `composition/standalone.js` adapts the scenes to the shared static HyperFrames player.

`npm run check` validates all eight slides, including reveal order, layout, contrast and runtime errors. It writes its temporary slide fixtures, audit JSON and screenshots to the directory printed at the end. A direct `hyperframes check composition` only checks the first top-level scene in this CLI version. See the [validation record](VALIDATION.md) for the checked scope.

The current HyperFrames slideshow output is a navigable deck. Do not run a linear MP4 render against this multi-scene source: this CLI resolves only the first top-level scene. The [existing interface walkthrough](../videos/trace-ui-walkthrough.mp4) is available separately.

## Evidence and assets

Interface captures show the camera off, with no shopper observations. Physical shelf accuracy remains unverified. The 68 Python and 19 JavaScript test results are from the recorded review on 3 October 2026. Forecasting, saved history and external data integrations remain proposed work.

See [asset provenance](ASSETS.md), [dependency notices](player/THIRD-PARTY.md) and the source URLs in each slide's notes. The conceptual cover illustration is not a photograph of an installed system.
