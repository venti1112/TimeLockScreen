# 时间管理锁屏 (TimeLockScreen)

一个基于 PySide6 的 Windows 桌面应用，可按照设定的时间规则自动锁定屏幕，帮助管理使用时长、防止过度用眼或控制儿童/员工的电脑使用时段。支持全屏覆盖、输入设备锁定、任务管理器禁用以及开机自启等功能。

## 功能特性

- 🔒 **全屏锁屏**  
  在锁定时段显示全屏黑底界面，带倒计时、系统锁屏提示，并阻止键盘输入。

- ⏱ **灵活的规则配置**  
  支持三种重复类型：  
  - **每天**：每日固定时间段锁定  
  - **每周特定**：可选择周一至周日中若干天  
  - **仅一次**：指定日期当日锁定

- 🚫 **强制锁屏**  
  锁定期间会自动禁用键盘/鼠标输入（通过 `BlockInput`）并禁止任务管理器（通过注册表），防止绕过锁定。

- 📋 **开机自启**  
  通过 Windows 任务计划程序以最高权限创建登录时运行的任务，无需每次手动启动，且避免 UAC 弹窗。

- 🖥 **系统托盘**  
  最小化至系统托盘，支持右键菜单快速显示/退出，双击恢复窗口。

- 💾 **配置持久化**  
  规则、运行状态和开机启动设置保存为 JSON 文件，便于管理和备份。

## 安装与依赖

### 环境要求

- Windows 操作系统（Windows 10/11 推荐）
- Python 3.8 或更高版本
- 管理员权限（程序自动请求）

### 安装依赖
```bash
pip install -r requirements.txt
```

### 从源码运行

```bash
python main.pyw
```

首次运行可能触发 UAC 弹窗请求管理员权限，请允许。

### 打包为独立 EXE

推荐使用 PyInstaller：

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --uac-admin --icon=lock_icon.ico --add-data "icon.ico;." main.pyw
```

## 使用指南

### 1. 添加规则

点击 **添加规则**，在弹出窗口中设置：

- 开始时间 / 结束时间
- 重复类型：每天 / 每周特定 / 仅一次
- 若选择“每周特定”，勾选所需星期
- 若选择“仅一次”，指定日期

### 2. 启动监控

点击 **开始监控**，程序将每秒检查所有启用的规则。一旦当前时间落入某个规则的时间段，屏幕将立即锁定并显示倒计时，直到规则结束时间到达。

### 3. 停止监控

点击 **停止监控** 可关闭锁屏并恢复正常。

### 4. 开机自启

勾选 **开机自动启动**，程序会通过 `schtasks` 创建计划任务，以最高权限在用户登录时自动运行，并直接进入后台监控状态。

### 5. 系统托盘

关闭主窗口时，程序会最小化至系统托盘，监控在后台持续运行。右键托盘图标可显示窗口或完全退出。

## 配置文件

规则和设置存储在 `lock_rules.json` 文件中（位于可执行文件或脚本所在目录）。格式示例：
```json
{
  "rules": [
    {
        "id": 1,
        "start_time": "22:00",
        "end_time": "06:00",
        "repeat_type": "everyday",
        "enabled": true
    },
    {
        "id": 2,
        "start_time": "14:00",
        "end_time": "15:30",
        "repeat_type": "weekly",
        "repeat_days": [0, 2, 4],
        "enabled": true
    },
    {
        "id": 3,
        "start_time": "08:00",
        "end_time": "12:00",
        "repeat_type": "once",
        "single_date": "2026-05-20",
        "enabled": true
    }],
    "monitoring": true,
    "next_id": 4,
    "autostart": true
}
```

## 注意事项

1. **权限要求**  
   锁定输入设备和修改注册表需要管理员权限。程序会通过 `--elevated` 参数重新启动自身请求提权。

2. **强制关闭风险**  
   在锁屏状态下，任务管理器默认被禁用。如需紧急停止程序，请使用安全模式或通过 Ctrl+Alt+Del 注销当前用户（锁屏仅在当前会话有效）。

3. **防火墙/杀毒软件**  
   某些安全软件可能阻止 `BlockInput` 或注册表写入，建议将程序加入白名单。

4. **计划任务自启**  
   使用任务计划程序实现开机自启，任务名为 `TimeLockScreen`。如需手动移除，可运行：

    ```bash
    schtasks /Delete /F /TN "TimeLockScreen"
    ```

   或取消勾选“开机自动启动”并保存。

## 开发与结构

```tree
    .
    ├── main.pyw             # 主程序
    ├── lock_rules.json      # 配置文件
    ├── icon.ico             # 图标
    └── README.md
```

核心类说明：
- `LockRule`：规则数据模型
- `LockScreen`：全屏锁定窗口（含倒计时）
- `RuleDialog`：规则编辑对话框
- `MainWindow`：主窗口，管理规则列表、监控循环、系统托盘、会话通知和自启

监控通过每秒定时器触发，比对当前时间与所有规则，取最早结束时间进行锁定。

## 许可证

本项目（即本仓库中除第三方组件以外的代码）以 [MIT License](LICENSE) 许可发布。

### 第三方组件

本软件使用了以下第三方库：

- **PySide6** (Qt for Python)
  版权所有 © 2026 The Qt Company Ltd.
  PySide6 以 GNU Lesser General Public License v3 (LGPLv3) 许可发布。
  完整的 LGPLv3 文本可以从 https://www.gnu.org/licenses/lgpl-3.0.html 获取。

## 致谢

- **[SelfControlLock](https://github.com/savhc/SelfControlLock)**
  本软件的锁屏时间管理思路受到了该项目的启发。  
  感谢作者将创意开源，为同类工具的开发提供了有价值的参考。

- **[PySide6](https://wiki.qt.io/Qt_for_Python)** 
  提供了强大的 GUI 框架支持。