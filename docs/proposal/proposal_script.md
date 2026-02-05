# Ghost Chessboard Proposal 演讲稿

> 5分钟演讲，两人分工

---

## 【成员A / Member A】约2分钟

### Slide 1: 封面 / Title

| 中文 | English |
|------|---------|
| 大家好，我们是XXX和XXX，我们的项目叫 Ghost Chessboard，幽灵棋盘。先给大家看一段视频。 | Hello everyone, we are XXX and XXX. Our project is called Ghost Chessboard. Let me show you a short video first. |

---

### Slide 2: 引入 / Introduction

（播放 Wizard Chess 视频片段 / Play Wizard Chess video clip）

| 中文 | English |
|------|---------|
| 刚才视频里是哈利波特的巫师棋，棋子可以自己移动，吃子的时候还会把对方打烂。我们想做一个类似的东西——当然，打烂对方棋子这个功能我们做不了，但至少棋子能自己动。 | That was the wizard chess from Harry Potter — pieces move on their own and smash each other when capturing. We want to build something similar. We can't do the smashing part, but at least the pieces will move by themselves. |

---

### Slide 3: Purpose of the System

| 中文 | English |
|------|---------|
| 基本原理是这样的：棋盘下方有一个 XY 运动平台，上面装着电磁铁。棋子底部贴有铁片，电磁铁通电后就能吸住棋子，然后拖着它移动。 | The basic idea is: there's an XY platform under the board with an electromagnet. Each piece has an iron plate at the bottom. When powered, the electromagnet grabs and drags the piece. |
| 棋盘上方有摄像头拍摄棋局，系统识别后控制棋子移动。 | A camera above captures the board, and the system recognizes the position and controls piece movement. |
| 我们的目标是做一个能完成基本走子的演示系统。 | Our goal is a demo system that performs basic piece movements. |

---

| 中文 | English |
|------|---------|
| 下面由我的队友介绍系统结构和其他细节。 | Now my teammate will cover the system structure and other details. |

---

## 【成员B / Member B】约2分钟

### Slide 4: Model

| 中文 | English |
|------|---------|
| 这是我们预期的成品效果图。当然，实际做出来肯定没这么好看。 | This is a concept image of our final product. Of course, the real thing won't look this good. |
| 外观上就是一个棋盘，棋子摆在上面，后面有个支架装摄像头。所有的机械结构都藏在底座里面。 | It looks like a regular chess board with pieces on top and a camera arm at the back. All the mechanics are hidden inside the base. |

---

### Slide 5: Budget Planning

（PPT 上展示表格，口述要点 / Show table on slide, verbally highlight key points）

| 中文 | English |
|------|---------|
| 这是预算表。主要成本是 XY 框架套件 449 元，加上控制板、电磁铁、摄像头这些，目前预算约 800 元。主机还在选型，确定后会有调整。 | Here's the budget. The main cost is the XY frame kit at 449 CNY. With controller, electromagnet, camera and other parts, current budget is around 800 CNY. The main computer is still TBD. |

**表格 / Table（展示用）：**

| 项目 / Item | 价格 / Price (CNY) |
|-------------|-------------------|
| XY 框架套件 / XY frame kit | 449 |
| 控制板+驱动 / Controller+drivers | ~115 |
| 电磁铁 / Electromagnet | ~30 |
| 摄像头+灯带 / Camera+LED | ~56 |
| 磁铁+引磁片 / Magnets+iron plates | ~21 |
| 亚克力板 / Acrylic panels | ~50 |
| 12V 10A 电源 / Power supply | ~35 |
| 主机 / Main computer | TBD |
| 杂项 / Misc | ~30 |
| **合计 / Total** | **~800+** |

---

### Slide 6: Working Schedule

（PPT 上展示表格，口述要点 / Show table on slide, verbally summarize）

| 中文 | English |
|------|---------|
| 时间安排：2 月采购，3 月搭建硬件和开发软件，4 月调试，月底展示。 | Schedule: purchasing in February, hardware and software in March, testing in April, demo at month end. |

**表格 / Table（展示用）：**

| 阶段 / Phase | 时间 / Time |
|--------------|-------------|
| 采购 / Purchasing | 2月 / Feb |
| 硬件搭建 / Hardware | 3月上旬 / Early Mar |
| 软件开发 / Software | 3月 / Mar |
| 调试 / Testing | 4月 / Apr |

---

### Slide 7: Workload Breakdown

| 中文 | English |
|------|---------|
| 分工方面，XXX 主要负责硬件，XXX 主要负责软件，调试一起做。 | For workload, XXX handles hardware, XXX handles software, and we test together. |

**表格 / Table（展示用）：**

| 工作 / Work | 负责人 / Person |
|-------------|----------------|
| 硬件 / Hardware | XXX |
| 软件 / Software | XXX |
| 调试 / Testing | 共同 / Both |

---

### Slide 8: END

| 中文 | English |
|------|---------|
| 以上就是我们的项目介绍，谢谢大家。 | That's our project. Thank you. |
