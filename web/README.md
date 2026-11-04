# Coconerd Web

Public website for the Coconerd bot, **no login required**. Night garden aesthetic inspired by Fernhollow documentation; section layout referenced from Jockie Music, without copying music bot visuals or content.

## Running Locally

Requires Node.js 22.12+:

```bash
cd web # from the coconerd repo root
npm ci
npm run dev
```

Open http://127.0.0.1:5173/. Do not open `index.html` via `file://`; the application requires a server to load components. No `.env`, API key, or database is needed to view the website and explore the demo.

## Pages

- Home: Custom Three.js floral scene, pointer interaction, pausable animation, optional ambience audio, and introductory content.
- Features: Three illustrated sections covering conversation linking, summarization, and processing boundaries, with direct links to demo examples.
- Guide: Three setup steps, searchable FAQ with accent-insensitive search, support channels, and service status combined on a single page.
- Add to Discord: Opens a dialog on the current page, using official links when available; allows opening the interactive demo when links are not yet configured. Escape closes the dialog and restores scroll position.
- Demo: Select sample workspaces, search and filter topics, read summaries and discussions, test closing topics, and reset sample data.
- Data & Privacy: Explains message scope, AI processing, storage policy, and demo sandbox boundaries.

All changes in the interactive demo are saved locally in the browser only. The website never reads private conversations, does not manage real servers, and has no login endpoints. Legacy paths `/app`, `/docs`, and `/connect` remain functional; `/faq`, `/support`, and `/status` all route to the Guide page. The navigation bar contains Features, Guide, Demo, and the Add Bot action; Data & Privacy is located in the footer.

The bot mascot sits above the home page headline; warm ivory, charcoal, and muted olive color palette matches the mascot design. The flower field slowly advances toward the viewer in a continuous loop. The pause button freezes the scene; content sections reveal on scroll, and page transitions start after content is loaded. The website respects the operating system's reduced-motion preference.

## Official Links and Status

When links are ready, copy `.env.example` to `.env` and fill in:

```dotenv
DISCORD_INVITE_URL=https://discord.com/oauth2/authorize?client_id=<REAL_ID>&scope=bot
DISCORD_SUPPORT_URL=https://discord.gg/<REAL_INVITE_CODE>
COCONERD_STATUS_URL=http://127.0.0.1:8000/api/v1/health
```

These are syntax templates, not actual invitations. Paste the **complete official invite link** of the bot, including necessary permissions configured in the Discord developer portal; the website does not grant administrative privileges on its own. All three variables can be left empty. Restart the web server after changes.

`GET /api/site` returns only validated Discord links. `GET /api/status` queries the public health endpoint if configured, returning normalized status and check timestamp. Results are cached for up to 30 seconds with a 5-second timeout. No API keys, cookies, or conversation data are sent to that endpoint. Legacy login APIs and admin proxies return 404.

## Local Production Build

```bash
npm run build
npm start
```

By default, listens only on `127.0.0.1:5173`. Not deployed to the public internet.

## Testing

```bash
npm test
npm run build
```

The test suite covers legacy route resolution, invitation dialog behavior, and HTTP endpoints: public links, unsafe URL rejection, elimination of login/admin proxies, unconfigured states, error responses, and caching. TypeScript routing tests use Node.js built-in type stripping. Visual verification notes are documented in [docs/verification.md](docs/verification.md); preview screenshots are in `docs/previews/`.

## Source Scope

The website is located in `web/`, alongside `../backend/` and `../bot/` in the same repository. Run npm commands in `web/`; Python API, worker, and `pyproject.toml` remain run from the repository root. The website does not generate unverified slash command lists.

`bridge/`, Python scripts, and `tests/test_bridge.py` from earlier deployment experiments are retained for internal integration reference. They are **not used by the public website**, do not run automatically, and are not required to run the site. They can be tested independently with `npm run test:bridge` after installing backend Python dependencies from the repository root. The test runner locates `../.venv/bin/python` and backend source in the parent directory of `web/`, independent of the current terminal directory; these can be overridden with `COCONERD_PYTHON` and `COCONERD_BACKEND_SOURCE`. Tests use an isolated database in `.cache/pytest`.

The floral scene and icons are custom-built. The mascot at `public/assets/coconerd-bot.png` is a transparent PNG provided by the user, preserved and displayed on the home page and in the demo. Antonio is used for home page English headings; subpages and body text use Manrope. Fonts are loaded from Google Fonts with standard fallbacks. The website contains no analytics or advertisements.
