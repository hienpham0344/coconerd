# Coconerd public website

## Current direction — 2026-11-04
The user explicitly requested no login and supplied https://www.jockiemusic.com/ as a reference only, not a layout to copy. They confirmed there are no invite/support URLs yet.

Keep the original Fernhollow-inspired night garden, cream typography and botanical visual identity. Organize a public bot website around features, usage guide, searchable FAQ, service status, invitation availability and a clearly labelled interactive demonstration. Everyone can browse without an account. No public guild administration or real message access.

The reference homepage has invite links, FAQ, commands, status and support navigation; its commands page offers search/category filtering. Adapt the discoverability of those patterns to Coconerd's verified conversation-organizing capabilities. Do not invent slash commands, music features, user counts, uptime history, testimonials or Discord IDs.

## Implementation decisions
- Keep React/TypeScript/Vite and the existing original Three.js scene.
- Remove login/session flows and the frontend live admin adapter. The sample explorer remains browser-local and labelled.
- Replace the Node auth/proxy API with public link configuration and a sanitized optional health endpoint. Real backend data and administrative actions are not exposed.
- Accept explicit Discord invite/support URLs in optional environment configuration. Without them show a complete coming-soon state and guide/demo links.
- Documentation on the website is for bot users. Developer setup belongs in README.
- Preserve the standalone internal bridge within this folder, but it is not used by the public website.
- Website source now lives in `web/`, alongside the existing `backend/` and `bot/`. The user's monorepo follow-up authorizes moving the website, fixing integration paths, making separate commits and pushing `main` and `fe` after fetching. Backend/bot behavior stays unchanged; hosting deployment is outside this follow-up.

## Secondary-page revision

The user accepts the landing but reports broken-looking typography, unattractive secondary pages and redundant destinations. Preserve the landing composition and garden. Use the existing Manrope body family for Vietnamese secondary headings, with smaller type and consistent cream/charcoal surfaces.

Keep three navigation destinations: Features, Guide and Demo. Features becomes three illustrated explanations of topics, summaries and channel/data control. Guide combines practical steps, searchable FAQs, support availability and compact service status. Keep privacy accessible from the footer. Old FAQ/support/status URLs resolve to Guide; invitation URLs open an accessible modal over the current page instead of a duplicate availability page. Never invent official links or service health.

Considered keeping all existing pages with cosmetic changes, but that leaves the duplication the user identified. Prefer consolidation plus typography/layout fixes. Keep the current React, Three.js, motion controls, browser-local demo and public API boundaries. No additional dependencies, commits or deployment.
