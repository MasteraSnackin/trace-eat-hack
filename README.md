# Trace

Trace is a local webcam prototype for EAT_HACK's Retail Futures track. It estimates gaze towards three broad shelf zones, records continuous visits and shows an example offer after sustained gaze towards a zone. The interface calls the prototype **Shelf Trace**.

Shoppers do not complete a calibration routine. The operator supplies the camera and shelf measurements. Physical shelf accuracy still needs testing: the current build estimates gaze direction, and does not detect product pickups, recognise returning shoppers or confirm purchases.

## Run locally

Use Python 3.12, `curl` and a webcam. These commands use a macOS or Linux shell. The recorded model checks were run on an Apple M4 Max with macOS; other platforms have not been validated.

```sh
git clone https://github.com/MasteraSnackin/trace-eat-hack.git
cd trace-eat-hack
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python scripts/download_models.py
./run.sh
```

Open the [operator view](http://127.0.0.1:4321) and choose **Start camera**. Grant the browser's camera permission. Open the [customer display](http://127.0.0.1:4321/display) in a separate window or on another monitor. Keep the operator view visible: hiding its tab stops capture. Use one active operator window.

The downloader retrieves about 18.7 MB of model data from Intel's storage over verified HTTPS. It checks file sizes and SHA-384 hashes against pinned manifests. Internet access is needed to install dependencies and download models; inference and both views then run locally without an API key. The server listens only on `127.0.0.1:4321`.

## Set up the shelf

1. Mount a level webcam in the shelf plane, facing the shopper. A laptop webcam can show gaze estimates, but shelf mapping requires the configured shelf to be in the camera's plane.
2. Arrange three large, equal-width zones: protein bars on the left, drinks in the centre and snacks on the right, as the shopper sees them.
3. Enter the shelf width and height, camera height above the shelf's bottom, camera offset from the centre, approximate eye-to-camera distance and horizontal field of view. Defaults are examples, not measurements of your equipment.
4. With one person and clearly visible eyes, look at known positions in each zone and check the estimates. This checks the installation; it is not a calibration step required of each shopper.

The preview is unmirrored. Camera-image right corresponds to the shopper's left on the shelf. The geometry uses an estimated distance and a vertical shelf plane. It does not measure depth or compensate for camera tilt or lens distortion. Changes in distance, glasses, occlusion, head rotation and lighting can affect the result.

## What the prototype does

- Runs five local OpenVINO models on the CPU: face detection, facial landmarks, head pose, eye state and gaze direction.
- Maps a usable single-face estimate onto left, centre or right shelf zones. Unclear eyes, extreme head angles, rays outside the shelf and estimates near zone boundaries remain unassigned.
- Accumulates continuous estimated gaze time. An uncertain sample or a gap over 1.5 seconds breaks continuity.
- Shows an example offer after a configurable dwell threshold, initially 1.5 seconds. A hold period limits switching between offers; uncertain observations restore a general message. Offers are labelled as demonstrations and cannot be redeemed.
- Suspends individual attribution when several faces appear. A gap over 2.5 seconds ends a visit, and an abrupt change in face position starts a new temporary track.
- Keeps events and zone totals in server memory. Restarting the server clears setup and activity. **Reset run** clears activity while keeping the current setup.

Visit IDs group continuous observations. They do not identify people or recognise returning customers. A person leaving briefly and another appearing in a similar position may be merged; a person moving abruptly may be split. Detected faces do not represent everyone present.

The application does not save images, face embeddings or recordings. Camera frames go to the server on the same computer for inference. The customer display reads the current visit and offer state, without receiving camera frames.

## Checks and limitations

```sh
.venv/bin/python -m pytest -q
.venv/bin/python scripts/download_models.py --verify-only
```

The tests cover geometry, ambiguous observations, dwell timing, offer behaviour, visit expiry, invalid requests, cross-origin controls and cancellation during inference. Server tests use a fake vision pipeline. Their synthetic inputs do not represent observed shopper behaviour.

[Model provenance](model-provenance.json) records separate checks with the real models on CPU using publisher sample images and video. Those records include input hashes, class and axis checks, and their limits. They show that inference ran, but do not establish webcam performance or retail accuracy.

A live webcam and physical shelf test is still required. Product pickups and returns, exact product recognition, purchases, returning customers, demographic inference and promotion redemption are not implemented. Estimated gaze direction does not establish a shopper's preference, motivation or intent to buy.

## EAT_HACK work and prior components

This repository contains the gaze prototype developed for EAT_HACK on 3 October 2026: the local Python service, shelf geometry, temporary visit and dwell logic, operator interface and example offer display.

An earlier project named Shelf produced adverts from product photos and optional portrait cutouts. That separate application is not included in this repository. The current gaze prototype does not include its product recognition or advert renderer.

The trained models and the upstream gaze demo existed before EAT_HACK. The inference pipeline adapts the [Open Model Zoo gaze demo](https://github.com/openvinotoolkit/open_model_zoo/tree/a6946b6d6ce42cbf4278df20275fab199655fc7d/demos/gaze_estimation_demo/cpp) to a Python service, with quality checks and a coordinate convention for the browser and shelf geometry. These foundations must be disclosed in the submission.

## Model sources and licences

[model-provenance.json](model-provenance.json) pins upstream source references, model URLs, file sizes, hashes and preprocessing details. Model files are downloaded during setup and excluded from Git.

The selected model manifests specify Apache 2.0. The upstream licence is included in [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES/). Python dependencies retain their own licences. No licence has yet been assigned to the original application code; public visibility does not change that.
