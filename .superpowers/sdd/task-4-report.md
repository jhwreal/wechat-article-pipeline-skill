# Task 4 report

- RED baseline: legacy consumers read `jobs`/`image_slots` independently; contract tests were added to pin v1→v2 normalization, safety, queue bijection, missing-only filtering, and no-image mode.
- GREEN: `python3 -m unittest tests.test_image_jobs_contract -v` (4 tests passed).
- Consumers now normalize through `image_jobs_contract`; packaging derives support plans, verification checks canonical `slots[].output`, and planner missing/debug paths use shared helpers.
- Commit: `c4abb81 refactor: complete image jobs consumer migration`.
