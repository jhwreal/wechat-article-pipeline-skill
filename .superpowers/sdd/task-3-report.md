Status: revision/HTTP/async refresh/source-state validation and staged transaction replay implemented.

Implemented revisioned WorkbenchDocument persistence, sidecar state, async manifest refresh, token/host/origin/content-type checks, status endpoint, RevisionConflict, and worker close. Existing server tests pass.

Commit: 177a157ddc466f864e8ef3f10002523eef325ef5

Limitations: visual fingerprint/source-state propagation, browser handshake/controller updates, transaction journal recovery, and manifest generation verification remain for follow-up.

Follow-up commits: `d0ef62d` (candidate manifest coalescing, source-state propagation, visual fingerprints), `c971009` (publisher source-state checks plus legacy/rejection tests).

Verification: `python3 -m unittest wechat-article-pipeline/tests/test_serve_wechat_workbench.py -v` and `python3 -m unittest tests/test_wechat_draft_html.py -v` pass.

Transaction replay landed in `21a8b6d`; startup replaces staged files in journal order when hashes match, otherwise enters `recovery_required`.
