# Desk doorbell

This file only exists so the "Desk doorbell" pull request has a diff. That PR is never merged.

The Desk fixer routine starts one session per new issue. Routine sessions can't message the Desk
orchestrator, but the orchestrator is subscribed to the doorbell PR, so a comment there wakes it
within seconds. The routine's session comments "Doorbell: issue #<n>" on it and stops; the
orchestrator puts the issue on Desk Desk and starts the fixer.
