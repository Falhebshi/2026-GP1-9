# Night mode

The moon / sun button at the end of the nav bar switches the whole app between light and night mode.

## How it works

- **The mode lives on `<html data-theme="light|dark">`.** A small script in `frontend/index.html` sets it before the page is drawn: the user's saved choice if they made one, otherwise their computer's setting. So night-mode users never see a white flash.
- **`frontend/src/theme/theme-dark.css` gives the color roles from `frontend/src/index.css` new values** when `data-theme="dark"`. Components don't change: they already use `var(--color-...)`. The file is imported in `frontend/src/main.jsx` after `frontend/src/index.css`.
- **`frontend/src/hooks/useTheme.js`** reads and switches the mode, saves the choice (`localStorage`, key `jaadah-theme`) and follows the computer's setting until the user picks one. Where the browser supports it, the switch is a short cross-fade.
- **`frontend/src/components/ThemeToggle.jsx`** is the button. Screen readers hear "Night mode, on/off".
- **The Network Overview map switches basemap too:** OpenFreeMap `positron` in light mode, `dark` in night mode (`NetworkMap.jsx`). `map.setStyle()` keeps our own sources and layers (segments, heat, intersections) across the switch.

## Rules for new code

1. **Use the roles from `frontend/src/index.css`, never a hex code.** Anything built from `var(--color-...)` gets night mode for free.
2. **Don't pair a pale fill with `--color-text`.** `--color-text` is light in night mode. For dark letters on a pale fill, use `--color-text-on-light` in `theme-dark.css` (see the LOS A–D rule there).
3. **Use `--color-selected` for fills, `--color-action` for colored text.** In light mode they look alike; in night mode the selected indigo is too dark to read as text.
4. **JavaScript that reads theme colors once** (like the MapLibre map with `themeColor()`) should listen for the switch and read them again:
   ```js
   import { THEME_EVENT } from '../hooks/useTheme'
   window.addEventListener(THEME_EVENT, () => { /* read the colors again */ })
   ```
   `NetworkMap.jsx` does this for the intersection dots.

## Kept the same in both modes

Chart series, LOS A–F, congestion levels and the heatmap scale keep their light-mode colors, so a color always means the same thing. Night mode only changes their backgrounds (grid lines, chart tracks, shaded windows) and adds a thin edge to LOS F, which is as dark as the page.

The 3D scene keeps its colors too, with one exception: an approach without an LOS grade is highlighted in `--color-selected` (`frontend/src/simulation_3d/selection.js`), so that highlight follows night mode like every other "selected" mark in the app.

## Known limitations

- **No toggle on Welcome and Login.** The button lives in the nav bar, which those pages don't have. A user whose computer is set to dark gets night mode there and can switch it off only after logging in.
- **Open tabs don't follow each other.** Switching the mode in one tab updates other open tabs only when they reload.

## Checking contrast

All text in night mode passes WCAG AA (4.5:1). Marks that are not text (dots, lines, bar fills) need 3:1 (WCAG 1.4.11):

- The alert-type dots measure about 5:1 on the page and 4.6–4.7:1 where the same colors appear on a card.
- One exception, accepted on purpose: the main chart color (`--chart-1`, blue `#2864a8`) is 2.9:1 against a dark card, just under 3:1. It is kept so charts look the same in both modes; LOS E uses the same blue and has a white letter on it.

When adding a color to `theme-dark.css`, check it against `--color-surface` (`#171a23`) and, for anything placed directly on the page, `--color-bg` (`#0f1117`), for example with https://webaim.org/resources/contrastchecker/.
