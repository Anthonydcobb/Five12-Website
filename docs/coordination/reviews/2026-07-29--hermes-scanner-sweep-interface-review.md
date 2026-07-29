# Hermes review — scanner interface selection and sweep hints

- **Reviewed branch:** `origin/fix/claude/scanner-sweep-interface`
- **Reviewed head:** `72797cca4d93b8c36790154208e1cccae9c49cbb`
- **Base:** `origin/main` at `aa4b25b9d2411ec9565ebcb918b3e302f9883701`
- **Verdict:** **Request changes; do not merge yet**
- **Evidence:** static review, Linux software tests, targeted runtime reproductions, and Claude's actual-rig evidence

## Critical

None.

## Warning 1 — invalid or mixed-family hints can disable scanning for a subnet

`backend/app/network_routes.py:15-27` and `:31-64` persist `sweepHints` without validating syntax, type, containment, address family, or width. Validation is deferred until scan time.

At `backend/app/scanner.py:262-274`, only parse-time `ValueError` is handled. `hint.subnet_of(subnet)` at line 267 raises `TypeError` when the hint and parent subnet use different IP versions. I reproduced:

```text
_hint_networks('fd00::/120', '10.0.0.0/8')
TypeError: fd00::/120 and 10.0.0.0/8 are not of the same version
```

`run_scan_now` catches that only at the outer per-subnet boundary, so that subnet's scan aborts instead of safely ignoring or rejecting the bad hint.

Even same-family invalid, outside, or over-wide hints are accepted with HTTP 201/200, stored, echoed back as configuration, and then silently ignored. That makes the API claim the setting was accepted while the scanner does something else.

**Required change:** validate and normalize IPv4 CIDRs at the POST/PATCH boundary and return a typed 400 for malformed, cross-family, outside-parent, or over-wide hints. Keep defensive scan-time validation too. Add API tests plus a mixed-family regression test.

## Warning 2 — the schema change breaks existing desktop SQLite databases

The branch correctly adds Alembic revision `d7c3a9f21b04` for development MySQL. However, the desktop startup path uses `db.create_all()` rather than Alembic. `create_all()` creates missing tables but does not add columns to existing tables.

I reproduced an old desktop schema, opened it with the branch, ran the desktop-style `create_all()`, and found that `network_subnets.sweep_hints` was still absent. Querying `NetworkSubnet` then failed with:

```text
sqlite3.OperationalError: no such column: network_subnets.sweep_hints
```

This would prevent an existing desktop database from using the network-subnet model after update.

**Required change:** add the project's safe desktop-SQLite schema-upgrade path before model queries, and test upgrade from a pre-branch SQLite file while preserving existing subnet/device rows. Do not rely on `create_all()` for column migration.

## Suggestion — narrow and validate the new PATCH route

`backend/app/network_routes.py:45-61` introduces a general subnet PATCH route that can also rewrite `label`, `cidr`, `active`, `color`, `interfaceHint`, and `ignoreCidrs` without field validation. The stated need is updating sweep hints. Changing an existing parent CIDR can leave attached device attribution semantically stale.

Either limit this initial route to `sweepHints`, or add explicit validation and tested semantics for every accepted field.

## Suggestion — provide an operator-facing configuration path

The branch exposes sweep hints through the API but does not provide a Five12 UI for editing them. If UI work is intentionally separate, document the exact safe API/configuration workflow and add the UI task to the handoff. Otherwise the feature depends on manual API calls.

## Looks good

- Explicit `iface=` use fixes the original Scapy layer-2 routing defect.
- Claude's actual-rig result finding all 15 SideCar nodes is strong hardware evidence.
- Interface fan-out is bounded to route/candidate interfaces and results are deduplicated.
- Valid hints remain contained within the parent subnet and bounded by `MAX_SWEEP_ADDRESSES`.
- Migration graph is structurally correct: one base, one head, correct parent.
- No new external exposure or authentication regression was found.

## Checks

```text
Focused scanner tests: 27 passed
Full backend suite from backend/: 410 passed, 10 warnings
git diff --check: passed
```

The repository-root form of the canonical command failed three pre-existing BLE subprocess tests because `test_ble_scanner.py` computes/inserts `backend/app` instead of `backend`; running from `backend/` masks that defect. This is not caused by this branch but should be corrected separately.
