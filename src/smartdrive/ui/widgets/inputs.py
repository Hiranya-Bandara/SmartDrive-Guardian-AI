"""Labelled form field with inline validation feedback."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from smartdrive.ui.widgets.base import label, set_props


class FormField(QWidget):
    def __init__(
        self,
        title: str,
        editor: QWidget,
        *,
        required: bool = False,
        hint: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.editor = editor
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.title_label: QLabel = label(f"{title}{' *' if required else ''}")
        self.title_label.setBuddy(editor)
        editor.setAccessibleName(title)
        if hint:
            editor.setToolTip(hint)
        self.error_label = label("", "field-error", wrap=True)
        self.error_label.hide()
        layout.addWidget(self.title_label)
        layout.addWidget(editor)
        layout.addWidget(self.error_label)

    @property
    def has_error(self) -> bool:
        return not self.error_label.isHidden()

    def set_error(self, message: str | None) -> None:
        self.error_label.setText(message or "")
        self.error_label.setVisible(bool(message))
        set_props(self.editor, invalid="true" if message else "false")
        self.editor.setAccessibleDescription(message or "")
