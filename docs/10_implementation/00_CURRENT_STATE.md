# Etat courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_08_MULTILINGUAL_TOPOLOGY_CANDIDATE` |
| Last completed/integrated stage | `STAGE_07_REACT_DASHBOARD_I18N_AND_INTERACTIONS` |
| Base main | `d644015903953ef1dc46626562004746f2208c1c` |
| STAGE 07 functional tested code | `3b81127fa5504ae9e0ad0a75e57da4b5d2362332` |
| STAGE 07 approved final head | `117b9a519e5edd4ff2f40d7d6e388693230ef595` |
| STAGE 07 merge commit | `215bdefeafee5f89c3db9d0817fa64e733e5ec61` |
| STAGE 07 tag | `stage-07-complete` -> `215bdefeafee5f89c3db9d0817fa64e733e5ec61` |
| Branch | `stage/08-multilingual-topology` |
| Last migration | `0014_stage_08`; parent `0013_stage_07`; single head pending final merge of candidate |
| Implementation | Stage 08 multilingual topology domain added: language profiles, member visible language sets without primary language, resource inheritance/override resolver, translation groups/routes, provider capability contract, and stage validator integration for `08`. |
| Data model | `language_profiles`, `member_visible_languages`, `resource_language_policies`, `translation_groups`, category/channel variants/groups, `translation_routes`, `translation_provider_bindings`, and `visibility_scope_language_roles` with tenant-scoped composite keys and fail-closed checks. |
| Tests status | `PASS` on Stage 08 targeted unit proof: 6/6 Stage 08 tests and full `python scripts/validate_stage.py 08` gate after format/lint cleanup. |
| Traceability | Stage 08 validation scaffold records `REQ-I18N-001..042` + `REQ-I18N-026A` in the stage validator; the feature remains a candidate pending broader live sandbox and provider-specific security confirmation. |
| Discord live status | `NOT_RUN` in this branch; no external bot token or sandbox config was introduced. |
| GitHub publication | Local branch prepared for draft PR, not merged or published yet from this workspace. |
| Next stage | `STAGE_08_READY_FOR_REVIEW` / `STAGE_09_CAMPAIGN_ENGINE_DISABLED` |
| Known limitations | Provider bindings are modeled and guarded but not fully exercised against external bot/provider credentials; real Discord sandbox proof remains required before full production acceptance. |

Le détail est dans [`STAGE_08_HANDOFF.md`](../90_handoffs/STAGE_08_HANDOFF.md). STAGE 08 est en candidate implementation on branch `stage/08-multilingual-topology`; elle n'a pas été mergée dans `main`.
