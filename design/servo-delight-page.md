# servo-delight — product page design brief

> Status: **v1 prototype built** at [`web/`](../web/) — `web/index.html`
> (landing) + `web/pc/index.html` (the kiosk, with the signature pulse
> animation over the hero). This file is the design intent; the prototype is a
> starting point to refine and to host on the product subdomain.

## The hero asset — sets the tone for the whole page

![servo-delight hero](../web/assets/hero.png)

This image **is** the brief. Everything below describes how to bring it to life.
A weathered, hand-built retro robot sits at a wooden desk, cradling a glowing
holographic **globe** (the live web) in one hand. From its **eyes** it projects
twin beams onto a vintage **CRT personal computer**, where the same globe
re-renders as a readable, wireframe display — the machine given *life*. Keyboard
and mouse sit in front, warm lamp-lit study behind. That feeling — **retro-futurist
wonder, hand-built, warm** — is the entire vibe. Match its palette, lighting, and
mood across the page.

## Routes

| Route | Purpose |
|---|---|
| `/` | Product landing page. |
| `/pc` | The **kiosk/hero scene** (analogous to the delightful terminal/markdown kiosk + the `/tv` page), themed around a **personal computer**. |

(Hosted on the servo-agent product subdomain.)

## The `/pc` scene (composition — straight from the hero)

- **Center stage:** a vintage personal computer (CRT monitor + keyboard + mouse)
  as the main focus — this is the "browser" the human reads. Its screen renders a
  real, readable page with **followable links** (it's Servo — the screen can be a
  live, distilled page).
- **Left:** the friendly **robot holding the glowing globe** (the live web).
- **Projection:** twin **eye-beams** from the robot onto the CRT — the robot is
  *giving life* to the display.

## The animation (the signature moment)

A single **pulse of current** travels a continuous path, looping — the
"circle-of-light" / flowing-current technique used on the `/tv` page:

```
globe ──▶ wire ──▶ up the robot's body ──▶ holographic eyes
      ──▶ projected beam ──▶ onto the PC screen ──▶ through the computer
      ──▶ down into the keyboard ──▶ (rest) ──▶ loop
```

Read it as the data's journey: **the live web → our engine → a page a human can
read and act on.** The keyboard landing closes the loop (human back in control).

### Technique (framework-agnostic, drop-in)

- Compose the scene as **one inline SVG** (globe, wire, robot, beams, monitor,
  keyboard as grouped paths) over the hero art, so the pulse rides real geometry.
- The traveling pulse = a glowing dot following the wire/beam path via
  **`offset-path: path(...)`** + animated `offset-distance` (or an SVG
  `<animateMotion>` along the same `<path>`), with a soft `drop-shadow` glow.
  "Current in the wire" segments use an animated **`stroke-dashoffset`** so the
  line itself appears to flow.
- One master timeline (CSS `@keyframes` or a tiny JS clock) sequences
  globe→eyes→screen→keyboard, then loops.
- The PC screen should be a **real embedded render** where possible — a distilled
  page from `read_page`, or a looping capture — so the "life" is literal.
- **Honor `prefers-reduced-motion`:** freeze on a lit, beautiful final frame.

## Palette & type (from the hero)

- Warm sepia/amber room; **electric cyan-blue** for the globe, beams, pulse, and
  CRT wireframe; soft lamp glow. CRT scanline + subtle film grain overlay.
- Retro-tech display type for headings; crisp, readable body text.

## Copy hook (hero)

> **servo-agent** — a browser our agents can read. A web engine that gives life
> to the page.

## Build notes

- Match whichever stack the existing delightful kiosk pages use; if greenfield,
  a single static page (SVG + CSS/JS, optionally Astro) is enough.
- Reuse the *delightful* shell/footer/nav so this feels native to the family.
- `web/assets/hero.png` is the canonical key art — use it as the page background
  / hero and key the animation overlay to its composition.
