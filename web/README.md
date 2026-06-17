# site/ — product page (servo-delight)

A self-contained, framework-free prototype of the `servo-agent` product page.

| File | Route | What |
|---|---|---|
| `index.html` | `/` | Landing — hero, tagline, CTAs. |
| `pc/index.html` | `/pc` | The **kiosk**: the hero art + the signature "follow the current" pulse animation (SVG `animateMotion` + flowing `stroke-dashoffset`), with a `prefers-reduced-motion` rest frame. |

Key art: [`../assets/hero.png`](../assets/hero.png). Design intent:
[`../design/servo-delight-page.md`](../design/servo-delight-page.md).

Preview locally (it's static):

```bash
python3 -m http.server -d web 8000   # then open http://localhost:8000/pc/
```

Or render it with the engine itself (fitting):

```bash
servoshell --headless --exit --window-size 1280x900 -o pc.png "file://$PWD/web/pc/index.html"
```
