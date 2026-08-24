# backend/app/print_queue_routes.py
#
# DYMO Connect 1.6.1.7's web service has no working job-status mechanism (see
# the amendment in docs/superpowers/specs/2026-08-03-dymo-print-sequencing-
# design.md): no getJobStatus method on the vendored DlsWebService,
# PrintLabel2 returns `true` instead of a job id, and the GetJobStatus HTTP
# endpoint 404s. DYMO jobs do land in the Windows print spooler under the
# same printer name, so the frontend engine sequences prints by polling this
# endpoint instead.
#
# SECURITY: the PowerShell command run here is a fixed literal. The
# client-supplied printer name is never interpolated into the command line —
# it reaches PowerShell only as an environment value, and is otherwise compared
# in Python against the printer names PowerShell enumerates on its own. An
# environment value is data, not syntax: nothing in it can be parsed as a
# command. test_printer_name_never_reaches_the_powershell_command_line pins
# this; do not "simplify" it into the command string.

import json
import os
import subprocess

from flask import Blueprint, jsonify, request

print_queue = Blueprint('print_queue', __name__, url_prefix='/api/print-queue')

# Fixed literal — do not interpolate the printer name into this string. It
# arrives as $env:FIVE12_PRINTER and is matched against the enumerated names,
# so the value handed to -PrinterName is one PowerShell produced itself.
#
# Jobs are fetched for the requested printer only. The previous version asked
# every installed printer for its jobs and discarded all but one; measured on
# the show rig (5 printers) the whole probe cost 791 ms, and it runs once per
# poll of a label's drain cycle.
_SPOOLER_SCRIPT = (
    "$name = $env:FIVE12_PRINTER\n"
    "$printers = Get-Printer | Select-Object Name, "
    "@{n='PrinterStatus';e={$_.PrinterStatus.ToString()}}, JobCount\n"
    "$match = $printers | Where-Object { $_.Name -eq $name } | Select-Object -First 1\n"
    "$jobs = if ($match) { Get-PrintJob -PrinterName $match.Name "
    "-ErrorAction SilentlyContinue | Select-Object @{n='Printer';e={$_.PrinterName}}, "
    "Id, @{n='JobStatus';e={$_.JobStatus.ToString()}} } else { @() }\n"
    "@{ printers = @($printers); jobs = @($jobs) } | ConvertTo-Json -Depth 4"
)


def _as_list(value):
    """ConvertTo-Json collapses a single-element array to a bare JSON object
    (observed even with `@()` forcing an array, on some PowerShell versions),
    and a pipeline that produced zero objects assigns $null to the variable
    (which `@($null)` then turns into a one-element array holding $null).
    Normalize every shape — dict, list, None, or a list containing None — to
    a plain Python list with no None entries."""
    if value is None:
        items = []
    elif isinstance(value, list):
        items = value
    else:
        items = [value]
    return [item for item in items if item is not None]


def query_print_queue(printer_name):
    """Run the fixed PowerShell spooler probe and return this printer's queue
    state, or an error. Return shape always includes 'status' (the HTTP
    status the caller should send); pop it before jsonify-ing the rest."""
    try:
        proc = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', _SPOOLER_SCRIPT],
            capture_output=True, text=True, timeout=10,
            # Inherited and extended, not replaced — PowerShell needs PATH.
            env={**os.environ, 'FIVE12_PRINTER': printer_name},
        )
    except (subprocess.TimeoutExpired, OSError):
        return {'error': 'spooler query failed', 'status': 502}

    if proc.returncode != 0:
        return {'error': 'spooler query failed', 'status': 502}

    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        return {'error': 'spooler query failed', 'status': 502}

    if not isinstance(data, dict):
        return {'error': 'spooler query failed', 'status': 502}

    printers = _as_list(data.get('printers'))
    jobs = _as_list(data.get('jobs'))

    match = next((p for p in printers if isinstance(p, dict) and p.get('Name') == printer_name), None)
    if match is None:
        return {'error': 'unknown printer', 'status': 404}

    # jobCount is computed from the jobs list for this printer, not trusted
    # from Get-Printer's JobCount snapshot field (per the spec amendment).
    printer_jobs = [j for j in jobs if isinstance(j, dict) and j.get('Printer') == printer_name]
    return {
        'jobCount': len(printer_jobs),
        'printerStatus': match.get('PrinterStatus') or '',
        'jobs': [{'id': j.get('Id'), 'status': j.get('JobStatus') or ''} for j in printer_jobs],
        'status': 200,
    }


@print_queue.get('')
def get_print_queue():
    printer_name = request.args.get('printer', '')
    result = query_print_queue(printer_name)
    status = result.pop('status')
    return jsonify(result), status
