# 字体资源（可选）

卡片内**中文文案**必须用支持 CJK 的字体，否则会显示为空白。当前逻辑：

1. **CJK 字体**（用于所有卡片文字）：优先本目录下的 `NotoSansSC-Regular.otf` / `NotoSansSC-Regular.ttf`，否则使用**系统字体**（macOS 苹方 PingFang、宋体 Songti，或 Linux Noto CJK）。
2. **Inter**（仅 year-sport 风格数字时用）：本目录或 `year-sport/assets/` 下的 `Inter-Bold.ttf`、`Inter-Regular.ttf`。卡片现已统一用 CJK 字体，Inter 可选。

**若中文仍不显示**：在本目录放入 Noto Sans SC 任一即可：

- 下载 [Noto Sans SC](https://fonts.google.com/noto/specimen/Noto+Sans+SC) 的 `NotoSansSC-Regular.otf` 或 `NotoSansSC-Regular.ttf`，放到本目录。
- macOS 一般无需额外安装，会使用系统自带的苹方。
