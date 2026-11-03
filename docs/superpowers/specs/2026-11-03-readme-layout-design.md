# README layout design

## Intent

Make the repository README easier to scan on GitHub while preserving the current setup, security, bot integration, API, configuration, testing, and documentation information.

## Goals and constraints

- Keep the content and Vietnamese language already in the README.
- Improve section order, whitespace, headings, and visual grouping.
- Keep bot implementation and setup explicitly outside this repository.
- Do not add unverified badges, metrics, or claims.

## Approaches

- **Compact landing page:** move most reference material into linked docs. Rejected because it removes useful context the user asked to retain.
- **Readable full README (chosen):** keep all current information, surface quickstart and bot boundary early, group the integration flow, and collapse long reference tables. This improves scanning without losing detail.

## Scope

Edit only `README.md`. Preserve existing technical behavior and links. Verify the links and Markdown diff; do not alter code or run the test suite for this documentation-only change.
