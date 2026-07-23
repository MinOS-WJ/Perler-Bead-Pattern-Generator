from __future__ import annotations

import copy
import io
import logging
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QByteArray, QSettings, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QApplication,
)

from perler_pattern.domain.editing import EditTool, PatternEditSession
from perler_pattern.domain.models import Dithering, FitMode, Project, ResultState
from perler_pattern.infrastructure.palette_io import (
    PaletteFormatError,
    load_default_palette,
    load_palette,
)
from perler_pattern.infrastructure.project_io import (
    ProjectFormatError,
    ProjectSaveError,
    load_project,
    save_project,
)
from perler_pattern.infrastructure.recovery import RecoveryStore
from perler_pattern.paths import application_data_directory, icon_path
from perler_pattern.processing.generator import generate_pattern
from perler_pattern.processing.image_io import ImageImportError, decode_source, import_source
from perler_pattern.processing.render import render_preview_png
from perler_pattern.presentation.canvas import PatternCanvas
from perler_pattern.presentation.workers import BackgroundWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("拼豆图纸生成器")
        self.setMinimumSize(1100, 720)
        self.thread_pool = QThreadPool.globalInstance()
        self.project = Project.new(load_default_palette())
        self.current_worker: BackgroundWorker | None = None
        self.generation_task_id = 0
        self.source_pixmap = QPixmap()
        self.edit_session: PatternEditSession | None = None
        self.current_palette_code: str | None = self.project.palette.colors[0].code
        self.zoom_percent = 100
        self.ribbon_collapsed = False
        self.loading_controls = False
        self.autosave_failure_count = 0
        self.data_directory = application_data_directory()
        self.data_directory.mkdir(parents=True, exist_ok=True)
        self.settings = QSettings(str(self.data_directory / "settings.ini"), QSettings.IniFormat)
        self.recovery_store = RecoveryStore(self.data_directory)
        self._build_actions()
        self._build_ui()
        self._restore_window_state()
        self._load_project_into_ui()
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(60_000)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start()
        QTimer.singleShot(0, self._offer_recovery)

    def _build_actions(self) -> None:
        self.action_new = self._action("新建", "Ctrl+N", self.new_project)
        self.action_open = self._action("打开", "Ctrl+O", self.open_project)
        self.action_save = self._action("保存", "Ctrl+S", self.save_project)
        self.action_save_as = self._action("另存为", "Ctrl+Shift+S", self.save_project_as)
        self.action_import = self._action("导入图片", "Ctrl+I", self.import_image)
        self.action_generate = self._action("生成图纸", "Ctrl+Return", self.start_generation)
        self.action_cancel = self._action("取消生成", "Esc", self.cancel_generation)
        self.action_fit = self._action("适应窗口", "0", self.fit_to_window)
        self.action_actual = self._action("实际大小", "1", self.actual_size)
        self.action_grid = self._action("显示网格", "G", self.toggle_grid, checkable=True)
        self.action_codes = self._action("显示色号", "Shift+G", self.toggle_codes, checkable=True)
        self.action_zoom_in = self._action("放大", "Ctrl++", lambda: self.set_zoom(self.zoom_percent + 10))
        self.action_zoom_out = self._action("缩小", "Ctrl+-", lambda: self.set_zoom(self.zoom_percent - 10))
        self.edit_tool_group = QActionGroup(self)
        self.edit_tool_group.setExclusive(True)
        self.action_brush = self._action("画笔", "B", lambda: self.set_edit_tool(EditTool.BRUSH), checkable=True)
        self.action_eraser = self._action("橡皮", "E", lambda: self.set_edit_tool(EditTool.ERASER), checkable=True)
        self.action_picker = self._action("取色器", "I", lambda: self.set_edit_tool(EditTool.PICKER), checkable=True)
        for action in (self.action_brush, self.action_eraser, self.action_picker):
            self.edit_tool_group.addAction(action)
        self.action_brush.setChecked(True)
        self.action_undo = self._action("撤销", "Ctrl+Z", self.undo_edit)
        self.action_redo = self._action("重做", "Ctrl+Y", self.redo_edit)

    def _action(self, text: str, shortcut: str, callback, *, checkable: bool = False) -> QAction:
        action = QAction(text, self)
        action.setShortcut(shortcut)
        action.setCheckable(checkable)
        action.triggered.connect(lambda checked=False: callback())
        self.addAction(action)
        return action

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_title_row())
        self.ribbon = self._build_ribbon()
        layout.addWidget(self.ribbon)
        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self._build_backstage())
        self.content_stack.addWidget(self._build_workspace())
        self.content_stack.setCurrentIndex(1)
        layout.addWidget(self.content_stack, 1)
        self.setCentralWidget(root)
        self._build_status_bar()

    def _build_title_row(self) -> QWidget:
        row = QFrame()
        row.setObjectName("TitleRow")
        row.setFixedHeight(42)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 5, 12, 5)
        logo = QLabel()
        logo.setPixmap(QIcon(str(icon_path("app_logo.svg"))).pixmap(26, 26))
        layout.addWidget(logo)
        title = QLabel("拼豆图纸生成器")
        title.setObjectName("AppTitle")
        layout.addWidget(title)
        self.save_state_label = QLabel("未保存")
        self.save_state_label.setObjectName("SaveState")
        layout.addWidget(self.save_state_label)
        for action in (self.action_save, self.action_undo, self.action_redo):
            button = QToolButton()
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            layout.addWidget(button)
        layout.addStretch()
        self.project_title_label = QLabel()
        layout.addWidget(self.project_title_label)
        self.collapse_ribbon_button = QPushButton("收起功能区")
        self.collapse_ribbon_button.clicked.connect(self.toggle_ribbon)
        layout.addWidget(self.collapse_ribbon_button)
        return row

    def _build_ribbon(self) -> QTabWidget:
        ribbon = QTabWidget()
        ribbon.setObjectName("Ribbon")
        ribbon.setDocumentMode(True)
        ribbon.setMaximumHeight(128)
        ribbon.addTab(self._ribbon_page([]), "文件")
        ribbon.addTab(
            self._ribbon_page(
                [
                    ("工程", [("新建", self.new_project, None), ("打开", self.open_project, None), ("保存", self.save_project, None)]),
                    ("素材", [("导入图片", self.import_image, None)]),
                    ("最近", [("打开最近工程", self._open_first_recent, None)]),
                ]
            ),
            "开始",
        )
        ribbon.addTab(
            self._ribbon_page(
                [
                    ("图纸", [("生成图纸", self.start_generation, None), ("取消生成", self.cancel_generation, None)]),
                    ("图像变换", [("左转 90°", lambda: self.rotate(-90), None), ("右转 90°", lambda: self.rotate(90), None), ("水平翻转", self.flip_horizontal, None), ("垂直翻转", self.flip_vertical, None)]),
                    ("颜色", [("导入色板", self.import_palette, None), ("恢复默认色板", self.restore_default_palette, None)]),
                ]
            ),
            "生成",
        )
        ribbon.addTab(self._build_edit_ribbon_page(), "编辑")
        ribbon.addTab(
            self._ribbon_page(
                [
                    ("缩放", [("适应窗口", self.fit_to_window, None), ("实际大小", self.actual_size, None), ("放大", lambda: self.set_zoom(self.zoom_percent + 10), None), ("缩小", lambda: self.set_zoom(self.zoom_percent - 10), None)]),
                    ("显示", [("显示网格", self.toggle_grid, None), ("显示色号", self.toggle_codes, None)]),
                    ("面板", [("左侧参数", self.toggle_left_panel, None), ("右侧项目", self.toggle_right_panel, None)]),
                ]
            ),
            "视图",
        )
        export_buttons = []
        for format_name in ("PNG", "PDF", "SVG", "CSV"):
            export_buttons.append((f"导出 {format_name}", lambda checked=False, value=format_name.lower(): self.export_format(value), format_name + ".svg"))
        self.export_page = self._ribbon_page([("导出图纸", export_buttons)])
        ribbon.addTab(self.export_page, "导出")
        ribbon.addTab(
            self._ribbon_page([("帮助", [("使用说明", self.show_help, None), ("关于应用", self.show_about, None), ("日志目录", self.show_log_directory, None)])]),
            "帮助",
        )
        ribbon.currentChanged.connect(self._ribbon_changed)
        return ribbon

    def _build_edit_ribbon_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("RibbonPage")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(8)

        tools = QWidget()
        tools.setObjectName("RibbonGroup")
        tools_layout = QVBoxLayout(tools)
        tools_layout.setContentsMargins(8, 0, 8, 0)
        tool_row = QHBoxLayout()
        for action in (self.action_brush, self.action_eraser, self.action_picker):
            button = QToolButton()
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            tool_row.addWidget(button)
        tools_layout.addLayout(tool_row)
        tools_layout.addWidget(self._ribbon_group_label("工具"))
        layout.addWidget(tools)

        color_group = QWidget()
        color_group.setObjectName("RibbonGroup")
        color_layout = QVBoxLayout(color_group)
        color_layout.setContentsMargins(10, 0, 10, 0)
        self.selected_color_label = QLabel("未选择颜色")
        self.selected_color_label.setObjectName("SelectedColor")
        self.selected_color_label.setMinimumWidth(132)
        self.selected_color_label.setAlignment(Qt.AlignCenter)
        color_layout.addWidget(self.selected_color_label)
        color_layout.addWidget(self._ribbon_group_label("当前颜色"))
        layout.addWidget(color_group)

        history = QWidget()
        history.setObjectName("RibbonGroup")
        history_layout = QVBoxLayout(history)
        history_layout.setContentsMargins(8, 0, 8, 0)
        history_row = QHBoxLayout()
        for action in (self.action_undo, self.action_redo):
            button = QToolButton()
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            history_row.addWidget(button)
        history_layout.addLayout(history_row)
        history_layout.addWidget(self._ribbon_group_label("历史"))
        layout.addWidget(history)
        layout.addStretch()
        return page

    @staticmethod
    def _ribbon_group_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setObjectName("RibbonGroupLabel")
        return label

    def _ribbon_page(self, groups: list[tuple[str, list[tuple[str, object, str | None]]]]) -> QWidget:
        page = QWidget()
        page.setObjectName("RibbonPage")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)
        for title, buttons in groups:
            group = QWidget()
            group.setObjectName("RibbonGroup")
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(6, 0, 6, 0)
            button_row = QHBoxLayout()
            for text, callback, icon_name in buttons:
                button = QPushButton(text)
                if icon_name:
                    button.setIcon(QIcon(str(icon_path(icon_name))))
                    button.setIconSize(button.iconSize() * 2)
                button.clicked.connect(lambda checked=False, selected=callback: self._invoke_ribbon(selected))
                button_row.addWidget(button)
            group_layout.addLayout(button_row)
            label = QLabel(title)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("color:#666;font-size:11px")
            group_layout.addWidget(label)
            layout.addWidget(group)
        layout.addStretch()
        return page

    def _build_backstage(self) -> QWidget:
        backstage = QWidget()
        backstage.setObjectName("Backstage")
        layout = QHBoxLayout(backstage)
        layout.setContentsMargins(0, 0, 0, 0)
        navigation = QWidget()
        navigation.setObjectName("BackstageNav")
        navigation.setFixedWidth(220)
        nav_layout = QVBoxLayout(navigation)
        items = [
            ("← 返回图纸", self._return_to_workspace),
            ("新建", self.new_project),
            ("打开", self.open_project),
            ("保存", self.save_project),
            ("另存为", self.save_project_as),
            ("导出 PNG", lambda: self.export_format("png")),
            ("导出 PDF", lambda: self.export_format("pdf")),
            ("导出 SVG", lambda: self.export_format("svg")),
            ("导出 CSV", lambda: self.export_format("csv")),
        ]
        for text, callback in items:
            button = QPushButton(text)
            button.clicked.connect(lambda checked=False, selected=callback: selected())
            nav_layout.addWidget(button)
        nav_layout.addStretch()
        exit_button = QPushButton("退出")
        exit_button.clicked.connect(self.close)
        nav_layout.addWidget(exit_button)
        layout.addWidget(navigation)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(45, 35, 45, 35)
        heading = QLabel("文件")
        heading.setStyleSheet("font-size:30px;font-weight:300")
        content_layout.addWidget(heading)
        card_row = QHBoxLayout()
        for text, callback in (("新建空白工程", self.new_project), ("打开 PBPG 工程", self.open_project)):
            button = QPushButton(text)
            button.setMinimumSize(220, 100)
            button.clicked.connect(callback)
            card_row.addWidget(button)
        card_row.addStretch()
        content_layout.addLayout(card_row)
        content_layout.addWidget(QLabel("最近工程"))
        self.recent_list = QVBoxLayout()
        content_layout.addLayout(self.recent_list)
        content_layout.addStretch()
        layout.addWidget(content, 1)
        return backstage

    def _build_workspace(self) -> QWidget:
        workspace = QWidget()
        layout = QHBoxLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        self.workspace_splitter = QSplitter(Qt.Horizontal)
        self.left_panel = self._build_left_panel()
        self.document_tabs = self._build_document_tabs()
        self.right_panel = self._build_right_panel()
        self.workspace_splitter.addWidget(self.left_panel)
        self.workspace_splitter.addWidget(self.document_tabs)
        self.workspace_splitter.addWidget(self.right_panel)
        self.workspace_splitter.setSizes([300, 900, 340])
        self.workspace_splitter.setStretchFactor(1, 1)
        layout.addWidget(self.workspace_splitter)
        return workspace

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(260)
        panel.setMaximumWidth(460)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 4, 8, 8)
        title = QLabel("生成参数")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        contents = QWidget()
        form_layout = QVBoxLayout(contents)
        self.parameter_widgets: dict[str, QWidget] = {}
        form_layout.addWidget(self._numeric_group())
        form_layout.addWidget(self._matching_group())
        form_layout.addWidget(self._adjustment_group())
        form_layout.addWidget(self._transform_group())
        form_layout.addStretch()
        scroll.setWidget(contents)
        layout.addWidget(scroll, 1)
        self.generate_button = QPushButton("生成图纸")
        self.generate_button.setObjectName("PrimaryButton")
        self.generate_button.clicked.connect(self.start_generation)
        layout.addWidget(self.generate_button)
        self.cancel_button = QPushButton("取消生成")
        self.cancel_button.clicked.connect(self.cancel_generation)
        self.cancel_button.hide()
        layout.addWidget(self.cancel_button)
        return panel

    def _numeric_group(self) -> QGroupBox:
        group = QGroupBox("网格与底板")
        form = QFormLayout(group)
        for key, label, minimum, maximum in (
            ("grid_width", "网格宽度", 1, 500),
            ("grid_height", "网格高度", 1, 500),
            ("board_width", "底板宽度", 1, 100),
            ("board_height", "底板高度", 1, 100),
            ("max_colors", "最大颜色数", 1, 256),
        ):
            widget = QSpinBox()
            widget.setRange(minimum, maximum)
            widget.valueChanged.connect(self._parameter_changed)
            self.parameter_widgets[key] = widget
            form.addRow(label, widget)
        return group

    def _matching_group(self) -> QGroupBox:
        group = QGroupBox("图像适配与颜色")
        form = QFormLayout(group)
        fit = QComboBox()
        fit.addItem("填充裁剪", FitMode.FILL_CROP.value)
        fit.addItem("完整适应", FitMode.CONTAIN.value)
        fit.addItem("拉伸", FitMode.STRETCH.value)
        fit.currentIndexChanged.connect(self._parameter_changed)
        self.parameter_widgets["fit_mode"] = fit
        form.addRow("适配方式", fit)
        algorithm = QComboBox()
        algorithm.addItem("CIEDE2000", "ciede2000")
        self.parameter_widgets["color_distance"] = algorithm
        form.addRow("色差算法", algorithm)
        dither = QComboBox()
        dither.addItem("无抖动", Dithering.NONE.value)
        dither.addItem("Floyd–Steinberg", Dithering.FLOYD_STEINBERG.value)
        dither.currentIndexChanged.connect(self._parameter_changed)
        self.parameter_widgets["dithering"] = dither
        form.addRow("抖动", dither)
        strength = self._double_box(0, 1, 0.05)
        self.parameter_widgets["dither_strength"] = strength
        form.addRow("抖动强度", strength)
        alpha = QSpinBox()
        alpha.setRange(0, 255)
        alpha.valueChanged.connect(self._parameter_changed)
        self.parameter_widgets["alpha_threshold"] = alpha
        form.addRow("透明阈值", alpha)
        return group

    def _adjustment_group(self) -> QGroupBox:
        group = QGroupBox("图像调整")
        form = QFormLayout(group)
        for key, label, minimum, maximum in (
            ("brightness", "亮度", 0.1, 3.0),
            ("contrast", "对比度", 0.1, 3.0),
            ("saturation", "饱和度", 0.0, 3.0),
            ("sharpness", "锐度", 0.0, 5.0),
        ):
            widget = self._double_box(minimum, maximum, 0.1)
            self.parameter_widgets[key] = widget
            form.addRow(label, widget)
        despeckle = QSpinBox()
        despeckle.setRange(0, 8)
        despeckle.valueChanged.connect(self._parameter_changed)
        self.parameter_widgets["despeckle_iterations"] = despeckle
        form.addRow("孤点简化", despeckle)
        return group

    def _double_box(self, minimum: float, maximum: float, step: float) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setSingleStep(step)
        widget.setDecimals(2)
        widget.valueChanged.connect(self._parameter_changed)
        return widget

    def _transform_group(self) -> QGroupBox:
        group = QGroupBox("变换")
        form = QFormLayout(group)
        rotation = QComboBox()
        for value in (0, 90, 180, 270):
            rotation.addItem(f"{value}°", value)
        rotation.currentIndexChanged.connect(self._parameter_changed)
        self.parameter_widgets["rotation"] = rotation
        form.addRow("旋转", rotation)
        for key, label in (("flip_horizontal", "水平翻转"), ("flip_vertical", "垂直翻转")):
            widget = QCheckBox(label)
            widget.toggled.connect(self._parameter_changed)
            self.parameter_widgets[key] = widget
            form.addRow(widget)
        return group

    def _build_document_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName("DocumentTabs")
        tabs.addTab(self._document_page("source"), "原图")
        tabs.addTab(self._document_page("preview"), "圆珠预览")
        tabs.currentChanged.connect(self._document_tab_changed)
        return tabs

    def _document_page(self, kind: str) -> QWidget:
        page = QWidget()
        page.setObjectName("DocumentArea")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        if kind == "preview":
            self.outdated_banner = QLabel("参数已变化，请重新生成")
            self.outdated_banner.setObjectName("OutdatedBanner")
            self.outdated_banner.hide()
            layout.addWidget(self.outdated_banner)
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignCenter)
        if kind == "source":
            label = QLabel("请先导入图片")
            label.setObjectName("DocumentPage")
            label.setAlignment(Qt.AlignCenter)
            label.setMinimumSize(520, 420)
            scroll.setWidget(label)
            self.source_scroll = scroll
            self.source_label = label
        else:
            self.pattern_canvas = PatternCanvas()
            self.pattern_canvas.stroke_committed.connect(self._commit_canvas_edit)
            self.pattern_canvas.color_picked.connect(self._canvas_color_picked)
            self.pattern_canvas.coordinate_hovered.connect(self._canvas_coordinate_hovered)
            self.pattern_canvas.zoom_requested.connect(self.set_zoom)
            scroll.setWidget(self.pattern_canvas)
            self.preview_scroll = scroll
        layout.addWidget(scroll, 1)
        return page

    def _build_right_panel(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setObjectName("SideTabs")
        tabs.setMinimumWidth(300)
        tabs.setMaximumWidth(520)
        tabs.addTab(self._palette_page(), "色板")
        tabs.addTab(self._usage_page(), "用珠")
        tabs.addTab(self._project_info_page(), "项目信息")
        return tabs

    def _palette_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.palette_filter = QLineEdit()
        self.palette_filter.setPlaceholderText("按色号或名称过滤")
        self.palette_filter.textChanged.connect(self._filter_palette)
        layout.addWidget(self.palette_filter)
        self.palette_table = QTableWidget(0, 4)
        self.palette_table.setHorizontalHeaderLabels(["启用/颜色", "色号", "名称", "库存"])
        self.palette_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.palette_table.itemChanged.connect(self._palette_item_changed)
        self.palette_table.cellClicked.connect(self._palette_cell_selected)
        layout.addWidget(self.palette_table, 1)
        buttons = QHBoxLayout()
        for text, callback in (("全选", self.enable_all_colors), ("全不选", self.disable_all_colors), ("恢复默认", self.restore_default_palette)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        return page

    def _usage_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.usage_summary_label = QLabel("总珠数 0 · 使用颜色 0 · 底板 0")
        layout.addWidget(self.usage_summary_label)
        self.usage_table = QTableWidget(0, 5)
        self.usage_table.setHorizontalHeaderLabels(["色号", "名称", "数量", "库存", "缺口"])
        self.usage_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.usage_table.setSortingEnabled(True)
        layout.addWidget(self.usage_table)
        return page

    def _project_info_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.project_title_edit = QLineEdit()
        self.project_title_edit.setMaxLength(120)
        self.project_author_edit = QLineEdit()
        self.project_author_edit.setMaxLength(80)
        self.project_notes_edit = QTextEdit()
        self.project_id_value = QLabel()
        self.project_created_value = QLabel()
        self.project_modified_value = QLabel()
        self.project_title_edit.editingFinished.connect(self._metadata_changed)
        self.project_author_edit.editingFinished.connect(self._metadata_changed)
        self.project_notes_edit.textChanged.connect(self._metadata_changed)
        form.addRow("标题", self.project_title_edit)
        form.addRow("作者", self.project_author_edit)
        form.addRow("备注", self.project_notes_edit)
        form.addRow("工程 ID", self.project_id_value)
        form.addRow("创建时间", self.project_created_value)
        form.addRow("修改时间", self.project_modified_value)
        return page

    def _build_status_bar(self) -> None:
        self.status_message = QLabel("就绪")
        self.statusBar().addWidget(self.status_message, 1)
        self.coordinate_label = QLabel("坐标 —")
        self.grid_status_label = QLabel()
        self.bead_status_label = QLabel("总珠数 0")
        self.task_status_label = QLabel("无后台任务")
        for widget in (self.coordinate_label, self.grid_status_label, self.bead_status_label, self.task_status_label):
            self.statusBar().addPermanentWidget(widget)
        minus = QPushButton("−")
        plus = QPushButton("+")
        minus.clicked.connect(lambda: self.set_zoom(self.zoom_percent - 10))
        plus.clicked.connect(lambda: self.set_zoom(self.zoom_percent + 10))
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 800)
        self.zoom_slider.setFixedWidth(110)
        self.zoom_slider.valueChanged.connect(self.set_zoom)
        self.zoom_label = QLabel("100%")
        self.statusBar().addPermanentWidget(minus)
        self.statusBar().addPermanentWidget(self.zoom_slider)
        self.statusBar().addPermanentWidget(plus)
        self.statusBar().addPermanentWidget(self.zoom_label)

    def _restore_window_state(self) -> None:
        geometry = self.settings.value("window/geometry")
        if isinstance(geometry, QByteArray) and not geometry.isEmpty():
            self.restoreGeometry(geometry)
        else:
            screen = self.screen().availableGeometry()
            width = min(1600, int(screen.width() * 0.85))
            height = min(1000, int(screen.height() * 0.85))
            self.resize(width, height)
            self.move(screen.center() - self.rect().center())
        if not any(screen.availableGeometry().intersects(self.frameGeometry()) for screen in QApplication.screens()):
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(screen.center() - self.rect().center())
        splitter = self.settings.value("window/splitter")
        if isinstance(splitter, QByteArray):
            self.workspace_splitter.restoreState(splitter)
        collapsed = self.settings.value("window/ribbon_collapsed", False, bool)
        if collapsed:
            self.toggle_ribbon()

    def _load_project_into_ui(self) -> None:
        self.loading_controls = True
        generation = self.project.generation
        boards = self.project.boards
        values = {
            "grid_width": generation.grid_width,
            "grid_height": generation.grid_height,
            "board_width": boards.width,
            "board_height": boards.height,
            "max_colors": generation.max_colors,
            "dither_strength": generation.dither_strength,
            "alpha_threshold": generation.alpha_threshold,
            "brightness": generation.brightness,
            "contrast": generation.contrast,
            "saturation": generation.saturation,
            "sharpness": generation.sharpness,
            "despeckle_iterations": generation.despeckle_iterations,
        }
        for key, value in values.items():
            self.parameter_widgets[key].setValue(value)
        for key, value in (
            ("fit_mode", generation.fit_mode.value),
            ("dithering", generation.dithering.value),
            ("rotation", generation.rotation),
        ):
            widget = self.parameter_widgets[key]
            widget.setCurrentIndex(widget.findData(value))
        self.parameter_widgets["flip_horizontal"].setChecked(generation.flip_horizontal)
        self.parameter_widgets["flip_vertical"].setChecked(generation.flip_vertical)
        self.project_title_edit.setText(self.project.metadata.title)
        self.project_author_edit.setText(self.project.metadata.author)
        self.project_notes_edit.setPlainText(self.project.metadata.notes)
        self.project_id_value.setText(self.project.id)
        self.project_created_value.setText(self.project.metadata.created_at)
        self.project_modified_value.setText(self.project.metadata.modified_at)
        self.action_grid.setChecked(self.project.view.show_grid)
        self.action_codes.setChecked(self.project.view.show_codes)
        self.zoom_percent = self.project.view.zoom_percent
        self.loading_controls = False
        self._populate_palette()
        self._reset_edit_session()
        self._refresh_images()
        self._refresh_usage()
        self._refresh_state()
        self._refresh_recent_list()
        self.document_tabs.setCurrentIndex(0 if self.project.view.active_tab == "source" else 1)
        self.left_panel.setVisible(self.project.view.left_panel_visible)
        self.right_panel.setVisible(self.project.view.right_panel_visible)

    def _parameter_changed(self) -> None:
        if self.loading_controls:
            return
        generation = self.project.generation
        generation.grid_width = self.parameter_widgets["grid_width"].value()
        generation.grid_height = self.parameter_widgets["grid_height"].value()
        generation.max_colors = self.parameter_widgets["max_colors"].value()
        generation.fit_mode = FitMode(self.parameter_widgets["fit_mode"].currentData())
        generation.dithering = Dithering(self.parameter_widgets["dithering"].currentData())
        generation.dither_strength = self.parameter_widgets["dither_strength"].value()
        generation.alpha_threshold = self.parameter_widgets["alpha_threshold"].value()
        generation.brightness = self.parameter_widgets["brightness"].value()
        generation.contrast = self.parameter_widgets["contrast"].value()
        generation.saturation = self.parameter_widgets["saturation"].value()
        generation.sharpness = self.parameter_widgets["sharpness"].value()
        generation.despeckle_iterations = self.parameter_widgets["despeckle_iterations"].value()
        generation.rotation = self.parameter_widgets["rotation"].currentData()
        generation.flip_horizontal = self.parameter_widgets["flip_horizontal"].isChecked()
        generation.flip_vertical = self.parameter_widgets["flip_vertical"].isChecked()
        self.project.boards.width = self.parameter_widgets["board_width"].value()
        self.project.boards.height = self.parameter_widgets["board_height"].value()
        self.project.touch(pattern_outdated=True)
        self.cancel_generation()
        self._refresh_state()

    def _metadata_changed(self) -> None:
        if self.loading_controls:
            return
        self.project.metadata.title = self.project_title_edit.text().strip() or "未命名图纸"
        self.project.metadata.author = self.project_author_edit.text().strip()
        self.project.metadata.notes = self.project_notes_edit.toPlainText()[:4000]
        self.project.touch()
        self._refresh_state()

    def _populate_palette(self) -> None:
        self.loading_controls = True
        self.palette_table.setRowCount(len(self.project.palette.colors))
        for row, color in enumerate(self.project.palette.colors):
            swatch = QTableWidgetItem(color.hex)
            swatch.setData(Qt.UserRole, color.code)
            swatch.setCheckState(Qt.Checked if color.enabled else Qt.Unchecked)
            swatch.setBackground(QColor(color.hex))
            swatch.setForeground(QColor("#111111" if sum(color.rgb) > 400 else "#FFFFFF"))
            self.palette_table.setItem(row, 0, swatch)
            self.palette_table.setItem(row, 1, QTableWidgetItem(color.code))
            self.palette_table.setItem(row, 2, QTableWidgetItem(color.name))
            self.palette_table.setItem(row, 3, QTableWidgetItem("" if color.stock is None else str(color.stock)))
        self.loading_controls = False
        self._filter_palette(self.palette_filter.text())
        available_codes = {color.code.casefold() for color in self.project.palette.colors}
        if self.current_palette_code is None or self.current_palette_code.casefold() not in available_codes:
            self.current_palette_code = self.project.palette.colors[0].code
        self._select_palette_code(self.current_palette_code)
        self._update_selected_color()

    def _palette_cell_selected(self, row: int, _column: int) -> None:
        if not 0 <= row < len(self.project.palette.colors):
            return
        self.current_palette_code = self.project.palette.colors[row].code
        self._update_selected_color()

    def _select_palette_code(self, code: str) -> None:
        folded = code.casefold()
        for row, color in enumerate(self.project.palette.colors):
            if color.code.casefold() == folded:
                self.palette_table.selectRow(row)
                return

    def _update_selected_color(self) -> None:
        if not self.current_palette_code:
            self.selected_color_label.setText("未选择颜色")
            self.selected_color_label.setStyleSheet("")
            self.pattern_canvas.set_selected_color(None)
            return
        try:
            color = self.project.palette.color_by_code(self.current_palette_code)
        except KeyError:
            self.current_palette_code = None
            self._update_selected_color()
            return
        red, green, blue = color.rgb
        foreground = "#111111" if red + green + blue > 400 else "#FFFFFF"
        self.selected_color_label.setText(f"{color.code}  {color.name}")
        self.selected_color_label.setStyleSheet(
            f"background:{color.hex};color:{foreground};border:1px solid #B8BEC7;border-radius:4px;padding:7px 10px;font-weight:600"
        )
        self.pattern_canvas.set_selected_color(color.code)

    def _palette_item_changed(self, item: QTableWidgetItem) -> None:
        if self.loading_controls:
            return
        row = item.row()
        color = self.project.palette.colors[row]
        if item.column() == 0:
            enabled = item.checkState() == Qt.Checked
            if not enabled and sum(value.enabled for value in self.project.palette.colors) == 1:
                self.loading_controls = True
                item.setCheckState(Qt.Checked)
                self.loading_controls = False
                self._status("至少需要启用一个颜色")
                return
            color.enabled = enabled
        elif item.column() == 3:
            text = item.text().strip()
            try:
                stock = int(text) if text else None
                if stock is not None and stock < 0:
                    raise ValueError
                color.stock = stock
            except ValueError:
                self.loading_controls = True
                item.setText("" if color.stock is None else str(color.stock))
                self.loading_controls = False
                self._error("库存必须是非负整数")
                return
        else:
            return
        self.project.touch(pattern_outdated=item.column() == 0)
        if item.column() == 0:
            self.cancel_generation()
        self._refresh_usage()
        self._refresh_state()

    def _filter_palette(self, text: str) -> None:
        query = text.strip().casefold()
        for row, color in enumerate(self.project.palette.colors):
            self.palette_table.setRowHidden(row, query not in color.code.casefold() and query not in color.name.casefold())

    def enable_all_colors(self) -> None:
        for color in self.project.palette.colors:
            color.enabled = True
        self.project.touch(pattern_outdated=True)
        self._populate_palette()
        self._refresh_state()

    def disable_all_colors(self) -> None:
        for index, color in enumerate(self.project.palette.colors):
            color.enabled = index == 0
        self.project.touch(pattern_outdated=True)
        self._populate_palette()
        self._status("已保留第一个颜色启用")
        self._refresh_state()

    def restore_default_palette(self) -> None:
        if self.project.grid is not None and QMessageBox.question(self, "恢复默认色板", "恢复色板会使当前图纸过期，是否继续？") != QMessageBox.Yes:
            return
        self.project.set_palette(load_default_palette())
        self._populate_palette()
        self._refresh_state()

    def import_palette(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入色板", "", "色板 (*.json *.csv)")
        if not path:
            return
        try:
            palette = load_palette(path)
        except (OSError, PaletteFormatError) as error:
            self._error(str(error))
            return
        if self.project.grid is not None and QMessageBox.question(self, "导入色板", "导入色板会使当前图纸过期，是否继续？") != QMessageBox.Yes:
            return
        self.project.set_palette(palette)
        self._populate_palette()
        self._refresh_state()

    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        self.cancel_generation()
        self.project = Project.new(load_default_palette())
        self._load_project_into_ui()
        self._return_to_workspace()
        self._status("已新建工程")

    def open_project(self, path: str | None = None) -> None:
        if not self._confirm_discard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "打开工程", "", "拼豆工程 (*.pbpg)")
        if not path:
            return
        try:
            project = load_project(path)
        except (OSError, ProjectFormatError) as error:
            self._error(f"无法打开工程：{error}")
            return
        self.cancel_generation()
        self.project = project
        self._remember_recent(Path(path))
        self._load_project_into_ui()
        self._return_to_workspace()
        self._status(f"已打开 {path}")

    def save_project(self) -> bool:
        if self.project.path is None:
            return self.save_project_as()
        return self._save_to(self.project.path)

    def save_project_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "保存工程", self.project.metadata.title + ".pbpg", "拼豆工程 (*.pbpg)")
        if not path:
            return False
        return self._save_to(Path(path))

    def _save_to(self, path: Path) -> bool:
        old_recovery = self.recovery_store.path_for(self.project)
        try:
            saved = save_project(self.project, path)
        except ProjectSaveError as error:
            detail = f"\n临时文件：{error.temporary_path}" if error.temporary_path else ""
            self._error(f"保存失败：{error}{detail}")
            return False
        if old_recovery.exists():
            old_recovery.unlink()
        formal_recovery = self.recovery_store.path_for(self.project)
        if formal_recovery.exists():
            formal_recovery.unlink()
        self._remember_recent(saved)
        self._refresh_state()
        self._status(f"已保存 {saved}")
        return True

    def import_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入图片", "", "图片 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        try:
            source = import_source(path)
        except (OSError, ImageImportError) as error:
            self._error(str(error))
            return
        self.cancel_generation()
        self.project.set_source(source)
        self._load_project_into_ui()
        self.document_tabs.setCurrentIndex(0)
        self._status(f"已导入 {path}")

    def start_generation(self) -> None:
        if self.project.source is None:
            self._status("请先导入图片")
            return
        if (
            self.project.grid is not None
            and self.project.grid.manually_edited
            and QMessageBox.question(
                self,
                "覆盖手动编辑",
                "重新生成会覆盖当前所有手动编辑，是否继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            self._status("已保留手动编辑")
            return
        self.cancel_generation()
        enabled_count = len(self.project.palette.enabled_colors)
        if self.project.generation.max_colors > enabled_count:
            self.project.generation.max_colors = enabled_count
            self.parameter_widgets["max_colors"].setValue(enabled_count)
            self._status("最大颜色数已调整为启用颜色数")
        self.generation_task_id += 1
        task_id = self.generation_task_id
        source = copy.deepcopy(self.project.source)
        settings = copy.deepcopy(self.project.generation)
        palette = copy.deepcopy(self.project.palette)
        fingerprint = self.project.input_fingerprint()

        def operation(cancel_event, progress):
            grid = generate_pattern(source, settings, palette, input_fingerprint=fingerprint, cancel_event=cancel_event, progress=progress)
            preview = render_preview_png(grid, palette)
            return task_id, fingerprint, grid, preview

        worker = BackgroundWorker(operation)
        worker.signals.progress.connect(lambda value, text, selected=task_id: self._generation_progress(selected, value, text))
        worker.signals.completed.connect(self._generation_completed)
        worker.signals.failed.connect(lambda detail, selected=task_id: self._generation_failed(selected, detail))
        worker.signals.cancelled.connect(lambda selected=task_id: self._generation_cancelled(selected))
        self.current_worker = worker
        self.generate_button.hide()
        self.cancel_button.show()
        self.task_status_label.setText("正在生成")
        self._refresh_state()
        self._status("正在后台生成图纸")
        self.thread_pool.start(worker)

    def cancel_generation(self) -> None:
        if self.current_worker is not None:
            self.current_worker.cancel()
            self.current_worker = None
            self.generation_task_id += 1
            self.task_status_label.setText("正在取消")

    def _generation_progress(self, task_id: int, value: int, text: str) -> None:
        if task_id != self.generation_task_id:
            return
        self.task_status_label.setText(f"{value}% {text}")

    def _generation_completed(self, result: object) -> None:
        task_id, fingerprint, grid, preview = result
        if task_id != self.generation_task_id or fingerprint != self.project.input_fingerprint():
            return
        self.current_worker = None
        self.project.set_grid(grid, preview)
        self._reset_edit_session()
        self.generate_button.show()
        self.cancel_button.hide()
        self.task_status_label.setText("无后台任务")
        self._refresh_images()
        self._refresh_usage()
        self._refresh_state()
        self.document_tabs.setCurrentIndex(1)
        self._status("图纸生成完成")

    def _generation_failed(self, task_id: int, detail: str) -> None:
        if task_id != self.generation_task_id:
            return
        self.current_worker = None
        self.generate_button.show()
        self.cancel_button.hide()
        self.task_status_label.setText("生成失败")
        self._refresh_state()
        self._error("生成图纸失败", detail)

    def _generation_cancelled(self, task_id: int) -> None:
        if task_id != self.generation_task_id:
            return
        self.generate_button.show()
        self.cancel_button.hide()
        self.task_status_label.setText("无后台任务")
        self._refresh_state()
        self._status("生成已取消")

    def _refresh_images(self) -> None:
        self.source_pixmap = QPixmap()
        if self.project.source is not None:
            image = decode_source(self.project.source)
            output = io.BytesIO()
            image.save(output, "PNG")
            self.source_pixmap.loadFromData(output.getvalue())
        self._update_document_pixmaps()

    def _update_document_pixmaps(self) -> None:
        if self.source_pixmap.isNull():
            self.source_label.setPixmap(QPixmap())
            self.source_label.setText("请先导入图片")
            self.source_label.setMinimumSize(520, 420)
            self.source_label.setMaximumSize(16_777_215, 16_777_215)
            return
        self.source_label.setText("")
        scaled = self.source_pixmap.scaled(
            max(1, int(self.source_pixmap.width() * self.zoom_percent / 100)),
            max(1, int(self.source_pixmap.height() * self.zoom_percent / 100)),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.source_label.setPixmap(scaled)
        self.source_label.setFixedSize(scaled.size())

    def _reset_edit_session(self) -> None:
        self.edit_session = PatternEditSession(self.project.grid) if self.project.grid is not None else None
        self.pattern_canvas.set_pattern(self.edit_session, self.project.palette)
        self.pattern_canvas.set_zoom(self.zoom_percent)
        self.pattern_canvas.set_display_options(
            show_grid=self.project.view.show_grid,
            show_codes=self.project.view.show_codes,
        )
        self.pattern_canvas.set_tool(self._current_edit_tool())
        self.pattern_canvas.set_selected_color(self.current_palette_code)

    def _current_edit_tool(self) -> EditTool:
        if self.action_eraser.isChecked():
            return EditTool.ERASER
        if self.action_picker.isChecked():
            return EditTool.PICKER
        return EditTool.BRUSH

    def set_edit_tool(self, tool: EditTool) -> None:
        actions = {
            EditTool.BRUSH: self.action_brush,
            EditTool.ERASER: self.action_eraser,
            EditTool.PICKER: self.action_picker,
        }
        actions[tool].setChecked(True)
        self.pattern_canvas.set_tool(tool)
        names = {EditTool.BRUSH: "画笔", EditTool.ERASER: "橡皮", EditTool.PICKER: "取色器"}
        self._status(f"当前工具：{names[tool]}")

    def _commit_canvas_edit(self) -> None:
        if self.edit_session is None:
            return
        self.project.apply_manual_edit(self.edit_session.to_grid())
        self.pattern_canvas.update()
        self._refresh_usage()
        self._refresh_state()
        self._status("已应用手动编辑")

    def undo_edit(self) -> None:
        if self.edit_session is None or not self.edit_session.undo():
            return
        self.project.apply_manual_edit(self.edit_session.to_grid())
        self.pattern_canvas.update()
        self._refresh_usage()
        self._refresh_state()
        self._status("已撤销一笔")

    def redo_edit(self) -> None:
        if self.edit_session is None or not self.edit_session.redo():
            return
        self.project.apply_manual_edit(self.edit_session.to_grid())
        self.pattern_canvas.update()
        self._refresh_usage()
        self._refresh_state()
        self._status("已重做一笔")

    def _canvas_color_picked(self, code: str) -> None:
        if not code:
            self.set_edit_tool(EditTool.ERASER)
            self._status("已取样透明格，切换到橡皮")
            return
        self.current_palette_code = code
        self._select_palette_code(code)
        self._update_selected_color()
        self.set_edit_tool(EditTool.BRUSH)
        self._status(f"已选择颜色 {code}")

    def _canvas_coordinate_hovered(self, row: int, column: int) -> None:
        if row < 0 or column < 0:
            self.coordinate_label.setText("坐标 —")
            return
        self.coordinate_label.setText(f"行 {row + 1} · 列 {column + 1}")

    def _refresh_usage(self) -> None:
        usage = self.project.usage_summary()
        self.usage_summary_label.setText(f"总珠数 {usage.total_beads} · 使用颜色 {usage.used_colors} · 底板 {usage.board_count}")
        self.usage_table.setSortingEnabled(False)
        self.usage_table.setRowCount(len(usage.items))
        for row, item in enumerate(usage.items):
            values = (item.code, item.name, str(item.quantity), "未设置" if item.stock is None else str(item.stock), "未设置" if item.shortage is None else str(item.shortage))
            for column, value in enumerate(values):
                self.usage_table.setItem(row, column, QTableWidgetItem(value))
        self.usage_table.setSortingEnabled(True)

    def _refresh_state(self) -> None:
        self.project_title_label.setText(self.project.metadata.title + (" *" if self.project.dirty else ""))
        self.save_state_label.setText("未保存" if self.project.dirty or self.project.path is None else "已保存")
        self.project_modified_value.setText(self.project.metadata.modified_at)
        self.grid_status_label.setText(f"网格 {self.project.generation.grid_width}×{self.project.generation.grid_height}")
        self.bead_status_label.setText(f"总珠数 {self.project.usage_summary().total_beads}")
        self.generate_button.setEnabled(self.project.source is not None)
        self.outdated_banner.setVisible(self.project.generation.result_state is ResultState.OUTDATED)
        valid = self.project.grid is not None and self.project.generation.result_state is ResultState.CURRENT
        editing_enabled = valid and self.current_worker is None
        self.export_page.setEnabled(valid and self.current_worker is None)
        self.pattern_canvas.set_interaction_enabled(editing_enabled)
        for action in (self.action_brush, self.action_eraser, self.action_picker):
            action.setEnabled(editing_enabled)
        self.action_undo.setEnabled(editing_enabled and self.edit_session is not None and self.edit_session.can_undo)
        self.action_redo.setEnabled(editing_enabled and self.edit_session is not None and self.edit_session.can_redo)
        self.action_generate.setEnabled(self.project.source is not None and self.current_worker is None)
        self.action_cancel.setEnabled(self.current_worker is not None)
        self.action_grid.setChecked(self.project.view.show_grid)
        self.action_codes.setChecked(self.project.view.show_codes)
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(self.zoom_percent)
        self.zoom_slider.blockSignals(False)
        self.zoom_label.setText(f"{self.zoom_percent}%")

    def rotate(self, degrees: int) -> None:
        self.project.generation.rotation = (self.project.generation.rotation + degrees) % 360
        self.parameter_widgets["rotation"].setCurrentIndex(self.parameter_widgets["rotation"].findData(self.project.generation.rotation))

    def flip_horizontal(self) -> None:
        widget = self.parameter_widgets["flip_horizontal"]
        widget.setChecked(not widget.isChecked())

    def flip_vertical(self) -> None:
        widget = self.parameter_widgets["flip_vertical"]
        widget.setChecked(not widget.isChecked())

    def toggle_grid(self) -> None:
        if self.loading_controls:
            return
        self.project.view.show_grid = not self.project.view.show_grid
        self.project.touch()
        self.action_grid.setChecked(self.project.view.show_grid)
        self._refresh_canvas_display()

    def toggle_codes(self) -> None:
        if self.loading_controls:
            return
        self.project.view.show_codes = not self.project.view.show_codes
        self.project.touch()
        self.action_codes.setChecked(self.project.view.show_codes)
        self._refresh_canvas_display()

    def _refresh_canvas_display(self) -> None:
        self.project.preview_png = None
        self.pattern_canvas.set_display_options(
            show_grid=self.project.view.show_grid,
            show_codes=self.project.view.show_codes,
        )
        self._refresh_state()

    def set_zoom(self, value: int) -> None:
        self.zoom_percent = max(10, min(800, int(value)))
        self.project.view.zoom_percent = self.zoom_percent
        self._update_document_pixmaps()
        self.pattern_canvas.set_zoom(self.zoom_percent)
        self._refresh_state()

    def actual_size(self) -> None:
        self.set_zoom(100)

    def fit_to_window(self) -> None:
        scroll = self.source_scroll if self.document_tabs.currentIndex() == 0 else self.preview_scroll
        viewport = scroll.viewport().size()
        if self.document_tabs.currentIndex() == 0:
            if self.source_pixmap.isNull():
                return
            content_width = self.source_pixmap.width()
            content_height = self.source_pixmap.height()
        else:
            if self.edit_session is None:
                return
            content_width = self.edit_session.width * PatternCanvas.BASE_CELL_SIZE
            content_height = self.edit_session.height * PatternCanvas.BASE_CELL_SIZE
        ratio = min(viewport.width() / content_width, viewport.height() / content_height)
        self.set_zoom(int(max(10, min(800, ratio * 100))))

    def toggle_left_panel(self) -> None:
        self.left_panel.setVisible(not self.left_panel.isVisible())
        self.project.view.left_panel_visible = self.left_panel.isVisible()

    def toggle_right_panel(self) -> None:
        self.right_panel.setVisible(not self.right_panel.isVisible())
        self.project.view.right_panel_visible = self.right_panel.isVisible()

    def toggle_ribbon(self) -> None:
        self.ribbon_collapsed = not self.ribbon_collapsed
        self.ribbon.setMaximumHeight(34 if self.ribbon_collapsed else 128)
        self.collapse_ribbon_button.setText("展开功能区" if self.ribbon_collapsed else "收起功能区")

    def _invoke_ribbon(self, callback) -> None:
        callback()
        if self.ribbon_collapsed:
            self.ribbon.setMaximumHeight(34)

    def _ribbon_changed(self, index: int) -> None:
        if self.ribbon_collapsed and index != 0:
            self.ribbon.setMaximumHeight(128)
        self.content_stack.setCurrentIndex(0 if index == 0 else 1)
        if index == 0:
            self._refresh_recent_list()

    def _document_tab_changed(self, index: int) -> None:
        self.project.view.active_tab = "source" if index == 0 else "preview"

    def _return_to_workspace(self) -> None:
        self.ribbon.setCurrentIndex(1)
        self.content_stack.setCurrentIndex(1)

    def export_format(self, format_id: str) -> None:
        if self.project.grid is None or self.project.generation.result_state is not ResultState.CURRENT:
            self._status("请先生成最新图纸")
            return
        try:
            from perler_pattern.infrastructure.exporters import export_project
            extension = format_id.lower()
            path, _ = QFileDialog.getSaveFileName(self, f"导出 {extension.upper()}", f"{self.project.metadata.title}.{extension}", f"{extension.upper()} (*.{extension})")
            if not path:
                return
            export_project(self.project, extension, Path(path))
            self._status(f"已导出 {path}")
        except Exception as error:
            self._error(f"导出失败：{error}")

    def _autosave(self) -> None:
        if not self.project.dirty or self.current_worker is not None:
            return
        self.save_state_label.setText("正在自动保存…")
        try:
            self.recovery_store.save(self.project)
            self.autosave_failure_count = 0
            self.autosave_timer.setInterval(60_000)
            self.save_state_label.setText("已自动保存")
        except OSError as error:
            self.autosave_failure_count += 1
            delays = (30_000, 60_000, 120_000)
            self.autosave_timer.setInterval(delays[min(self.autosave_failure_count - 1, 2)])
            self.save_state_label.setText("保存失败")
            self._status(f"自动保存失败：{error}")

    def _offer_recovery(self) -> None:
        recent = [Path(value) for value in self.settings.value("recent/projects", [], list)]
        sidecars = tuple(path.parent / f".{path.name}.autosave.pbpg" for path in recent if (path.parent / f".{path.name}.autosave.pbpg").exists())
        candidates, _invalid = self.recovery_store.scan(sidecars)
        if not candidates:
            return
        candidate = candidates[0]
        box = QMessageBox(self)
        box.setWindowTitle("发现自动恢复副本")
        box.setText(f"发现“{candidate.title}”的自动恢复副本。")
        restore = box.addButton("恢复", QMessageBox.AcceptRole)
        ignore = box.addButton("忽略", QMessageBox.RejectRole)
        delete = box.addButton("删除副本", QMessageBox.DestructiveRole)
        box.exec()
        if box.clickedButton() is restore:
            project = load_project(candidate.path)
            project.path = candidate.recovery_for
            project.dirty = True
            self.project = project
            self._load_project_into_ui()
        elif box.clickedButton() is delete:
            candidate.path.unlink()
        else:
            _ = ignore

    def _confirm_discard(self) -> bool:
        if not self.project.dirty:
            return True
        result = QMessageBox.warning(self, "未保存修改", "当前工程有未保存修改。", QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if result == QMessageBox.Save:
            return self.save_project()
        return result == QMessageBox.Discard

    def _remember_recent(self, path: Path) -> None:
        resolved = str(path.resolve())
        recent = [value for value in self.settings.value("recent/projects", [], list) if value != resolved]
        self.settings.setValue("recent/projects", [resolved, *recent][:10])
        self._refresh_recent_list()

    def _refresh_recent_list(self) -> None:
        while self.recent_list.count():
            item = self.recent_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for value in self.settings.value("recent/projects", [], list):
            path = Path(value)
            text = str(path) if path.exists() else f"{path}（文件已移动）"
            button = QPushButton(text)
            button.setEnabled(path.exists())
            button.clicked.connect(lambda checked=False, selected=str(path): self.open_project(selected))
            self.recent_list.addWidget(button)

    def _open_first_recent(self) -> None:
        recent = self.settings.value("recent/projects", [], list)
        if recent and Path(recent[0]).exists():
            self.open_project(recent[0])
        else:
            self.open_project()

    def show_help(self) -> None:
        QMessageBox.information(
            self,
            "使用说明",
            "1. 导入图片并调整参数\n2. 生成图纸\n3. 在编辑页使用画笔、橡皮或取色器\n4. 保存工程或导出制作文件",
        )

    def show_about(self) -> None:
        QMessageBox.about(self, "关于", "拼豆图纸生成器 2.0.0\n完全离线的 Windows 桌面应用")

    def show_log_directory(self) -> None:
        QMessageBox.information(self, "日志目录", str(self.data_directory / "logs"))

    def _status(self, text: str) -> None:
        self.status_message.setText(text)
        self.statusBar().showMessage(text, 6000)

    def _error(self, text: str, detail: str = "") -> None:
        logging.getLogger(__name__).error("%s%s", text, f"\n{detail}" if detail else "")
        box = QMessageBox(QMessageBox.Critical, "错误", text, parent=self)
        if detail:
            box.setDetailedText(detail)
        box.exec()
        self.status_message.setText(text)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        self.cancel_generation()
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/splitter", self.workspace_splitter.saveState())
        self.settings.setValue("window/ribbon_collapsed", self.ribbon_collapsed)
        self.settings.sync()
        event.accept()
