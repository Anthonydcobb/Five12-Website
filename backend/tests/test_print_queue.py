import json
import subprocess
from unittest.mock import patch

TWO_PRINTER_DATA = {
    'printers': [
        {'Name': 'DYMO LabelWriter 450 Twin Turbo', 'PrinterStatus': 'Normal', 'JobCount': 2},
        {'Name': 'DYMO LabelWriter 450', 'PrinterStatus': 'Normal', 'JobCount': 0},
    ],
    'jobs': [
        {'Printer': 'DYMO LabelWriter 450 Twin Turbo', 'Id': 10, 'JobStatus': 'Printing'},
        {'Printer': 'DYMO LabelWriter 450 Twin Turbo', 'Id': 11, 'JobStatus': 'Spooling'},
    ],
}


def _run(stdout='', returncode=0):
    return type('Proc', (), {'stdout': stdout, 'stderr': '', 'returncode': returncode})()


def test_known_printer_with_jobs(client):
    with patch('app.print_queue_routes.subprocess.run',
               return_value=_run(json.dumps(TWO_PRINTER_DATA))):
        r = client.get('/api/print-queue?printer=' + 'DYMO LabelWriter 450 Twin Turbo'.replace(' ', '%20'))
    assert r.status_code == 200
    body = r.get_json()
    assert body['jobCount'] == 2
    assert body['printerStatus'] == 'Normal'
    assert body['jobs'] == [
        {'id': 10, 'status': 'Printing'},
        {'id': 11, 'status': 'Spooling'},
    ]


def test_known_printer_zero_jobs(client):
    with patch('app.print_queue_routes.subprocess.run',
               return_value=_run(json.dumps(TWO_PRINTER_DATA))):
        r = client.get('/api/print-queue?printer=' + 'DYMO LabelWriter 450'.replace(' ', '%20'))
    assert r.status_code == 200
    body = r.get_json()
    assert body['jobCount'] == 0
    assert body['jobs'] == []
    # jobCount is derived from the jobs list, not Get-Printer's own JobCount field
    assert body['jobCount'] != TWO_PRINTER_DATA['printers'][1]['JobCount'] + 1


def test_unknown_printer_404(client):
    with patch('app.print_queue_routes.subprocess.run',
               return_value=_run(json.dumps(TWO_PRINTER_DATA))):
        r = client.get('/api/print-queue?printer=NoSuchPrinter')
    assert r.status_code == 404
    assert r.get_json() == {'error': 'unknown printer'}


def test_subprocess_timeout_is_502(client):
    with patch('app.print_queue_routes.subprocess.run',
               side_effect=subprocess.TimeoutExpired(cmd='powershell', timeout=10)):
        r = client.get('/api/print-queue?printer=DYMO')
    assert r.status_code == 502
    assert r.get_json() == {'error': 'spooler query failed'}


def test_powershell_failure_is_502(client):
    with patch('app.print_queue_routes.subprocess.run',
               return_value=_run(stdout='not json', returncode=1)):
        r = client.get('/api/print-queue?printer=DYMO')
    assert r.status_code == 502
    assert r.get_json() == {'error': 'spooler query failed'}


def test_unparseable_json_is_502(client):
    with patch('app.print_queue_routes.subprocess.run',
               return_value=_run(stdout='{not valid json')):
        r = client.get('/api/print-queue?printer=DYMO')
    assert r.status_code == 502
    assert r.get_json() == {'error': 'spooler query failed'}


def test_single_printer_single_job_shape_is_normalized(client):
    # ConvertTo-Json collapses a one-element array to a bare object even with
    # @() forcing an array, on some PowerShell versions — the parser must
    # accept a dict in place of a list for both `printers` and `jobs`.
    solo = {
        'printers': {'Name': 'Solo Printer', 'PrinterStatus': 'Normal', 'JobCount': 1},
        'jobs': {'Printer': 'Solo Printer', 'Id': 5, 'JobStatus': 'Printing'},
    }
    with patch('app.print_queue_routes.subprocess.run',
               return_value=_run(json.dumps(solo))):
        r = client.get('/api/print-queue?printer=' + 'Solo Printer'.replace(' ', '%20'))
    assert r.status_code == 200
    body = r.get_json()
    assert body['jobCount'] == 1
    assert body['printerStatus'] == 'Normal'
    assert body['jobs'] == [{'id': 5, 'status': 'Printing'}]


# The module's SECURITY block claims the client-supplied printer name is never
# interpolated into the PowerShell command line. Until now that claim was
# asserted in a comment and proven by nothing: every test above patches
# subprocess.run and inspects only the response, so appending the name to the
# script would keep the whole suite green while turning a fixed literal into a
# command-injection vector. These two pin the mechanism.
HOSTILE_NAME = "'; Write-Output PWNED #"


def test_printer_name_never_reaches_the_powershell_command_line(client):
    with patch('app.print_queue_routes.subprocess.run',
               return_value=_run(json.dumps(TWO_PRINTER_DATA))) as run:
        client.get('/api/print-queue', query_string={'printer': HOSTILE_NAME})

    argv = run.call_args[0][0]
    assert all(HOSTILE_NAME not in part for part in argv), argv
    # Not even a fragment — a partial interpolation is still injection.
    assert all('PWNED' not in part for part in argv), argv


def test_printer_name_is_passed_as_an_environment_value(client):
    with patch('app.print_queue_routes.subprocess.run',
               return_value=_run(json.dumps(TWO_PRINTER_DATA))) as run:
        client.get('/api/print-queue', query_string={'printer': 'DYMO LabelWriter 450'})

    env = run.call_args.kwargs.get('env') or {}
    assert env.get('FIVE12_PRINTER') == 'DYMO LabelWriter 450'
    # Inherited, not replaced — PowerShell needs PATH.
    assert 'PATH' in {k.upper() for k in env}
