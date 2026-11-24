"""Exception hierarchy. Every error raised deliberately by the application derives from
:class:`SmartDriveError` so callers (and the UI) can separate expected failures from bugs."""


class SmartDriveError(Exception):
    """Base class for expected application errors.

    ``user_message`` is safe to show in the interface; ``str(exc)`` may carry technical detail.
    """

    default_user_message = "An unexpected problem occurred."

    def __init__(self, message: str, *, user_message: str | None = None) -> None:
        super().__init__(message)
        self.user_message = user_message or self.default_user_message


class ConfigurationError(SmartDriveError):
    default_user_message = "The application configuration could not be loaded."


class DataValidationError(SmartDriveError):
    default_user_message = "Some of the supplied values are not valid."


class DatabaseError(SmartDriveError):
    default_user_message = "A database operation failed."


class MigrationError(DatabaseError):
    default_user_message = "The database could not be upgraded to the current version."


class BackupError(DatabaseError):
    default_user_message = "The database backup or restore did not complete."


class RecordNotFoundError(DatabaseError):
    default_user_message = "The requested record no longer exists."


class HardwareError(SmartDriveError):
    default_user_message = "The vehicle adapter reported an error."


class ConnectionTimeoutError(HardwareError):
    default_user_message = "The vehicle adapter did not respond in time."


class ModelError(SmartDriveError):
    default_user_message = "The diagnostic model could not be used."


class UntrustedModelError(ModelError):
    default_user_message = "The model file failed its integrity check and was not loaded."


class ExportError(SmartDriveError):
    default_user_message = "The export could not be written."
