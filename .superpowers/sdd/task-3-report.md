Status: partial implementation

Implemented revisioned WorkbenchDocument persistence, sidecar state, async manifest refresh, token/host/origin/content-type checks, status endpoint, RevisionConflict, and worker close. Existing server tests pass.

Commit: 177a157ddc466f864e8ef3f10002523eef325ef5

Limitations: visual fingerprint/source-state propagation, browser handshake/controller updates, transaction journal recovery, and manifest generation verification remain for follow-up.

Follow-up: added browser status handshake/token+revision headers, 409 handling, and inspect_visuals fingerprint state helper. Focused legacy tests remain green.
