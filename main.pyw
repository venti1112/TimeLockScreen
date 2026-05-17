import sys
import json
import os
import ctypes
from ctypes import wintypes
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QListWidgetItem, QSystemTrayIcon, QMenu,
    QDialog, QTimeEdit, QRadioButton, QButtonGroup, QCheckBox, QDateEdit,
    QDialogButtonBox, QMessageBox, QGridLayout
)
from PySide6.QtCore import Qt, QTimer, QTime, QDate, QDateTime, QRect, Signal
from PySide6.QtGui import QColor, QPalette, QIcon, QPainter, QPixmap, QFont, QAction


# ---------- Windows API 声明 ----------
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    if sys.argv[-1] != '--elevated':
        script = os.path.abspath(sys.argv[0])
        params = ' '.join([f'"{arg}"' for arg in sys.argv[1:]])
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{script}" {params} --elevated', None, 1
        )
        sys.exit(0)

# 会话通知
WTS_CURRENT_SERVER_HANDLE = 0
NOTIFY_FOR_THIS_SESSION = 0
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8

WTSRegisterSessionNotification = ctypes.windll.wtsapi32.WTSRegisterSessionNotification
WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
WTSRegisterSessionNotification.restype = wintypes.BOOL

WTSUnRegisterSessionNotification = ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification
WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
WTSUnRegisterSessionNotification.restype = wintypes.BOOL


# ---------- 规则数据结构 ----------
class LockRule:
    def __init__(self, rule_id, start_time, end_time, repeat_type, repeat_days=None, single_date=None, enabled=True):
        self.id = rule_id
        self.start_time = start_time          # QTime
        self.end_time = end_time              # QTime
        self.repeat_type = repeat_type        # "everyday", "weekly", "once"
        self.repeat_days = repeat_days or []  # list of int 0=Mon ~ 6=Sun
        self.single_date = single_date        # QDate or None
        self.enabled = enabled

    def to_dict(self):
        d = {
            "id": self.id,
            "start_time": self.start_time.toString("HH:mm"),
            "end_time": self.end_time.toString("HH:mm"),
            "repeat_type": self.repeat_type,
            "enabled": self.enabled
        }
        if self.repeat_type == "weekly":
            d["repeat_days"] = self.repeat_days
        elif self.repeat_type == "once":
            d["single_date"] = self.single_date.toString("yyyy-MM-dd") if self.single_date else ""
        return d

    @staticmethod
    def from_dict(d):
        start = QTime.fromString(d["start_time"], "HH:mm")
        end = QTime.fromString(d["end_time"], "HH:mm")
        rtype = d["repeat_type"]
        rdays = d.get("repeat_days", [])
        sdate = QDate.fromString(d.get("single_date", ""), "yyyy-MM-dd") if d.get("single_date") else None
        enabled = d.get("enabled", True)
        return LockRule(d["id"], start, end, rtype, rdays, sdate, enabled)

    def summary(self):
        base = f"{self.start_time.toString('HH:mm')} - {self.end_time.toString('HH:mm')}"
        if self.repeat_type == "everyday":
            return f"每天 {base}"
        elif self.repeat_type == "weekly":
            days_str = ["一","二","三","四","五","六","日"]
            sel = [days_str[i] for i in sorted(self.repeat_days) if 0 <= i <= 6]
            return f"每周{'、'.join(sel)} {base}"
        elif self.repeat_type == "once":
            d = self.single_date.toString("yyyy-MM-dd") if self.single_date else "???"
            return f"单次 {d} {base}"
        return base


# ---------- 全屏锁屏窗口 ----------
class LockScreen(QWidget):
    def __init__(self, unlock_dt: QDateTime):
        super().__init__()
        self.unlock_dt = unlock_dt
        self.allow_close = False

        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint |
            Qt.Tool
        )
        self.setGeometry(self._get_total_screen_geometry())
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(0, 0, 0))
        self.setPalette(palette)

        # 当前时间
        self.current_time_label = QLabel(self)
        self.current_time_label.setAlignment(Qt.AlignCenter)
        self.current_time_label.setStyleSheet("color: #AAAAAA; font-size: 32px;")

        # 锁定提示
        self.info_label = QLabel("屏幕已锁定", self)
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setStyleSheet("color: white; font-size: 48px; font-weight: bold;")

        # 倒计时
        self.time_label = QLabel(self)
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet("color: red; font-size: 72px; font-weight: bold;")

        layout = QVBoxLayout(self)
        layout.addWidget(self.current_time_label, 1)
        layout.addStretch(2)
        layout.addWidget(self.info_label)
        layout.addSpacing(30)
        layout.addWidget(self.time_label)
        layout.addStretch(3)

        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_all)
        self.update_timer.start(200)
        self.update_all()

    def _get_total_screen_geometry(self) -> QRect:
        screens = QApplication.screens()
        total = QRect()
        for s in screens:
            total = total.united(s.geometry())
        return total

    def set_unlock_datetime(self, dt: QDateTime):
        self.unlock_dt = dt
        self.update_all()

    def update_all(self):
        now = QDateTime.currentDateTime()
        self.current_time_label.setText(now.toString("yyyy-MM-dd HH:mm:ss"))
        secs = now.secsTo(self.unlock_dt)
        if secs <= 0:
            self.allow_close = True
            self.close()
            return
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        self.time_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def keyPressEvent(self, event):
        # 忽略所有键盘操作
        return

    def closeEvent(self, event):
        if self.allow_close:
            event.accept()
        else:
            event.ignore()


# ---------- 规则编辑对话框 ----------
class RuleDialog(QDialog):
    def __init__(self, rule: LockRule = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑规则" if rule else "新建规则")
        self.setFixedSize(450, 320)
        self.editing_rule = rule

        layout = QVBoxLayout(self)

        # 时间选择
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("开始时间:"))
        self.start_edit = QTimeEdit(self)
        self.start_edit.setDisplayFormat("HH:mm")
        time_layout.addWidget(self.start_edit)
        time_layout.addWidget(QLabel("结束时间:"))
        self.end_edit = QTimeEdit(self)
        self.end_edit.setDisplayFormat("HH:mm")
        time_layout.addWidget(self.end_edit)
        layout.addLayout(time_layout)

        # 重复类型单选
        self.everyday_radio = QRadioButton("每天")
        self.weekly_radio = QRadioButton("每周特定")
        self.once_radio = QRadioButton("仅一次")
        type_group = QButtonGroup(self)
        type_group.addButton(self.everyday_radio, 0)
        type_group.addButton(self.weekly_radio, 1)
        type_group.addButton(self.once_radio, 2)
        radio_layout = QHBoxLayout()
        radio_layout.addWidget(self.everyday_radio)
        radio_layout.addWidget(self.weekly_radio)
        radio_layout.addWidget(self.once_radio)
        layout.addLayout(radio_layout)

        # 星期选择（两行网格）
        self.days_widget = QWidget(self)
        grid = QGridLayout(self.days_widget)
        self.day_checks = []
        day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        for i, name in enumerate(day_names):
            cb = QCheckBox(name)
            self.day_checks.append(cb)
            row = i // 4
            col = i % 4
            grid.addWidget(cb, row, col)
        layout.addWidget(self.days_widget)

        # 单次日期选择
        self.date_edit = QDateEdit(self)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        layout.addWidget(self.date_edit)

        # 按钮
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        # 信号
        self.everyday_radio.toggled.connect(self.on_type_changed)
        self.weekly_radio.toggled.connect(self.on_type_changed)
        self.once_radio.toggled.connect(self.on_type_changed)

        # 填充编辑数据
        if rule:
            self.start_edit.setTime(rule.start_time)
            self.end_edit.setTime(rule.end_time)
            if rule.repeat_type == "everyday":
                self.everyday_radio.setChecked(True)
            elif rule.repeat_type == "weekly":
                self.weekly_radio.setChecked(True)
                for i in rule.repeat_days:
                    if 0 <= i < len(self.day_checks):
                        self.day_checks[i].setChecked(True)
            elif rule.repeat_type == "once":
                self.once_radio.setChecked(True)
                self.date_edit.setDate(rule.single_date if rule.single_date else QDate.currentDate())
        else:
            self.everyday_radio.setChecked(True)

        self.on_type_changed()

    def on_type_changed(self):
        self.days_widget.setVisible(self.weekly_radio.isChecked())
        self.date_edit.setVisible(self.once_radio.isChecked())

    def get_rule(self):
        start = self.start_edit.time()
        end = self.end_edit.time()
        if self.everyday_radio.isChecked():
            rtype = "everyday"
            rdays = []
            sdate = None
        elif self.weekly_radio.isChecked():
            rtype = "weekly"
            rdays = [i for i, cb in enumerate(self.day_checks) if cb.isChecked()]
            sdate = None
        else:
            rtype = "once"
            rdays = []
            sdate = self.date_edit.date()
        rule_id = self.editing_rule.id if self.editing_rule else None
        return LockRule(rule_id, start, end, rtype, rdays, sdate, True)


# ---------- 主窗口 ----------
class MainWindow(QMainWindow):
    def __init__(self, start_hidden=False):
        super().__init__()
        self.setWindowTitle("时间管理锁屏")
        self.setFixedSize(500, 400)

        self.rules: list[LockRule] = []
        self.next_rule_id = 1
        self.monitoring = False
        self.lock_screen: LockScreen | None = None
        self.autostart_enabled = False
        if getattr(sys, 'frozen', False):
            # 打包后：配置文件放在可执行文件同级目录（可写）
            base_dir = Path(sys.executable).parent
        else:
            # 开发环境：放在脚本同级目录
            base_dir = Path(__file__).parent

        self.config_path = base_dir / "lock_rules.json"
        # 控件
        self.rule_list = QListWidget(self)
        self.rule_list.setSelectionMode(QListWidget.SingleSelection)

        self.add_btn = QPushButton("添加规则")
        self.edit_btn = QPushButton("编辑规则")
        self.del_btn = QPushButton("删除规则")
        self.start_btn = QPushButton("开始监控")
        self.stop_btn = QPushButton("停止监控")
        self.stop_btn.setEnabled(False)
        self.status_label = QLabel("监控未启动")

        # 开机自启复选框
        self.autostart_check = QCheckBox("开机自动启动")

        # 布局
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        layout.addWidget(QLabel("锁定规则列表:"))
        layout.addWidget(self.rule_list)

        btn_layout1 = QHBoxLayout()
        btn_layout1.addWidget(self.add_btn)
        btn_layout1.addWidget(self.edit_btn)
        btn_layout1.addWidget(self.del_btn)
        layout.addLayout(btn_layout1)

        layout.addWidget(self.autostart_check)
        layout.addSpacing(10)
        layout.addWidget(self.status_label)

        btn_layout2 = QHBoxLayout()
        btn_layout2.addStretch()
        btn_layout2.addWidget(self.start_btn)
        btn_layout2.addWidget(self.stop_btn)
        layout.addLayout(btn_layout2)

        # 信号连接
        self.add_btn.clicked.connect(self.add_rule)
        self.edit_btn.clicked.connect(self.edit_rule)
        self.del_btn.clicked.connect(self.delete_rule)
        self.start_btn.clicked.connect(self.start_monitoring)
        self.stop_btn.clicked.connect(self.stop_monitoring)
        self.rule_list.itemDoubleClicked.connect(self.edit_rule)
        self.autostart_check.toggled.connect(self.on_autostart_toggled)

        # 监控定时器
        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self.check_schedule)

        # 系统托盘
        self.tray_icon = QSystemTrayIcon(self)
        icon_path = Path(__file__).parent / "icon.ico"
        if not icon_path.exists():
            pixmap = QPixmap(64, 64)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor("#2196F3"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(4, 4, 56, 56)
            painter.setPen(Qt.white)
            painter.setFont(QFont("Arial", 30, QFont.Bold))
            painter.drawText(QRect(0, 0, 64, 64), Qt.AlignCenter, "⏳")
            painter.end()
            pixmap.save(str(icon_path), "ICO")
        self.icon = QIcon(str(icon_path))
        self.tray_icon.setIcon(self.icon)
        self.setWindowIcon(self.icon)
        self.update_tray_tooltip()
        tray_menu = QMenu()
        show_action = QAction("显示设置", self)
        quit_action = QAction("退出", self)
        show_action.triggered.connect(self.show_normal)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

        # 注册会话通知（Win+L 解锁后恢复）
        self.register_session_notification()

        # 加载配置并决定是否显示窗口
        self.load_config()
        self.autostart_check.setChecked(self.autostart_enabled)

        if start_hidden:
            self.hide()
        else:
            self.show()

    # ---------- 系统限制函数 ----------
    def block_input(self, block: bool):
        try:
            ctypes.windll.user32.BlockInput(block)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"锁定输入设备失败: {e}")

    def set_task_manager(self, disable: bool):
        try:
            import winreg
            key = winreg.CreateKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
            )
            winreg.SetValueEx(key, "DisableTaskMgr", 0, winreg.REG_DWORD, 1 if disable else 0)
            winreg.CloseKey(key)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"任务管理器设置失败: {e}")

    def _unlock_system(self):
        self.block_input(False)
        self.set_task_manager(False)

    # ---------- 开机自启 ----------
    def on_autostart_toggled(self, checked):
        self.autostart_enabled = checked
        self.set_autostart(checked)
        self.save_config()

    def set_autostart(self, enable):
        """通过任务计划程序实现开机自启"""
        import subprocess
        app_name = "TimeLockScreen"

        # 获取当前可执行文件路径
        if getattr(sys, 'frozen', False):
            exe_path = sys.executable
        else:
            exe_path = os.path.abspath(sys.argv[0])

        try:
            if enable:
                # 创建任务：以最高权限运行，不弹 UAC
                cmd = (
                    f'schtasks /Create /F /SC ONLOGON /RL HIGHEST /TN "{app_name}" '
                    f'/TR "\"{exe_path}\" --autostart"'
                )
                subprocess.run(cmd, check=True, shell=True, capture_output=True)
            else:
                # 删除任务
                cmd = f'schtasks /Delete /F /TN "{app_name}"'
                subprocess.run(cmd, check=True, shell=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else "未知错误"
            QMessageBox.warning(self, "开机自启设置失败", f"任务计划操作失败:\n{error_msg}")
        except Exception as e:
            QMessageBox.warning(self, "开机自启设置失败", f"{e}")

    # ---------- 会话通知 ----------
    def register_session_notification(self):
        if not WTSRegisterSessionNotification(int(self.winId()), NOTIFY_FOR_THIS_SESSION):
            QMessageBox.warning(self, "错误", "注册会话通知失败，锁定后将无法自动恢复。")

    def unregister_session_notification(self):
        WTSUnRegisterSessionNotification(int(self.winId()))

    def nativeEvent(self, eventType, message):
        msg = ctypes.wintypes.MSG.from_address(message.__int__())
        if msg.message == WM_WTSSESSION_CHANGE:
            if msg.wParam == WTS_SESSION_UNLOCK:
                self.restore_lock_after_unlock()
        return super().nativeEvent(eventType, message)

    def restore_lock_after_unlock(self):
        if not self.monitoring:
            return
        active_unlock_times = []
        for rule in self.rules:
            if not rule.enabled:
                continue
            result = self._is_rule_active_now(rule)
            if result is not None:
                active_unlock_times.append(result)
        if active_unlock_times:
            latest_unlock = max(active_unlock_times)
            if self.lock_screen is None:
                self.lock_screen = LockScreen(latest_unlock)
                self.lock_screen.destroyed.connect(self._on_lock_screen_closed)
            self.lock_screen.set_unlock_datetime(latest_unlock)
            self.lock_screen.showFullScreen()
            self.block_input(True)
            self.set_task_manager(True)
        else:
            if self.lock_screen is not None:
                self._unlock_system()
                self.lock_screen.allow_close = True
                self.lock_screen.close()
                self.lock_screen = None

    def _on_lock_screen_closed(self):
        self._unlock_system()
        if self.lock_screen is not None:
            self.lock_screen = None

    # ---------- 托盘 ----------
    def update_tray_tooltip(self):
        status = "监控运行中" if self.monitoring else "未运行"
        self.tray_icon.setToolTip(f"时间管理锁屏 - {status}")

    def show_normal(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.tray_icon.isVisible():
            self.hide()
            event.ignore()
        else:
            event.accept()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_normal()

    def quit_app(self):
        self.unregister_session_notification()
        self.stop_monitoring()
        self.save_config()
        self.tray_icon.hide()
        QApplication.quit()

    # ---------- 规则管理 ----------
    def add_rule(self):
        dlg = RuleDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            new_rule = dlg.get_rule()
            new_rule.id = self.next_rule_id
            self.next_rule_id += 1
            self.rules.append(new_rule)
            self._update_list()
            self.save_config()

    def edit_rule(self):
        current_item = self.rule_list.currentItem()
        if not current_item:
            return
        idx = self.rule_list.row(current_item)
        rule = self.rules[idx]
        dlg = RuleDialog(rule, parent=self)
        if dlg.exec() == QDialog.Accepted:
            updated = dlg.get_rule()
            updated.id = rule.id
            self.rules[idx] = updated
            self._update_list()
            self.save_config()

    def delete_rule(self):
        current_item = self.rule_list.currentItem()
        if not current_item:
            return
        idx = self.rule_list.row(current_item)
        reply = QMessageBox.question(
            self, "确认删除", "确定要删除选中的规则吗？",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            del self.rules[idx]
            self._update_list()
            self.save_config()

    def _update_list(self):
        self.rule_list.clear()
        for rule in self.rules:
            text = rule.summary()
            if not rule.enabled:
                text += " [禁用]"
            self.rule_list.addItem(text)

    # ---------- 监控控制 ----------
    def start_monitoring(self):
        if not self.rules:
            QMessageBox.information(self, "提示", "请先添加至少一条锁定规则。")
            return
        self.monitoring = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("监控运行中...")
        self.status_label.setStyleSheet("color: green;")
        self.monitor_timer.start(1000)
        self.update_tray_tooltip()
        self.save_config()
        self.check_schedule()

    def stop_monitoring(self):
        self.monitoring = False
        self.monitor_timer.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("监控未启动")
        self.status_label.setStyleSheet("color: gray;")
        self._unlock_system()
        if self.lock_screen is not None:
            self.lock_screen.allow_close = True
            self.lock_screen.close()
            self.lock_screen = None
        self.update_tray_tooltip()
        self.save_config()

    def _is_rule_active_now(self, rule: LockRule) -> bool | None:
        now_dt = QDateTime.currentDateTime()
        today = now_dt.date()
        active_today = False
        if rule.repeat_type == "everyday":
            active_today = True
        elif rule.repeat_type == "weekly":
            weekday = today.dayOfWeek() - 1
            if weekday in rule.repeat_days:
                active_today = True
        elif rule.repeat_type == "once":
            if rule.single_date and today == rule.single_date:
                active_today = True
        if not active_today:
            return None
        start_t = rule.start_time
        end_t = rule.end_time
        start_dt = QDateTime(today, start_t)
        if start_t <= end_t:
            end_dt = QDateTime(today, end_t)
        else:
            end_dt = QDateTime(today.addDays(1), end_t)
        if start_dt <= now_dt < end_dt:
            return end_dt
        return None

    def check_schedule(self):
        if not self.monitoring:
            return
        active_unlock_times = []
        for rule in self.rules:
            if not rule.enabled:
                continue
            result = self._is_rule_active_now(rule)
            if result is not None:
                active_unlock_times.append(result)
        if active_unlock_times:
            latest_unlock = max(active_unlock_times)
            if self.lock_screen is None:
                self.lock_screen = LockScreen(latest_unlock)
                self.lock_screen.destroyed.connect(self._on_lock_screen_closed)
                self.lock_screen.showFullScreen()
                self.block_input(True)
                self.set_task_manager(True)
            else:
                self.lock_screen.set_unlock_datetime(latest_unlock)
        else:
            if self.lock_screen is not None:
                self._unlock_system()
                self.lock_screen.allow_close = True
                self.lock_screen.close()
                self.lock_screen = None

    # ---------- 配置存取 ----------
    def save_config(self):
        data = {
            "rules": [r.to_dict() for r in self.rules],
            "monitoring": self.monitoring,
            "next_id": self.next_rule_id,
            "autostart": self.autostart_enabled
        }
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.warning(self, "保存配置失败", f"无法写入配置文件: {e}")

    def load_config(self):
        if not self.config_path.exists():
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.rules = [LockRule.from_dict(d) for d in data.get("rules", [])]
            self.next_rule_id = data.get("next_id", 1)
            self.autostart_enabled = data.get("autostart", False)
            self._update_list()
            if data.get("monitoring", False):
                self.start_monitoring()
        except Exception as e:
            QMessageBox.warning(self, "加载配置失败", f"配置文件损坏或无法读取: {e}")


if __name__ == "__main__":
    if not is_admin() and '--elevated' not in sys.argv:
        run_as_admin()

    start_hidden = '--autostart' in sys.argv

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(start_hidden=start_hidden)
    sys.exit(app.exec())