# 本地字体与图标

运行时全部从本机 /assets 加载，不使用 Google Fonts、外部 CDN 或模型接口。来源、字节数与 SHA-256 见 manifest.json。

- 正文：思源黑体 SC Regular，Adobe 原始 OTF 转 WOFF2；保留原字形与字符覆盖。
- 中文标题：思源宋体 SC SemiBold，同上。
- 英文标题与拉丁字符：Space Grotesk 可变字体。
- 图标：Lucide 0.468.0，本地 UMD 包，统一 stroke-width=1.6。

原始字体缓存在 D:/CodexWork/cache/intent-workbench-assets。压缩时使用 D 盘研究虚拟环境已有的 fontTools 与新增的 brotli 1.2.1；生产运行不需要这些压缩依赖。C 盘既有 Python 基础解释器未迁移。

许可证原文随各资源保留。未修改字体设计。不要为展示界面而把正文裁剪为仅支持固定文案的字库。

## product-v5：按需字库

界面改用 Intent Sans SC，这是从本地思源黑体原件构建的分片字体。依据原字体保留名称条款，派生文件的 name/CFF 字体名称均改为 Intent Sans SC，原版权和OFL许可证保留。字体字形未重新设计。

`fonts.css`使用unicode-range按字符加载：常用字与界面字符一片，其余按Unicode区段拆分，完整保留原字体44,853个Unicode字符覆盖。每片字符集合互斥、并集等于原cmap，构建脚本逐片验证。`font-partitions.json`记录来源SHA-256、各片字符数量、字节数与哈希。

离线重建：D盘研究环境执行 `python -B scripts/build_font_subsets.py`；输入为 D:/CodexWork/cache/intent-workbench-assets/SourceHanSansSC.otf。开发依赖为fontTools和brotli，运行产品无需这些构建依赖。原完整字库仍保留用于追溯，当前界面不再请求它们。
