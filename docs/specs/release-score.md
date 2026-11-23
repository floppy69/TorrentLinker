# ReleaseScore integration, #117

Approved preview: branch `codex/release-score-preview`, commit `a2e5254`, `docs/specs/release-score/prototype.html`. The owner approved the compact pills and profile-fit colours on 20 November 2026 after reviewing desktop/Web, French and light theme. Approval was recorded in issue #117 before implementation.

Decisions: equipment questionnaire now; editor in existing Search settings; unknown season estimates until enough facts exist; Poussée later. The numeric score and profile colour are independent. Do not replace the pills with large score cards.

The Python engine follows ReleaseScore 0.3.0, pinned at cb65746203871d29a04acdf5447c3f662ba072cb. `scripts/generate_release_score_reference.cjs` regenerates the offline reference fixture from that checkout. Tests never fetch upstream or c411. Licensing is bundled in the Python package and both Documentation guides.

Search re-scores saved listing facts and cached detail documents. Settings persist the six built-in profiles, custom profiles, active choice and equipment in the shared app settings. No supplementary Indexer calls are used for scoring. The best green row is selected within the returned page, not across unrequested pages.
