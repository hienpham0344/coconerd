# Public bot website implementation

The earlier admin-dashboard direction is superseded by the user's explicit no-login request.

- [x] Replace session/login/proxy routes with public link configuration and sanitized health, with HTTP regression tests.
- [x] Build public navigation, feature search, usage guide, searchable FAQ, invitation/support availability and status pages.
- [x] Keep the garden landing and a useful demo explorer; remove login and live settings from visitor flows.
- [x] Verify build, public/private API boundaries, desktop/mobile behavior and update README/verification evidence.

Verified backend capability: organizing original messages into topics, summaries, thread actions, guild/channel allowlisting and retention. Discord bot itself is external to this repository, so no command names are invented.

## Mascot, palette and motion follow-up

- [x] Place the supplied mascot above the landing headline and in the demo welcome; enlarge the hero description and harmonize the lower sections with the cream/charcoal palette.
- [x] Move the flower field slowly toward the viewer in a seamless loop, retain pause, and add scroll reveals/page arrival respecting reduced motion.
- [x] Build and visually check desktop/mobile layouts, scroll/navigation animation, pause and original asset integrity.

## Secondary-page simplification

Execute inline in the existing non-Git web directory; preserve sibling repositories and the accepted landing composition.

- [x] Replace secondary display typography with Manrope and compact warm layouts; turn Features into three illustrated capability sections, retaining meaningful demo/privacy links.
- [x] Consolidate Guide/FAQ/Support/Status into Guide with practical steps, searchable answers and actual public configuration/health states. Simplify shared header/footer navigation.
- [x] Replace the duplicate invitation page with the existing accessible Dialog pattern; retain route aliases, current page/scroll on open/close, safe links and useful missing/error states.
- [x] Verify invitation routing/close, FAQ search, legacy URLs, desktop/mobile typography and overflow, demo topic dialog, build and HTTP tests. Refresh screenshots and documentation from observed results.

Files: `src/pages/PublicPages.tsx`, `src/components/PublicLayout.tsx`, `src/components/InviteDialog.tsx`, `src/App.tsx`, `src/components/PageMotion.tsx`, `src/styles.css`, routing tests and these existing docs. Keep the invitation overlay outside route Suspense so it does not restart page arrival or the garden.

## Monorepo migration and publication

User explicitly authorized moving the complete website into the Coconerd repository, testing, creating logical commits and pushing both `main` and `fe` after fetching and resolving conflicts. Initial fetched main: `47ca104`. Created `fe` from that main. The existing classification branch and the separate checkout remain intact.

- [x] Move `coconerd-web/` to `web/`, retaining source, assets and ignored local tooling.
- [x] Fix the bridge launcher to resolve the parent backend and its virtualenv independently of the caller's directory; update root/web setup documentation and ignore rules.
- [x] Verify backend (180 tests), bridge (2 tests), web (11 tests), production build and Python lint/format checks from the new location.
- [x] Start the production preview from `web/` on the existing local URL.

Direct production HTTP smoke and browser checks could not run: automatic permission review timed out twice for the CLI smoke and once for the browser read. These checks are not claimed as passed. Group commits into the public website, optional backend bridge and monorepo documentation; fetch again and reconcile main/fe before publishing both refs without rewriting remote history.
