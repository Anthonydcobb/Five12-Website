# Cintenna BLE Write Phase — Hardware Acceptance

Run on the Windows 11 ThinkPad against the known Cintenna, firmware `1.0.7.2`.

Launch with both gates on:

    cd backend
    $env:FIVE12_BLE_TOOLS='1'; $env:FIVE12_BLE_WRITE='1'
    & 'C:\Users\antho\AppData\Local\Programs\Python\Python312\python.exe' -m flask run --port 5000

## Before you start — Link is hazardous

Link puts a transmitter into pairing mode. **Any unlinked receiver in range
will pair to it**, not only the one you intend. Either isolate the RF
environment or knowingly accept the risk to other CRMX gear present. Do not run
this step during a show.

## Gate behaviour

- [ ] With `FIVE12_BLE_WRITE` unset, the Cintenna panel shows no mode toggle,
      no Link, and no Unlink
- [ ] With it unset, `POST /api/ble/devices/x/commands` returns 404 **or**
      405 — either is correct. No POST handler is registered for that path
      with the gate off; whether the app matches it against the read-only
      SPA catch-all (`/<path:path>`, GET/HEAD/OPTIONS only, which yields 405
      Method Not Allowed) or against nothing at all (a bare 404) depends on
      what else the app has registered, not on the gate. See
      `backend/tests/test_ble_command_routes.py`'s
      `test_command_routes_are_unreachable_with_the_write_gate_off` for the
      full explanation — do not mark this FAILED on a 405, and do not "fix"
      this checklist item back to a bare 404 requirement.
- [ ] With both gates unset, Patch, Labels, Network and Devices all work

## Reads still work

- [ ] Passive scan finds the radio, Toolbox closed
- [ ] Read status returns battery, firmware and mode

## Unlink (receiver)

- [ ] On an RX radio, Unlink is offered and Link is not
- [ ] The dialog names the radio and warns that its fixture goes dark
- [ ] Confirm is disabled until the checkbox is ticked
- [ ] Pressing Enter in the dialog does nothing
- [ ] After confirming, the result says the write was accepted and does **not**
      claim anything about RF association
- [ ] The receiver has actually dropped its transmitter (verify on the fixture)

## Mode change — measure the timing

- [ ] Switch RX → TX. **Time how long** until the radio reappears and the mode
      reads back
- [ ] Record that figure here: ................ seconds
- [ ] If it exceeds `REBOOT_REDISCOVERY_TIMEOUT_S` (currently 30.0 in
      `command_service.py`), raise the constant and re-run
- [ ] The panel showed progress during the reboot rather than appearing frozen
- [ ] Outcome reported as "verified", not "accepted, unverified"
- [ ] Switch TX → RX and confirm the same

## Device identity across the reboot

- [ ] After a mode change, does the radio return with the **same** osId?
      Yes / No: ................
- [ ] If No, the panel must ask the operator to re-select it from the roster
      rather than silently acting on a stale selection. Confirm it does.

## Link (transmitter) — RF isolation required

- [ ] On a TX radio, Link is offered and Unlink is not
- [ ] The dialog warns that any unlinked receiver in range will pair
- [ ] After confirming, a receiver actually pairs
- [ ] The result copy does not say "linked"

## Refusals

- [ ] Open the dialog on a TX radio, change its mode from Toolbox or the panel
      in another window, then confirm — the write is refused as stale
- [ ] Leave a dialog open for over 60 seconds, then confirm — refused as an
      expired confirmation

## Toolbox conflict during a write

- [ ] Open CRMX Toolbox, connect it to the radio, then attempt a write
- [ ] The error names Toolbox and tells the operator to close it

  This is the known-fragile English-substring detection recorded in the
  handoff. If the message is the generic out-of-range one instead, record the
  exact error text here for the eventual HRESULT-based fix.
