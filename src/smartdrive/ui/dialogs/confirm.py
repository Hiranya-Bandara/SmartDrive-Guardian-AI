"""Confirmation and message dialogs styled with the application theme."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from smartdrive.ui.icons import pixmap
from smartdrive.ui.themes.palette import DARK, ThemePalette
from smartdrive.ui.widgets.base import IconPushButton, label


class ConfirmDialog(QDialog):
    def __init__(
        self,
        title: str,
        message: str,
        *,
        confirm_text: str = "Confirm",
        destructive: bool = False,
        palette: ThemePalette = DARK,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(14)
        header = QHBoxLayout()
        badge = QLabel()
        badge.setPixmap(
            pixmap(
                "alert" if destructive else "info",
                palette.critical if destructive else palette.accent,
                26,
            )
        )
        header.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(label(title, "section-title", wrap=True), 1)
        layout.addLayout(header)
        self.message_label = label(message, "muted", wrap=True)
        layout.addWidget(self.message_label)
        buttons = QDialogButtonBox()
        self.cancel_button = IconPushButton("Cancel")
        self.confirm_button = IconPushButton(
            confirm_text,
            "trash" if destructive else "check",
            variant="danger" if destructive else "primary",
        )
        self.confirm_button.apply_palette(palette)
        buttons.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.addButton(self.confirm_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.cancel_button.setDefault(True)
        self.cancel_button.setFocus()
        layout.addWidget(buttons)


def confirm(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    confirm_text: str = "Confirm",
    destructive: bool = False,
    palette: ThemePalette = DARK,
) -> bool:
    """Ask the user to confirm. The safe choice (Cancel) is the default button."""
    dialog = ConfirmDialog(
        title,
        message,
        confirm_text=confirm_text,
        destructive=destructive,
        palette=palette,
        parent=parent,
    )
    return dialog.exec() == QDialog.DialogCode.Accepted
