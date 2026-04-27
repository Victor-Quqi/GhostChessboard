# 现场网络

本文件只记录可公开的网络部署方式。真实 SSID、IP、公网跳板、用户名和 MCP
别名应写在本地私有笔记或运维配置中，不要提交到仓库。

## 现场方案

- 手机或现场路由器提供专用热点，例如 `<PHONE_HOTSPOT_SSID>`。
- NUC 和演示电脑都连这个热点。
- WebUI 监听：`0.0.0.0:8080`，使用方式见 [`web.md`](web.md)。
- 浏览器访问：`http://<NUC-热点IP>:8080`。

现场记录模板：

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
<FALLBACK_WIFI_SSID>   50
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
- 不依赖非现场专用 WiFi。
- 同热点设备都可能访问 WebUI，不要随便共享热点密码。
