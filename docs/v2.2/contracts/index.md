# v2.2 SC-1–SC-9 contract specifications and fixture provenance

This directory is the P0-02 delivery package for `KHAEntertainment/showrunner#184`. It specifies the SDP SC-1–SC-9 producer/consumer contract examples and retained fixture provenance. It implements no runtime, records no policy default, and never claims behavioral/runtime/cross-harness/pilot proof from text.

**Canonical source.** Showrunner v2.2 SDP, snapshot SHA-256 `63124e802cb0452f586617b8b913e563941fc700ea7c93efa2dac35db7baddfb` (815 lines), retained at `~/.traycer/epics/6266293c-edb0-48f6-b8f6-ddd561de1f05/artifacts/v2-2-development-plan/index.md`. Issue #184's body cites the superseded snapshot `dae53a66…` (789 lines); this package binds the current snapshot `63124e80…` per the admission ledger's re-pin note (ledger l.444).

## Global rules

- **Representation rule** (SDP l.536): the named `*-v1` forms are concrete specification targets, not installed schemas or approved policy defaults. Preserve Dev `schema_version: 2` YAML profile and separate Foreman/board schemas. Version a projection without forcing every source to adopt the same serialization. Unsupported major versions, ambiguous identity, required missing fields, or malformed input yield explicit `invalid`/`unavailable` results. Additive optional fields require common-reader fixtures, not silent parser leniency. Never put operational policy values into examples and call them approved — all fixture values here are synthetic placeholders.
- **Evidence-bundle rule** (SDP l.550): each evidence bundle names source commits, producer/consumer revisions, fixture revision, executed check/result or explicit `not-run`, incompatibilities, and counterpart disposition. **No compatible value is inferred from silence.** Counterpart acceptance is `pending` per consumer in every spec until that consumer records explicit acceptance.
- **SC-2 note** (SDP l.552): the evidence bundle includes the Continue-after-rotation/start-expiry positive case and the replayed-Begin negative case. A generic stale-grant rejection is insufficient and must not accidentally prohibit an acknowledged operation from reaching safety.
- **Version domains** (l.536, D4.5 l.445): three distinct version discriminators are scoped separately — a `*-v1` interface major mismatch is `invalid`; a Dev ledger `schema_version != 2` is failed by the Dev validator (`dev_state.py` l.156–159); and a missing/unknown `completion-result-v1` `profile_version` is `unknown` (not `invalid`). They are never conflated.

## Provenance table

| SC | Contract(s) | Source revision (SDP `63124e80…`) | Semantic owner | Producer | Consumers (package) |
| --- | --- | --- | --- | --- | --- |
| SC-1 | `assignment-v1` | l.540; D1 l.85; D6.5 l.142 | Dev planning owner | Dev planning + backend adapter | P1; P2, GV, panel; I1 (later) |
| SC-2 | `authorization-context-v1` | l.541; l.250; D2 | Dev execution/recovery owner | Dev operation gates; Foreman grant owner | P2; I1, O-DB, O-STOP (later) |
| SC-3 | `completion-evidence-v1` + `completion-result-v1` | l.542; D4.2 l.372; D4.5 l.426 | GV owner | GV (read-only); Dev lead sole writer | P3, pilot, resume, panel; Foreman audit/hooks (later) |
| SC-4 | `conformance-v1` | l.543 | Dev workflow owner | Dev gate rules + Foreman status checklist | P2, P3; supervisor, Scout (later) |
| SC-5 | `provider-request-v1` / `provider-result-v1` | l.544 | shared utility owner | locator/review helpers + migration diagnostic | P1; U2, O-STOP, O-DB (later) |
| SC-6 | `project-binding-v1` + `record-link-v1` | l.545 | tracker integration owner | `.dev.json` closed schema, Foreman project config/bridge, board config | P1; O-TRACK (later) |
| SC-7 | `run-projection-v1` + `custody-reference-v1` | l.546 | source lead (Dev) | Dev schema-v2 state, Foreman sessions/packets, board | P4, #112; I1, O-LIFE (later) |
| SC-8 | `component-receipt-v1` | l.547 | package/component maintainers | installers/catalog + Foreman install/discovery | P5; I1, U1 (later) |
| SC-9 | `checkpoint-reference-v1` + `recovery-receipt-v1` | l.548; H1 l.479 | handoff adapter + workflow recovery owner | handoff adapter + Dev recovery + Foreman procedures | P2, G3; I1 (later) |

Per-SC spec files: `sc-1.md` … `sc-9.md`. Each names the `*-v1` name/version, semantic + version owner, producer, consumers with package, the required/conditional field table (meanings from the SDP only), accepted/rejected examples, edge cases, and `counterpart_acceptance: pending`.

## Fixture digest index

Every fixture file's SHA-256, recomputed after the last edit. Each fixture carries `status: "not-run"` and `counterpart_acceptance: "pending"`. Values are synthetic placeholders; no operational policy value appears.

| Fixture | SHA-256 |
| --- | --- |
| `fixtures/common/additive-optional-field-common-reader.json` | `98b3d63721db75191c5d1674a91fc84c3c216f89d723eaf87398e8ecb0772e54` |
| `fixtures/common/ambiguous-identity.json` | `2d38a6959c05bba1e551d529a12b7b7d4512b738c672f3afefc853061c4e2267` |
| `fixtures/common/dev-ledger-unsupported-schema-version.json` | `dd279f985167f1e77677a919f7eaf9efc085a99e7bcbc5e5367fa4eb21a53136` |
| `fixtures/common/malformed-input.json` | `5dc13b6342f902b9dc693a6e22e285a2a223c467e465a3ede46e197c9b42cdb4` |
| `fixtures/common/required-field-missing.json` | `36e6cd9e4ac70879d85627f5249e6e076620cb085dff4d5eb6964aead367bc21` |
| `fixtures/common/unsupported-major-version.json` | `294f36cdb88c52e9e5986ce5ae56ec67d5d9b7e4ce53f4d2832106707fbc7f14` |
| `fixtures/sc-1/accepted-two-distinct-runs.json` | `4d41af3b80572dc43388b47c7ed6431fa3dd0b54be6d3159a8925bc21f0af4c5` |
| `fixtures/sc-1/rejected-bare-ambiguous-issue-id.json` | `d1b483a1ee780098df8affbc9fd6252bc5a4e9b667f457afc8741c6a45d6a970` |
| `fixtures/sc-1/rejected-missing-managed-source.json` | `2f7fe68c9ae1ef066fedfb630461abfcb3638549a03e72754a7ca3209d634875` |
| `fixtures/sc-2/accepted-continue-epoch-rotation.json` | `882d8734defd0c03af6df040f2b570be71690c8eefcee6ac2788d46e3c0cb135` |
| `fixtures/sc-2/accepted-continue-latest-start-expiry.json` | `14f95376c40f153429cca3ca14a962a3707aa685d858996a9e013f7abac87118` |
| `fixtures/sc-2/rejected-replayed-begin.json` | `33465025e28bd45c8fd946cbb668725f72f9ac00c692a7d7375622bcfd6cbc86` |
| `fixtures/sc-3/accepted-final-verified-completion.json` | `99cec4b0b2febd3f20b8f0d233d5de1f3a7b074be02bf1b2dc2831f751b8add2` |
| `fixtures/sc-3/unusable-readiness-never-verified.json` | `22c1f3155808b034fac834300a452ce22da49f3d5eeacc6c0e4527c81d63512a` |
| `fixtures/sc-3/unusable-outcome-outside-vocabulary.json` | `32b752acdc91355d4b125b91494d4f15db2ee91029feb34a0400ff4e283030bd` |
| `fixtures/sc-3/unknown-missing-profile-version.json` | `ad2657e13b2a919402b4ac2ef6be019e2915bd5c86de2014dc6e7061879e8319` |
| `fixtures/sc-3/rejected-cross-repo-goal-at-arming.json` | `18ae9d661e628b934e70d1163d96bdedc8c8f879cea820ccf46111f32fe4865f` |
| `fixtures/sc-3/evidence-accepted-pr-assurance.json` | `49d1513241b767ec9c64f3b5ea6bc9a1ebd9853e9eabff9c8263a65d3d047724` |
| `fixtures/sc-3/evidence-rejected-pr-assurance-noncurrent-no-stale-reason.json` | `de26c50b2513d4d16222dd030451f5707c34dd54fc3c7de737369fa285e35705` |
| `fixtures/sc-3/evidence-accepted-parent-acceptance.json` | `11847ae86c6c9cae442f63f27b901962d003f514643f9da751bb33e94b210d72` |
| `fixtures/sc-3/evidence-rejected-parent-acceptance-carries-result.json` | `45bb71c55b2e14bd42ccd839bc40cfd0f29987608494c755e45e4fe91d0d8710` |
| `fixtures/sc-4/accepted-documented-skip-below-qa.json` | `dc04835081a39784c4fbde580ae5ef0890c1b7557c434050386a9b4f2545abd9` |
| `fixtures/sc-4/accepted-mapped-acceptance-lane.json` | `b9c5b3987d52b735dc1619dd7f694e172330d50f609920259218aa8183df3ae4` |
| `fixtures/sc-4/rejected-missing-mandatory-qa.json` | `8db4136df3f16c9938de475b559fe21034e0df3b196464ce52bb7ffb97b1b28c` |
| `fixtures/sc-5/accepted-scoped-read-only-finding.json` | `8d26b87a3b18b1c7823845106b2bd56f5b7bba6682b2eb23259088c4244e4e3f` |
| `fixtures/sc-5/rejected-secret-bearing-request.json` | `6da13850d1d76d1907375e8d45f3845ba1cb13daab4f935ebd175af4e7f68227` |
| `fixtures/sc-6/accepted-verified-provenance-document.json` | `cb402b28d4980ead26798e57c15bcb9e52741725ea01138a06f617bff5d7ee2a` |
| `fixtures/sc-6/accepted-mapped-config-bridge.json` | `4d8e688cf021d3b0f048ff0559d0e1cf83b7954dc9254cf256bff306faf9571a` |
| `fixtures/sc-6/rejected-guessed-cwd-project.json` | `f71859baa3f7f6cfec708af37555c6c5d95f97ae936bdbd05c9fc11f11ec3cf3` |
| `fixtures/sc-7/accepted-distinct-concurrent-runs.json` | `bdcaa5959ec0d090d2e27b57d465aaa0332540f1872fedb8d98d402dafb81291` |
| `fixtures/sc-7/accepted-explicit-unknown-source.json` | `c6db82cd27ac12f56a68e407ae74305df4cb9c5a190b5b204575ffc1413f053b` |
| `fixtures/sc-7/rejected-two-active-writers.json` | `209356215056c1d591f2ed0a67901bc924658d19b9e1e70e45ac7ce4a7f98a0b` |
| `fixtures/sc-7/rejected-idle-inferred-done.json` | `b193a316eeecaacf216adb649a1b9011ec576551d02fa0042ee0274088646dfa` |
| `fixtures/sc-8/accepted-compatible-existing-installation.json` | `a818f89f20d6e88174d1122e5ecb85bdbd39a7c95c2c4c91247a3b290e944958` |
| `fixtures/sc-8/rejected-hot-replacement.json` | `e20a615e5cc88bec9b7695c7ad817aa41c873e2a1c51307418fda79b1f74bb66` |
| `fixtures/sc-9/accepted-restored-context-current-state-check.json` | `6c5a1ab2afcc376f252899b8db189453695cabf8e7e1a3598a4ecad98197cbd5` |
| `fixtures/sc-9/rejected-stale-note-overriding-pause.json` | `ec109e5445b3e84223a0080835b9d90465593c1274048e029cfb6e205353acf0` |
