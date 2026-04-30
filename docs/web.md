# Web 控制台

Web 控制台用于现场对弈、硬件调试、日志查看和摄像头预览。网络与 IP 查询见 [`network.md`](network.md)。

## 安装依赖

在 NUC 上使用独立虚拟环境：

```bash
python3 -m venv --system-site-packages .web-venv
.web-venv/bin/python -m pip install -r requirements-web.txt
```

`requirements-web.txt` 包含 FastAPI/Uvicorn、摄像头预览所需的 OpenCV，以及 `web-stop` 进程管理所需的 psutil。

## 启动与停止

启动：

```bash
GHOSTCHESSBOARD_WEB_PASSWORD=your-password .web-venv/bin/python -m src.cli web --host 0.0.0.0 --port 8080
```

停止指定端口上的 Web 控制台：

```bash
.web-venv/bin/python -m src.cli web-stop --port 8080
```

若要先查看匹配到的进程：

```bash
.web-venv/bin/python -m src.cli web-stop --port 8080 --dry-run
```

`web-stop` 会优先读取 `.ghostchessboard-web-<port>.pid`，找不到有效 PID 时再按端口监听进程回退查找。

## 配置入口

- `GHOSTCHESSBOARD_WEB_PASSWORD`：共享登录密码；未设置时允许空密码登录。
- `GHOSTCHESSBOARD_PIKAFISH`：Pikafish 可执行文件路径；未设置时 Web 端 AI 走子不可用。
- `GHOSTCHESSBOARD_WEB_STATE_PATH`：Web 棋局状态保存路径；未设置时只保存在进程内存。
- 其它默认值见 `src/config.py` 的 `WebConfig`；可用 `--config` 覆盖。

## 现场约定

- 同一热点内设备都可能访问 WebUI，不要共享热点密码或 Web 密码。
- WebUI 支持两个席位；只能操作自己颜色一方的回合。
- Web 端走子会通过 GRBL 执行实体运动；小车位置不确定时，先在界面记录当前位置。
- “同步视觉”会暂停摄像头预览，调用 GhostVision 获取当前棋面，再恢复预览。
- 如果一方在 WebUI 走子、另一方直接在实体棋盘走子，使用“同步视觉”更新 Web 状态；能唯一解释为合法走子时会推进回合，否则按视觉结果更新棋盘并保留告警。

## 摄像头预览

默认设备为 `/dev/video0`，默认参数见 `src/config.py` 的 `web.video_*` 配置。摄像头被 GhostVision 抓图占用时，Web 预览会短暂停止并在抓图后重启。
