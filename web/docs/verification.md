# Verification — 2026-11-04

The public website below supersedes the earlier login/admin interface after the user's correction. Only coconerd-web was edited.

## Observed checks
- `npm test`: **6/6 passed**. The new public-website tests first failed against the old login server, then passed after implementation.
- Public config returns only validated invite/support links without a cookie or login. Invalid URLs are rejected. Old login, session and private backend routes return 404, even with an old-style cookie.
- Health tests cover missing configuration, healthy/degraded responses, unknown/malformed responses, sanitized output and the 30-second cache.
- `npm run build`: TypeScript and Vite production build passed after the public-site changes and again after the final contrast fix (exit 0).
- Production HTTP smoke: root and 3 referenced assets returned 200; public config/status worked; environment, bridge/server source, login and private backend paths returned 404. Temporary production server stopped successfully.
- Backend sibling `git status --short`: clean after the public-site build.

## Browser verification
- Mobile: actual content width 375px, viewport height 844px. Navigation opened and routed to features; feature and invitation pages fitted the screen. Guide also rendered at mobile width.
- Feature search `tom tat` returned one summary feature; combining it with the conversation category returned the designed empty state.
- FAQ search `tai khoan` returned and expanded the relevant account-free answer.
- Legacy `/connect` displayed the invitation availability page, with no password form. Missing invitation URL displayed “Sắp ra mắt” and a disabled external invitation action.
- Desktop: actual content width 1265px, viewport height 720px. Full public navigation and feature layout rendered correctly.
- Status page displayed “Chưa có trạng thái trực tiếp”, website reachable, and unknown storage/processing status when no health source was configured.
- A direct demo topic link opened the correct sample guild/topic without login. Summary and 4 conversation messages loaded; confirmation changed the topic to closed; resetting the demo restored the original resumed status.
- Garden landing rendered with the new public navigation. No error/warn entries were returned from the final desktop QA tab.
- Earlier in this same task: garden pause/audio toggle, landing example tabs and demo search were exercised. Mobile headline clipping was reproduced and fixed. Final image review found the contrast overlay below the appended canvas; it was moved above the canvas and rechecked.
- Screenshots: `previews/home-desktop.png`, `previews/features-mobile.png`.

## Practical limits
- User confirmed that official Discord invite/support URLs do not exist yet; availability states are intentional, not working invitations.
- No real Discord, AI provider, credentials, or production conversation data was used. The website does not expose the private backend.
- Real health data can be enabled later with the optional public health URL; until then no bot-online or uptime claim is made.
- No slash-command catalogue was invented: the bot implementation is outside the backend repository.
- Reduced-motion and no-WebGL fallback are present in source; those browser conditions were not forced in QA. Audio toggle state was checked, not independently listened to.
- The retained standalone bridge previously passed 2 isolated integration tests; it is not used by this public website and was not changed or rerun in this revision.

Final continuation: preview restarted after the interrupted session, latest landing screenshot saved, temporary viewport override reset, and the public preview tab retained. Backend working tree remained clean.

## Mascot, palette and motion continuation

- Resumed the existing follow-up implementation without replacing the mascot or rebuilding the website. The mascot sits above the landing headline and appears in the demo welcome. Lower sections use warm ivory, charcoal and muted olive.
- Flower and stem shaders share forward travel at 0.6 scene units per active second and recycle in distant fog. Paused native browser screenshots were identical; movement can be enabled again through the existing control.
- Observed staggered scroll reveals with intermediate opacity values on the landing. Feature cards also revealed after lazy loading; FAQ search `tai khoan` produced one expanded, revealed answer. Extended reveal targets to FAQ, status and privacy content.
- Moved the page-motion wrapper inside the route Suspense boundary so page arrival waits for lazy content. Kept the wrapper unkeyed to preserve demo state between its routes.
- Actual desktop viewport 1280×720 and mobile viewport 375×844 reported no horizontal overflow. The mascot was above the headline, mobile navigation opened and routed, and the demo welcome rendered the supplied image.
- `npm test`: 6/6 passed after allowing localhost listeners. The initial sandbox run could not listen on localhost (`EPERM`); no test or server code change was needed.
- `npm run build`: TypeScript and Vite passed. Reduced-motion and no-WebGL conditions remain source-reviewed, not forced in this browser session. No deployment or commit was performed.
- Final native screenshots changed while the garden ran with unchanged scroll position. Saved desktop preview: `previews/home-motion-desktop.png`; retained the local preview tab and reset the viewport override. The mascot asset checksum matched before and after this continuation.

## Secondary-page simplification — 2026-11-05

- Replaced Antonio on Vietnamese secondary headings with the existing Manrope family, reduced oversized headings and replaced the public-page CSS block. The accepted landing composition and original mascot remain. Manrope's official Google Fonts metadata includes the Vietnamese subset; observed rendered headings use `Manrope, "Noto Sans", sans-serif`.
- Navigation now contains Features, Guide and Demo. Guide contains three setup steps, searchable FAQs, actual support availability and compact public health status. Features contains three illustrated explanations; invitation opens a modal. Privacy remains in the footer. Old FAQ/support/status paths resolve to Guide; no login or private backend routes were added.
- Routing regression tests were written first, failed before the new resolver existed, then passed. Final `npm test`: **11/11 passed**, including five routing cases and the six existing HTTP boundary/configuration tests. `npm run build`: TypeScript/Vite passed after the final source changes.
- Browser: Features rendered three illustrated sections at an actual 1280×720 desktop viewport and 375×844 mobile viewport without horizontal overflow. Guide was also checked at desktop/mobile sizes; its heading uses Manrope and its three steps and ten questions rendered.
- FAQ query `tai khoan` returned the account-free answer, expanded and revealed at opacity 1. Mobile menu navigated from Features to Guide. Direct `/support` displayed the combined Guide and correct title. Missing health configuration displayed that bot status has not been published.
- Invitation modal displayed the real missing-link state. Escape closed it, removed the dialog and restored body scrolling. Reproduced and fixed focus restoration jumping to an earlier input by restoring focus without scrolling and preserving dialog scroll position; the final mobile check closed at the same scroll position as the open modal (304px). Browser click automation itself scrolled the opener into view before opening.
- The sample `new-website` topic still opened its native dialog and rendered its summary after the shared Dialog change. No horizontal overflow was reported there.
- Final images: `previews/features-refined-desktop.png`, `previews/features-refined-mobile.png`, `previews/guide-refined-desktop.png`. Reset the temporary viewport and retained the final Features tab. The first preview tab stopped attaching during QA; a new tab in the same browser completed the remaining checks.
- Mascot checksum remains `86bed6206b7a642383dbef22b93d14d3fcb0b85d24ffa5a2e81d30907335fdc0`. The backend sibling remained clean. No dependency additions, lockfile changes, commits or deployment.
- Existing reduced-motion and no-WebGL paths remain source-reviewed; those browser conditions were not forced. New UI request-error branches were source-reviewed; the live browser used the configured missing-link/missing-health states.

## Monorepo relocation — 2026-11-05

- Moved the complete website from the sibling `coconerd-web/` directory into `web/` alongside the fetched repository's existing `backend/` and `bot/`. The old sibling directory no longer exists. Local dependencies, cache and build output moved with the directory and remain ignored.
- Reproduced the old bridge launcher's failure after moving: its `../coconerd` default missed the backend virtualenv and selected a system Python without `httpx`. The launcher now resolves `web/` from its module URL, defaults the backend to the parent repository, finds that repository's `.venv`, and sets the child working directory explicitly. The bridge was also formatted to the repository's Ruff rules.
- From the relocated repository: **180 backend tests passed** (two existing Alembic deprecation warnings), **2 bridge tests passed**, **11 web tests passed**, and TypeScript/Vite production build passed. Python tests initially stalled inside the restricted sandbox; the bounded rerun outside it completed in 27.73s plus 6.45s for the bridge. The bridge rerun was launched from the repository root, exercising caller-directory independence.
- Ruff check and format check passed for `web/bridge/` and `web/tests/test_bridge.py`. Root backend/bot implementation was not changed. Git ignore checks covered web dependencies, dist, cache, TypeScript build metadata and private environment files. A source scan found no credential-pattern matches; configuration sample values were not printed.
- Production preview started successfully from `web/` at `http://127.0.0.1:5173/`. A new direct HTTP smoke attempt and its one retry were rejected because automatic permission review exceeded its deadline. The browser read also hit the review deadline. No HTTP-smoke or post-move browser success is claimed; the automated HTTP/routing tests above did complete.
- Root and web setup documentation now describe the monorepo layout and portable commands. Publication is to `main` and `fe` after a fresh fetch and conflict reconciliation; no force push or hosting deployment is part of this work.

## Authenticated dashboard — 2026-11-05

- Backend suite: **501 passed, 2 skipped**; PostgreSQL-only tests skipped because no disposable test server was supplied. All DB/migration tests used isolated SQLite files.
- Optional bridge: **2 passed** with the main backend dashboard routes.
- Web: **24 passed**, including OAuth/PKCE, encrypted persistent session, CSRF/origin, owner/Administrator scope, forbidden cross-guild/global proxy access, permission revocation, refresh/logout race, serverless body handling, live/demo separation and full review snapshots.
- Production `npm run build` and targeted Python Ruff checks passed. No package dependency/lockfile changes were required for the dashboard.
- Browser QA used a temporary localhost fixture with fake Discord/backend/tokens: login, guild overview, settings save, topic messages/summary, correction with memory/sources, paused sync, resume, performed-action recovery, logout and reload back to login were visibly verified.
- Screenshot of the desktop dashboard was captured using fixture data. Viewport emulation was unavailable; mobile behavior was not directly exercised.
- Actual Discord OAuth, production migration and production deployment were not exercised in this chat. Configure the server-only values in `../.env.example` and follow `../README.md` before enabling the real dashboard.
- Final review caught SQLite expiry without an explicit timezone; credentials now serialize UTC consistently. Regression was observed failing, then the complete backend suite passed after the fix.
