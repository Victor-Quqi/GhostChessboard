const state = {
  payload: null,
  selected: null,
  ws: null,
  showCoords: false,
  videoRotationDeg: 90,
};

const MAX_RENDERED_LOGS = 200;
const COORD_LONG_PRESS_MS = 450;
const COORD_CLICK_SUPPRESS_MS = 800;

const pieceText = {
  r_jiang: "帅",
  r_shi: "仕",
  r_xiang: "相",
  r_ma: "马",
  r_ju: "车",
  r_pao: "炮",
  r_zu: "兵",
  b_jiang: "将",
  b_shi: "士",
  b_xiang: "象",
  b_ma: "马",
  b_ju: "车",
  b_pao: "炮",
  b_zu: "卒",
};

const sideText = {
  red: "红方",
  black: "黑方",
};

const sideLogText = {
  red: "red",
  black: "black",
};

const SVG_NS = "http://www.w3.org/2000/svg";
const X_CELL_PITCH_MM = 370 / 9;
const Y_CELL_PITCH_MM = 337 / 8;

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(payload.detail || `HTTP ${response.status}`);
  }
  return payload;
}

function post(path, body = {}) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

function cellKey(x, y) {
  return `${x},${y}`;
}

function pieceSide(piece) {
  return piece && piece.startsWith("r_") ? "red" : "black";
}

function pieceAt(payload, x, y) {
  const pieces = payload?.state?.board_pieces || [];
  return pieces.find((item) => item.cell[0] === x && item.cell[1] === y)?.piece || null;
}

function canOperate() {
  const current = state.payload?.state;
  const user = current?.user;
  if (current?.game_over) {
    return false;
  }
  if (!current || !user || current.hardware.busy) {
    return false;
  }
  if (user.color !== current.side_to_move) {
    return false;
  }
  return true;
}

function canActForTurn() {
  const current = state.payload?.state;
  const user = current?.user;
  if (current?.game_over) {
    return false;
  }
  if (!current || !user || current.hardware.busy) {
    return false;
  }
  return user.color === current.side_to_move;
}

function seatsText(seats = []) {
  if (!seats.length) {
    return "-";
  }
  return seats.map((seat) => `${seat.id}:${sideText[seat.color] || seat.color}`).join(" / ");
}

function compactNumber(value) {
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) {
    return value;
  }
  const digits = Math.abs(parsed) >= 1000 ? 1 : 3;
  return parsed.toFixed(digits).replace(/\.?0+$/, "");
}

function formatHardwareStatus(rawStatus) {
  if (!rawStatus) {
    return "空闲";
  }
  const raw = String(rawStatus).trim();
  const match = raw.match(/^<([^|>]+)(?:\|(.+))?>$/);
  if (!match) {
    return raw.replace(/[<>]/g, "").replace(/\|/g, " ");
  }

  const parts = [match[1]];
  const fields = match[2] ? match[2].split("|") : [];
  for (const field of fields) {
    if (field.startsWith("MPos:")) {
      const values = field.slice(5).split(",");
      ["X", "Y", "Z", "A"].forEach((axis, index) => {
        if (values[index] !== undefined) {
          parts.push(`${axis}${compactNumber(values[index])}`);
        }
      });
    } else if (field.startsWith("WPos:")) {
      const values = field.slice(5).split(",");
      ["X", "Y", "Z", "A"].forEach((axis, index) => {
        if (values[index] !== undefined) {
          parts.push(`${axis}${compactNumber(values[index])}`);
        }
      });
    } else if (field.startsWith("FS:")) {
      const [feed, spindle] = field.slice(3).split(",");
      if (feed !== undefined) {
        parts.push(`F${compactNumber(feed)}`);
      }
      if (spindle !== undefined) {
        parts.push(`S${compactNumber(spindle)}`);
      }
    } else if (field.startsWith("Pn:")) {
      parts.push(`Pn:${field.slice(3)}`);
    } else {
      parts.push(field.replace(":", ""));
    }
  }
  return parts.join(" ");
}

function riverTurnText(current, user) {
  if (current.game_over) {
    return terminalDisplayText(current);
  }
  const side = sideText[current.side_to_move] || current.side_to_move;
  if (!user) {
    return `当前回合：${side}`;
  }
  if (current.hardware.busy) {
    return `${side}回合 · 硬件执行中`;
  }
  if (user.color !== current.side_to_move) {
    return `${side}回合 · 等待席位`;
  }
  return `当前回合：${side}`;
}

function terminalDisplayText(current) {
  if (!current?.game_over) {
    return "";
  }
  if (current.winner) {
    return `${sideText[current.winner] || current.winner}获胜`;
  }
  if (current.reason === "stalemate") {
    return "无合法步 · 和棋";
  }
  return "对局结束";
}

function terminalDetailText(current) {
  if (!current?.game_over) {
    return "";
  }
  if (current.reason === "checkmate" && current.winner) {
    const loser = current.winner === "red" ? "黑方" : "红方";
    return `${loser}被将死，${sideText[current.winner] || current.winner}获胜。`;
  }
  if (current.reason === "stalemate") {
    return "当前方无合法步且未被将军，判为和棋。";
  }
  return current.message || "对局已结束。";
}

function cellJogTarget(direction) {
  const current = state.payload?.state?.carriage_cell;
  if (!Array.isArray(current) || current.length !== 2) {
    throw new Error("小车格点未知，先设置小车位置。");
  }
  const target = [Number(current[0]), Number(current[1])];
  if (direction === "x+") {
    target[0] += 1;
  } else if (direction === "x-") {
    target[0] -= 1;
  } else if (direction === "y+") {
    target[1] += 1;
  } else if (direction === "y-") {
    target[1] -= 1;
  }
  if (target[0] < 0 || target[0] > 9 || target[1] < 0 || target[1] > 10) {
    throw new Error(`目标格点越界：${target.join(",")}`);
  }
  return target;
}

function cellJogDelta(direction) {
  return {
    dx_mm: direction === "x+" ? X_CELL_PITCH_MM : direction === "x-" ? -X_CELL_PITCH_MM : 0,
    dy_mm: direction === "y+" ? Y_CELL_PITCH_MM : direction === "y-" ? -Y_CELL_PITCH_MM : 0,
  };
}

function targetCellFromInputs() {
  const cell = [
    Number.parseInt($("carriageX").value, 10),
    Number.parseInt($("carriageY").value, 10),
  ];
  if (!Number.isInteger(cell[0]) || !Number.isInteger(cell[1])) {
    throw new Error("小车目标格点必须是整数。");
  }
  if (cell[0] < 0 || cell[0] > 9 || cell[1] < 0 || cell[1] > 10) {
    throw new Error(`目标格点越界：${cell.join(",")}`);
  }
  return cell;
}

function deltaToCell(target) {
  const current = state.payload?.state?.carriage_cell;
  if (!Array.isArray(current) || current.length !== 2) {
    throw new Error("小车格点未知，先只记录当前位置。");
  }
  return {
    dx_mm: (target[0] - Number(current[0])) * X_CELL_PITCH_MM,
    dy_mm: (target[1] - Number(current[1])) * Y_CELL_PITCH_MM,
  };
}

function syncCarriageInputs(cell) {
  if (!Array.isArray(cell) || cell.length !== 2) {
    return;
  }
  if (document.activeElement === $("carriageX") || document.activeElement === $("carriageY")) {
    return;
  }
  $("carriageX").value = String(cell[0]);
  $("carriageY").value = String(cell[1]);
}

function render(payload) {
  if (!payload?.state) {
    return;
  }
  state.payload = payload;
  renderVideoRotation();
  const current = payload.state;
  const user = current.user;
  const turnCell = $("turnLabel").closest(".status-cell");
  turnCell.classList.toggle("terminal", Boolean(current.game_over));
  $("turnLabel").textContent = current.game_over
    ? terminalDisplayText(current)
    : sideText[current.side_to_move] || "-";
  $("turnLabel").title = current.game_over ? terminalDetailText(current) : "";
  $("seatLabel").textContent = user ? `${sideText[user.color]} ${user.id}` : "-";
  $("seatsLabel").textContent = seatsText(current.seats);
  const hardwareText = current.hardware.busy ? "忙" : formatHardwareStatus(current.hardware.status);
  $("busyLabel").textContent = hardwareText;
  $("busyLabel").title = current.hardware.status || hardwareText;
  $("busyLabel").style.color = current.hardware.busy ? "var(--amber)" : "var(--green)";
  $("carriageLabel").textContent = current.carriage_cell ? current.carriage_cell.join(",") : "未知";
  $("warningLine").textContent = current.game_over
    ? terminalDetailText(current)
    : current.sync_warning || "";
  $("visionLabel").textContent = current.last_vision?.frame_id
    ? `frame ${current.last_vision.frame_id}`
    : "等待同步";
  const aiReady = current.ai?.engine_available !== false;
  $("aiButton").textContent = current.game_over
    ? "对局已结束"
    : aiReady
    ? `AI 为${sideText[current.side_to_move] || current.side_to_move}走子`
    : "AI 未配置";
  $("aiButton").title = current.game_over
    ? terminalDetailText(current)
    : aiReady
    ? `让 AI 为当前回合的${sideText[current.side_to_move] || current.side_to_move}计算并执行一步`
    : "Pikafish 未配置：设置 GHOSTCHESSBOARD_PIKAFISH 或 web.ai_engine_path";
  syncCarriageInputs(current.carriage_cell);
  $("seatSelect").value = user?.color || "red";
  $("switchSeatButton").disabled = !user?.can_switch_color;

  const disabled = current.hardware.busy;
  document.querySelectorAll("button").forEach((button) => {
    if (!["logoutButton", "switchSeatButton", "videoRotateButton"].includes(button.id)) {
      button.disabled = disabled;
    }
  });
  $("aiButton").disabled = disabled || current.game_over || !aiReady || !canActForTurn();
  $("switchSeatButton").disabled = disabled || !user?.can_switch_color;

  renderBoard();
  if (payload.logs) {
    renderLogs(payload.logs);
  }
}

function renderBoard() {
  const grid = $("boardGrid");
  grid.innerHTML = "";
  const current = state.payload?.state;
  grid.appendChild(createBoardLines());
  grid.appendChild(createRiverBand(current, current?.user));
  const selectedKey = state.selected ? cellKey(state.selected[0], state.selected[1]) : null;
  for (let x = 9; x >= 0; x -= 1) {
    for (let y = 0; y <= 8; y += 1) {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "cell";
      cell.dataset.x = String(x);
      cell.dataset.y = String(y);
      const key = cellKey(x, y);
      if (key === selectedKey) {
        cell.classList.add("selected");
      }
      if (canOperate()) {
        cell.classList.add("targetable");
      }

      if (state.showCoords) {
        const coord = document.createElement("span");
        coord.className = "coord";
        coord.textContent = key;
        cell.appendChild(coord);
      }

      const coordHint = document.createElement("span");
      coordHint.className = "coord-popover";
      coordHint.textContent = key;
      cell.appendChild(coordHint);

      const piece = pieceAt(state.payload, x, y);
      if (piece) {
        const pieceNode = document.createElement("span");
        pieceNode.className = `piece ${pieceSide(piece)}`;
        pieceNode.textContent = pieceText[piece] || "?";
        cell.appendChild(pieceNode);
      }
      setupCellCoordinateHint(cell);
      cell.addEventListener("click", () => {
        if (cell.dataset.suppressClick === "true") {
          cell.dataset.suppressClick = "";
          return;
        }
        handleCellClick(x, y);
      });
      grid.appendChild(cell);
    }
  }
  const readout = $("moveReadout");
  if (state.selected) {
    const piece = pieceAt(state.payload, state.selected[0], state.selected[1]);
    readout.textContent = `已选择 ${pieceText[piece] || piece} @ ${state.selected.join(",")}`;
  } else if (current?.game_over) {
    readout.textContent = terminalDetailText(current);
  } else {
    readout.textContent = "未选择棋子";
  }
}

function renderVideoRotation() {
  const frame = $("videoFrame");
  frame.classList.remove("video-rotate-0", "video-rotate-90", "video-rotate-180", "video-rotate-270");
  frame.classList.add(`video-rotate-${state.videoRotationDeg}`);
  $("videoRotateButton").textContent = `旋转 ${state.videoRotationDeg}°`;
  $("videoRotateButton").title = `当前画面旋转 ${state.videoRotationDeg}°；点击后顺时针再转 90°`;
}

function setupCellCoordinateHint(cell) {
  let longPressTimer = null;
  let suppressClickClearTimer = null;

  const clearLongPressTimer = () => {
    if (longPressTimer !== null) {
      window.clearTimeout(longPressTimer);
      longPressTimer = null;
    }
  };

  const clearSuppressClickClearTimer = () => {
    if (suppressClickClearTimer !== null) {
      window.clearTimeout(suppressClickClearTimer);
      suppressClickClearTimer = null;
    }
  };

  const scheduleSuppressClickClear = () => {
    clearSuppressClickClearTimer();
    suppressClickClearTimer = window.setTimeout(() => {
      suppressClickClearTimer = null;
      cell.dataset.suppressClick = "";
    }, COORD_CLICK_SUPPRESS_MS);
  };

  cell.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "touch") {
      return;
    }
    clearLongPressTimer();
    clearSuppressClickClearTimer();
    cell.dataset.suppressClick = "";
    longPressTimer = window.setTimeout(() => {
      longPressTimer = null;
      cell.classList.add("coord-pressed");
      cell.dataset.suppressClick = "true";
    }, COORD_LONG_PRESS_MS);
  });

  for (const eventName of ["pointerup", "pointercancel", "pointerleave"]) {
    cell.addEventListener(eventName, () => {
      clearLongPressTimer();
      if (cell.classList.contains("coord-pressed")) {
        window.setTimeout(() => cell.classList.remove("coord-pressed"), 700);
        scheduleSuppressClickClear();
      }
    });
  }

  cell.addEventListener("click", clearSuppressClickClearTimer, { capture: true });
}

function createBoardLines() {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.classList.add("board-lines");
  svg.setAttribute("viewBox", "0 0 8 9");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");

  for (let row = 0; row <= 9; row += 1) {
    appendSvgLine(svg, 0, row, 8, row);
  }
  for (let col = 0; col <= 8; col += 1) {
    if (col === 0 || col === 8) {
      appendSvgLine(svg, col, 0, col, 9);
    } else {
      appendSvgLine(svg, col, 0, col, 4);
      appendSvgLine(svg, col, 5, col, 9);
    }
  }
  appendSvgLine(svg, 3, 0, 5, 2, "palace-line");
  appendSvgLine(svg, 5, 0, 3, 2, "palace-line");
  appendSvgLine(svg, 3, 7, 5, 9, "palace-line");
  appendSvgLine(svg, 5, 7, 3, 9, "palace-line");
  return svg;
}

function appendSvgLine(svg, x1, y1, x2, y2, extraClass = "") {
  const line = document.createElementNS(SVG_NS, "line");
  line.setAttribute("x1", String(x1));
  line.setAttribute("y1", String(y1));
  line.setAttribute("x2", String(x2));
  line.setAttribute("y2", String(y2));
  line.setAttribute("class", extraClass ? `line ${extraClass}` : "line");
  svg.appendChild(line);
}

function createRiverBand(current, user) {
  const band = document.createElement("div");
  band.className = "river-band";

  const chu = document.createElement("span");
  chu.className = "river-word";
  chu.textContent = "楚河";
  band.appendChild(chu);

  const turn = document.createElement("strong");
  turn.className = "river-turn";
  turn.textContent = current ? riverTurnText(current, user) : "当前回合：-";
  band.appendChild(turn);

  const han = document.createElement("span");
  han.className = "river-word";
  han.textContent = "汉界";
  band.appendChild(han);

  return band;
}

async function handleCellClick(x, y) {
  if (!canOperate()) {
    return;
  }
  const current = state.payload.state;
  const piece = pieceAt(state.payload, x, y);
  if (!state.selected) {
    if (piece && pieceSide(piece) === current.side_to_move) {
      state.selected = [x, y];
      renderBoard();
    }
    return;
  }

  const start = state.selected;
  state.selected = null;
  if (start[0] === x && start[1] === y) {
    renderBoard();
    return;
  }

  try {
    const payload = await post("/api/move", { start, end: [x, y] });
    render(payload);
  } catch (error) {
    appendLocalLog("error", error.message);
    renderBoard();
  }
}

function renderLogs(entries) {
  const list = $("logList");
  list.innerHTML = "";
  for (const entry of entries.slice(-MAX_RENDERED_LOGS)) {
    appendLogNode(entry);
  }
  list.scrollTop = list.scrollHeight;
}

function appendLocalLog(level, message) {
  appendLog({ level, message, created_at: Date.now() / 1000 });
  const list = $("logList");
  list.scrollTop = list.scrollHeight;
}

function appendLog(entry) {
  if (state.payload) {
    const logs = [...(state.payload.logs || []), entry].slice(-MAX_RENDERED_LOGS);
    state.payload = { ...state.payload, logs };
  }
  appendLogNode(entry);
}

function appendLogNode(entry) {
  const list = $("logList");
  const row = document.createElement("div");
  row.className = `log-entry ${entry.level}`;
  const time = new Date(entry.created_at * 1000).toLocaleTimeString("zh-CN", { hour12: false });
  row.innerHTML = `<span class="time">${time}</span><span class="level">${entry.level}</span><span></span>`;
  row.lastElementChild.textContent = entry.message;
  list.appendChild(row);
}

function connectWs() {
  if (state.ws) {
    state.ws.close();
  }
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${location.host}/ws`);
  state.ws = ws;
  ws.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "state") {
      const merged = { ...state.payload?.state, ...payload.state };
      if (!payload.state.user && state.payload?.state?.user) {
        merged.user = state.payload.state.user;
      }
      render({ state: merged, logs: state.payload?.logs || [] });
    } else if (payload.type === "log") {
      appendLog(payload.entry);
      const list = $("logList");
      list.scrollTop = list.scrollHeight;
    } else if (payload.type === "video_restart") {
      restartVideo();
    } else if (payload.state) {
      render(payload);
    }
  });
  ws.addEventListener("close", () => {
    if (!$("loginLayer").classList.contains("hidden")) {
      return;
    }
    setTimeout(connectWs, 1600);
  });
}

async function refreshState() {
  const payload = await api("/api/state");
  render(payload);
  return payload;
}

function restartVideo() {
  $("videoImage").src = `/api/video.mjpg?t=${Date.now()}`;
}

function enterConsole() {
  $("loginLayer").classList.add("hidden");
  if (!$("videoImage").src) {
    restartVideo();
  }
  connectWs();
}

function setupEvents() {
  $("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("loginError").textContent = "";
    try {
      await post("/api/login", { password: $("passwordInput").value });
      await refreshState();
      enterConsole();
    } catch (error) {
      $("loginError").textContent = error.message;
    }
  });

  $("logoutButton").addEventListener("click", async () => {
    await post("/api/logout");
    location.reload();
  });

  $("switchSeatButton").addEventListener("click", async () => {
    try {
      const payload = await post("/api/seat", { color: $("seatSelect").value });
      await refreshState();
      appendLocalLog("info", `Seat switched to ${sideLogText[payload.user.color] || payload.user.color}.`);
    } catch (error) {
      appendLocalLog("error", error.message);
    }
  });
  $("coordToggle").addEventListener("change", () => {
    state.showCoords = $("coordToggle").checked;
    renderBoard();
  });
  $("videoRotateButton").addEventListener("click", () => {
    state.videoRotationDeg = (state.videoRotationDeg + 90) % 360;
    renderVideoRotation();
  });

  $("syncButton").addEventListener("click", () => runAndRender("/api/vision/sync", { force: false }));
  $("forceSyncButton").addEventListener("click", () => runAndRender("/api/vision/sync", { force: true }));
  $("resetGameButton").addEventListener("click", () => {
    if (window.confirm("确认已把棋子摆回开局，并将小车当前位置记录为 0,0？")) {
      runAndRender("/api/game/reset", {});
    }
  });
  $("aiButton").addEventListener("click", () => runAndRender("/api/ai-move", {}));
  $("statusButton").addEventListener("click", () => runAndRender("/api/grbl/status", {}));
  $("magnetOnButton").addEventListener("click", () => runAndRender("/api/magnet", { state: "on" }));
  $("magnetOffButton").addEventListener("click", () => runAndRender("/api/magnet", { state: "off" }));
  $("moveCarriageButton").addEventListener("click", async () => {
    try {
      const target = targetCellFromInputs();
      const delta = deltaToCell(target);
      if (delta.dx_mm !== 0 || delta.dy_mm !== 0) {
        render(await post("/api/jog", delta));
      }
      render(await post("/api/carriage", { cell: target }));
    } catch (error) {
      appendLocalLog("error", error.message);
    }
  });
  $("setCarriageButton").addEventListener("click", () => {
    try {
      runAndRender("/api/carriage", { cell: targetCellFromInputs() });
    } catch (error) {
      appendLocalLog("error", error.message);
    }
  });
  $("resetCarriageButton").addEventListener("click", () => runAndRender("/api/carriage", { reset: true }));

  document.querySelectorAll("[data-jog]").forEach((button) => {
    button.addEventListener("click", () => {
      const step = Number.parseFloat($("jogStepInput").value) || 0;
      const direction = button.dataset.jog;
      const body = {
        dx_mm: direction === "x+" ? step : direction === "x-" ? -step : 0,
        dy_mm: direction === "y+" ? step : direction === "y-" ? -step : 0,
      };
      runAndRender("/api/jog", body);
    });
  });

  document.querySelectorAll("[data-cell-jog]").forEach((button) => {
    button.addEventListener("click", async () => {
      const direction = button.dataset.cellJog;
      try {
        const target = cellJogTarget(direction);
        render(await post("/api/jog", cellJogDelta(direction)));
        render(await post("/api/carriage", { cell: target }));
      } catch (error) {
        appendLocalLog("error", error.message);
      }
    });
  });
}

async function boot() {
  try {
    await refreshState();
    enterConsole();
  } catch {
    $("loginLayer").classList.remove("hidden");
  }
}

async function runAndRender(path, body) {
  try {
    const payload = await post(path, body);
    render(payload);
  } catch (error) {
    const message = error.message;
    $("warningLine").textContent = message;
    try {
      await refreshState();
      if (!state.payload?.state?.game_over) {
        $("warningLine").textContent = message;
      }
    } catch {
      // Keep the inline error visible if the state endpoint is unavailable.
    }
  } finally {
    if (path === "/api/vision/sync") {
      restartVideo();
    }
  }
}

setupEvents();
renderVideoRotation();
boot();
