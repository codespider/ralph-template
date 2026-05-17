# Ralph Loop Builder Guidelines

These notes capture how to build a reusable Ralph-style loop setup: spec,
plan, progress log, kernel prompt, and loop runner. They are written so they
can later be split into a Codex skill.

## Use Ralph When

- The work has clear acceptance criteria and can be verified by tests, builds,
  screenshots, smoke tests, or other repeatable checks.
- The project can tolerate autonomous local edits, local commits, and repeated
  agent sessions.
- The scope is a POC, greenfield build, contained refactor, or focused feature
  branch.

Avoid Ralph for exploratory product discovery, production incident response,
security-sensitive systems without a sandbox, or work that needs frequent human
judgment.

## Recommended File Set

- `ralph/SPEC.md`: immutable contract for what must be built.
- `ralph/PLAN.md`: mutable ordered checklist of work items.
- `ralph/PROMPT.md`: kernel prompt fed to the agent each iteration.
- `ralph/PROGRESS.md`: append-only iteration log.
- `ralph/STOP`: sentinel file created by a human or the agent.
- `ralph/iterations/`: per-iteration logs, ignored by git.
- `ralph/ralph.sh`: loop runner.

Optional files:

- `AGENTS.md`: short operational notes for all coding agents.
- `ralph/COSTS.md`: manual or automated token, duration, and model tracking.
- `ralph/REVIEWS.md`: human review findings after loop runs.

Keep long status history out of `AGENTS.md`. It pollutes every future agent
context. Put status in `PROGRESS.md` and durable operating lessons in
`AGENTS.md`.

## SPEC.md Rules

Treat the spec as the contract. The loop should not edit it.

Include:

- Goal, user-visible behavior, non-goals, and frozen technology choices.
- Inputs, outputs, state changes, data model, and external integrations.
- Hard constraints and prohibited approaches.
- Acceptance criteria written as observable outcomes.
- Definition of done, including exact verification commands.
- Manual smoke test steps for the final gate.

Avoid:

- Vague criteria like "works well" or "make it robust".
- Hardcoded dates that will age out. Use relative generation instructions for
  payloads that require recent timestamps.
- Over-specifying implementation details that should be left to the agent,
  unless the detail is a real constraint.

## PLAN.md Rules

The plan is mutable and disposable. It exists to keep each fresh-context
iteration aligned.

Each item should be small enough for one iteration and should imply:

- Code changes.
- Required tests or validation.
- Documentation or config updates if relevant.
- A clear done condition.

Prefer phase ordering:

1. Foundation and dependencies.
2. Domain model and validation.
3. Persistence and durable constraints.
4. External clients.
5. Business handlers.
6. Integration layer.
7. Operability and docs.
8. Final clean build and smoke test.

Require the agent to mark an item complete only after implementation,
verification, progress logging, and commit. If the plan is stale or cluttered,
regenerate it from the spec and current code.

## PROMPT.md Rules

The kernel prompt should be short, strict, and repeatable.

Include:

- Required reading order: spec, plan, recent progress, agent instructions,
  git status, relevant code.
- Instruction to pick the smallest next unchecked task.
- Instruction to verify the code state because the plan can be wrong.
- One-slice-per-iteration rule.
- Test and build expectations.
- Progress log template.
- Commit policy.
- Stop and escalation criteria.

Escalate when:

- The spec is contradictory.
- Three iterations make no forward progress on the same task.
- Required infrastructure cannot be reached.
- The agent would need risky credentials or broad system access.

## PROGRESS.md Rules

Make progress append-only and concise. Each entry should include:

- Timestamp and iteration number.
- Picked task.
- Files or modules changed.
- Tests added or changed.
- Validation command and result.
- Build duration, if known.
- Model and token/cost data, if available.
- Next recommended task.
- Blockers or decisions.

Do not let the progress log become a substitute for code review. It is a trace,
not proof of correctness.

## Loop Runner Requirements

A Ralph runner should be intentionally boring.

Required capabilities:

- Fresh agent process per iteration.
- Max iteration cap.
- Consecutive failure cap.
- Consecutive no-progress cap.
- `STOP` sentinel support.
- Dry-run mode that does not require the agent binary.
- Per-iteration logs.
- Session log.
- Claude cost ledger and summary when using `claude -p --output-format json`.
- Signal handling.
- Configurable prompt, stop file, log directory, model, and sleep interval.
- Dangerous permission bypass only by explicit opt-in.

Completion signaling:

- Prefer `STOP` as the primary completion signal.
- Optionally support a completion phrase, but do not rely on it alone.
- On repeated failure or no progress, create `STOP` with `ESCALATE` and a short
  reason.

Telemetry to capture:

- Iteration number.
- Claude command and model.
- Exit code.
- Start and end timestamp.
- Duration.
- Git diff or commit movement.
- `total_cost_usd` from Claude Code JSON output when available.
- Token fields from Claude Code JSON output as best-effort supporting detail.

Avoid:

- `eval` for arbitrary command construction.
- Unlimited default iterations.
- Silent retries after nonzero exits.
- Requiring the agent binary for dry-run.
- Treating a green build as proof that acceptance criteria were met.

## Code Quality Lessons From This POC

Use durable correctness boundaries. Application-level idempotency checks are
not enough for concurrent queue delivery. Add database unique constraints or
other atomic guards where correctness depends on uniqueness.

Test production configuration, not only handcrafted test configuration. If
runtime uses Spring's `ObjectMapper`, test that exact mapper for schema
behavior.

Avoid time-sensitive tests and docs. Inject `Clock` for validators and generate
fresh event timestamps in smoke-test commands.

Keep dependency requirements current. If the spec says "latest stable 3.x",
verify the latest version during planning instead of relying on memory.

Test concurrency and failure behavior where the system is concurrent. Unit tests
for happy-path idempotency do not prove race safety.

Separate high-risk and low-risk tasks. Split persistence, concurrency, schema,
and integration work tightly. Batch low-risk docs and config when it reduces
iteration cost without increasing correctness risk.

## Cost Controls

Start with conservative defaults:

- `RALPH_MAX_ITER=10` or `20` for a first run.
- Stop after three consecutive failures.
- Stop after three consecutive no-progress iterations.
- Use targeted tests inside most iterations.
- Run full build at phase gates and at the end.
- Use `claude -p --output-format json` so the runner can capture
  `total_cost_usd` per iteration.
- Set a per-iteration cap with Claude Code's `--max-budget-usd`.
- Set a loop-level cap such as `RALPH_MAX_TOTAL_COST_USD=5`.

Model strategy:

- Use a cheaper model for docs, config, small tests, and mechanical cleanup.
- Use a stronger model for spec writing, plan generation, stuck analysis, and
  high-risk architecture decisions.
- Record model and duration for each iteration even if exact tokens are not
  available.

The cheapest iteration is the one you do not run. Spend human effort upfront on
specific acceptance criteria and validation commands.

## Community Options To Evaluate

- Anthropic's official Ralph Loop plugin is verified and convenient inside
  Claude Code, but it runs as a plugin loop inside the session model. Evaluate
  whether that matches your desire for fresh context.
- Geoffrey Huntley's Ralph playbook is the canonical methodology reference:
  simple outer loop, plan/spec state on disk, and backpressure through tests.
- `fstandhartinger/ralph-wiggum` combines Ralph with a SpecKit-style workflow
  and includes scripts for multiple agents, including Codex.
- `coleam00/ralph-loop-quickstart` and JeredBlu's guide are useful process
  references, especially for POCs and frontend visual validation.

Treat community scripts as examples, not drop-in infrastructure. Read them,
pin a commit, and adapt safety defaults to your environment.

## Future Skill Shape

When converting this into a skill, keep `SKILL.md` short:

- Frontmatter description should trigger on requests to create Ralph loops,
  spec-driven autonomous coding harnesses, or Ralph artifacts.
- Body should contain only the workflow and file map.
- Put this longer guide under `references/ralph-loop-builder.md`.
- Put the runner under `scripts/ralph-loop.sh`.
- If choosing Python, put the runner under `scripts/ralph-loop.py`.
- Put the Claude cost parser under `scripts/claude-cost-accounting.py`.
- Optionally add templates under `assets/ralph/`.

Forward-test the skill on a small throwaway repo before using it on valuable
code.
