# web/ — product page (servo-delight)

A self-contained, framework-free prototype of the `servo-agent` product page.
Deploy `web/` at the domain root; routes are absolute (`/pc/`, `/info/`, `/assets/`).

| File | Route | What |
|---|---|---|
| `index.html` | `/` | Redirects into the kiosk (`/pc/`). |
| `pc/index.html` | `/pc` | The **kiosk**: the hero art + the **"Easy as 1-2-3"** Canvas pulse animation — type (keyboard pebble-pond) → charge in the robot's head → multi-beam hologram onto the screen → loop. `prefers-reduced-motion` rest frame. |
| `info/index.html` | `/info` | The **main info page** — tactical theme, the README story (why Servo, use cases, tools, quickstart). |

Key art: [`assets/hero.png`](assets/hero.png). Design intent:
[`../design/servo-delight-page.md`](../design/servo-delight-page.md).

Preview locally (it's static, served with `web/` as the root):

```bash
python3 -m http.server -d web 8799   # then open http://localhost:8799/pc/ and /info/
```

Or render it with the engine itself (fitting):

```bash
servoshell --headless --exit --window-size 1280x900 -o pc.png "http://localhost:8799/pc/"
```
