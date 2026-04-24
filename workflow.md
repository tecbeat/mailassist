# AI Mail Manager -- Workflow

> Binding instructions for AI agents. Follow sequentially. No steps may be skipped.

## 1. GitLab (git.teccave.de)

**Remote:** `git@git.teccave.de:tecbeat/mailer.git`
**CLI:** Use `glab` for all GitLab interactions.
**Language:** All issues, comments, MR descriptions, and commit messages must be written in **English**.

## 2. Structure

```
Milestone (overarching goal)
  └── Issue (self-contained work unit)
       └── Task (checkbox in issue body: `- [ ]`)
            └── Todo (nested checkbox: `  - [ ]`)
```

- Every issue belongs to exactly one milestone.
- Tasks break an issue into implementable steps.
- Todos break a task into atomic actions.

**Example issue body:**
```markdown
## Description
Brief goal description.

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Tasks
- [ ] Task 1: Implement X
  - [ ] Create file Y
  - [ ] Add function Z
  - [ ] Write tests
- [ ] Task 2: Update config
  - [ ] Add env variable
  - [ ] Update docs
```

## 3. Issue Title Prefixes

Every issue title **must** start with exactly one prefix:

| Prefix | Purpose |
|---|---|
| `[BUG]` | Bug fix |
| `[FEATURE]` | New functionality |
| `[UI]` | Frontend / design change |

**Examples:**
- `[BUG] Email summary fails on duplicate mail_uid`
- `[FEATURE] Auto-add sender email to contact after assignment`
- `[UI] Dashboard shows wrong provider count`

## 4. Workflow Labels

Strictly linear. No skipping. Each issue carries exactly **one** workflow label at a time.

**Allowed labels — these are the ONLY labels that may exist on the project:**

| Label | Purpose |
|---|---|
| `ready` | Refined and ready for implementation |
| `doing` | Actively being worked on |
| `review` | Implementation complete, user must review MR |

> **No other labels may be used.** Do not create, assign, or keep any labels beyond these three.

> There is no `done` label. When the user accepts a review, the issue is **closed**.

### Issue lifecycle

```
(open, no label) → ready → doing → review → (close issue)
```

When an issue is created (by the user or AI), the AI **immediately refines it**:
1. Rewrite the title into proper English with the correct prefix (`[BUG]`, `[FEATURE]`, or `[UI]`)
2. Analyze the issue and relevant codebase
3. Fill the issue body: description, acceptance criteria, tasks with todos (see example in section 2)
4. Assign a milestone (create if needed)
5. **Do NOT set any label.** The issue stays unlabelled (backlog) until the user moves it to `ready`.

> Issues without a label are the backlog. The user decides when an issue is ready for implementation by setting the `ready` label.

### Transitions

| Transition | Who | Condition |
|---|---|---|
| (open) → refined (no label) | AI | Issue body complete (description, criteria, tasks with todos) |
| (no label) → `ready` | **User** | User approves and moves issue to ready |
| `ready` → `doing` | AI | AI starts implementation |
| `doing` → `review` | AI | All tasks done, MR created |
| `review` → closed | User | User accepts, closes the issue |
| `review` → `doing` | User | User requests changes |

**Rules:** Max 1 issue on `doing` at a time. AI never sets `ready` or closes issues. User never sets `doing` or `review`.

## 5. Workflow Steps

### 5.1 Pick Up Work

1. `glab issue list --label="doing"` → Continue there (5.4)
2. `glab issue list --label="ready"` → Pick oldest, go to 5.4
3. `glab issue list` (open, unlabelled) → Refine (5.3), then **stop** — the issue stays in backlog until the user sets `ready`
4. No issues → Check milestones, propose new issues if appropriate

### 5.2 Housekeeping

```
glab issue list --all
```

Ensure all open issues have: one workflow label, one milestone, proper description, correct title prefix. Fix any that don't.

### 5.3 Refinement (new issue → backlog)

1. **Rewrite the title** into proper English with the correct prefix (`[BUG]`, `[FEATURE]`, or `[UI]`).
   ```
   glab issue update <id> --title "[FEATURE] Descriptive title"
   ```
2. Analyze issue and relevant codebase
3. Fill issue body: description, acceptance criteria, tasks with todos (see example in section 2)
4. Assign milestone (create if needed)
5. **Do NOT set any label.** The issue stays unlabelled (backlog).
6. **Stop. The user will set `ready` when they want it implemented.**

### 5.4 Implementation (`ready` → `doing`)

#### Pre-flight check: find or create the feature branch

There must be **at most one** open MR targeting `development` at any time. Check:

```
glab mr list
```

- **No open MR exists:** Create a new feature branch from `development` (see "New feature branch" below).
- **An open MR exists:** Reuse its feature branch. Create a working branch from that feature branch and merge your work into it. Update the MR title and description to cover all included issues.

> This ensures there is always exactly one MR open — no parallel branches, no merge conflicts. You can keep working without waiting for the user to merge.

#### New feature branch (no open MR)

1. Set label:
   ```
   glab issue update <id> --unlabel "ready" --label "doing"
   ```

2. Create **feature branch** from `development`:
   ```
   git fetch origin
   git checkout -b <id>-<issue-title-slug> origin/development
   git push -u origin <id>-<issue-title-slug>
   ```

3. Create **working branch** from the feature branch:
   ```
   git checkout -b work/<id>-<issue-title-slug> <id>-<issue-title-slug>
   ```

#### Join existing feature branch (open MR exists)

1. First, check if the user has **already merged** the existing MR since last check:
   ```
   glab mr list
   ```
   If the MR is gone (merged), clean up locally and start fresh with "New feature branch" above.

2. If the MR is still open, create a working branch from the existing feature branch:
   ```
   git fetch origin
   git checkout <existing-feature-branch>
   git pull origin <existing-feature-branch>
   git checkout -b work/<id>-<issue-title-slug> <existing-feature-branch>
   ```

3. Set label:
   ```
   glab issue update <id> --unlabel "ready" --label "doing"
   ```

#### Implement

- Work through tasks/todos sequentially
- Follow `docs/requirements.md` conventions
- Commit regularly with concise English messages
- Check off completed todos (`- [x]`) in the issue body
- Found bugs → create new issues with `[BUG]` prefix
- After completing a task (or a logical group of changes), post a comment **on the MR** (not the issue) explaining what was done, why, and which files were affected. Always reference the issue in the comment:
  ```
  glab mr note <mr-id> -m "Re #<issue-id>: <what was done>"
  ```

### 5.5 Merge Request

The merge flow is always: **working branch → feature branch → development**.

#### Step 1: Merge working branch into feature branch

1. Rebase working branch onto feature branch:
   ```
   git checkout work/<id>-<issue-title-slug>
   git rebase <feature-branch>
   ```

2. Fast-forward the feature branch:
   ```
   git checkout <feature-branch>
   git merge work/<id>-<issue-title-slug>
   git branch -d work/<id>-<issue-title-slug>
   ```

#### Step 2: Push and create or update MR

1. Rebase onto latest `development`:
   ```
   git fetch origin
   git rebase origin/development
   ```
   Resolve any conflicts, then continue.

2. Push:
   ```
   git push origin <feature-branch> --force-with-lease
   ```

3. **If no MR exists yet**, create one. The MR must reference **all issues** included in the feature branch:
   ```
   glab mr create \
     --title "Resolve: <Issue Title>" \
     --description "$(cat <<'EOF'
   ## Summary
   <What changed and why>

   ## Changes
   - <Change 1>
   - <Change 2>

   Closes #<issue-id-1>
   Closes #<issue-id-2>
   EOF
   )" \
     --target-branch development \
     --source-branch <feature-branch> \
     --remove-source-branch
   ```

4. **If an MR already exists**, update its title and description to include the new issue:
   ```
   glab mr update <mr-id> \
     --title "Resolve: <combined title>" \
     --description "$(cat <<'EOF'
   ## Summary
   <Updated summary covering all issues>

   ## Changes
   - <Change 1>
   - <Change 2>

   Closes #<issue-id-1>
   Closes #<issue-id-2>
   EOF
   )"
   ```

   > **All progress comments go on the MR, not the issue.** The issue is only for the spec; the MR is the place for implementation discussion. Always reference the issue (`#<id>`) in MR comments.

5. Set label on completed issues:
   ```
   glab issue update <id> --unlabel "doing" --label "review"
   ```

6. Continue with the next issue (back to 5.1). No need to wait — merge your next working branch into the same feature branch.

#### After user merges the MR

Before picking up the next issue, always check if the MR was merged:

```
glab mr list
```

If merged: clean up local branches, then start a new feature branch from `development` for the next issue.

## 6. Git Rules

| Rule | |
|---|---|
| No direct push/merge to `main` or `development` | Only via merge requests |
| Branches always from `development` | `git checkout -b <branch> origin/development` |
| One working branch per issue | Working branch: `work/<id>-<slug>`, merged into feature branch |
| Only one MR open to `development` at a time | Multiple issues share one feature branch — no parallel MRs |
| Commit messages in English | Short, explains the "why" |
| MR target is `development` | Never target `main` directly |
| Rebase before MR push | `git rebase origin/development` |
| Enable "Delete source branch" on MR | Always set `--remove-source-branch` |
| Delete branches after merge | `git branch -d <branch>` locally after MR is merged |
| Check MR status before new work | If MR was merged, start fresh feature branch; if open, join it |

### Boy Scout Rule

> Leave the codebase cleaner than you found it.

Before starting new work, run a quick housekeeping check:

```
git fetch --prune
git branch --merged origin/development   # delete any listed (except main/development)
```

Delete stale local and remote branches. There should never be branches lingering without an open MR.
