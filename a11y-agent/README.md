# a11y-agent

> **Work in progress.** The widget is live on gonzalezerik.com and the ops
> agent is deployed, but the loop is not working end to end today — see
> [Known gaps](#known-gaps). These files are extracted from two larger
> Next.js apps (the portfolio site and a private ops dashboard), with their
> commit history, so they are a reference implementation rather than a
> package you can install.

A visitor-facing accessibility reporting loop: someone hits a barrier on the
site, reports it, an agent triages the report against a named WCAG 2.2
success criterion and proposes a patch, and a human decides whether it ships.

## The flow

1. **Report** (`site-widget/`). A floating "Report an accessibility issue"
   button opens a modal dialog (focus trapped, Escape closes, focus returns
   to the trigger). The visitor describes the problem and can leave an email
   for status updates. `POST /api/a11y-report` stores it in the site's
   `a11y_reports` table and forwards it to the ops agent with a shared-secret
   webhook.
2. **Triage** (`ops-agent/lib/a11y-agent.ts`, `lib/agent-llm.ts`). The agent
   emails the reporter "received", then asks an OpenAI-compatible model
   whether this is a genuine WCAG 2.2 Level AA failure, which success
   criterion, which source file, and a minimal patch (original lines →
   patched lines) with a confidence.
3. **Record.** Every triage is written to the `agent_runs` audit log. A
   dismissal emails the reporter the reason; a valid report becomes a
   `proposed fix` run and an ntfy notification.
4. **Human approval** (`ops-agent/app/a11y/`, `components/a11y/`). The
   dashboard lists reports with the criterion, analysis, confidence and diff.
   Nothing ships without a person pressing Deploy.
5. **Deploy** (`ops-agent/app/api/a11y/[id]/deploy/route.ts`). The patch is
   applied only if the original lines still match the current file exactly
   (otherwise 422, review by hand), committed to the site repo with the run
   id in the message, and a Kaniko build Job is started. A background task
   waits for the build, restarts the site pod, checks that the site answers
   HTTP 200, and emails the reporter that the fix is live. It does not
   re-test the reported barrier itself.

`ops-agent/evals/a11y_fix/tasks.json` holds two eval cases (a
low-contrast report classified valid, a non-accessibility complaint
dismissed) for the dashboard's agent eval runner, which is not part of this extraction.

## Known gaps

Found while extracting this on 2026-10-08:

- **A failed model call is treated as "not a valid issue".** If the LLM
  endpoint is unreachable, `diagnoseA11y()` returns `null`, and the agent
  dismisses the report and emails the reporter that it isn't a WCAG barrier.
  The configured endpoint is currently down, so the next real report would
  be wrongly dismissed. A failed call should leave the report pending and
  alert a human instead.
- **The ops side never stores the report.** `insertA11yReport()` is never
  called, so the status updates and run links in `a11y-agent.ts` match no
  rows: the dashboard's report list stays empty and the site's copy stays
  `pending`. The triage still lands in `agent_runs`.
- **The patch is written blind.** The model guesses the file and the
  original lines without seeing the source; the file is fetched only after
  the diagnosis. The exact-match check at deploy time makes this fail safe,
  but most real patches will not apply. The source should go into the
  prompt.
- **Free-text parsing.** The model answers in labeled sections parsed with
  regexes. A JSON-schema-constrained call with typed answers (the pattern
  `luna/` uses) would remove a class of parse failures.
- **SMTP skips certificate verification** (`rejectUnauthorized: false`),
  and the webhook secret is compared with `!==` rather than a constant-time
  comparison.
- **Retention.** Reporter IP and email are stored with no retention policy.
- **No automated accessibility checks** for the widget or the dashboard
  page yet, and no record of screen-reader testing. The widget was built
  with keyboard and ARIA dialog behavior in mind, but that is not the same
  as verified WCAG 2.2 AA conformance. An axe-core check in CI is the next
  step.

## Configuration

Site: `MISSION_CONTROL_WEBHOOK_URL`, `MISSION_CONTROL_WEBHOOK_SECRET`.
Ops agent: `MISSION_CONTROL_WEBHOOK_SECRET`, `DATABASE_URL`, `A11Y_LLM_URL`,
`A11Y_LLM_MODEL`, `FORGEJO_URL`, `FORGEJO_TOKEN`, `PORTFOLIO_REPO_OWNER`,
`PORTFOLIO_REPO_NAME`, `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASS`/
`SMTP_FROM`/`SMTP_SECURE`, `NTFY_URL`, `NTFY_TOPIC`.

The dashboard page imports the host app's `PageShell` layout component, and
the site route imports the host app's Drizzle `db` instance; neither is
included here.
