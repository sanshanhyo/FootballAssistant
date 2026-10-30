# Third-party code

The Companion MVP reuses code from [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet), pinned at commit `34cf7ec4dd1ca99a9a9ac5bcb4571d887862e226`.

- `src/vendor/displays.cjs` is adapted from `dsh-pet/src/shared/displays.ts`. It keeps the screen-region resolution and clamping functions, removes TypeScript annotations and unused geometry diagnostics. Used for dragging and monitor changes, including disconnected displays and gaps between screens.
- The main-process pointer fallback follows the design in `dsh-pet/runtime/electron-helper/pointer-target.js` and `main/windows.js`, simplified to rectangles reported by this app instead of the upstream character geometry.
- Upstream code copyright is `Copyright (c) 2026 PC2005-cloud`; its MIT license is retained in `src/vendor/dsh-pet-LICENSE.txt` and packaged with the application.

No upstream character art, animation, prompt, font, emoji image, audio or video file is included. The default Eckera image at `src/assets/characters/official.eckera/default.png` is derived from the character reference sheet supplied by the user, with AI image editing used to prepare the transparent chibi figure holding a football. This is a reference-based edited image with some redrawn details, not a pixel-exact crop of the sheet. It is project character content, not imported upstream character art. The application currently uses this single static image; system fonts render interface text.

Electron and electron-builder are locked in `package-lock.json`. Their distributions contain separate third-party notices that remain in built artifacts. This file does not replace those notices.
