"""Errors raised by the read-only OBD-II layer.

Each class carries a message that is safe to show to the user; ``str(exc)`` holds technical detail
for the log. ``recoverable`` tells the connection session whether a bounded reconnect is worth
attempting.
"""

from __future__ import annotations

from smartdrive.utils.exceptions import ConnectionTimeoutError, HardwareError


class ObdError(HardwareError):
    default_user_message = "The OBD-II adapter reported an error."
    recoverable = False


class ProhibitedCommandError(ObdError):
    """A command outside the read-only allowlist was requested. Never sent to the adapter."""

    default_user_message = (
        "SmartDrive blocked a command that is not on its read-only allowlist. Nothing was sent "
        "to the vehicle."
    )


class NoAdapterError(ObdError):
    default_user_message = (
        "No serial port was selected. Connect a USB or Bluetooth (serial) ELM327 adapter, "
        "refresh the list and choose its port."
    )


class InvalidPortError(ObdError):
    default_user_message = (
        "The selected port does not exist. The adapter may have been unplugged or paired under "
        "a different COM port. Refresh the adapter list."
    )


class PortInUseError(ObdError):
    default_user_message = (
        "The port is in use by another program (for example another OBD app or a serial "
        "terminal). Close it and try again."
    )


class AdapterNotRespondingError(ObdError):
    default_user_message = (
        "The port opened but no ELM327-compatible adapter answered. Check that the device is an "
        "ELM327 adapter, that it is powered (plugged into the vehicle) and the baud rate."
    )
    recoverable = True


class AdapterDisconnectedError(ObdError):
    default_user_message = "The connection to the OBD-II adapter was lost."
    recoverable = True


class EcuUnavailableError(ObdError):
    default_user_message = (
        "The adapter is connected but the vehicle's engine control unit did not answer. Turn "
        "the ignition on (key position II or engine running) and check that the vehicle "
        "supports OBD-II. The vehicle's protocol may also be unsupported by this adapter."
    )
    recoverable = True


class UnsupportedProtocolError(EcuUnavailableError):
    """ELM327 ``UNABLE TO CONNECT``: no protocol answered. The adapter cannot tell why."""

    default_user_message = (
        "The adapter could not reach the vehicle on any OBD-II protocol. Most often the ignition "
        "is off; otherwise the vehicle may use a protocol this adapter does not support."
    )


class CommunicationTimeoutError(ConnectionTimeoutError, ObdError):
    default_user_message = "The OBD-II adapter did not respond in time."
    recoverable = True


class MalformedResponseError(ObdError):
    default_user_message = "The adapter returned a response that could not be decoded."
    recoverable = False


class NoDataError(ObdError):
    """The vehicle answered NO DATA: the parameter is unsupported or unavailable right now."""

    default_user_message = "The vehicle did not provide this value."


class AdapterReportedError(ObdError):
    """The adapter reported a bus or internal error (CAN ERROR, BUS ERROR, BUFFER FULL…)."""

    default_user_message = "The adapter reported a communication error on the vehicle bus."
    recoverable = True


class OperationCancelledError(ObdError):
    default_user_message = "The adapter operation was cancelled."
