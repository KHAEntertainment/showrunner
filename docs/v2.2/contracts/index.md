# v2.2 SC-1–SC-9 contract specifications and fixture provenance

This directory is the P0-02 delivery package for `KHAEntertainment/showrunner#184`. It specifies the SDP SC-1–SC-9 producer/consumer contract examples and retained fixture provenance. It implements no runtime, records no policy default, and never claims behavioral/runtime/cross-harness/pilot proof from text.

**Canonical source.** Showrunner v2.2 SDP, snapshot SHA-256 `7177580c8429d6e5f8f07e6138de72506ac7a419e9697f5102f842d43a93315b` (819 lines), retained at `~/.traycer/epics/6266293c-edb0-48f6-b8f6-ddd561de1f05/artifacts/v2-2-development-plan/index.md`. Issue #184's body cites the superseded snapshot `dae53a66…` (789 lines); the earlier snapshot `fee134d9…` is superseded by `7177580c…` (re-pinned 2026-11-05).

L0b revision (2026-11-05) cites SDP `7177580c…`; l.540/544/545 unchanged from `fee134d9`.

## Global rules

- **Representation rule** (SDP l.536): the named `*-v1` forms are concrete specification targets, not installed schemas or approved policy defaults. Preserve Dev `schema_version: 2` YAML profile and separate Foreman/board schemas. Version a projection without forcing every source to adopt the same serialization. Unsupported major versions, ambiguous identity, required missing fields, or malformed input yield explicit `invalid`/`unavailable` results. Additive optional fields require common-reader fixtures, not silent parser leniency. Never put operational policy values into examples and call them approved — all fixture values here are synthetic placeholders.
- **Evidence-bundle rule** (SDP l.550): each evidence bundle names source commits, producer/consumer revisions, fixture revision, executed check/result or explicit `not-run`, incompatibilities, and counterpart disposition. **No compatible value is inferred from silence.** Counterpart acceptance is `pending` per consumer in every spec until that consumer records explicit acceptance.
- **SC-2 note** (SDP l.552): the evidence bundle includes the Continue-after-rotation/start-expiry positive case and the replayed-Begin negative case. A generic stale-grant rejection is insufficient and must not accidentally prohibit an acknowledged operation from reaching safety.
- **Version domains** (l.536, D4.5 l.445): three distinct version discriminators are scoped separately — a `*-v1` interface major mismatch is `invalid`; a Dev ledger `schema_version != 2` is failed by the Dev validator (`dev_state.py` l.156–159); and a missing/unknown `completion-result-v1` `profile_version` is `unknown` (not `invalid`). They are never conflated.

## Provenance table

| SC | Contract(s) | Source revision (SDP `fee134d9…`) | Semantic owner | Producer | Consumers (package) |
| --- | --- | --- | --- | --- | --- |
| SC-1 | `assignment-v1` | l.540; D1 l.85; D6.5 l.142 | Dev planning owner | Dev planning + backend adapter | P1; P2, GV, panel (U1); I1 (later) |
| SC-2 | `authorization-context-v1` | l.541; l.250; D2 | Dev execution/recovery owner | Dev operation gates; Foreman grant owner | P2; I1, O-DB, O-STOP (later) |
| SC-3 | `completion-evidence-v1` + `completion-result-v1` | l.542; D4.2 l.372; D4.5 l.426 | GV owner | GV (read-only); Dev lead sole writer | P3, pilot, resume, panel (U1); Foreman audit/hooks (later) |
| SC-4 | `conformance-v1` | l.543 | Dev workflow owner | Dev gate rules + Foreman status checklist | P2, P3; supervisor, Scout (later) |
| SC-5 | `provider-request-v1` / `provider-result-v1` | l.544 | shared utility owner | locator/review helpers + migration diagnostic | P1; U2, O-STOP, O-DB (later) |
| SC-6 | `project-binding-v1` + `record-link-v1` | l.545 | tracker integration owner | `.dev.json` closed schema, Foreman project config/bridge, board config | P1; O-TRACK (later) |
| SC-7 | `run-projection-v1` + `custody-reference-v1` | l.546 | source lead (Dev) | Dev schema-v2 state, Foreman sessions/packets, board | U1 panel, P4, #112; I1, O-LIFE (later) |
| SC-8 | `component-receipt-v1` | l.547 | package/component maintainers | installers/catalog + Foreman install/discovery | P5; I1, U1 (later) |
| SC-9 | `checkpoint-reference-v1` + `recovery-receipt-v1` | l.548; H1 l.479 | handoff adapter + workflow recovery owner | handoff adapter + Dev recovery + Foreman procedures | P2, G3; I1 (later) |

Per-SC spec files: `sc-1.md` … `sc-9.md`. Each names the `*-v1` name/version, semantic + version owner, producer, consumers with package, the required/conditional field table (meanings from the SDP only), accepted/rejected examples, edge cases, and `counterpart_acceptance: pending`.

## Fixture digest index

Every fixture file's SHA-256, recomputed after the last edit. Each fixture carries `status: "not-run"` and `counterpart_acceptance: "pending"`. Values are synthetic placeholders; no operational policy value appears.

| Fixture | SHA-256 |
| --- | --- |
| `fixtures/common/additive-optional-field-common-reader.json` | `98b3d63721db75191c5d1674a91fc84c3c216f89d723eaf87398e8ecb0772e54` |
| `fixtures/common/ambiguous-identity.json` | `7c293bd06cde533d5a8b4f59c2a7a65f021dc77934a84d9948c7ba2324fc5a99` |
| `fixtures/common/dev-ledger-unsupported-schema-version.json` | `dd279f985167f1e77677a919f7eaf9efc085a99e7bcbc5e5367fa4eb21a53136` |
| `fixtures/common/malformed-input.json` | `5dc13b6342f902b9dc693a6e22e285a2a223c467e465a3ede46e197c9b42cdb4` |
| `fixtures/common/required-field-missing.json` | `36e6cd9e4ac70879d85627f5249e6e076620cb085dff4d5eb6964aead367bc21` |
| `fixtures/common/unsupported-major-version.json` | `71d3a7b79a381eb4d7f8f3420ac3788e46a708276d13330299d4d5e5477774fa` |
| `fixtures/sc-1/accepted-structured-plan-ref.json` | `81d00015525e1f415ea9f51ef403c4530fa20a48002bd688ccf5499efc6594f6` |
| `fixtures/sc-1/accepted-two-distinct-runs.json` | `dab391a7be6e3874177fcc1000020ee8b52d06f7d940052cca6db203b94cb3f6` |
| `fixtures/sc-1/rejected-approval-revision-mismatch.json` | `5c9cb61b0a0480fd3313b90260a490b8ea1dec0ccf24fcf7c07bce650d5b5d95` |
| `fixtures/sc-1/rejected-bare-ambiguous-issue-id.json` | `10337809fc832a00e7bb89da52bcc2d65f2dadee8db7015b7193129aa2b2f197` |
| `fixtures/sc-1/rejected-machine-path-plan-ref.json` | `660177869580a256dfc648f0f213dd3f2504d261fd79eecdf563df58dd4db834` |
| `fixtures/sc-1/rejected-missing-managed-source.json` | `f199e6f7c1cc7d3f2e7519dd2830c238ee9c8143dbc94a3662f98dbe9a2d3abf` |
| `fixtures/sc-2/accepted-continue-epoch-rotation.json` | `0616d15296c88dc7394a8c77985393c8a60763f9ecc889c78e84524042656021` |
| `fixtures/sc-2/accepted-continue-latest-start-expiry.json` | `8c05043366ec54b347f4ba88de9691cef7e7ad7e490ed9da9e2eb5f6099b4936` |
| `fixtures/sc-2/rejected-replayed-begin.json` | `4164a59604421cac8a7674b2f815b801bed3ed3d7d65372fe568de3729070576` |
| `fixtures/sc-3/accepted-final-verified-completion.json` | `ef039c27d9fd12e04f3f89f9366c2bb171947d845643285a404525bbaf872aab` |
| `fixtures/sc-3/unusable-readiness-never-verified.json` | `65c5e81bb0ad7e2c081f5e604f2686cca6c49a49b110e2080a8885d7d2f46fb2` |
| `fixtures/sc-3/unusable-outcome-outside-vocabulary.json` | `9afe22c7307ada27e8122969b246744c71dbe4112f4ae65baabb01d0a647c02f` |
| `fixtures/sc-3/unknown-missing-profile-version.json` | `54c6c03aba8bfbe2b51b94dfb9c896595ecfab2dfbc4599f31c06468e67f0b34` |
| `fixtures/sc-3/rejected-cross-repo-goal-at-arming.json` | `e0c0a6c038b7e7314fdfdd8a410f0320394b1064cc4b536da74dcf166dc538fb` |
| `fixtures/sc-3/evidence-accepted-pr-assurance.json` | `49d1513241b767ec9c64f3b5ea6bc9a1ebd9853e9eabff9c8263a65d3d047724` |
| `fixtures/sc-3/evidence-rejected-pr-assurance-noncurrent-no-stale-reason.json` | `de26c50b2513d4d16222dd030451f5707c34dd54fc3c7de737369fa285e35705` |
| `fixtures/sc-3/evidence-accepted-parent-acceptance.json` | `11847ae86c6c9cae442f63f27b901962d003f514643f9da751bb33e94b210d72` |
| `fixtures/sc-3/evidence-rejected-parent-acceptance-carries-result.json` | `45bb71c55b2e14bd42ccd839bc40cfd0f29987608494c755e45e4fe91d0d8710` |
| `fixtures/sc-4/accepted-documented-skip-below-qa.json` | `bc99b3afc095a0e772f9c95f031b9a397481545cb5bae6c024aa7c17dd5b8576` |
| `fixtures/sc-4/accepted-mapped-acceptance-lane.json` | `5da5c4ee61e8e5951be3a3a27eb484ebd0ab82a7feafe69f686da134ac67cde0` |
| `fixtures/sc-4/rejected-missing-mandatory-qa.json` | `ed6c30ce2968548c85132701fd5c7d8ff86766adfd5993dc4c60b1f3f9645284` |
| `fixtures/sc-5/accepted-drift-fallback.json` | `00d83cd67366a930c1575a7c2286d32c5e0c75132791668725bcb096e0f88965` |
| `fixtures/sc-5/accepted-needs-input.json` | `4a870ec99b043c7770a38ac3f4536c860eea06f5e5943aeeeb11f1c25a62e680` |
| `fixtures/sc-5/accepted-scoped-read-only-finding.json` | `81e1e7ace3f34a8ba71672b4e5966abec2f1db45135a94435dc47c1287b8d76c` |
| `fixtures/sc-5/rejected-not-available-without-cause.json` | `9c23fa4789d4b6b74550f91ab891e8946e6c9df41aa807cf37128dfcdfbf629b` |
| `fixtures/sc-5/rejected-secret-bearing-request.json` | `8f89c71441bf67ea3da61e5df288a5865ca644c2899518c0c20d9a7a370d90ed` |
| `fixtures/sc-6/accepted-verified-provenance-document.json` | `cb402b28d4980ead26798e57c15bcb9e52741725ea01138a06f617bff5d7ee2a` |
| `fixtures/sc-6/accepted-mapped-config-bridge.json` | `4d8e688cf021d3b0f048ff0559d0e1cf83b7954dc9254cf256bff306faf9571a` |
| `fixtures/sc-6/rejected-guessed-cwd-project.json` | `f71859baa3f7f6cfec708af37555c6c5d95f97ae936bdbd05c9fc11f11ec3cf3` |
| `fixtures/sc-7/accepted-distinct-concurrent-runs.json` | `bdcaa5959ec0d090d2e27b57d465aaa0332540f1872fedb8d98d402dafb81291` |
| `fixtures/sc-7/accepted-explicit-unknown-source.json` | `c6db82cd27ac12f56a68e407ae74305df4cb9c5a190b5b204575ffc1413f053b` |
| `fixtures/sc-7/rejected-two-active-writers.json` | `209356215056c1d591f2ed0a67901bc924658d19b9e1e70e45ac7ce4a7f98a0b` |
| `fixtures/sc-7/rejected-idle-inferred-done.json` | `b193a316eeecaacf216adb649a1b9011ec576551d02fa0042ee0274088646dfa` |
| `fixtures/sc-8/accepted-compatible-existing-installation.json` | `abcf8cbf0ad23a8d58d101b96e86dd84ad70189fc39418396c2141e062815a36` |
| `fixtures/sc-8/rejected-hot-replacement.json` | `218da61bbd97ff5889d91d71675d85bd9d2a1b0cc6ce737641f470d21464f38e` |
| `fixtures/sc-9/accepted-restored-context-current-state-check.json` | `6c5a1ab2afcc376f252899b8db189453695cabf8e7e1a3598a4ecad98197cbd5` |
| `fixtures/sc-9/rejected-stale-note-overriding-pause.json` | `ec109e5445b3e84223a0080835b9d90465593c1274048e029cfb6e205353acf0` |
