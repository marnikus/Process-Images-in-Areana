"""
MVP Desktop UI with PySide6.
Provides:
- URL list: add, edit, remove, enable, disable, test
- URL status
- Folder picker
- Image queue with thumbnail, relative path, etc.
- Bulk controls
- Prompt editor with preview including correlation token
- Run controls: Start, Pause, Resume, Stop after current, Cancel current, Retry
- Progress summary
- Activity log
- Settings
"""
from pathlib import Path
import json
import asyncio
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QCheckBox, QGroupBox, QSplitter,
    QProgressBar, QComboBox, QSpinBox, QFormLayout, QTabWidget, QToolBar
)
from PySide6.QtCore import Qt, Signal, Slot, QThread, QObject
from PySide6.QtGui import QAction, QIcon

from ..core.models import AppState, UrlRow, ImageItem
from ..core.enums import UrlStatus, ImageStatus, RunState
from ..core.scanner import scan_folder
from ..core.persistence import load_state, save_state, save_preset, load_preset, reconcile_with_filesystem
from ..utils.correlation import generate_correlation_id, build_final_prompt
from ..browser.controller import BrowserController
from ..services.job_runner import JobRunner

# For async integration
try:
    from qasync import asyncSlot
except ImportError:
    # Fallback dummy decorator
    def asyncSlot(*args, **kwargs):
        def decorator(fn):
            return fn
        return decorator

class BrowserWorker(QObject):
    """Worker that runs browser tasks in asyncio loop."""
    log_signal = Signal(dict)
    progress_signal = Signal(object, object)  # job, image
    url_status_signal = Signal(str, str, str)  # url_id, status, error
    finished_signal = Signal()
    error_signal = Signal(str)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.browser: BrowserController | None = None
        self.runner: JobRunner | None = None
        self._loop = None

    def set_state(self, state: AppState):
        self.state = state

    async def _ensure_browser(self):
        if not self.browser:
            user_data_dir = self.state.settings.browser.get("user_data_dir", "./browser_profile")
            headless = self.state.settings.browser.get("headless", False)
            slow_mo = self.state.settings.browser.get("slow_mo", 0)
            self.browser = BrowserController(user_data_dir=user_data_dir, headless=headless, slow_mo=slow_mo)
            self.browser.set_log_callback(lambda msg: self.log_signal.emit({"timestamp": datetime.utcnow().isoformat()+"Z", "job_id": "browser", "message": msg, "level": "info"}))
            await self.browser.launch()
            self.runner = JobRunner(self.browser, self.state, log_callback=self.log_signal.emit)

    @Slot()
    def start_batch(self):
        asyncio.create_task(self._run_batch())

    async def _run_batch(self):
        try:
            await self._ensure_browser()
            user_prompt = self.state.prompt.get("user_prompt", "")
            await self.runner.run_batch(self.state.images, self.state.urls, user_prompt, progress_callback=lambda job, img: self.progress_signal.emit(job, img))
            self.finished_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e))
            self.finished_signal.emit()

    @Slot(str)
    def test_url(self, url_id: str):
        asyncio.create_task(self._test_url(url_id))

    async def _test_url(self, url_id: str):
        try:
            await self._ensure_browser()
            url_row = next((u for u in self.state.urls if u.id == url_id), None)
            if not url_row:
                self.url_status_signal.emit(url_id, UrlStatus.ERROR.value, "URL not found")
                return
            self.url_status_signal.emit(url_id, UrlStatus.CHECKING.value, "")
            status = await self.browser.check_url_status(url_row)
            self.url_status_signal.emit(url_id, status.value, url_row.error or "")
        except Exception as e:
            self.url_status_signal.emit(url_id, UrlStatus.ERROR.value, str(e))

    @Slot()
    def stop_browser(self):
        asyncio.create_task(self._stop_browser())

    async def _stop_browser(self):
        if self.browser:
            await self.browser.close()
            self.browser = None
            self.runner = None

    def request_pause(self):
        if self.runner:
            self.runner.request_pause()

    def request_resume(self):
        if self.runner:
            self.runner.request_resume()

    def request_cancel(self):
        if self.runner:
            self.runner.request_cancel()

    def request_stop_after_current(self):
        if self.runner:
            self.runner.request_stop_after_current()

class MainWindow(QMainWindow):
    def __init__(self, state_path: Path = Path("config/app_state.json")):
        super().__init__()
        self.state_path = Path(state_path)
        self.state = load_state(self.state_path)
        self.browser_worker = BrowserWorker(self.state)
        self.browser_thread = None
        self._loop = None

        self.setWindowTitle("Arena Image Processor — MVP")
        self.resize(1400, 900)

        self._init_ui()
        self._connect_signals()
        self._refresh_all()

        # Reconcile on startup
        if self.state.folder.get("root_path"):
            try:
                result = reconcile_with_filesystem(self.state, Path(self.state.folder["root_path"]))
                self.log(f"Reconciled filesystem: {result}")
                self._refresh_images()
            except Exception as e:
                self.log(f"Reconcile failed: {e}", level="error")

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Top splitter: left URLs, middle main, right settings
        top_splitter = QSplitter(Qt.Horizontal)

        # === URL List Group ===
        url_group = QGroupBox("URL List")
        url_layout = QVBoxLayout(url_group)
        self.url_list = QListWidget()
        url_layout.addWidget(self.url_list)

        url_btn_layout = QHBoxLayout()
        self.btn_add_url = QPushButton("Add")
        self.btn_edit_url = QPushButton("Edit")
        self.btn_remove_url = QPushButton("Remove")
        self.btn_test_url = QPushButton("Test")
        self.btn_test_all = QPushButton("Test All")
        url_btn_layout.addWidget(self.btn_add_url)
        url_btn_layout.addWidget(self.btn_edit_url)
        url_btn_layout.addWidget(self.btn_remove_url)
        url_btn_layout.addWidget(self.btn_test_url)
        url_btn_layout.addWidget(self.btn_test_all)
        url_layout.addLayout(url_btn_layout)

        url_enable_layout = QHBoxLayout()
        self.btn_enable_url = QPushButton("Enable")
        self.btn_disable_url = QPushButton("Disable")
        url_enable_layout.addWidget(self.btn_enable_url)
        url_enable_layout.addWidget(self.btn_disable_url)
        url_enable_layout.addStretch()
        url_layout.addLayout(url_enable_layout)

        self.label_url_status = QLabel("Status: -")
        url_layout.addWidget(self.label_url_status)

        top_splitter.addWidget(url_group)

        # === Middle: Folder, Prompt, Queue, Run Controls ===
        middle_widget = QWidget()
        middle_layout = QVBoxLayout(middle_widget)

        # Folder picker
        folder_group = QGroupBox("Folder Picker")
        folder_layout = QHBoxLayout(folder_group)
        self.edit_folder = QLineEdit()
        self.edit_folder.setPlaceholderText("Select root folder")
        self.edit_folder.setText(self.state.folder.get("root_path", ""))
        self.btn_pick_folder = QPushButton("Choose Folder")
        self.btn_scan = QPushButton("Scan")
        folder_layout.addWidget(self.edit_folder, stretch=1)
        folder_layout.addWidget(self.btn_pick_folder)
        folder_layout.addWidget(self.btn_scan)
        middle_layout.addWidget(folder_group)

        # Prompt editor
        prompt_group = QGroupBox("Prompt Editor")
        prompt_layout = QVBoxLayout(prompt_group)
        self.edit_prompt = QTextEdit()
        self.edit_prompt.setPlaceholderText("Enter your prompt here...")
        self.edit_prompt.setText(self.state.prompt.get("user_prompt", ""))
        prompt_layout.addWidget(self.edit_prompt)
        self.label_prompt_preview = QLabel("Preview with correlation token will appear here")
        self.label_prompt_preview.setWordWrap(True)
        self.label_prompt_preview.setStyleSheet("color: gray; font-family: monospace;")
        prompt_layout.addWidget(self.label_prompt_preview)
        middle_layout.addWidget(prompt_group)

        # Run controls
        run_group = QGroupBox("Run Controls")
        run_layout = QHBoxLayout(run_group)
        self.btn_start = QPushButton("Start")
        self.btn_pause = QPushButton("Pause")
        self.btn_resume = QPushButton("Resume")
        self.btn_stop_after = QPushButton("Stop After Current")
        self.btn_cancel = QPushButton("Cancel Current")
        self.btn_retry_failed = QPushButton("Retry Failed")
        run_layout.addWidget(self.btn_start)
        run_layout.addWidget(self.btn_pause)
        run_layout.addWidget(self.btn_resume)
        run_layout.addWidget(self.btn_stop_after)
        run_layout.addWidget(self.btn_cancel)
        run_layout.addWidget(self.btn_retry_failed)
        middle_layout.addWidget(run_group)

        # Progress summary
        progress_group = QGroupBox("Progress Summary")
        progress_layout = QHBoxLayout(progress_group)
        self.label_progress = QLabel("Total: 0 | Selected: 0 | Pending: 0 | Processing: 0 | Completed: 0 | Failed: 0 | Needs Review: 0")
        progress_layout.addWidget(self.label_progress)
        middle_layout.addWidget(progress_group)

        # Bulk controls
        bulk_group = QGroupBox("Image Queue — Bulk Controls")
        bulk_layout = QVBoxLayout(bulk_group)
        bulk_btn_layout = QHBoxLayout()
        self.btn_select_all = QPushButton("Select All")
        self.btn_deselect_all = QPushButton("Deselect All")
        self.btn_select_pending = QPushButton("Select Pending")
        self.btn_clear_completed = QPushButton("Clear Completed")
        bulk_btn_layout.addWidget(self.btn_select_all)
        bulk_btn_layout.addWidget(self.btn_deselect_all)
        bulk_btn_layout.addWidget(self.btn_select_pending)
        bulk_btn_layout.addWidget(self.btn_clear_completed)
        bulk_btn_layout.addStretch()
        bulk_layout.addLayout(bulk_btn_layout)

        # Image queue table
        self.table_images = QTableWidget()
        self.table_images.setColumnCount(9)
        self.table_images.setHorizontalHeaderLabels(["Sel", "Rel Path", "Filename", "Status", "Assigned URL", "Attempts", "Output Path", "Error", "Size"])
        self.table_images.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table_images.setSelectionBehavior(QTableWidget.SelectRows)
        bulk_layout.addWidget(self.table_images)

        middle_layout.addWidget(bulk_group, stretch=1)

        top_splitter.addWidget(middle_widget)
        top_splitter.setStretchFactor(1, 2)

        # === Settings Tab ===
        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        self.tabs_settings = QTabWidget()

        # Timeouts tab
        timeout_tab = QWidget()
        timeout_form = QFormLayout(timeout_tab)
        self.spin_page_load = QSpinBox(); self.spin_page_load.setRange(5, 120); self.spin_page_load.setValue(self.state.settings.timeouts.get("page_load", 30))
        self.spin_selector = QSpinBox(); self.spin_selector.setRange(1, 60); self.spin_selector.setValue(self.state.settings.timeouts.get("selector", 10))
        self.spin_attachment = QSpinBox(); self.spin_attachment.setRange(1, 60); self.spin_attachment.setValue(self.state.settings.timeouts.get("attachment", 15))
        self.spin_generation = QSpinBox(); self.spin_generation.setRange(30, 600); self.spin_generation.setValue(self.state.settings.timeouts.get("generation", 180))
        self.spin_download = QSpinBox(); self.spin_download.setRange(5, 120); self.spin_download.setValue(self.state.settings.timeouts.get("download", 30))
        timeout_form.addRow("Page Load (s)", self.spin_page_load)
        timeout_form.addRow("Selector (s)", self.spin_selector)
        timeout_form.addRow("Attachment (s)", self.spin_attachment)
        timeout_form.addRow("Generation (s)", self.spin_generation)
        timeout_form.addRow("Download (s)", self.spin_download)
        self.tabs_settings.addTab(timeout_tab, "Timeouts")

        # Output tab
        output_tab = QWidget()
        output_form = QFormLayout(output_tab)
        self.edit_suffix = QLineEdit(self.state.settings.output.get("suffix", "_AI"))
        self.check_preserve = QCheckBox(); self.check_preserve.setChecked(self.state.settings.output.get("preserve_format", True))
        self.check_overwrite = QCheckBox(); self.check_overwrite.setChecked(self.state.settings.output.get("overwrite", False))
        self.edit_unique_template = QLineEdit(self.state.settings.output.get("unique_suffix_template", "{base}_AI_{n}{ext}"))
        output_form.addRow("Suffix", self.edit_suffix)
        output_form.addRow("Preserve Format", self.check_preserve)
        output_form.addRow("Overwrite", self.check_overwrite)
        output_form.addRow("Unique Template", self.edit_unique_template)
        self.tabs_settings.addTab(output_tab, "Output")

        # Highlight tab
        highlight_tab = QWidget()
        highlight_form = QFormLayout(highlight_tab)
        self.check_highlight = QCheckBox(); self.check_highlight.setChecked(self.state.settings.highlight.get("enabled", True))
        self.spin_highlight_duration = QSpinBox(); self.spin_highlight_duration.setRange(1, 10); self.spin_highlight_duration.setValue(self.state.settings.highlight.get("duration_seconds", 2))
        self.edit_highlight_color = QLineEdit(self.state.settings.highlight.get("color", "#FF0000"))
        self.spin_highlight_width = QSpinBox(); self.spin_highlight_width.setRange(1, 10); self.spin_highlight_width.setValue(self.state.settings.highlight.get("border_width", 3))
        highlight_form.addRow("Enabled", self.check_highlight)
        highlight_form.addRow("Duration (s)", self.spin_highlight_duration)
        highlight_form.addRow("Color", self.edit_highlight_color)
        highlight_form.addRow("Border Width", self.spin_highlight_width)
        self.tabs_settings.addTab(highlight_tab, "Highlight")

        # Browser tab
        browser_tab = QWidget()
        browser_form = QFormLayout(browser_tab)
        self.edit_user_data_dir = QLineEdit(self.state.settings.browser.get("user_data_dir", "./browser_profile"))
        self.check_headless = QCheckBox(); self.check_headless.setChecked(self.state.settings.browser.get("headless", False))
        self.spin_slow_mo = QSpinBox(); self.spin_slow_mo.setRange(0, 1000); self.spin_slow_mo.setValue(self.state.settings.browser.get("slow_mo", 0))
        browser_form.addRow("User Data Dir", self.edit_user_data_dir)
        browser_form.addRow("Headless", self.check_headless)
        browser_form.addRow("Slow Mo (ms)", self.spin_slow_mo)
        self.tabs_settings.addTab(browser_tab, "Browser")

        # Supported types tab
        types_tab = QWidget()
        types_layout = QVBoxLayout(types_tab)
        self.edit_supported_types = QLineEdit(",".join(self.state.settings.supported_types))
        types_layout.addWidget(QLabel("Supported file types (comma separated, e.g. .png,.jpg)"))
        types_layout.addWidget(self.edit_supported_types)
        self.check_ignore_ai = QCheckBox("Ignore _AI suffix"); self.check_ignore_ai.setChecked(self.state.settings.ignore_ai_suffix)
        types_layout.addWidget(self.check_ignore_ai)
        self.tabs_settings.addTab(types_tab, "Files")

        settings_layout.addWidget(self.tabs_settings)

        # Preset buttons
        preset_layout = QHBoxLayout()
        self.btn_save_preset = QPushButton("Save Preset")
        self.btn_load_preset = QPushButton("Load Preset")
        preset_layout.addWidget(self.btn_save_preset)
        preset_layout.addWidget(self.btn_load_preset)
        settings_layout.addLayout(preset_layout)

        top_splitter.addWidget(settings_widget)

        main_layout.addWidget(top_splitter, stretch=3)

        # Activity log
        log_group = QGroupBox("Activity Log")
        log_layout = QVBoxLayout(log_group)
        self.edit_log = QTextEdit()
        self.edit_log.setReadOnly(True)
        self.edit_log.setMaximumHeight(200)
        log_layout.addWidget(self.edit_log)
        main_layout.addWidget(log_group, stretch=1)

        # Status bar
        self.statusBar().showMessage("Ready")

    def _connect_signals(self):
        self.btn_add_url.clicked.connect(self.add_url)
        self.btn_edit_url.clicked.connect(self.edit_url)
        self.btn_remove_url.clicked.connect(self.remove_url)
        self.btn_test_url.clicked.connect(self.test_selected_url)
        self.btn_test_all.clicked.connect(self.test_all_urls)
        self.btn_enable_url.clicked.connect(lambda: self.set_url_enabled(True))
        self.btn_disable_url.clicked.connect(lambda: self.set_url_enabled(False))

        self.btn_pick_folder.clicked.connect(self.pick_folder)
        self.btn_scan.clicked.connect(self.scan_folder)

        self.edit_prompt.textChanged.connect(self.update_prompt_preview)
        self.edit_prompt.textChanged.connect(self.save_state_delayed)

        self.btn_start.clicked.connect(self.start_batch)
        self.btn_pause.clicked.connect(self.pause_batch)
        self.btn_resume.clicked.connect(self.resume_batch)
        self.btn_stop_after.clicked.connect(self.stop_after_current)
        self.btn_cancel.clicked.connect(self.cancel_current)
        self.btn_retry_failed.clicked.connect(self.retry_failed)

        self.btn_select_all.clicked.connect(self.select_all)
        self.btn_deselect_all.clicked.connect(self.deselect_all)
        self.btn_select_pending.clicked.connect(self.select_pending)
        self.btn_clear_completed.clicked.connect(self.clear_completed)

        self.btn_save_preset.clicked.connect(self.save_preset)
        self.btn_load_preset.clicked.connect(self.load_preset)

        # Settings changes
        self.spin_page_load.valueChanged.connect(self.save_state_delayed)
        self.spin_selector.valueChanged.connect(self.save_state_delayed)
        self.spin_attachment.valueChanged.connect(self.save_state_delayed)
        self.spin_generation.valueChanged.connect(self.save_state_delayed)
        self.spin_download.valueChanged.connect(self.save_state_delayed)
        self.edit_suffix.textChanged.connect(self.save_state_delayed)
        self.check_preserve.stateChanged.connect(self.save_state_delayed)
        self.check_overwrite.stateChanged.connect(self.save_state_delayed)
        self.edit_unique_template.textChanged.connect(self.save_state_delayed)
        self.check_highlight.stateChanged.connect(self.save_state_delayed)
        self.spin_highlight_duration.valueChanged.connect(self.save_state_delayed)
        self.edit_highlight_color.textChanged.connect(self.save_state_delayed)
        self.spin_highlight_width.valueChanged.connect(self.save_state_delayed)
        self.edit_user_data_dir.textChanged.connect(self.save_state_delayed)
        self.check_headless.stateChanged.connect(self.save_state_delayed)
        self.spin_slow_mo.valueChanged.connect(self.save_state_delayed)
        self.edit_supported_types.textChanged.connect(self.save_state_delayed)
        self.check_ignore_ai.stateChanged.connect(self.save_state_delayed)
        self.edit_folder.textChanged.connect(self.save_state_delayed)

        # Browser worker signals
        self.browser_worker.log_signal.connect(self.on_log)
        self.browser_worker.progress_signal.connect(self.on_job_progress)
        self.browser_worker.url_status_signal.connect(self.on_url_status)
        self.browser_worker.finished_signal.connect(self.on_batch_finished)
        self.browser_worker.error_signal.connect(self.on_batch_error)

    def log(self, message: str, level: str = "info"):
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self.edit_log.append(f"[{ts}] [{level}] {message}")
        self.statusBar().showMessage(message, 5000)

    @Slot(dict)
    def on_log(self, entry: dict):
        ts = entry.get("timestamp", "")
        job_id = entry.get("job_id", "")
        msg = entry.get("message", "")
        level = entry.get("level", "info")
        self.edit_log.append(f"[{ts}] [{job_id}] [{level}] {msg}")

    @Slot(object, object)
    def on_job_progress(self, job, image):
        self._refresh_images()
        self._refresh_progress()
        save_state(self.state, self.state_path)

    @Slot(str, str, str)
    def on_url_status(self, url_id: str, status: str, error: str):
        for url in self.state.urls:
            if url.id == url_id:
                url.last_status = status
                url.error = error
                break
        self._refresh_urls()
        save_state(self.state, self.state_path)
        self.log(f"URL {url_id} status: {status} {error}")

    @Slot()
    def on_batch_finished(self):
        self.state.run_state = RunState.IDLE.value
        self._refresh_progress()
        save_state(self.state, self.state_path)
        self.log("Batch finished")
        self.statusBar().showMessage("Batch finished")

    @Slot(str)
    def on_batch_error(self, error: str):
        self.log(f"Batch error: {error}", level="error")
        self.state.run_state = RunState.ERROR.value
        save_state(self.state, self.state_path)

    def _refresh_all(self):
        self._refresh_urls()
        self._refresh_images()
        self._refresh_progress()
        self.update_prompt_preview()

    def _refresh_urls(self):
        self.url_list.clear()
        for url in self.state.urls:
            status = url.last_status
            enabled = "✓" if url.enabled else "✗"
            item = QListWidgetItem(f"[{enabled}] [{status}] {url.url}")
            item.setData(Qt.UserRole, url.id)
            self.url_list.addItem(item)
        self.label_url_status.setText(f"URLs: {len(self.state.urls)} | Ready: {sum(1 for u in self.state.urls if u.last_status == UrlStatus.READY.value)}")

    def _refresh_images(self):
        self.table_images.setRowCount(0)
        for img in self.state.images:
            row = self.table_images.rowCount()
            self.table_images.insertRow(row)

            # Selected checkbox
            chk = QTableWidgetItem()
            chk.setFlags(chk.flags() | Qt.ItemIsUserCheckable)
            chk.setCheckState(Qt.Checked if img.selected else Qt.Unchecked)
            # Store image id in first column
            chk.setData(Qt.UserRole, img.id)
            self.table_images.setItem(row, 0, chk)

            self.table_images.setItem(row, 1, QTableWidgetItem(img.relative_path))
            self.table_images.setItem(row, 2, QTableWidgetItem(img.filename))
            self.table_images.setItem(row, 3, QTableWidgetItem(img.status))
            self.table_images.setItem(row, 4, QTableWidgetItem(img.assigned_url_id or ""))
            self.table_images.setItem(row, 5, QTableWidgetItem(str(img.attempt_count)))
            self.table_images.setItem(row, 6, QTableWidgetItem(img.output_path or ""))
            self.table_images.setItem(row, 7, QTableWidgetItem(img.error or ""))
            self.table_images.setItem(row, 8, QTableWidgetItem(str(img.size)))

        self.table_images.resizeColumnsToContents()

    def _refresh_progress(self):
        self.state.recalculate_progress()
        p = self.state.progress
        self.label_progress.setText(
            f"Total: {p['total']} | Selected: {p['selected']} | Pending: {p['pending']} | Processing: {p['processing']} | Completed: {p['completed']} | Skipped: {p['skipped']} | Failed: {p['failed']} | Needs Review: {p['needs_review']}"
        )

    def add_url(self):
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Add URL", "Enter exact webpage URL:")
        if ok and text:
            url_row = UrlRow.create(text.strip())
            self.state.urls.append(url_row)
            self._refresh_urls()
            save_state(self.state, self.state_path)
            self.log(f"Added URL {text}")

    def edit_url(self):
        current = self.url_list.currentItem()
        if not current:
            return
        url_id = current.data(Qt.UserRole)
        url_row = next((u for u in self.state.urls if u.id == url_id), None)
        if not url_row:
            return
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Edit URL", "Enter exact webpage URL:", text=url_row.url)
        if ok and text:
            url_row.url = text.strip()
            url_row.last_status = UrlStatus.UNCHECKED.value
            self._refresh_urls()
            save_state(self.state, self.state_path)
            self.log(f"Edited URL {url_id} to {text}")

    def remove_url(self):
        current = self.url_list.currentItem()
        if not current:
            return
        url_id = current.data(Qt.UserRole)
        self.state.urls = [u for u in self.state.urls if u.id != url_id]
        self._refresh_urls()
        save_state(self.state, self.state_path)
        self.log(f"Removed URL {url_id}")

    def set_url_enabled(self, enabled: bool):
        current = self.url_list.currentItem()
        if not current:
            return
        url_id = current.data(Qt.UserRole)
        for url in self.state.urls:
            if url.id == url_id:
                url.enabled = enabled
                break
        self._refresh_urls()
        save_state(self.state, self.state_path)

    def test_selected_url(self):
        current = self.url_list.currentItem()
        if not current:
            return
        url_id = current.data(Qt.UserRole)
        self.log(f"Testing URL {url_id}")
        # Need asyncio loop running
        # For simplicity, we will run in worker if loop exists
        # If qasync not used, we need to start loop manually
        # Here we assume worker will handle
        self.browser_worker.test_url(url_id)

    def test_all_urls(self):
        for url in self.state.urls:
            if url.enabled:
                self.browser_worker.test_url(url.id)

    def pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Root Folder")
        if folder:
            self.edit_folder.setText(folder)
            self.state.folder["root_path"] = folder
            save_state(self.state, self.state_path)
            self.log(f"Selected folder {folder}")

    def scan_folder(self):
        root = self.edit_folder.text().strip()
        if not root:
            QMessageBox.warning(self, "No Folder", "Please select a folder first")
            return
        supported_str = self.edit_supported_types.text()
        supported = [s.strip() for s in supported_str.split(",") if s.strip()]
        if not supported:
            supported = [".png", ".jpg", ".jpeg", ".webp"]
        ignore_ai = self.check_ignore_ai.isChecked()
        try:
            scanned = scan_folder(Path(root), set(supported), ignore_ai)
            # Merge with existing, preserve selections
            existing_by_rel = {img.relative_path: img for img in self.state.images}
            new_images = []
            for s in scanned:
                if s["relative_path"] in existing_by_rel:
                    # Update metadata but keep selection/status
                    existing = existing_by_rel[s["relative_path"]]
                    existing.size = s["size"]
                    existing.mtime = s["mtime"]
                    existing.fingerprint = s["fingerprint"]
                    existing.absolute_path = s["absolute_path"]
                    new_images.append(existing)
                else:
                    # New file, create pending
                    img_item = ImageItem.from_scan_dict(s, selected=False)
                    new_images.append(img_item)
            # Detect removed
            scanned_rels = {s["relative_path"] for s in scanned}
            for rel, img in existing_by_rel.items():
                if rel not in scanned_rels:
                    # Mark as skipped? Or keep? For now keep but mark error
                    img.error = "Source missing after scan"
                    # Keep it? We'll keep but not in new_images? Let's keep for history
                    # Actually if file removed, we should keep but mark skipped
                    # We'll include if previously selected? Simplify: keep all existing that are not in scanned but mark skipped
                    if img not in new_images:
                        new_images.append(img)

            self.state.images = new_images
            self.state.folder["root_path"] = root
            self.state.folder["supported_types"] = supported
            self.state.folder["ignore_ai_suffix"] = ignore_ai
            self._refresh_images()
            self._refresh_progress()
            save_state(self.state, self.state_path)
            self.log(f"Scanned folder {root}: found {len(scanned)} images")
        except Exception as e:
            QMessageBox.critical(self, "Scan Failed", str(e))
            self.log(f"Scan failed: {e}", level="error")

    def update_prompt_preview(self):
        user_prompt = self.edit_prompt.toPlainText()
        self.state.prompt["user_prompt"] = user_prompt
        # Generate dummy correlation for preview
        dummy_id = generate_correlation_id()
        preview = build_final_prompt(dummy_id, user_prompt)
        self.label_prompt_preview.setText(f"Preview:\n{preview}")
        self.state.prompt["preview_with_token"] = preview

    def save_state_delayed(self):
        # Update settings from UI
        self.state.settings.timeouts["page_load"] = self.spin_page_load.value()
        self.state.settings.timeouts["selector"] = self.spin_selector.value()
        self.state.settings.timeouts["attachment"] = self.spin_attachment.value()
        self.state.settings.timeouts["generation"] = self.spin_generation.value()
        self.state.settings.timeouts["download"] = self.spin_download.value()

        self.state.settings.output["suffix"] = self.edit_suffix.text()
        self.state.settings.output["preserve_format"] = self.check_preserve.isChecked()
        self.state.settings.output["overwrite"] = self.check_overwrite.isChecked()
        self.state.settings.output["unique_suffix_template"] = self.edit_unique_template.text()

        self.state.settings.highlight["enabled"] = self.check_highlight.isChecked()
        self.state.settings.highlight["duration_seconds"] = self.spin_highlight_duration.value()
        self.state.settings.highlight["color"] = self.edit_highlight_color.text()
        self.state.settings.highlight["border_width"] = self.spin_highlight_width.value()

        self.state.settings.browser["user_data_dir"] = self.edit_user_data_dir.text()
        self.state.settings.browser["headless"] = self.check_headless.isChecked()
        self.state.settings.browser["slow_mo"] = self.spin_slow_mo.value()

        supported_str = self.edit_supported_types.text()
        supported = [s.strip() for s in supported_str.split(",") if s.strip()]
        self.state.settings.supported_types = supported
        self.state.settings.ignore_ai_suffix = self.check_ignore_ai.isChecked()

        self.state.folder["root_path"] = self.edit_folder.text()
        self.state.folder["supported_types"] = supported
        self.state.folder["ignore_ai_suffix"] = self.check_ignore_ai.isChecked()

        # Prompt already handled
        save_state(self.state, self.state_path)

    def start_batch(self):
        if self.state.run_state == RunState.RUNNING.value:
            QMessageBox.warning(self, "Already Running", "Batch is already running")
            return
        # Ensure folder scanned?
        if not self.state.images:
            QMessageBox.warning(self, "No Images", "No images in queue, scan folder first")
            return
        ready_urls = [u for u in self.state.urls if u.enabled and u.last_status == UrlStatus.READY.value]
        if not ready_urls:
            QMessageBox.warning(self, "No Ready URLs", "No ready URLs, test URLs first")
            return
        selected = [img for img in self.state.images if img.selected]
        if not selected:
            QMessageBox.warning(self, "No Selected", "No images selected")
            return
        self.state.run_state = RunState.RUNNING.value
        save_state(self.state, self.state_path)
        self.log(f"Starting batch with {len(selected)} images")
        self.browser_worker.set_state(self.state)
        # Need to run async task — if using qasync, we can call directly
        # For simplicity, try to get running loop
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self.browser_worker._run_batch())
        except Exception as e:
            self.log(f"Failed to start batch: {e}", level="error")

    def pause_batch(self):
        self.browser_worker.request_pause()
        self.state.run_state = RunState.PAUSED.value
        self.log("Pause requested")

    def resume_batch(self):
        self.browser_worker.request_resume()
        self.state.run_state = RunState.RUNNING.value
        self.log("Resume requested")

    def stop_after_current(self):
        self.browser_worker.request_stop_after_current()
        self.state.run_state = RunState.STOPPING_AFTER_CURRENT.value
        self.log("Stop after current requested")

    def cancel_current(self):
        self.browser_worker.request_cancel()
        self.state.run_state = RunState.CANCELLING_CURRENT.value
        self.log("Cancel current requested")

    def retry_failed(self):
        for img in self.state.images:
            if img.status == ImageStatus.FAILED.value:
                img.status = ImageStatus.SELECTED.value
                img.selected = True
                img.error = None
        self._refresh_images()
        self._refresh_progress()
        save_state(self.state, self.state_path)
        self.log("Retry failed: marked failed as selected")

    def select_all(self):
        for img in self.state.images:
            img.selected = True
            if img.status == ImageStatus.DESELECTED.value:
                img.status = ImageStatus.PENDING.value
        self._refresh_images()
        self._refresh_progress()
        save_state(self.state, self.state_path)

    def deselect_all(self):
        for img in self.state.images:
            img.selected = False
            if img.status in [ImageStatus.PENDING.value, ImageStatus.SELECTED.value]:
                img.status = ImageStatus.DESELECTED.value
        self._refresh_images()
        self._refresh_progress()
        save_state(self.state, self.state_path)

    def select_pending(self):
        for img in self.state.images:
            if img.status == ImageStatus.PENDING.value:
                img.selected = True
                img.status = ImageStatus.SELECTED.value
        self._refresh_images()
        self._refresh_progress()
        save_state(self.state, self.state_path)

    def clear_completed(self):
        self.state.images = [img for img in self.state.images if img.status != ImageStatus.COMPLETED.value]
        self._refresh_images()
        self._refresh_progress()
        save_state(self.state, self.state_path)
        self.log("Cleared completed")

    def save_preset(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Preset", "config/preset.json", "JSON Files (*.json)")
        if path:
            save_preset(self.state, Path(path))
            self.log(f"Preset saved to {path}")

    def load_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Preset", "config", "JSON Files (*.json)")
        if path:
            try:
                data = load_preset(Path(path))
                # Apply to state
                # URLs
                if "urls" in data:
                    from ..core.models import UrlRow
                    self.state.urls = [UrlRow(**u) for u in data["urls"]]
                if "folder" in data:
                    self.state.folder = data["folder"]
                    self.edit_folder.setText(self.state.folder.get("root_path", ""))
                if "prompt" in data:
                    self.state.prompt = data["prompt"]
                    self.edit_prompt.setText(self.state.prompt.get("user_prompt", ""))
                if "settings" in data:
                    # Merge settings
                    from ..core.models import AppSettings
                    s = data["settings"]
                    # Update UI spinners etc.
                    self.state.settings = AppSettings(
                        timeouts=s.get("timeouts", self.state.settings.timeouts),
                        retries=s.get("retries", self.state.settings.retries),
                        output=s.get("output", self.state.settings.output),
                        highlight=s.get("highlight", self.state.settings.highlight),
                        browser=s.get("browser", self.state.settings.browser),
                        scheduling=s.get("scheduling", "round-robin"),
                        concurrency=s.get("concurrency", 1),
                        supported_types=s.get("supported_types", [".png", ".jpg", ".jpeg", ".webp"]),
                        ignore_ai_suffix=s.get("ignore_ai_suffix", True),
                    )
                    # Refresh settings UI
                    self.spin_page_load.setValue(self.state.settings.timeouts.get("page_load", 30))
                    self.spin_selector.setValue(self.state.settings.timeouts.get("selector", 10))
                    self.spin_attachment.setValue(self.state.settings.timeouts.get("attachment", 15))
                    self.spin_generation.setValue(self.state.settings.timeouts.get("generation", 180))
                    self.spin_download.setValue(self.state.settings.timeouts.get("download", 30))
                    self.edit_suffix.setText(self.state.settings.output.get("suffix", "_AI"))
                    self.check_preserve.setChecked(self.state.settings.output.get("preserve_format", True))
                    self.check_overwrite.setChecked(self.state.settings.output.get("overwrite", False))
                    self.edit_unique_template.setText(self.state.settings.output.get("unique_suffix_template", "{base}_AI_{n}{ext}"))
                    self.check_highlight.setChecked(self.state.settings.highlight.get("enabled", True))
                    self.spin_highlight_duration.setValue(self.state.settings.highlight.get("duration_seconds", 2))
                    self.edit_highlight_color.setText(self.state.settings.highlight.get("color", "#FF0000"))
                    self.spin_highlight_width.setValue(self.state.settings.highlight.get("border_width", 3))
                    self.edit_user_data_dir.setText(self.state.settings.browser.get("user_data_dir", "./browser_profile"))
                    self.check_headless.setChecked(self.state.settings.browser.get("headless", False))
                    self.spin_slow_mo.setValue(self.state.settings.browser.get("slow_mo", 0))
                    self.edit_supported_types.setText(",".join(self.state.settings.supported_types))
                    self.check_ignore_ai.setChecked(self.state.settings.ignore_ai_suffix)

                self._refresh_all()
                save_state(self.state, self.state_path)
                self.log(f"Preset loaded from {path}")
            except Exception as e:
                QMessageBox.critical(self, "Load Preset Failed", str(e))
                self.log(f"Load preset failed: {e}", level="error")

    def closeEvent(self, event):
        # Save state
        save_state(self.state, self.state_path)
        # Try to close browser
        try:
            if self.browser_worker.browser:
                # Schedule close
                loop = asyncio.get_event_loop()
                loop.create_task(self.browser_worker.browser.close())
        except Exception:
            pass
        event.accept()
