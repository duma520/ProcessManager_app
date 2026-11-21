__version__ = "3.5.0"
__build_date__ = "2026-08-20"

import sys
import psutil
import ctypes
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                               QListWidget, QTabWidget, QPushButton, QLabel, QMenu, 
                               QSplitter, QCheckBox, QTextEdit, QScrollArea, QMessageBox, 
                               QListWidgetItem, QComboBox, QTableWidget, QTableWidgetItem, 
                               QHeaderView, QProgressBar)
from PySide6.QtCore import Qt, QTimer, QCoreApplication, Signal, QSettings, QThread, QObject
from PySide6.QtGui import QFont, QTextCursor, QColor, QIcon, QAction

# Windows API常量
PROCESS_ALL_ACCESS = 0x1F0FFF


class ProcessRefreshWorker(QObject):
    """后台线程：获取进程列表数据，避免阻塞UI"""
    progress = Signal(int, str)          # 进度值, 进度文本
    finished = Signal(object)            # 进程数据列表 (list of dict)
    error = Signal(str)                  # 错误信息

    def __init__(self, show_hidden=False, hidden_processes=None):
        super().__init__()
        self._show_hidden = show_hidden
        self._hidden_processes = hidden_processes or {}

    def run(self):
        """在工作线程中执行进程枚举"""
        try:
            # 阶段1：获取窗口标题
            self.progress.emit(5, "正在获取窗口标题...")
            all_window_titles = self._get_all_window_titles()

            # 阶段2：枚举进程
            self.progress.emit(15, "正在枚举进程...")
            processes = list(psutil.process_iter(['pid', 'name']))
            total = len(processes)

            if total == 0:
                self.progress.emit(100, "无进程数据")
                self.finished.emit([])
                return

            # 阶段3：构建进程数据
            process_data = []
            for idx, proc in enumerate(processes):
                try:
                    pid = proc.info['pid']
                    name = proc.info['name']

                    is_hidden = pid in self._hidden_processes and self._hidden_processes[pid]
                    if not self._show_hidden and is_hidden:
                        continue

                    window_titles = all_window_titles.get(pid, [])
                    title_info = ', '.join(window_titles) if window_titles else ""

                    process_data.append({
                        'pid': pid,
                        'name': name,
                        'is_hidden': is_hidden,
                        'title': title_info
                    })

                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

                # 更新进度（15%~90%）
                progress = 15 + int((idx + 1) / total * 75)
                if progress % 5 == 0 or idx == total - 1:
                    self.progress.emit(progress, f"正在加载进程 {idx + 1}/{total}...")

            self.progress.emit(100, f"刷新完成（共 {len(process_data)} 个进程）")
            self.finished.emit(process_data)

        except Exception as e:
            self.error.emit(str(e))

    def _get_all_window_titles(self):
        """在工作线程中获取所有窗口标题"""
        pid_titles = {}
        try:
            def callback(hwnd, lparam):
                window_pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                pid = window_pid.value
                if pid:
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                        title = buff.value
                        if title:
                            if pid not in pid_titles:
                                pid_titles[pid] = []
                            pid_titles[pid].append(title)
                return True

            ctypes.windll.user32.EnumWindows(
                ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))(callback), 0)
        except Exception:
            pass
        return pid_titles


class KillHiddenWorker(QObject):
    """后台线程：批量结束隐藏进程"""
    progress = Signal(int, str)
    finished = Signal(object)            # 成功结束的数量 (int)
    log_message = Signal(object)         # 日志消息 (str, bool) 元组

    def __init__(self, hidden_pids):
        super().__init__()
        self._hidden_pids = list(hidden_pids)

    def run(self):
        killed = 0
        total = len(self._hidden_pids)
        for idx, pid in enumerate(self._hidden_pids):
            try:
                proc = psutil.Process(pid)
                name = proc.name()
                proc.terminate()
                killed += 1
                self.log_message.emit((f"已结束隐藏进程: {name} (PID: {pid})", False))
            except Exception as e:
                self.log_message.emit((f"结束隐藏进程失败(PID: {pid}): {str(e)}", True))
            
            progress = int((idx + 1) / total * 100)
            self.progress.emit(progress, f"正在结束隐藏进程 {idx + 1}/{total}...")

        self.progress.emit(100, f"已成功结束 {killed} 个隐藏进程")
        self.finished.emit(killed)


class ProcessInfoWorker(QObject):
    """后台线程：获取单个进程详细信息"""
    finished = Signal(object)            # (pid, details) 元组
    error = Signal(str)

    def __init__(self, pid):
        super().__init__()
        self._pid = pid

    def run(self):
        from datetime import datetime
        try:
            proc = psutil.Process(self._pid)
            with proc.oneshot():
                cpu_percent = proc.cpu_percent(interval=0.1)
                mem_info = proc.memory_info()
                threads = proc.num_threads()

                details = (
                    f"===== 进程详细信息 =====\n"
                    f"进程名称: {proc.name()}\n"
                    f"进程ID: {self._pid}\n"
                    f"状态: {proc.status()}\n"
                    f"创建时间: {datetime.fromtimestamp(proc.create_time()).strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"CPU使用率: {cpu_percent}%\n"
                    f"内存使用(RSS): {mem_info.rss / 1024 / 1024:.2f} MB\n"
                    f"内存使用(VMS): {mem_info.vms / 1024 / 1024:.2f} MB\n"
                    f"线程数: {threads}\n"
                    f"执行路径: {proc.exe() or 'N/A'}\n"
                    f"命令行: {' '.join(proc.cmdline()) if proc.cmdline() else 'N/A'}\n"
                    f"用户名: {proc.username()}\n"
                    f"工作目录: {proc.cwd() or 'N/A'}\n"
                )
            self.finished.emit((self._pid, details))
        except Exception as e:
            self.error.emit(str(e))

class ProcessManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"进程管理工具 v{__version__} (Build {__build_date__})")
        self.resize(500, 700)

        # 设置程序图标
        self.setWindowIcon(QIcon('icon.ico'))

        # 添加全局样式表
        self.setStyleSheet("""
            QWidget {
                font-size: 9pt;
            }
            QTextEdit, QComboBox {
                border: 1px solid #ccc;
                border-radius: 3px;
            }
        """)
        
        # 初始化隐藏进程字典
        self.hidden_processes = {}

        # 排序控制变量
        self.current_sort_column = 0
        self.sort_order = Qt.AscendingOrder
        self.sort_methods = {
            0: self.sort_by_pid,
            1: self.sort_by_name,
            2: self.sort_by_title
        }

        # 设置实时自动保存（500ms 防抖单次定时器，变更即写盘）
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.timeout.connect(self._save_settings_now)
        self._loading_settings = False

        # 主窗口布局
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QHBoxLayout(self.main_widget)
        
        # 创建分割器
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_layout.addWidget(self.splitter)
        
        # 上部区域 - 进程列表和控制按钮
        self.top_container = QWidget()
        self.top_layout = QVBoxLayout(self.top_container)
        
        # 添加展开/收起按钮到列表上方
        self.toggle_button = QPushButton("▼ 展开控制面板")
        self.toggle_button.clicked.connect(self.toggle_control_panel)
        self.top_layout.addWidget(self.toggle_button)
        
        # 添加搜索框
        self.search_container = QWidget()
        self.search_layout = QHBoxLayout(self.search_container)
        self.search_layout.setContentsMargins(0, 0, 0, 0)
        self.search_layout.setSpacing(5)
        self.search_input = QTextEdit()
        self.search_input.setMaximumHeight(28)
        self.search_input.setPlaceholderText("输入进程名/窗口标题/拼音首字母搜索...")
        self.search_input.textChanged.connect(self.filter_process_list)
        self.search_input.setStyleSheet("QTextEdit { padding: 1px; }")
        self.search_layout.addWidget(self.search_input)
        
        # 添加搜索选项
        self.search_options = QComboBox()
        self.search_options.setMaximumHeight(28)
        self.search_options.addItems(["模糊搜索", "精确匹配"])
        self.search_options.currentIndexChanged.connect(self.filter_process_list)
        self.search_layout.addWidget(self.search_options)
        
        self.search_container.setMaximumHeight(30)
        self.top_layout.addWidget(self.search_container)
        self.top_layout.setSpacing(5)

        # 全局进度条（始终可见，不受控制面板展开/收起影响）
        self.global_progress_bar = QProgressBar()
        self.global_progress_bar.setRange(0, 100)
        self.global_progress_bar.setValue(0)
        self.global_progress_bar.setTextVisible(True)
        self.global_progress_bar.setFormat("就绪")
        self.global_progress_bar.setMaximumHeight(20)
        self.top_layout.addWidget(self.global_progress_bar)

        # 进程列表 - 表格形式
        self.process_list = QTableWidget()
        self.process_list.setFont(QFont("Microsoft YaHei", 10))
        self.process_list.setColumnCount(3)
        self.process_list.setHorizontalHeaderLabels(["PID", "进程名", "窗口标题"])
        self.process_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.process_list.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.process_list.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.process_list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.process_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.process_list.customContextMenuRequested.connect(self.show_context_menu)
        self.process_list.itemClicked.connect(self.show_process_details)
        self.process_list.setSortingEnabled(True)

        self.process_list.horizontalHeader().sectionClicked.connect(self.on_header_clicked)

        # 设置表头样式
        header = self.process_list.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(0, Qt.AscendingOrder)
        self.top_layout.addWidget(self.process_list)

        # 下部区域 - 控制面板
        self.bottom_widget = QWidget()
        self.bottom_layout = QVBoxLayout(self.bottom_widget)
        
        # 控制面板内容
        self.control_panel = QTabWidget()
        self.control_panel.setVisible(False)
        
        # 创建各个标签页
        self.create_common_tab()
        self.create_empty_tabs(2, 3)
        self.create_log_tab()
        
        self.bottom_layout.addWidget(self.control_panel)
        
        # 将上下部分添加到分割器
        self.splitter.addWidget(self.top_container)
        self.splitter.addWidget(self.bottom_widget)
        
        # 控制面板固定高度：监听分割器移动，强制保持底部面板高度不变
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        self._panel_fixed_height = 200  # 控制面板固定高度
        
        # 设置默认分割器位置（控制面板初始隐藏，底部设为0避免空白区域）
        self.splitter.setSizes([500, 0])

        # 恢复上次的窗口状态
        self._restore_settings()

        # 连接设置控件自动保存信号（放在恢复之后，避免加载触发保存）
        self._connect_autosave()

        # 延迟加载进程列表（让窗口先显示出来，提升启动体验）
        QTimer.singleShot(0, self._initial_load)
        
        # 日志记录
        self.log("程序启动成功")

    def _restore_settings(self):
        """恢复上次保存的全部设置（窗口/分割器/控制面板/搜索/排序/显示隐藏）"""
        self._loading_settings = True
        try:
            settings = QSettings("ProcessManager", "App")

            geometry = settings.value("window/geometry")
            if geometry:
                self.restoreGeometry(geometry)
            else:
                self.resize(500, 700)

            splitter_sizes = settings.value("window/splitterSizes")
            if splitter_sizes:
                self.splitter.setSizes([int(s) for s in splitter_sizes])

            panel_expanded = settings.value("window/panelExpanded")
            if panel_expanded == "true":
                self.control_panel.setVisible(True)
                self.toggle_button.setText("▲ 收起控制面板")

            # 搜索模式（0=模糊搜索, 1=精确匹配）
            search_mode = settings.value("window/searchMode")
            if search_mode is not None:
                idx = int(search_mode)
                self.search_options.setCurrentIndex(0 if idx not in (0, 1) else idx)

            # 排序状态（排序列 + 升降序）
            sort_column = settings.value("window/sortColumn")
            if sort_column is not None:
                self.current_sort_column = int(sort_column)
            sort_order = settings.value("window/sortOrder")
            if sort_order is not None:
                val = int(sort_order)
                self.sort_order = Qt.SortOrder(0 if val not in (0, 1) else val)

            # 显示隐藏进程（blockSignals 避免加载时触发刷新）
            show_hidden = settings.value("window/showHidden")
            if show_hidden == "true":
                self.show_hidden_checkbox.blockSignals(True)
                self.show_hidden_checkbox.setChecked(True)
                self.show_hidden_checkbox.blockSignals(False)

            # 确保恢复后控制面板高度固定
            if self.control_panel.isVisible():
                total_height = self.splitter.height()
                if total_height > 0:
                    top_height = max(100, total_height - self._panel_fixed_height)
                    self.splitter.setSizes([top_height, self._panel_fixed_height])
        finally:
            self._loading_settings = False

    def _save_settings(self):
        """保存全部设置（窗口/分割器/控制面板/搜索/排序/显示隐藏）"""
        settings = QSettings("ProcessManager", "App")
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue("window/splitterSizes", self.splitter.sizes())
        settings.setValue("window/panelExpanded",
                          "true" if self.control_panel.isVisible() else "false")
        settings.setValue("window/searchMode", self.search_options.currentIndex())
        settings.setValue("window/sortColumn", self.current_sort_column)
        settings.setValue("window/sortOrder", self.sort_order.value)
        settings.setValue("window/showHidden",
                          "true" if self.show_hidden_checkbox.isChecked() else "false")

    def _autosave_settings(self):
        """设置变更防抖触发自动保存（500ms 内多次变更只写盘一次）"""
        if self._loading_settings:
            return
        self._settings_save_timer.start(500)

    def _save_settings_now(self):
        """立即写盘保存设置"""
        self._settings_save_timer.stop()
        self._save_settings()

    def _connect_autosave(self):
        """连接所有设置控件的变更信号到自动保存"""
        self.show_hidden_checkbox.stateChanged.connect(self._autosave_settings)
        self.search_options.currentIndexChanged.connect(self._autosave_settings)

    def closeEvent(self, event):
        """关闭窗口时强制保存设置"""
        self._settings_save_timer.stop()
        self._save_settings()
        super().closeEvent(event)

    def _initial_load(self):
        """程序启动后的初始加载（延迟执行以加快窗口显示，使用多线程避免卡顿）"""
        # 先让界面完全显示，再启动后台刷新
        QTimer.singleShot(100, self._start_refresh_thread)

    def _start_refresh_thread(self):
        """启动后台刷新线程"""
        if hasattr(self, '_refresh_in_progress') and self._refresh_in_progress:
            return  # 已在刷新中
        self._refresh_in_progress = True
        self.refresh_btn.setEnabled(False)
        self._run_refresh_worker()

    def get_all_window_titles(self):
        """一次性获取所有进程的窗口标题映射（性能优化：只调用一次EnumWindows）"""
        pid_titles = {}
        try:
            def callback(hwnd, lparam):
                window_pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                pid = window_pid.value
                if pid:
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                        title = buff.value
                        if title:
                            if pid not in pid_titles:
                                pid_titles[pid] = []
                            pid_titles[pid].append(title)
                return True

            ctypes.windll.user32.EnumWindows(
                ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))(callback), 0)
        except Exception as e:
            self.log(f"获取窗口标题失败: {str(e)}", error=True)
        return pid_titles

    def get_window_titles(self, pid):
        """获取进程的所有窗口标题（兼容旧接口，用于显示进程详情时获取单个进程窗口标题）"""
        titles = []
        try:
            def callback(hwnd, lparam):
                window_pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                if window_pid.value == pid:
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    buff = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                    if buff.value:
                        titles.append(buff.value)
                return True
            
            ctypes.windll.user32.EnumWindows(
                ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))(callback), 0)
        except Exception as e:
            self.log(f"获取窗口标题失败(PID: {pid}): {str(e)}", error=True)
        return titles
    
    def create_common_tab(self):
        """创建常用标签页"""
        self.common_tab = QWidget()
        layout = QVBoxLayout(self.common_tab)
        
        # 显示隐藏进程选项
        self.show_hidden_checkbox = QCheckBox("显示隐藏进程")
        self.show_hidden_checkbox.setChecked(False)
        self.show_hidden_checkbox.stateChanged.connect(self.update_process_list)
        layout.addWidget(self.show_hidden_checkbox)
        
        # 添加一些常用按钮
        self.refresh_btn = QPushButton("刷新进程列表")
        self.refresh_btn.clicked.connect(self.on_refresh_clicked)
        layout.addWidget(self.refresh_btn)
        
        # 结束所有隐藏进程按钮
        self.kill_hidden_btn = QPushButton("结束所有隐藏进程")
        self.kill_hidden_btn.clicked.connect(self.kill_all_hidden_processes)
        layout.addWidget(self.kill_hidden_btn)
        
        layout.addStretch()
        self.control_panel.addTab(self.common_tab, "常用")
    
    def on_refresh_clicked(self):
        """刷新按钮点击事件（使用后台线程，避免UI卡顿）"""
        if hasattr(self, '_refresh_in_progress') and self._refresh_in_progress:
            return  # 防止重复刷新
        self._start_refresh_thread()
    
    def create_empty_tabs(self, start, end):
        """创建空的标签页"""
        for i in range(start, end+1):
            tab = QWidget()
            layout = QVBoxLayout(tab)
            label = QLabel(f"标签页 {i} - 功能待实现")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
            layout.addStretch()
            self.control_panel.addTab(tab, f"标签{i}")
    
    def create_log_tab(self):
        """创建日志标签页"""
        self.log_tab = QWidget()
        layout = QVBoxLayout(self.log_tab)
        
        # 日志文本框
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Microsoft YaHei", 9))
        
        # 添加滚动区域
        scroll = QScrollArea()
        scroll.setWidget(self.log_text)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)
        
        # 添加清空日志按钮
        clear_btn = QPushButton("清空日志")
        clear_btn.clicked.connect(self.clear_log)
        layout.addWidget(clear_btn)
        
        self.control_panel.addTab(self.log_tab, "日志")
    
    def toggle_control_panel(self):
        """切换控制面板的显示/隐藏（面板高度固定为200px）"""
        PANEL_HEIGHT = 200
        if self.control_panel.isVisible():
            self.control_panel.setVisible(False)
            self.toggle_button.setText("▼ 展开控制面板")
            self.splitter.setSizes([500, 0])
        else:
            self.control_panel.setVisible(True)
            self.toggle_button.setText("▲ 收起控制面板")
            total_height = self.splitter.height()
            top_height = max(100, total_height - PANEL_HEIGHT)
            self.splitter.setSizes([top_height, PANEL_HEIGHT])
        self._autosave_settings()
    
    def _on_splitter_moved(self, pos, index):
        """分割器移动时强制保持控制面板固定高度"""
        if self.control_panel.isVisible():
            total_height = self.splitter.height()
            top_height = max(100, total_height - self._panel_fixed_height)
            self.splitter.blockSignals(True)
            self.splitter.setSizes([top_height, self._panel_fixed_height])
            self.splitter.blockSignals(False)
        self._autosave_settings()
    
    def update_process_list(self):
        """更新进程列表（由UI线程调用，启动后台worker）"""
        self._start_refresh_thread()

    def _run_refresh_worker(self):
        """创建并启动后台刷新Worker"""
        self._refresh_in_progress = True
        self.refresh_btn.setEnabled(False)
        self.global_progress_bar.setValue(0)
        self.global_progress_bar.setFormat("正在刷新... %p%")

        # 创建线程和worker
        self._refresh_thread = QThread()
        self._refresh_worker = ProcessRefreshWorker(
            show_hidden=self.show_hidden_checkbox.isChecked(),
            hidden_processes=self.hidden_processes
        )
        self._refresh_worker.moveToThread(self._refresh_thread)

        # 连接信号
        self._refresh_thread.started.connect(self._refresh_worker.run)
        self._refresh_worker.progress.connect(self._on_refresh_progress)
        self._refresh_worker.finished.connect(self._on_refresh_finished)
        self._refresh_worker.error.connect(self._on_refresh_error)
        self._refresh_worker.finished.connect(self._refresh_thread.quit)
        self._refresh_worker.finished.connect(self._refresh_worker.deleteLater)
        self._refresh_thread.finished.connect(self._refresh_thread.deleteLater)

        self._refresh_thread.start()

    def _on_refresh_progress(self, value, text):
        """刷新进度更新（UI线程）"""
        self.global_progress_bar.setValue(value)
        self.global_progress_bar.setFormat(f"{text} %p%")

    def _on_refresh_finished(self, process_data):
        """刷新完成，填充进程列表（UI线程）"""
        self._refresh_in_progress = False
        self.refresh_btn.setEnabled(True)

        self.process_list.setSortingEnabled(False)
        self.process_list.setRowCount(0)

        for data in process_data:
            row = self.process_list.rowCount()
            self.process_list.insertRow(row)

            pid = data['pid']
            name = data['name']
            is_hidden = data['is_hidden']
            title_info = data['title']

            pid_item = QTableWidgetItem(str(pid))
            pid_item.setData(Qt.ItemDataRole.UserRole, pid)
            if is_hidden:
                pid_item.setForeground(QColor(255, 0, 0))
            self.process_list.setItem(row, 0, pid_item)

            name_item = QTableWidgetItem(name)
            if is_hidden:
                name_item.setText("[隐藏] " + name)
                name_item.setForeground(QColor(255, 0, 0))
            self.process_list.setItem(row, 1, name_item)

            title_item = QTableWidgetItem(title_info)
            if is_hidden:
                title_item.setForeground(QColor(255, 0, 0))
            self.process_list.setItem(row, 2, title_item)

        self.process_list.setSortingEnabled(True)

        # 恢复排序状态
        if hasattr(self, 'current_sort_column'):
            sort_method = self.sort_methods.get(self.current_sort_column, self.sort_by_pid)
            sort_method(self.sort_order)
            self.process_list.horizontalHeader().setSortIndicator(self.current_sort_column, self.sort_order)

        # 恢复搜索过滤
        if self.search_input.toPlainText().strip():
            self.filter_process_list()

        self.log("进程列表已更新")

    def _on_refresh_error(self, error_msg):
        """刷新出错（UI线程）"""
        self._refresh_in_progress = False
        self.refresh_btn.setEnabled(True)
        self.global_progress_bar.setFormat(f"刷新失败: {error_msg}")
        self.log(f"刷新进程列表失败: {error_msg}", error=True)
    
    def show_context_menu(self, position):
        """显示右键菜单（包含常用功能和控制面板功能）"""
        item = self.process_list.itemAt(position)
        if not item:
            # 点击空白区域也显示菜单（通用功能）
            menu = QMenu()
            
            # === 控制面板功能 ===
            refresh_action = QAction("🔄 刷新进程列表", menu)
            refresh_action.triggered.connect(self.on_refresh_clicked)
            menu.addAction(refresh_action)
            
            menu.addSeparator()
            
            # 显示/隐藏隐藏进程
            show_hidden_action = QAction(
                "👁 隐藏隐藏进程" if self.show_hidden_checkbox.isChecked() else "👁 显示隐藏进程", 
                menu
            )
            show_hidden_action.triggered.connect(lambda: self.show_hidden_checkbox.setChecked(
                not self.show_hidden_checkbox.isChecked()
            ))
            menu.addAction(show_hidden_action)
            
            # 展开/收起控制面板
            panel_action = QAction(
                "▲ 收起控制面板" if self.control_panel.isVisible() else "▼ 展开控制面板",
                menu
            )
            panel_action.triggered.connect(self.toggle_control_panel)
            menu.addAction(panel_action)
            
            menu.addSeparator()
            
            # 排序子菜单
            sort_menu = menu.addMenu("📊 排序方式")
            sort_menu.addAction("按PID排序", lambda: self.on_header_clicked(0))
            sort_menu.addAction("按进程名排序", lambda: self.on_header_clicked(1))
            sort_menu.addAction("按窗口标题排序", lambda: self.on_header_clicked(2))
            
            # 结束所有隐藏进程
            kill_hidden_action = QAction("💀 结束所有隐藏进程", menu)
            kill_hidden_action.triggered.connect(self.kill_all_hidden_processes)
            menu.addAction(kill_hidden_action)
            
            menu.addSeparator()
            
            # 清空日志
            clear_log_action = QAction("🗑 清空日志", menu)
            clear_log_action.triggered.connect(self.clear_log)
            menu.addAction(clear_log_action)
            
            menu.exec(self.process_list.mapToGlobal(position))
            return
        
        row = item.row()
        pid_item = self.process_list.item(row, 0)
        pid = pid_item.data(Qt.ItemDataRole.UserRole)
        proc_name_item = self.process_list.item(row, 1)
        proc_name = proc_name_item.text().replace("[隐藏] ", "")
        
        is_hidden = pid in self.hidden_processes and self.hidden_processes[pid]
        
        menu = QMenu()
        
        # === 进程操作 ===
        # 查看详情
        detail_action = QAction(f"📋 查看进程详情: {proc_name} (PID: {pid})", menu)
        detail_action.triggered.connect(lambda: self.show_process_details_by_pid(pid))
        menu.addAction(detail_action)
        
        menu.addSeparator()
        
        # 隐藏/显示进程
        show_hide_action = QAction("👁 隐藏进程" if not is_hidden else "👁 显示进程", menu)
        show_hide_action.triggered.connect(lambda: self.toggle_process_visibility(pid, not is_hidden))
        menu.addAction(show_hide_action)
        
        # 结束进程
        kill_action = QAction(f"💀 结束进程: {proc_name}", menu)
        kill_action.triggered.connect(lambda: self.kill_process(pid))
        menu.addAction(kill_action)
        
        # 挂起进程
        suspend_action = QAction("⏸ 挂起进程", menu)
        suspend_action.triggered.connect(lambda: self.suspend_process(pid))
        menu.addAction(suspend_action)
        
        # 恢复进程
        resume_action = QAction("▶ 恢复进程", menu)
        resume_action.triggered.connect(lambda: self.resume_process(pid))
        menu.addAction(resume_action)
        
        menu.addSeparator()
        
        # === 控制面板功能 ===
        panel_menu = menu.addMenu("⚙ 控制面板功能")
        
        refresh_action = QAction("🔄 刷新进程列表", panel_menu)
        refresh_action.triggered.connect(self.on_refresh_clicked)
        panel_menu.addAction(refresh_action)
        
        show_hidden_toggle = QAction(
            "隐藏隐藏进程" if self.show_hidden_checkbox.isChecked() else "显示隐藏进程",
            panel_menu
        )
        show_hidden_toggle.triggered.connect(lambda: self.show_hidden_checkbox.setChecked(
            not self.show_hidden_checkbox.isChecked()
        ))
        panel_menu.addAction(show_hidden_toggle)
        
        panel_toggle = QAction(
            "收起控制面板" if self.control_panel.isVisible() else "展开控制面板",
            panel_menu
        )
        panel_toggle.triggered.connect(self.toggle_control_panel)
        panel_menu.addAction(panel_toggle)
        
        menu.addSeparator()
        
        # === 排序子菜单 ===
        sort_menu = menu.addMenu("📊 排序方式")
        sort_menu.addAction("按PID排序", lambda: self.on_header_clicked(0))
        sort_menu.addAction("按进程名排序", lambda: self.on_header_clicked(1))
        sort_menu.addAction("按窗口标题排序", lambda: self.on_header_clicked(2))
        
        menu.addSeparator()
        
        # 结束所有隐藏进程
        kill_hidden_action = QAction("💀 结束所有隐藏进程", menu)
        kill_hidden_action.triggered.connect(self.kill_all_hidden_processes)
        menu.addAction(kill_hidden_action)
        
        # 清空日志
        clear_log_action = QAction("🗑 清空日志", menu)
        clear_log_action.triggered.connect(self.clear_log)
        menu.addAction(clear_log_action)
        
        menu.exec(self.process_list.mapToGlobal(position))
    
    def toggle_process_visibility(self, pid, hide):
        """切换进程显示/隐藏状态"""
        try:
            user32 = ctypes.windll.user32
            
            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
            def enum_windows_callback(hwnd, lparam):
                window_pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                
                if window_pid.value == pid:
                    user32.ShowWindow(hwnd, 0 if hide else 1)
                return True
            
            user32.EnumWindows(enum_windows_callback, 0)
            
            self.hidden_processes[pid] = hide
            status = "隐藏" if hide else "显示"
            self.log(f"已{status}进程(PID: {pid})")
            self.update_process_list()
            
        except Exception as e:
            self.log(f"切换进程显示状态失败(PID: {pid}): {str(e)}", error=True)
    
    def kill_process(self, pid):
        """结束进程"""
        try:
            reply = QMessageBox.question(
                self, '确认', 
                f"确定要结束进程(PID: {pid})吗?", 
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                proc = psutil.Process(pid)
                proc_name = proc.name()
                proc.terminate()
                self.log(f"已结束进程: {proc_name} (PID: {pid})")
                
                if pid in self.hidden_processes:
                    del self.hidden_processes[pid]
                
                self.update_process_list()
        except Exception as e:
            self.log(f"结束进程失败(PID: {pid}): {str(e)}", error=True)
    
    def suspend_process(self, pid):
        """挂起进程"""
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.DebugActiveProcess(pid)
            self.log(f"已挂起进程(PID: {pid})")
        except Exception as e:
            self.log(f"挂起进程失败(PID: {pid}): {str(e)}", error=True)
    
    def resume_process(self, pid):
        """恢复进程"""
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.DebugActiveProcessStop(pid)
            self.log(f"已恢复进程(PID: {pid})")
        except Exception as e:
            self.log(f"恢复进程失败(PID: {pid}): {str(e)}", error=True)
    
    def kill_all_hidden_processes(self):
        """结束所有隐藏进程（使用后台线程，避免UI卡顿）"""
        if not self.hidden_processes:
            self.log("没有隐藏的进程")
            return

        if hasattr(self, '_kill_in_progress') and self._kill_in_progress:
            self.log("正在结束隐藏进程，请稍候...")
            return
        
        reply = QMessageBox.question(
            self, '确认', 
            f"确定要结束所有{len(self.hidden_processes)}个隐藏进程吗?", 
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._kill_in_progress = True
        self.kill_hidden_btn.setEnabled(False)
        self.global_progress_bar.setValue(0)
        self.global_progress_bar.setFormat("正在结束隐藏进程... %p%")

        # 创建后台线程
        pids = list(self.hidden_processes.keys())
        self._kill_thread = QThread()
        self._kill_worker = KillHiddenWorker(pids)
        self._kill_worker.moveToThread(self._kill_thread)

        self._kill_thread.started.connect(self._kill_worker.run)
        self._kill_worker.progress.connect(self._on_kill_progress)
        self._kill_worker.log_message.connect(self._on_kill_log)
        self._kill_worker.finished.connect(self._on_kill_finished)
        self._kill_worker.finished.connect(self._kill_thread.quit)
        self._kill_worker.finished.connect(self._kill_worker.deleteLater)
        self._kill_thread.finished.connect(self._kill_thread.deleteLater)

        self._kill_thread.start()

    def _on_kill_progress(self, value, text):
        """结束进程进度更新（UI线程）"""
        self.global_progress_bar.setValue(value)
        self.global_progress_bar.setFormat(f"{text} %p%")

    def _on_kill_log(self, data):
        """结束进程日志（UI线程）"""
        message, is_error = data
        self.log(message, error=is_error)

    def _on_kill_finished(self, killed):
        """结束进程完成（UI线程）"""
        self._kill_in_progress = False
        self.kill_hidden_btn.setEnabled(True)
        # 清理已结束的隐藏进程
        for pid in list(self.hidden_processes.keys()):
            try:
                psutil.Process(pid)
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                del self.hidden_processes[pid]
        self.log(f"已成功结束{killed}个隐藏进程")
        self.update_process_list()
    
    def show_process_details(self, item):
        """显示进程详细信息（通过点击列表项触发）"""
        pid = item.data(Qt.ItemDataRole.UserRole)
        self.show_process_details_by_pid(pid)
    
    def show_process_details_by_pid(self, pid):
        """显示进程详细信息（使用后台线程，避免UI卡顿）"""
        self.global_progress_bar.setValue(0)
        self.global_progress_bar.setFormat("正在获取进程详情... %p%")

        # 创建后台线程
        self._info_thread = QThread()
        self._info_worker = ProcessInfoWorker(pid)
        self._info_worker.moveToThread(self._info_thread)

        self._info_thread.started.connect(self._info_worker.run)
        self._info_worker.finished.connect(self._on_info_finished)
        self._info_worker.error.connect(self._on_info_error)
        self._info_worker.finished.connect(self._info_thread.quit)
        self._info_worker.finished.connect(self._info_worker.deleteLater)
        self._info_thread.finished.connect(self._info_thread.deleteLater)

        self._info_thread.start()

    def _on_info_finished(self, data):
        """进程详情获取完成（UI线程）"""
        pid, details = data
        self.global_progress_bar.setValue(100)
        self.global_progress_bar.setFormat("就绪")
        try:
            proc = psutil.Process(pid)
            proc_name = proc.name()
            is_hidden = pid in self.hidden_processes and self.hidden_processes[pid]
            hidden_str = "是" if is_hidden else "否"
            details += f"是否隐藏: {hidden_str}\n"
            self.log(f"查看进程详情: {proc_name} (PID: {pid})")
        except Exception:
            pass
        self.log_text.append(details)

    def _on_info_error(self, error_msg):
        """进程详情获取失败（UI线程）"""
        self.global_progress_bar.setValue(0)
        self.global_progress_bar.setFormat("就绪")
        self.log(f"获取进程详情失败: {error_msg}", error=True)
    
    def format_time(self, timestamp):
        """格式化时间戳"""
        from datetime import datetime
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    
    def log(self, message, error=False):
        """记录日志"""
        prefix = "[ERROR] " if error else "[INFO] "
        
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)
        
        if error:
            self.log_text.setTextColor(QColor(255, 0, 0))
            self.log_text.insertPlainText(prefix + message + "\n")
            self.log_text.setTextColor(QColor(0, 0, 0))
        else:
            self.log_text.insertPlainText(prefix + message + "\n")
        
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    
    def clear_log(self):
        """清空日志"""
        self.log_text.clear()
        self.log("日志已清空")

    def get_pinyin_initials(self, text):
        """获取文本的拼音首字母"""
        if not text or not isinstance(text, str):
            return ""
        try:
            from pypinyin import lazy_pinyin
            initials = [p[0].upper() for p in lazy_pinyin(text) if p]
            return "".join(initials)
        except ImportError:
            return ""

    def filter_process_list(self):
        """根据搜索条件过滤进程列表"""
        search_text = self.search_input.toPlainText().strip().lower()
        if not search_text:
            for i in range(self.process_list.rowCount()):
                self.process_list.setRowHidden(i, False)
            return
        
        exact_match = self.search_options.currentIndex() == 1
        
        for i in range(self.process_list.rowCount()):
            pid_item = self.process_list.item(i, 0)
            name_item = self.process_list.item(i, 1)
            title_item = self.process_list.item(i, 2)
            
            pid = pid_item.data(Qt.ItemDataRole.UserRole)
            process_name = name_item.text().replace("[隐藏] ", "").lower()
            window_titles = title_item.text().lower()
            
            pinyin_initials = self.get_pinyin_initials(process_name)
            
            match_found = False
            if exact_match:
                match_found = (search_text == process_name or 
                            search_text == window_titles)
            else:
                match_found = (search_text in process_name or 
                            search_text in window_titles or
                            search_text in pinyin_initials.lower())
            
            self.process_list.setRowHidden(i, not match_found)

    def sort_table(self, logicalIndex):
        """表格排序方法"""
        self.process_list.sortItems(logicalIndex)

    def sort_by_pid(self, order):
        """按PID排序"""
        self.process_list.sortItems(0, order)
        
    def sort_by_name(self, order):
        """按进程名排序"""
        for row in range(self.process_list.rowCount()):
            item = self.process_list.item(row, 1)
            text = item.text().replace("[隐藏] ", "")
            item.setData(Qt.ItemDataRole.UserRole + 1, text.lower())
        self.process_list.sortItems(1, order)

    def sort_by_title(self, order):
        """按窗口标题排序"""
        for row in range(self.process_list.rowCount()):
            item = self.process_list.item(row, 2)
            text = item.text() if item.text() else ""
            item.setData(Qt.ItemDataRole.UserRole + 1, text.lower())
        self.process_list.sortItems(2, order)

    def on_header_clicked(self, logicalIndex):
        """表头点击事件处理"""
        if logicalIndex == self.current_sort_column:
            self.sort_order = Qt.DescendingOrder if self.sort_order == Qt.AscendingOrder else Qt.AscendingOrder
        else:
            self.current_sort_column = logicalIndex
            self.sort_order = Qt.AscendingOrder
        
        sort_method = self.sort_methods.get(logicalIndex, self.sort_by_pid)
        sort_method(self.sort_order)
        
        self.process_list.horizontalHeader().setSortIndicator(logicalIndex, self.sort_order)
        self._autosave_settings()


if __name__ == "__main__":
    def is_admin():
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False
    
    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit()
    
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 9))
    manager = ProcessManager()
    manager.show()
    sys.exit(app.exec())