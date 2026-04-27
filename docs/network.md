# 现场网络

## 现场方案

- 手机开热点：`<PHONE_HOTSPOT_SSID>`。
- NUC 和演示电脑都连这个热点。
- WebUI 监听：`0.0.0.0:8080`，使用方式见 [`web.md`](web.md)。
- 浏览器访问：`http://<NUC-热点IP>:8080`。

最近一次验证（`2026-04-27`）：

```text
NUC WiFi: <PHONE_HOTSPOT_SSID>
NUC IP: <NUC_HOTSPOT_IP>
WebUI: http://<NUC_HOTSPOT_IP>:8080
MCP: <LOCAL_MCP_ALIAS>
```

查当前 IP：

```bash
nmcli -g IP4.ADDRESS device show <WIFI_IFACE>
```

## 自动切换

NUC 优先级：

```text
<PHONE_HOTSPOT_SSID>  300
<FALLBACK_WIFI_SSID>       50
```

timer：

```text
ghost-prefer-phone-hotspot.timer
```

检查：

```bash
systemctl status ghost-prefer-phone-hotspot.timer
journalctl -u ghost-prefer-phone-hotspot.service -n 30 --no-pager
```

开关：

```bash
sudo systemctl stop ghost-prefer-phone-hotspot.timer
sudo systemctl enable --now ghost-prefer-phone-hotspot.timer
```

## SSH 兜底

只在手机热点方案不可用时使用：

```powershell
ssh -N -L 22022:127.0.0.1:22022 <jump-user>@<jump-host>
ssh -N -L 8080:127.0.0.1:8080 -p 22022 <nuc-user>@127.0.0.1
```

访问：`http://127.0.0.1:8080`

## 注意

- 不用 NUC 自开热点。
- 不依赖 <PERSONAL_WIFI>。
- 同热点设备都可能访问 WebUI，不要随便共享热点密码。
