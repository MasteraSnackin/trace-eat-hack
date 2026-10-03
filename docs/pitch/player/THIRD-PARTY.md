# Player dependencies

The two player bundles in this folder are unmodified files from the official `hyperframes` npm package, version **0.8.114**:

- `dist/hyperframes-player.global.js`
- `dist/hyperframes-slideshow.global.js`

Source: <https://github.com/heygen-com/hyperframes>.
Package: <https://www.npmjs.com/package/hyperframes/v/0.8.114>.
Licence: Apache 2.0; see `LICENSE-HYPERFRAMES`.

`../composition/assets/gsap.min.js` is the unmodified `dist/gsap.min.js` from the official `gsap` npm package, version **3.14.2**. The package's own copyright banner is retained. GSAP uses its [Standard "no charge" licence](https://gsap.com/standard-license), separate from this repository's licence.

Source: <https://github.com/greensock/GSAP>.
Package: <https://www.npmjs.com/package/gsap/v/3.14.2>.

These files are stored locally so the published deck does not need to load scripts from a CDN. The official player contains an upstream CDN fallback for compositions without a usable timeline. This deck provides its timeline synchronously through `composition/standalone.js`, so that fallback is not used during normal operation.

The local bridge is separate from these upstream bundles. It exposes the full deck to the standalone player and applies temporary entrance fades when a presenter navigates. Normal CLI checks and snapshots keep the authored scene timelines.

To refresh the player deliberately, extract the same two `dist` files from a reviewed npm package version, update this notice and the CLI pins in `../package.json`, then repeat the deck's navigation and presenter checks.
