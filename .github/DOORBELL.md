# Desk doorbell

This branch and its pull request are never merged.

The Desk fixer routine starts one session per new issue. Routine sessions can't message the Desk
orchestrator, and comments made through the Claude app don't reach it, but CI finishing on this
PR does. So the routine's session appends "issue #<n>" to `.github/doorbell.log` here and pushes;
the `doorbell` workflow finishes in seconds, which wakes the orchestrator. On this branch only,
the `test` workflow is skipped so the ring stays fast.
