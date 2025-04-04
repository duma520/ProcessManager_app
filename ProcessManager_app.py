import sys
import psutil
import ctypes
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QListWidget, QTabWidget, QPushButton, QLabel, QMenu, 
                             QSplitter, QCheckBox, QTextEdit, QScrollArea, QMessageBox, QListWidgetItem)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QTextCursor, QColor

# Windows API常量
PROCESS_ALL_ACCESS = 0x1F0FFF

class ProcessManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("进程管理工具 v1.1.0")
        self.resize(500, 700)
        
        # 初始化隐藏进程字典
        self.hidden_processes = {}  # 先初始化这个属性
        
        # 主窗口布局
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QHBoxLayout(self.main_widget)
        
        # 创建分割器
        self.splitter = QSplitter(Qt.Vertical)
        self.main_layout.addWidget(self.splitter)
        
        # 上部区域 - 进程列表和控制按钮
        self.top_container = QWidget()
        self.top_layout = QVBoxLayout(self.top_container)
        
        # 添加展开/收起按钮到列表上方
        self.toggle_button = QPushButton("▼ 展开控制面板")
        self.toggle_button.clicked.connect(self.toggle_control_panel)
        self.top_layout.addWidget(self.toggle_button)
        
        # 进程列表
        self.process_list = QListWidget()
        self.process_list.setFont(QFont("Microsoft YaHei", 10))
        self.process_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.process_list.customContextMenuRequested.connect(self.show_context_menu)
        self.process_list.itemClicked.connect(self.show_process_details)
        self.top_layout.addWidget(self.process_list)
        
        # 下部区域 - 控制面板
        self.bottom_widget = QWidget()
        self.bottom_layout = QVBoxLayout(self.bottom_widget)
        
        # 控制面板内容
        self.control_panel = QTabWidget()
        self.control_panel.setVisible(False)  # 默认收起
        
        # 创建各个标签页
        self.create_common_tab()      # 标签1: 常用
        self.create_empty_tabs(2, 3)  # 标签2-8: 空标签
        self.create_log_tab()         # 标签9: 日志
        
        self.bottom_layout.addWidget(self.control_panel)
        
        # 将上下部分添加到分割器
        self.splitter.addWidget(self.top_container)
        self.splitter.addWidget(self.bottom_widget)
        
        # 设置初始分割器位置
        self.splitter.setSizes([500, 100])
        
        # 初始化进程列表
        self.update_process_list()
        
        # 日志记录
        self.log("程序启动成功")

    def get_window_titles(self, pid):
        """获取进程的所有窗口标题"""
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
            
            ctypes.windll.user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))(callback), 0)
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
        """刷新按钮点击事件"""
        self.refresh_btn.setEnabled(False)  # 禁用按钮
        QApplication.processEvents()  # 立即更新UI
        self.update_process_list()
        self.refresh_btn.setEnabled(True)  # 重新启用按钮
    
    def create_empty_tabs(self, start, end):
        """创建空的标签页"""
        for i in range(start, end+1):
            tab = QWidget()
            layout = QVBoxLayout(tab)
            label = QLabel(f"标签页 {i} - 功能待实现")
            label.setAlignment(Qt.AlignCenter)
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
        """切换控制面板的显示/隐藏"""
        if self.control_panel.isVisible():
            self.control_panel.setVisible(False)
            self.toggle_button.setText("▼ 展开控制面板")
            self.splitter.setSizes([500, 0])  # 完全收起
        else:
            self.control_panel.setVisible(True)
            self.toggle_button.setText("▲ 收起控制面板")
            self.splitter.setSizes([400, 200])  # 展开状态
    
    def update_process_list(self):
        """更新进程列表"""
        current_item = self.process_list.currentItem()
        selected_pid = current_item.data(Qt.UserRole) if current_item else None
        
        self.process_list.clear()
        
        show_hidden = self.show_hidden_checkbox.isChecked()
        
        for proc in psutil.process_iter(['pid', 'name', 'username', 'status']):
            try:
                pid = proc.info['pid']
                
                # 检查进程是否被隐藏
                is_hidden = pid in self.hidden_processes and self.hidden_processes[pid]
                
                # 如果不显示隐藏进程且进程是隐藏状态，则跳过
                if not show_hidden and is_hidden:
                    continue
                
                # 获取窗口标题
                window_titles = self.get_window_titles(pid)
                title_info = f" - 窗口: {', '.join(window_titles)}" if window_titles else ""
                
                item_text = f"{proc.info['name']} (PID: {pid}){title_info}"
                if is_hidden:
                    item_text = "[隐藏] " + item_text
                
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, pid)
                
                # 如果是隐藏进程，设置特殊颜色
                if is_hidden:
                    item.setForeground(QColor(255, 0, 0))  # 红色
                
                self.process_list.addItem(item)
                
                # 恢复之前选中的进程
                if selected_pid and pid == selected_pid:
                    self.process_list.setCurrentItem(item)
            
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        
        self.log("进程列表已更新")
    
    def show_context_menu(self, position):
        """显示右键菜单"""
        item = self.process_list.itemAt(position)
        if not item:
            return
        
        menu = QMenu()
        
        pid = item.data(Qt.UserRole)
        proc_name = item.text().split(" (PID:")[0].replace("[隐藏] ", "")
        
        # 检查进程是否已隐藏
        is_hidden = pid in self.hidden_processes and self.hidden_processes[pid]
        
        # 添加菜单项
        show_hide_action = menu.addAction("隐藏进程" if not is_hidden else "显示进程")
        kill_action = menu.addAction(f"结束进程: {proc_name}")
        suspend_action = menu.addAction("挂起进程")
        resume_action = menu.addAction("恢复进程")
        
        # 显示菜单并获取选择
        action = menu.exec_(self.process_list.mapToGlobal(position))
        
        if action == show_hide_action:
            self.toggle_process_visibility(pid, not is_hidden)
        elif action == kill_action:
            self.kill_process(pid)
        elif action == suspend_action:
            self.suspend_process(pid)
        elif action == resume_action:
            self.resume_process(pid)
    
    def toggle_process_visibility(self, pid, hide):
        """切换进程显示/隐藏状态"""
        try:
            # 使用Windows API隐藏进程窗口
            user32 = ctypes.windll.user32
            
            # 枚举进程的所有窗口
            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.POINTER(ctypes.c_int))
            def enum_windows_callback(hwnd, lparam):
                # 获取窗口所属进程ID
                window_pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                
                if window_pid.value == pid:
                    # 隐藏或显示窗口
                    user32.ShowWindow(hwnd, 0 if hide else 1)
                return True
            
            # 枚举所有窗口
            user32.EnumWindows(enum_windows_callback, 0)
            
            # 更新隐藏状态
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
                QMessageBox.Yes | QMessageBox.No, 
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                proc = psutil.Process(pid)
                proc_name = proc.name()
                proc.terminate()
                self.log(f"已结束进程: {proc_name} (PID: {pid})")
                
                # 如果进程是隐藏的，从字典中移除
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
        """结束所有隐藏进程"""
        if not self.hidden_processes:
            self.log("没有隐藏的进程")
            return
        
        reply = QMessageBox.question(
            self, '确认', 
            f"确定要结束所有{len(self.hidden_processes)}个隐藏进程吗?", 
            QMessageBox.Yes | QMessageBox.No, 
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            killed = 0
            for pid in list(self.hidden_processes.keys()):
                try:
                    proc = psutil.Process(pid)
                    proc.terminate()
                    del self.hidden_processes[pid]
                    killed += 1
                    self.log(f"已结束隐藏进程: {proc.name()} (PID: {pid})")
                except Exception as e:
                    self.log(f"结束隐藏进程失败(PID: {pid}): {str(e)}", error=True)
            
            self.log(f"已成功结束{killed}个隐藏进程")
            self.update_process_list()
    
    def show_process_details(self, item):
        """显示进程详细信息"""
        pid = item.data(Qt.UserRole)
        try:
            proc = psutil.Process(pid)
            with proc.oneshot():
                # 获取更多进程信息
                cpu_percent = proc.cpu_percent(interval=0.1)
                mem_info = proc.memory_info()
                threads = proc.num_threads()
                
                details = (
                    f"===== 进程详细信息 =====\n"
                    f"进程名称: {proc.name()}\n"
                    f"进程ID: {pid}\n"
                    f"状态: {proc.status()}\n"
                    f"创建时间: {self.format_time(proc.create_time())}\n"
                    f"CPU使用率: {cpu_percent}%\n"
                    f"内存使用(RSS): {mem_info.rss / 1024 / 1024:.2f} MB\n"
                    f"内存使用(VMS): {mem_info.vms / 1024 / 1024:.2f} MB\n"
                    f"线程数: {threads}\n"
                    f"执行路径: {proc.exe() or 'N/A'}\n"
                    f"命令行: {' '.join(proc.cmdline()) if proc.cmdline() else 'N/A'}\n"
                    f"用户名: {proc.username()}\n"
                    f"工作目录: {proc.cwd() or 'N/A'}\n"
                    f"是否隐藏: {'是' if pid in self.hidden_processes and self.hidden_processes[pid] else '否'}\n"
                )
            
            self.log(f"查看进程详情: {proc.name()} (PID: {pid})")
            self.log_text.append(details)
            
        except Exception as e:
            self.log(f"获取进程详情失败(PID: {pid}): {str(e)}", error=True)
    
    def format_time(self, timestamp):
        """格式化时间戳"""
        from datetime import datetime
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    
    def log(self, message, error=False):
        """记录日志"""
        prefix = "[ERROR] " if error else "[INFO] "
        
        self.log_text.moveCursor(QTextCursor.End)
        
        if error:
            # 错误信息显示为红色
            self.log_text.setTextColor(QColor(255, 0, 0))
            self.log_text.insertPlainText(prefix + message + "\n")
            self.log_text.setTextColor(QColor(0, 0, 0))
        else:
            self.log_text.insertPlainText(prefix + message + "\n")
        
        # 自动滚动到最后
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    
    def clear_log(self):
        """清空日志"""
        self.log_text.clear()
        self.log("日志已清空")


if __name__ == "__main__":
    # 检查是否以管理员权限运行
    def is_admin():
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except:
            return False
    
    if not is_admin():
        # 如果不是管理员，尝试以管理员权限重新运行
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit()
    
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 9))
    manager = ProcessManager()
    manager.show()
    sys.exit(app.exec_())