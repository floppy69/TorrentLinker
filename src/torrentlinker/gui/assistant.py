"""Native Assistant UI. Model/network work never runs on the Qt event thread."""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any

from PySide6.QtCore import QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from torrentlinker.assistant.models import Conversation
from torrentlinker.gui.chat_composer import ChatComposer
from torrentlinker.gui.chat_folders import ChatFolders
from torrentlinker.gui.chat_transcript import ChatTranscript
from torrentlinker.gui.controls import icon_button, set_role
from torrentlinker.gui.request_details import JsonCode, RequestDetails
from torrentlinker.gui.tasks import run_in_background


class AssistantEditor(QDialog):
    def __init__(self, service, *, initial=None, defaults=False, parent=None):
        super().__init__(parent)
        self.service, self.defaults = service, defaults
        self.initial = initial or {}
        self.setWindowTitle(
            self.tr("Chat defaults") if defaults else self.tr("Discussion settings")
        )
        self.resize(620, 440)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        pane = QWidget()
        form = QFormLayout(pane)
        scroll.setWidget(pane)
        layout.addWidget(scroll)
        self.name = QLineEdit(self.initial.get("name", ""))
        self.name.setAccessibleName(self.tr("Name"))
        form.addRow(self.tr("Name"), self.name)
        if defaults:
            form.setRowVisible(self.name, False)
        self.provider = QComboBox()
        for p in service.setup()["providers"]:
            self.provider.addItem(p["name"] + " · " + p["model"], p["id"])
        if self.initial.get("provider_id"):
            self.provider.setCurrentIndex(self.provider.findData(self.initial["provider_id"]))
        form.addRow(self.tr("Model connection"), self.provider)
        policy = self.initial.get("policy", {})
        self.mode = QComboBox()
        self.mode.addItem(self.tr("Proposals only"), "propose")
        self.mode.addItem(self.tr("Execute within limits"), "execute")
        self.mode.setCurrentIndex(self.mode.findData(policy.get("mode", "propose")))
        form.addRow(self.tr("Action policy"), self.mode)
        self.clients = []
        clients = QWidget()
        choices = QVBoxLayout(clients)
        for p in service.agent.setup.settings.client_profiles:
            if p.enabled:
                check = QCheckBox(p.name)
                check.setChecked(
                    p.id in policy.get("clients", [service.agent.setup.settings.default_client_id])
                )
                choices.addWidget(check)
                self.clients.append((p.id, check))
        form.addRow(self.tr("Allowed Torrent Clients"), clients)
        self.web = QCheckBox(self.tr("Allow public Web research"))
        self.web.setChecked(self.initial.get("web", False))
        form.addRow(self.web)
        advanced = QGroupBox(self.tr("Permissions and limits"))
        advanced.setCheckable(True)
        advanced.setChecked(False)
        al = QVBoxLayout(advanced)
        self.options = QWidget()
        af = QFormLayout(self.options)
        al.addWidget(self.options)
        self.options.hide()
        advanced.toggled.connect(self.options.setVisible)
        self.permissions = []
        for value, label in [
            ("queue", self.tr("Prepare and edit download queue")),
            ("downloads", self.tr("Start downloads")),
            ("controls", self.tr("Torrent controls")),
            ("reseed", self.tr("Reseeds")),
            ("uploads", self.tr("Uploads")),
            ("media", self.tr("Media playback, queues and playlists")),
        ]:
            check = QCheckBox(label)
            check.setChecked(value in policy.get("permissions", []))
            af.addRow(check)
            self.permissions.append((value, check))
        self.mode.currentIndexChanged.connect(self.policy_changed)
        self.policy_changed()
        self.daily_bytes = self.number(
            af,
            self.tr("Downloads per day, GiB"),
            policy.get("daily_bytes", 10 * 1024**3) // 1024**3,
            0,
            1000000,
        )
        self.daily_torrents = self.number(
            af, self.tr("Torrents per day"), policy.get("daily_torrents", 20), 0, 1000
        )
        self.reserve = self.number(
            af,
            self.tr("Keep free, GiB"),
            policy.get("reserve_bytes", 0) // 1024**3,
            0,
            1000000,
        )
        self.reserve.setSpecialValueText(self.tr("No extra reserve"))
        self.calls = self.number(
            af,
            self.tr("Model calls per run"),
            self.initial.get("max_calls", 0),
            0,
            200,
        )
        self.seconds = self.number(
            af,
            self.tr("Maximum duration, seconds"),
            self.initial.get("max_seconds", 0),
            0,
            1800,
        )
        self.calls.setSpecialValueText(self.tr("No limit"))
        self.seconds.setSpecialValueText(self.tr("No limit"))
        form.addRow(advanced)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.saved = ""

    def number(self, form, label, value, minimum, maximum):
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        form.addRow(label, widget)
        return widget

    def policy_changed(self):
        for _, check in self.permissions:
            check.setEnabled(self.mode.currentData() == "execute")

    def value(self):
        data = dict(
            name=self.name.text().strip(),
            provider_id=self.provider.currentData() or "",
            web=self.web.isChecked(),
            max_output_tokens=self.initial.get("max_output_tokens", 2048),
            max_calls=self.calls.value(),
            max_seconds=self.seconds.value(),
            policy=dict(
                name=self.name.text().strip(),
                clients=[v for v, c in self.clients if c.isChecked()],
                mode=self.mode.currentData(),
                permissions=[v for v, c in self.permissions if c.isEnabled() and c.isChecked()],
                daily_bytes=self.daily_bytes.value() * 1024**3,
                daily_torrents=self.daily_torrents.value(),
                reserve_bytes=self.reserve.value() * 1024**3,
            ),
        )
        return Conversation(**data)

    def save(self):
        try:
            value = self.value()
            if self.defaults:
                result = self.service.save_chat_defaults(value)
            else:
                result = self.service.update_conversation(self.initial["id"], value)
            self.saved = result.get("id", "")
            self.accept()
        except Exception as error:
            QMessageBox.warning(self, self.tr("Assistant"), str(error))


class AssistantTab(QWidget):
    def status_text(self, value):
        return {
            "queued": self.tr("Queued"),
            "running": self.tr("Running"),
            "completed": self.tr("Completed"),
            "failed": self.tr("Failed"),
            "cancelled": self.tr("Cancelled"),
            "interrupted": self.tr("Interrupted"),
            "awaiting_approval": self.tr("Awaiting approval"),
            "awaiting_user": self.tr("Awaiting your answer"),
            "waiting_settings": self.tr("Waiting for settings to finish updating"),
            "finished": self.tr("Finished"),
        }.get(value, value)

    # Model connections live in Settings → Assistant; the host opens them.
    connectionsRequested = Signal()

    def __init__(self, get_service, parent=None):
        super().__init__(parent)
        self.get_service = get_service
        self.service: Any = None
        self.conversation_id = ""
        self.run_id = ""
        self.render_key = ""
        self.provider_data = []
        self.drafts = {}
        # The mode chosen with the chip before a new discussion exists.
        self.pending_mode = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # Errors and progress only; the discussion header carries the title.
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setProperty("role", "muted")
        self.notice.hide()
        layout.addWidget(self.notice)
        self.pages = QTabWidget()
        layout.addWidget(self.pages, 1)
        chat = QWidget()
        cl = QVBoxLayout(chat)
        splitter = QSplitter()
        left = QWidget()
        self.folder_column = left
        left.setMinimumWidth(180)
        left.setMaximumWidth(420)
        ll = QVBoxLayout(left)
        top = QHBoxLayout()
        top.setSpacing(4)
        self.search_chats = QLineEdit()
        self.search_chats.setPlaceholderText(self.tr("Search discussions"))
        self.search_chats.setAccessibleName(self.tr("Search discussions"))
        self.search_chats.setClearButtonEnabled(True)
        top.addWidget(self.search_chats, 1)
        self.new_chat = icon_button("＋", self.tr("New discussion"))
        self.new_chat.clicked.connect(self.new_discussion)
        top.addWidget(self.new_chat)
        ll.addLayout(top)
        self.conversations = ChatFolders()
        self.conversations.conversationSelected.connect(self.select_conversation)
        self.conversations.actionRequested.connect(self.conversation_action)
        self.search_chats.textChanged.connect(self.conversations.set_filter)
        ll.addWidget(self.conversations)
        splitter.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 0, 0, 0)
        header = QHBoxLayout()
        header.setContentsMargins(4, 6, 0, 2)
        header.setSpacing(2)
        self.chat_title = QLabel(self.tr("New discussion"))
        self.chat_title.setObjectName("chatTitle")
        self.chat_title.setTextFormat(Qt.TextFormat.PlainText)
        header.addWidget(self.chat_title, 1)
        self.more_menu = QMenu(self)
        self.chat_settings = self.more_menu.addAction(
            self.tr("Discussion settings"), self.edit_chat_settings
        )
        self.rename_chat = self.more_menu.addAction(self.tr("Rename…"), self.rename_conversation)
        self.move_chat = self.more_menu.addAction(
            self.tr("Move to folder…"), self.move_conversation
        )
        self.delete_chat = self.more_menu.addAction(
            self.tr("Delete discussion"), self.delete_discussion
        )
        self.more_button = icon_button("⋯", self.tr("More"))
        self.more_button.setMenu(self.more_menu)
        self.more_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        header.addWidget(self.more_button)
        self.header = header
        rl.addLayout(header)
        self.transcript = ChatTranscript(
            presentation_page=lambda *a, **kw: self.service.presentation_page(*a, **kw),
            presentation_item=lambda *a, **kw: self.service.presentation_item(*a, **kw),
        )
        self.transcript.decisionSubmitted.connect(self.submit_decision)
        self.transcript.answerSubmitted.connect(self.submit_answer)
        self.transcript.anchorClicked.connect(self.open_receipt)
        self.transcript.examples = [
            self.tr("Find ten films I don't seed yet and show them before any action."),
            self.tr("Prepare a Plan within 200 GB with the best Zen gain."),
            self.tr("Review my local upload drafts and list what is missing."),
            self.tr("Play a film with French subtitles."),
        ]
        self.transcript.promptChosen.connect(self.use_example)
        rl.addWidget(self.transcript, 1)
        self.composer = ChatComposer()
        self.composer.sendRequested.connect(self.send_message)
        self.composer.stopRequested.connect(self.stop_run)
        self.composer.modeRequested.connect(self.toggle_mode)
        self.prompt = self.composer.prompt
        self.chat_model = self.composer.model
        self.chat_model.activated.connect(self.change_chat_model)
        self.send = self.composer.send
        rl.addWidget(self.composer)
        # Without a model the composer is useless: one clear way to connect one instead.
        self.connect_model = set_role(QPushButton(self.tr("Connect a model")), "primary")
        self.connect_model.clicked.connect(self.connectionsRequested.emit)
        rl.addWidget(self.connect_model, 0, Qt.AlignmentFlag.AlignHCenter)
        splitter.addWidget(right)
        # The sidebar keeps the width you give it (design principle 3).
        self.splitter = splitter
        saved = QSettings().value("assistant/sidebar_width")
        splitter.setSizes([int(saved) if saved else 240, 760])
        splitter.splitterMoved.connect(
            lambda *_: QSettings().setValue("assistant/sidebar_width", splitter.sizes()[0])
        )
        cl.addWidget(splitter)
        self.pages.addTab(chat, self.tr("Discussion"))
        self.history = ChatTranscript(
            presentation_page=lambda *a, **kw: self.service.presentation_page(*a, **kw),
            presentation_item=lambda *a, **kw: self.service.presentation_item(*a, **kw),
        )
        self.history.anchorClicked.connect(self.open_receipt)
        self.history.run_heading = self.run_heading
        self.history.decisionSubmitted.connect(self.submit_decision)
        self.history.answerSubmitted.connect(self.submit_answer)
        self.pages.addTab(self.history, self.tr("History"))
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh_run)
        self.timer.start()

    def _sync_header(self):
        current = next(
            (c for c in getattr(self, "conversation_data", []) if c["id"] == self.conversation_id),
            None,
        )
        self.chat_title.setText(current["name"] if current else self.tr("New discussion"))
        for action in (self.rename_chat, self.move_chat, self.delete_chat):
            action.setEnabled(current is not None)
        if current and self.service:
            profiles = {p.id: p.name for p in self.service.agent.setup.settings.client_profiles}
            clients = [profiles.get(i, i) for i in current["policy"]["clients"]]
            self.chat_title.setToolTip(self.tr("Clients: %1").replace("%1", ", ".join(clients)))
        else:
            self.chat_title.setToolTip("")

    def _notify(self, text):
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def use_example(self, text):
        self.prompt.setPlainText(text)
        self.prompt.setFocus()
        self.prompt.moveCursor(QTextCursor.MoveOperation.End)

    def conversation_action(self, action, identifier):
        self.select_conversation(identifier)
        {
            "rename": self.rename_conversation,
            "move": self.move_conversation,
            "delete": self.delete_discussion,
        }[action]()

    def toggle_mode(self):
        if not self.service:
            return
        if self.conversation_id:
            body = self.service.conversation(self.conversation_id)[0]
            current = body.policy.mode
        else:
            current = self.pending_mode or self.service.chat_defaults().policy.mode
        mode = "propose" if current == "execute" else "execute"
        if mode == "execute" and not self.service.setup()["execute_acknowledged"]:
            answer = QMessageBox.question(
                self,
                self.tr("Execute within limits"),
                self.tr(
                    "In this mode the assistant runs the actions allowed in this discussion's "
                    "settings without asking, within its limits on clients, size and downloads "
                    "per day. Removing queue entries or torrents and deleting files still need "
                    "your approval.\n\n"
                    "Switch to Execute within limits? You will not be asked again."
                ),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.service.acknowledge_execute()
            QSettings().setValue("assistant/execute_confirmed", True)
        if self.conversation_id:
            body.policy.mode = mode
            self.perform(lambda: self.service.update_conversation(self.conversation_id, body))
        else:
            self.pending_mode = mode
            self.composer.set_mode(mode == "execute")

    def rename_conversation(self):
        if not self.service or not self.conversation_id:
            return
        body = self.service.conversation(self.conversation_id)[0]
        name, accepted = QInputDialog.getText(
            self, self.tr("Rename discussion"), self.tr("Name"), text=body.name
        )
        if accepted and name.strip():
            body.name = name.strip()[:120]
            self.perform(lambda: self.service.update_conversation(self.conversation_id, body))

    def activate(self):
        try:
            self.service = self.get_service()
            self._notify("")
            self.refresh()
        except Exception as error:
            self._notify(str(error))

    def perform(self, action):
        try:
            if self.service:
                result = action()
                self.refresh()
                return result
        except Exception as error:
            QMessageBox.warning(self, self.tr("Assistant"), str(error))

    def refresh(self):
        if not self.service:
            return
        self.conversation_data = self.service.conversations()
        self.conversations.set_rows(self.conversation_data, self.conversation_id)
        self.provider_data = self.service.setup()["providers"]
        current = next((c for c in self.conversation_data if c["id"] == self.conversation_id), None)
        chosen = (
            current["provider_id"]
            if current
            else self.chat_model.currentData() or self.service.chat_defaults().provider_id
        )
        self.chat_model.blockSignals(True)
        self.chat_model.clear()
        for p in self.provider_data:
            self.chat_model.addItem(p["name"] + " · " + p["model"], p["id"])
        index = self.chat_model.findData(chosen)
        if index >= 0:
            self.chat_model.setCurrentIndex(index)
        self.chat_model.blockSignals(False)
        self.connect_model.setVisible(not self.provider_data)
        self.composer.setVisible(bool(self.provider_data))
        self.render_key = ""
        self.refresh_run()

    def change_chat_model(self):
        if self.service and self.conversation_id:
            body, _ = self.service.conversation(self.conversation_id)
            body.provider_id = self.chat_model.currentData() or ""
            self.perform(lambda: self.service.update_conversation(self.conversation_id, body))
            self.refresh()

    def edit_chat_settings(self, *, defaults=False):
        if not self.service:
            return
        defaults = defaults or not self.conversation_id
        if defaults:
            initial = self.service.chat_defaults().model_dump()
            initial["provider_id"] = self.chat_model.currentData() or initial["provider_id"]
        else:
            body, _ = self.service.conversation(self.conversation_id)
            initial = {"id": self.conversation_id, **body.model_dump()}
        editor = AssistantEditor(self.service, initial=initial, defaults=defaults, parent=self)
        if editor.exec():
            if defaults and not self.conversation_id:
                self.chat_model.setCurrentIndex(
                    self.chat_model.findData(editor.provider.currentData())
                )
            self.refresh()

    def delete_discussion(self):
        if not self.service or not self.conversation_id:
            return
        if (
            QMessageBox.question(
                self,
                self.tr("Delete discussion"),
                self.tr(
                    "Delete this discussion and its history? Pending proposals will be rejected. "
                    "Torrents and files will not be removed."
                ),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            identifier = self.conversation_id
            self.service.delete_conversation(identifier)
            self.new_discussion()
            self.drafts.pop(identifier, None)
            self.refresh()
        except Exception as error:
            self.error(error)

    def move_conversation(self):
        if not self.service or not self.conversation_id:
            return
        current = next(c for c in self.conversation_data if c["id"] == self.conversation_id)
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Move to folder…"))
        layout = QFormLayout(dialog)
        folder = QComboBox()
        folder.setEditable(True)
        folder.lineEdit().setMaxLength(80)
        choices = dict.fromkeys(
            ["", "uploads", "film_research", "series_research", "troubleshooting"]
            + [c.get("folder", "") for c in self.conversation_data]
        )
        for value in choices:
            folder.addItem(self.conversations.folder_label(value), value)
        folder.setCurrentIndex(folder.findData(current.get("folder", "")))
        layout.addRow(self.tr("Folder"), folder)
        automatic = QCheckBox(self.tr("Let the assistant organize this conversation"))
        automatic.setChecked(current.get("folder_source", "auto") == "auto")
        # Choosing a folder manually pins it; opting back in permits future classification.
        folder.editTextChanged.connect(lambda _: automatic.setChecked(False))
        layout.addRow(automatic)
        actions = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addRow(actions)
        if dialog.exec():
            index = folder.currentIndex()
            value = (
                folder.itemData(index)
                if index >= 0 and folder.itemText(index) == folder.currentText()
                else folder.currentText().strip()
            )
            self.perform(
                lambda: self.service.move_conversation(
                    self.conversation_id, value, automatic=automatic.isChecked()
                )
            )

    def new_discussion(self):
        self.drafts[self.conversation_id] = self.prompt.toPlainText()
        self.drafts.pop("", None)
        self.conversation_id = ""
        self.pending_mode = ""
        self.run_id = ""
        self.prompt.clear()
        self.conversations.select_id("")
        self.chat_model.setCurrentIndex(
            self.chat_model.findData(self.service.chat_defaults().provider_id)
        )
        self.render_key = ""
        self.refresh_run()
        self.prompt.setFocus()

    def select_conversation(self, identifier):
        conversation = next((c for c in self.conversation_data if c["id"] == identifier), None)
        if conversation:
            self.drafts[self.conversation_id] = self.prompt.toPlainText()
            self.conversation_id = conversation["id"]
            self.chat_model.setCurrentIndex(self.chat_model.findData(conversation["provider_id"]))
            self.prompt.setPlainText(self.drafts.get(self.conversation_id, ""))
            self.run_id = ""
            self.render_key = ""
            self.refresh_run()

    def run_heading(self, run):
        names = {c["id"]: c["name"] for c in getattr(self, "conversation_data", [])}
        name = names.get(run.get("conversation_id"), self.tr("Automation"))
        when = datetime.fromtimestamp(run.get("created") or 0).astimezone()
        return " · ".join((name, when.strftime("%d/%m %H:%M"), self.status_text(run["status"])))

    def stop_run(self):
        if self.service and self.run_id:
            self.perform(lambda: self.service.cancel(self.run_id))

    def send_message(self):
        message = self.prompt.toPlainText().strip()
        if not self.service or not self.composer.can_send or not message:
            return

        def submit():
            if not self.conversation_id:
                body = self.service.chat_defaults()
                body.provider_id = self.chat_model.currentData() or ""
                if self.pending_mode:
                    body.policy.mode = self.pending_mode
                body.name = "Discussion"
                self.conversation_id = self.service.create_conversation(body)["id"]
                self.pending_mode = ""
            return self.service.start(self.conversation_id, message)

        result = self.perform(submit)
        if result:
            self.run_id = result["id"]
            self.drafts.pop(self.conversation_id, None)
            self.drafts.pop("", None)
            self.prompt.clear()

    def render_transcript(self, rows):
        parts = ["<style>p{line-height:1.6;}pre{white-space:pre-wrap;}a{color:#55bdb7;}</style>"]
        for run in reversed(rows):
            parts.append(
                "<p><small>"
                + html.escape(
                    self.status_text(run["status"])
                    + " · "
                    + self.tr("%1 calls · %2 tokens")
                    .replace("%1", str(run["calls"]))
                    .replace("%2", str(run["tokens"]))
                )
                + "</small></p>"
            )
            for m in run["messages"]:
                parts.append(
                    "<p><b>"
                    + html.escape(self.tr("You") if m["role"] == "user" else "Assistant")
                    + "</b></p><p>"
                    + html.escape(m["content"]).replace("\n", "<br>")
                    + "</p>"
                )
            if run["error"]:
                parts.append("<p>" + html.escape(run["error"]) + "</p>")
            for i, event in enumerate(run["events"]):
                parts.append(
                    f'<p><a href="receipt:{run["id"]}:{i}">'
                    + html.escape(event["tool"] + " · " + self.status_text(event["status"]))
                    + "</a></p>"
                )
                result = event.get("result", {})
                if result.get("requires_owner_approval"):
                    parts.append(
                        f'<p><a href="proposal:{result["id"]}">'
                        + html.escape(self.tr("Review proposal"))
                        + "</a></p>"
                    )
        return "".join(parts)

    def refresh_run(self):
        if not self.service or not self.isVisible():
            return
        self.conversation_data = self.service.conversations()
        self.conversations.set_rows(self.conversation_data, self.conversation_id)
        rows = self.service.history(self.conversation_id) if self.conversation_id else []
        all_rows = self.service.history() if self.pages.currentWidget() is self.history else []
        key = json.dumps([rows, all_rows])
        if key == self.render_key:
            return
        self.render_key = key
        bar = self.transcript.verticalScrollBar()
        position, bottom = bar.value(), bar.value() >= bar.maximum() - 10
        self.transcript.follow_bottom = bottom
        self.transcript.set_runs(rows, self.status_text)

        def restore_scroll():
            if self.render_key == key:
                bar.setValue(bar.maximum() if bottom else position)

        QTimer.singleShot(0, self, restore_scroll)
        active = next(
            (
                r
                for r in rows
                if r["status"]
                in {"queued", "running", "awaiting_approval", "awaiting_user", "waiting_settings"}
            ),
            None,
        )
        self.composer.set_state(
            running=bool(active), can_send=not active and bool(self.chat_model.currentData())
        )
        self.chat_settings.setEnabled(not active and bool(self.provider_data))
        body = (
            self.service.conversation(self.conversation_id)[0]
            if self.conversation_id
            else self.service.chat_defaults()
        )
        mode = body.policy.mode if self.conversation_id else self.pending_mode or body.policy.mode
        self.composer.set_mode(mode == "execute")
        self.run_id = active["id"] if active else self.run_id
        self._sync_header()
        if all_rows:
            self.history.set_runs(all_rows, self.status_text)

    def open_receipt(self, url):
        try:
            parts = url.toString().split(":")
            if parts[0] == "proposal":
                run_in_background(
                    lambda: self.service.agent.review(parts[1]),
                    lambda review: self.review_dialog(parts[1], review),
                    self.error,
                )
                return
            event = self.service.run(parts[1])["events"][int(parts[2])]
            dialog = QDialog(self)
            dialog.resize(720, 520)
            layout = QVBoxLayout(dialog)
            text = JsonCode(event)
            text.setReadOnly(True)
            layout.addWidget(text)
            result = event.get("result", {})
            if result.get("job_id"):
                progress = QPushButton(self.tr("Job progress"))
                progress.clicked.connect(
                    lambda: text.setPlainText(
                        json.dumps(
                            self.service.agent.jobs.get(result["job_id"]),
                            indent=2,
                            ensure_ascii=False,
                        )
                    )
                )
                layout.addWidget(progress)
            dialog.exec()
        except Exception as error:
            self.error(error)

    def submit_decision(self, run, index, approve):
        run_in_background(
            lambda: self.service.decide(run, index, approve),
            lambda _: self.refresh_run(),
            self.error,
        )

    def submit_answer(self, run, index, answer):
        run_in_background(
            lambda: self.service.answer(run, index, answer),
            lambda _: self.refresh_run(),
            self.error,
        )

    def review_dialog(self, identifier, review):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("Review proposal"))
        dialog.resize(720, 520)
        layout = QVBoxLayout(dialog)
        layout.addWidget(RequestDetails({"review": review}))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        approve = buttons.addButton(
            self.tr("Approve this action"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        reject = buttons.addButton(self.tr("Reject"), QDialogButtonBox.ButtonRole.DestructiveRole)
        approve.clicked.connect(
            lambda: run_in_background(
                lambda: self.service.agent.execute(identifier, approved=True),
                lambda _: dialog.accept(),
                self.error,
            )
        )

        def decline():
            self.service.agent.reject(identifier)
            dialog.accept()

        reject.clicked.connect(decline)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def error(self, error):
        detail = self.service.secrets.redact(str(error)) if self.service else str(error)
        QMessageBox.warning(self, self.tr("Assistant"), detail)
