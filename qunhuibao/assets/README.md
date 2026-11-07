# 群汇报品牌与交互资源

本目录随 Python 包分发。`renderer.py` 读取并内嵌资源，生成页面不从网络加载 Logo、字体、CSS 或脚本。

- `tongcheng-logo.png`：AI同城圈原始 Logo 字节副本。正式来源 `D:/同城圈/LOGO/PNG.png`，复制入口 `C:/Users/cheng/.codex/tools/delivery-overview/assets/tongcheng-logo.png`。不重绘、不变色、不裁切。
- `qunhuibao-logo.png`：原版流线Q造型、群汇报及域名保留；2026-11-07按本人要求用imagegen局部编辑放大网址。2172×724 RGBA、Alpha 0—255，已目视核对拼写与造型。不是逐像素不变承诺；旧正式资源备份位于outputs/refine-20261107-hierarchy。根目录透明PNG同步更新。
- `tongcheng-proposal.css`：已确认的 `tongcheng-proposal-20261102` 品牌样式快照。正式来源 `D:/同城圈/公共素材库/品牌组件库/04-提案组件/提案完整样式.css`，复制入口为公共交付总览工具的同名文件。保留品牌橙、暖白、左右封面与编号导航卡片。
- `report.css`：本地群汇报的正文、引用、窄屏与打印布局补充。
- `report.js`：搜索定位、话题词云导航、复制行动清单与打印。静态脚本不含聊天输入，交互只读取页面文本。无后台同步或云端发布。
- `digest.css`：阅读版的功能布局补充，只负责重点、资料、问答、署名原话与清空按钮；暖橙浅底封面和编号导航复用tongcheng-proposal.css。2026-11-07已撤回擅自增加的深色封面、蓝绿配色及杂志字体。

原始资产 SHA256：

| 文件 | SHA256 |
| --- | --- |
| tongcheng-logo.png | fcd67fbb4d238624a58b03efe131a5610efc207c67a5944e753eff2f32128238 |
| tongcheng-proposal.css | dd09c28e5e182966dc65857ff7a0eb6e335eed32728154e6726ffd748eef6ae8 |

维护品牌时核对正式规范 `D:/坤晟的外脑/2-产品库/品牌视觉/推广提案统一使用同城圈品牌视觉-20261021.md`。这些路径只记录开发来源，生成页面不会将其展示或用于访问。
