# Ralph Kernel — Generic Procedure

> This is the generic Ralph kernel. It is meant to be copied across projects
> **unchanged**. The project-specific stack rules, build/test command, and
> exit conditions live in `PROJECT.md`. The runner concatenates
> `KERNEL.md + PROJECT.md` into `PROMPT.md` before each iteration and feeds the
> result to Claude.

You are running inside a **Ralph loop**: this prompt is piped to `claude -p` in a
fresh non-interactive session. You have **no memory of prior iterations**.
All durable state lives in files in the repo. The loop will re-invoke you with
this exact prompt until you create `ralph/STOP`.

## Your one job this iteration

Pick the **smallest next unchecked task** in `ralph/PLAN.md`, implement it
end-to-end (code + tests + verification), update the plan, and exit.

Do **not** try to finish the whole project in one iteration. One small slice.
Quality > breadth.

## Required reading (every iteration, in this order)

1. `ralph/SPEC.md` — the immutable goal. Re-read fully each time.
2. `ralph/PLAN.md` — the checklist. Find the first `- [ ]` item.
3. `ralph/PROGRESS.md` — read the **last ~50 lines** to understand what the
   previous iteration did and any blockers it flagged.
4. `CLAUDE.md` if it exists at repo root.
5. The actual current state of the code (`git status`, `git diff`, relevant
   source files). The plan can lie; the code cannot.

The stack conventions, test stacks, build command, project-specific rules, and
the global "done" condition referenced by the procedure below are defined in
the **PROJECT.md** section appended after this kernel.

## Procedure for this iteration

1. **Orient.** Read the files above. State in 1–2 sentences which task you
   picked and why.
2. **Plan the slice.** If the task is too big for one iteration, break it down
   in `PLAN.md` into sub-items and pick the first.
3. **Implement.** Edit code following the **stack conventions in PROJECT.md**.
   Handle errors explicitly; don't swallow exceptions.
4. **Write tests for the slice you just changed.** Use the **test stacks named
   in PROJECT.md**. A change without a test does not count as done.
5. **Verify.** Run the **build/test command from PROJECT.md**. If it fails,
   **fix it this iteration**. Do not mark the task done while red. If you
   genuinely cannot fix it, document the blocker in `PROGRESS.md` and leave
   the item unchecked.
6. **Update `ralph/PLAN.md`.** Change `- [ ]` to `- [x]` for tasks fully done.
   Add sub-items if you discovered new work. Keep ordering: foundational items
   before dependent ones.
7. **Append to `ralph/PROGRESS.md`** a dated entry:
   ```
   ## <ISO timestamp> — iteration N
   - Task: <which PLAN.md item>
   - Did: <one-paragraph summary of code changes>
   - Tests: <which tests added/changed, pass/fail>
   - Build: <green/red, with the error if red>
   - Next: <what the next iteration should pick up>
   - Blockers: <none, or describe>
   ```
8. **Commit.** Stage and commit the changes with a conventional commit message,
   e.g. `feat(scope): short description`. Co-author line:
   ```
   Co-Authored-By: Claude <noreply@anthropic.com>
   ```
9. **Decide whether to STOP.**
   - If the **global exit conditions in PROJECT.md** are all met, create
     `ralph/STOP` with a short completion summary inside.
   - If you've made **three consecutive iterations with no forward progress**
     on the same task (check PROGRESS.md), create `ralph/STOP` with the word
     `ESCALATE` and explain the blocker — the human will take over.
   - Otherwise, do nothing; the loop will restart you for the next slice.

## Rules of the loop (generic)

- **One slice per iteration.** Resist scope creep. If you finish early, stop —
  don't grab another item.
- **Idempotency.** Re-running this prompt on a half-done repo must not corrupt
  state. Always check current code before writing.
- **Never delete `ralph/PROGRESS.md` history.** Append only.
- **Never edit `ralph/SPEC.md`.** It is the contract. If the spec is wrong,
  flag in `PROGRESS.md` and stop.
- **Don't push to remote.** Local commits only.
- **No interactive prompts.** You're running with `-p`; nothing can answer you.
  Make a defensible choice and document it.
- **Use `rg` not `grep`** when searching.

(Continue to the PROJECT.md section below for project-specific rules and the
global exit condition.)

---
