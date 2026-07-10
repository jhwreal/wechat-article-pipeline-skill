Status: partial implementation (revision/HTTP/async refresh and source-state validation landed; transaction recovery remains limited)

Implemented revisioned WorkbenchDocument persistence, sidecar state, async manifest refresh, token/host/origin/content-type checks, status endpoint, RevisionConflict, and worker close. Existing server tests pass.

Commit: 177a157ddc466f864e8ef3f10002523eef325ef5

Limitations: visual fingerprint/source-state propagation, browser handshake/controller updates, transaction journal recovery, and manifest generation verification remain for follow-up.

Follow-up commits: `d0ef62d` (candidate manifest coalescing, source-state propagation, visual fingerprints), `c971009` (publisher source-state checks plus legacy/rejection tests).

Verification: `python3 -m unittest wechat-article-pipeline/tests/test_serve_wechat_workbench.py -v` and `python3 -m unittest tests/test_wechat_draft_html.py -v` pass.

Known limitation: transaction journal recovery currently validates the journal's recorded file hashes and removes an intact journal, or reports `recovery_required` on mismatch; it does not yet replay staged temporary files. Do not claim full crash-recovery completion until replay is implemented.
