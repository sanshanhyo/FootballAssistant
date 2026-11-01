# Third-party code

The Companion MVP reuses code from [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet), pinned at commit `34cf7ec4dd1ca99a9a9ac5bcb4571d887862e226`.

- `src/vendor/displays.cjs` is adapted from `dsh-pet/src/shared/displays.ts`. It keeps the screen-region resolution and clamping functions, removes TypeScript annotations and unused geometry diagnostics. Used for dragging and monitor changes, including disconnected displays and gaps between screens.
- The main-process pointer fallback follows the design in `dsh-pet/runtime/electron-helper/pointer-target.js` and `main/windows.js`, simplified to rectangles reported by this app instead of the upstream character geometry.
- Upstream code copyright is `Copyright (c) 2026 PC2005-cloud`; its MIT license is retained in `src/vendor/dsh-pet-LICENSE.txt` and packaged with the application.

No upstream character art, animation, prompt, font, emoji image, audio or video file is included. The default Eckera image at `src/assets/characters/official.eckera/default.png` is derived from the character reference sheet supplied by the user, with AI image editing used to prepare the transparent chibi figure holding a football. This is a reference-based edited image with some redrawn details, not a pixel-exact crop of the sheet. It is project character content, not imported upstream character art. The application currently uses this single static image; system fonts render the interface outside dialogue text.

The speech-bubble outline at `src/assets/ui/speech-bubble.png` is the original transparent PNG supplied by the user. Its bitmap is unchanged; a code-defined white SVG backing fills the bubble interior without redrawing the hand-drawn outline.

Dialogue text uses the unmodified **851 GBai Marker** font (851 GBai 记号笔), Version 0.04, by 8:51:22 pm with Chinese extension by lamda05. The author-supplied release permits software/game embedding and redistribution; its original notice and source links are included beside `src/assets/fonts/851GBaiMarker-Regular.ttf` as `851GBaiMarker-LICENSE.txt` and `851GBaiMarker-SOURCE.md`. The font is loaded locally and is not installed into the operating system. Other UI text continues to use system fonts.

Electron and electron-builder are locked in `package-lock.json`. Their distributions contain separate third-party notices that remain in built artifacts. This file does not replace those notices.

The installed Windows update adapter depends on **electron-updater 6.6.2** (MIT), pinned in `package-lock.json`. Its upstream LICENSE and dependency notices remain in the packaged production modules. It is dormant until release trust is explicitly configured.

## License scope and retained author terms

Third-party code and fonts retain their original licenses; the project's root
license does not relicense them. In particular, 851 GBai Marker is **not**
GPL-licensed. The unchanged original author's complete terms are retained in
`src/assets/fonts/851-original-author-terms.html` (retrieved 2026-10-31 from
https://pm85122.onamae.jp/851fontTerm.html), alongside the Chinese release notice
and source record. These terms permit software/game embedding and redistribution,
but restrict standalone font sales and sales of modified font files. Do not
replace them with a blanket "all assets GPL" statement. The project's character
and bubble assets have the provenance described above; their public resource
licensing is to be specified separately (角色资源授权另行说明).

The bundled backend carries `third-party-licenses/manifest.json` and hashed notice
files, collected from its actual PyInstaller analysis. This includes the CPython
runtime license and notices for bundled Python distributions, not only direct
dependencies. A missing notice fails backend building. The manifest separately
lists native runtime files for release review: collecting notices does not itself
verify every native-library obligation or satisfy all corresponding-source duties.
Electron/Chromium/Node notices and production npm module licenses must additionally
be checked in the final target-platform application; this document cannot replace
them. No Doorstop, CoreCLR, BepInEx or Dobby binary is included by this configuration.


## Bundled local speech recognition

- Engine: whisper.cpp v1.7.6, commit `a8d002cfd879315632a579e73f0148d06959de36`, MIT. Built from source, CPU-only, no CUDA/Metal runtime requirement.
- Model: OpenAI Whisper tiny multilingual, GGML Q5_1 conversion distributed by whisper.cpp's maintainer. MIT. 32,152,673 bytes (~30.7 MiB). SHA-256 `818710568da3ca15689e31a743197b520007872ff9576237bda97bd1b469c3d7`.
- Model source: https://huggingface.co/ggerganov/whisper.cpp/tree/5359861c739e955e79d9a303bcbc70fb988958b1
- Engine source: https://github.com/ggml-org/whisper.cpp/tree/a8d002cfd879315632a579e73f0148d06959de36
- Engine and model MIT license texts are retained alongside binaries in `resources/local-stt/`. The CLI also embeds miniaudio and stb_vorbis under their public-domain alternatives; their complete dual-license notices and the engine/GGML MIT license are retained alongside the engine.
- `packaging/build-local-stt.py` verifies pinned source/model hashes, compiles the platform binary, and runs actual CPU inference on upstream's public JFK sample. Build-time downloads only; recorded audio is never uploaded by this provider.
- Tiny prioritizes footprint over accuracy, especially for Chinese proper names and football terms. Transcripts remain editable drafts, never automatically sent. Speed and peak RAM depend on CPU/audio duration; no real-time guarantee. Upstream reports ~273 MB RAM for unquantized tiny; this is not a measured Q5_1 memory promise.
