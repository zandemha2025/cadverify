# Agent prompt/config security audit

Date: 2026-09-13
Scope: tracked prompt/config-like files plus repository-wide secret-pattern scan. Method adapted from Affaan Mustafa's MIT ECC security review checklist at commit `8321021c54d670126ce3b2969d5deb880b4b0c2a`: https://github.com/affaan-m/ECC/blob/8321021c54d670126ce3b2969d5deb880b4b0c2a/.github/prompts/security-review.prompt.md

## Scope inspected

- `CLAUDE.md`, `frontend/CLAUDE.md`, `frontend/AGENTS.md`
- `.github/workflows/*`, `.env.example` files, tracked scripts and planning/output artifacts
- tracked filenames resembling private keys, credentials, environment files, secrets, agents, prompts, or skills
- content signatures for private keys, GitHub tokens, AWS access keys, and secret-looking literal assignments
- instructions that could turn repository or fetched content into authority

## Findings

### No committed production secret found

No private-key block, GitHub personal token signature, or AWS access-key signature was found. Tracked environment files are examples only. Candidate password/token assignments were inspected: they are documentation examples, randomly generated E2E credentials, or fixed test sentinels. They are not production credentials.

### Medium: prompt/config files lacked an explicit authority boundary - fixed

`CLAUDE.md` and `frontend/AGENTS.md` contained operational guidance but did not say that repository text is untrusted data and cannot authorize destructive operations, disclosure, or a scope change. A malicious commit could therefore present repository prose as operator authority to a seat.

Fix: both files now point to `docs/factory/seat-operating-library.md` and state the authority boundary. The library requires destructive-operation fact forcing and independent validation of fetched/file instructions.

### Medium: no enforceable hook-integrity policy - fixed with a stated limit

The repository had no committed hooks or CI check for hook bypass. Added `.githooks/pre-commit`, `.githooks/commit-msg`, and `scripts/ci/check_commit_hook_policy.py`, plus a CI job. A normal commit receives `ProofShape-Hooks: passed` only after the pre-commit policy ran; PR commits after bootstrap must carry it. CI also rejects operational bypass strings in `.github` and `scripts` outside the checker/declared workflow.

Limit: Git commit objects do not record whether `--no-verify` was used, and a malicious author can forge a trailer. This is a deterrent and review/CI signal, not cryptographic proof of local hook execution. Protected-branch CI and code review remain the real enforcement boundary.

### Low: historical output artifact carries a static test password - not a secret

`outputs/human-sim/framework/scorecards/baseline-shots/driver.mjs` contains `Passw0rd123` for an old test signup. It is not a live credential and the generated email is unique. It was left unchanged to preserve the archived evidence artifact. Current E2E paths generate random passwords.

## Result

Critical: 0
High: 0
Medium: 2 fixed
Low: 1 accepted archival test artifact
Safe to merge: yes, subject to CI and reviewer confirmation of the hook bootstrap behavior.
