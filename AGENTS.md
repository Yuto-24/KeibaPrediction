# Repository working rules

- Treat forecast snapshots as immutable historical evidence. Never overwrite them with post-race tuned values.
- Enforce `asof < race_at`; every data feature/market quote used in a decision must have `available_at <= asof`.
- Keep outcome files separate from prediction features. Never introduce target leakage to improve scores.
- Use only real, traceable source results. Mark fixtures and sensitivity calculations explicitly; do not fabricate real predictions.
- Run `python -m unittest discover -s tests -v` after code changes.
- Read `docs/DECISIONS.md` before changing probability models or the minimum training-race guard.
- Historical data imports must preserve source/capture evidence and reject future data by default. Never present synthetic or retrospective-only features as independent real-world validation.
- Review `docs/HISTORICAL_FEATURES.md` and `docs/SOURCES.md` before bringing any third-party race data into a public repository; do not republish restricted vendor extracts.
