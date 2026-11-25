"""Read-only OBD-II access through ELM327-compatible serial adapters.

Only :mod:`smartdrive.obd.elm327` writes to an adapter, and only commands on the allowlist in
:mod:`smartdrive.obd.commands` can be sent. See ``docs/hardware.md``.
"""
