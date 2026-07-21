"""Local interface enumeration, shared by both discovery paths.

Extracted from `integrations/stardust.py` (where it was `_local_ipv4s`) because
it encodes host-topology knowledge that Art-Net discovery and the sACN listener
both depend on — see docs/superpowers/specs/2026-07-20-sacn-listener-design.md.
Behaviour is unchanged for Art-Net.
"""

import os
import socket


def local_ipv4s(pin_env=None):
    """Every local IPv4 to poll from / join multicast groups on.

    [VERIFIED 2026-07-20] The scanner host has several overlapping 10.0.0.0/8
    interfaces and the devices are reachable ONLY from one of them, so a
    single socket on the default route finds zero nodes. Fanning out across
    every interface is what makes discovery work.

    `pin_env` names an environment variable that pins discovery to one source
    IP when fanning out is undesirable (firewall prompts, noisy broadcast on
    unrelated VLANs): 'FIVE12_ARTNET_SRC' for Art-Net, 'FIVE12_SACN_SRC' for
    the sACN listener.
    """
    if pin_env:
        pin = os.getenv(pin_env, '').strip()
        if pin:
            return [pin]
    ips = set()
    try:
        for *_, sa in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(sa[0])
    except socket.gaierror:
        pass
    # '' (INADDR_ANY) is the last resort — it is the behaviour that failed on
    # the multi-homed host, but it is better than not polling at all.
    return sorted(ips) or ['']
