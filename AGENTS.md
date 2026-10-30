# Project UI guidance

For HTML, CSS, and JavaScript UI changes, read and follow
[`skills/daisyui/SKILL.md`](skills/daisyui/SKILL.md), including its applicable
installation, usage, color, and component guides.

Create expressive, cohesive café interfaces that suit EMBER: warm surfaces,
burgundy accents, editorial typography, appetizing photography, and clear ordering
controls. Use responsive layouts, readable contrast, visible keyboard focus, and
comfortable touch targets. Respect reduced-motion preferences for animations.

Preserve the existing Python server and SQLite ordering flow. Keep customer,
kitchen, and admin workflows functional. Before adding daisyUI styles to existing
pages, check for collisions with custom classes such as `badge`, `steps`, and
`status`. Follow the installation guide when introducing the library; the skill
files themselves do not load daisyUI CSS into the application.

For functional changes, run `python -m unittest -v test_app` and
`node --test test_ui.js`. For visual changes, also verify desktop and mobile
layouts and the affected ordering or staff flow in a browser.
