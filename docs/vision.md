# 视觉集成

## 当前状态

- `GhostVision` 已在 NUC 上打通抓图、去畸变、棋盘定位、棋子识别和标准结果导出。
- `GhostChessboard` 已可读取该结果，转换为 `BoardState` / FEN，并调用 `Pikafish` 生成走法。
- 当前已验证“标准开局 → 识别 → FEN → 引擎出步”链路可直接跑通。
- 当前测试棋子为规整贴纸方案，直径约 `28mm`。

## 当前架构

- 主仓库不再内置相机采集、OpenCV 几何校正或本地识别流程。
- 主仓库接收外部视觉系统产出的标准化 JSON 结果，也可在场景验证时调用 GhostVision CLI 生成结果。
- 外部视觉系统可独立部署、独立选型；具体模型、依赖和推理链路由 `../GhostVision` 维护。
- 视觉仓库约定为同级独立目录 `../GhostVision`。
- 当前物理棋面为“引磁片直拖 + 棋子贴纸”，但视觉结果中的 `piece` 字段仍表示逻辑棋种，不受当前载体形态影响。

## 主仓库职责

- 读取并校验外部视觉结果。
- 将视觉结果投影为主仓库可用的 `BoardState`。
- 在 `--verify-vision` 场景复验中编排 GhostVision CLI。
- 保持运动控制与视觉实现解耦。

## 结果契约

入口代码：

- `src/vision/contracts.py`
- `src/vision/external.py`
- `src/vision/fen.py`
- `src/vision/probe.py`

CLI 调试入口：

- `python -m src.cli vision-result path/to/result.json --json`
- 若已安装命令入口，也可使用 `ghostchessboard vision-result path/to/result.json --json`
- 场景复验同理：未安装命令入口时使用 `python -m src.cli scenario <json> --verify-vision`

JSON 示例（必填：`provider`、`board_pieces`；`frame_id`、`produced_at`、`capture_pieces`、`pose`、`metadata` 均为可选）：

```json
{
  "provider": "ghostvision",
  "frame_id": "frame-001",
  "produced_at": "2026-04-09T10:00:00+08:00",
  "board_pieces": [
    {"cell": [0, 0], "piece": "r_ju", "confidence": 0.98},
    {"cell": [4, 0], "piece": "r_jiang", "confidence": 0.99}
  ],
  "capture_pieces": [
    {"slot": 3, "piece": "b_zu", "confidence": 0.87}
  ],
  "pose": {
    "corners_px": {
      "top_left": [10.0, 20.0],
      "top_right": [110.0, 20.0],
      "bottom_right": [110.0, 220.0],
      "bottom_left": [10.0, 220.0]
    },
    "main_board_points_px": {
      "0,0": [11.0, 21.0],
      "4,0": [55.0, 21.0]
    },
    "confidence": 0.95
  },
  "metadata": {
    "model": "rtmpose-4pt"
  }
}
```

## 约束

- `board_pieces` 中每个 `cell` 必须是主棋盘坐标，范围 `x=0..9`、`y=0..8`。
- `capture_pieces` 中每个 `slot` 必须在 `0..19`。
- 同一 `cell` 和同一 `slot` 不允许重复。
- `confidence` 省略时为未知；出现时必须是 `0..1` 的数字。
- `piece` 必须是非空字符串；转换 FEN 时仅支持 `r_jiang/r_shi/r_xiang/r_ma/r_ju/r_pao/r_zu` 和 `b_jiang/b_shi/b_xiang/b_ma/b_ju/b_pao/b_zu`。
- `pose` 为可选调试信息，不参与主仓库内部几何计算。
- `pose.corners_px` 若出现，必须同时包含 `top_left`、`top_right`、`bottom_right`、`bottom_left`。
- `pose.main_board_points_px` 的键使用 `"x,y"`，值使用 `[px_x, px_y]`。

## 扩展原则

- 识别稳定性、模型训练和相机参数优先在 `../GhostVision` 内维护。
- 若接入本地 IPC、HTTP 或串口协议，应复用当前 JSON 契约作为载荷格式。
