# GhostChessboard 幽灵棋盘

中国象棋自动对弈棋盘 —— **嵌入式**课程项目

## 项目简介

当前默认棋面载体为直接拖动的扁平棋片：以引磁片作载片，上表面贴棋子贴纸，由棋盘下方 XY 平台上的电磁铁拖动，在棋盘表面自动滑动，可用于人机对弈或 AI 演示。

## 文档

- [技术规划](docs/tech.md)
- [物料清单](docs/bom.md)
- [项目进度](docs/progress.md)
- [视觉集成](docs/vision.md)
- [GRBL 调试记录](docs/grbl.md)
- [电磁铁验证记录](docs/magnet.md)

## 仓库边界

- 当前仓库负责运动控制、棋盘状态接收与系统集成。
- 视觉推理链路已从当前仓库解耦，后续放在同级独立仓库 `../GhostVision`。
- 当前仓库只接收标准化外部视觉结果，不内置 OpenCV、本地采集或模型推理流程。

## 团队

| 成员 | 方向 |
|---|---|
| [@Victor-Quqi](https://github.com/Victor-Quqi) | 软件（视觉/AI/运动控制） |
| [@AmakusaMika](https://github.com/AmakusaMika) | 演示视频与 presentation 准备 |
