# README Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Make the GitHub README easier to scan while preserving its current technical information.

**Architecture:** Change only `README.md`. Keep the existing Vietnamese copy and details, improve heading hierarchy and whitespace, and make dense reference sections collapsible.

**Tech Stack:** GitHub-flavored Markdown.

**Spec:** `docs/superpowers/specs/2026-11-03-readme-layout-design.md`

## Global Constraints

- Keep bot implementation and setup outside this repository.
- Do not add unverified badges, metrics, or claims.
- Preserve setup, security, integration, API, configuration, testing, and documentation details.

## Review Focus

- Relative README links: verify every target still exists.
- Bot boundary: retain clear language that the bot is external and not included.

---

### Task 1: Improve README scanability

**Files:**
- Modify: `README.md`

- [x] Reorder and format sections for quick scanning while retaining all existing information.
- [x] Verify relative Markdown links resolve and `git diff --check` passes.
