# 弧光木牌商店插件 (ARC Sign Shop Plugin)

[![版本](https://img.shields.io/badge/版本-1.0.6-blue.svg)](https://github.com/ARC-Minecraft/EndstoneMC-ARC-Sign-Shop-Plugin)
[![EndStone](https://img.shields.io/badge/EndStone-0.10+-green.svg)](https://github.com/EndstoneMC/endstone)

用木牌创建商店：右键开店/交易，牌面自动显示商店信息。

## 商店类型

| 类型 | 说明 |
|------|------|
| 玩家出售 / 收购 / 交易 | 玩家自营 |
| **官方商店（默认）** | 出售+回收**二合一** + 市场经济自动定价；管理里可关闭出售或回收，降级为单功能 |
| 官方手动 | 固定单价的仅出售或仅回收系统无限店 |

## 官方定价方式

- **自动定价**：依赖 [弧光市场经济](https://github.com/ARC-Minecraft/EndstoneMC-ARC-Market-Economy-Plugin)，默认建二合一时，玩家交互再选买/卖
- **手动定价**：OP 自填固定单价（仅出售或仅回收）

## 指令

| 指令 | 权限 | 说明 |
|------|------|------|
| `/ss` | 玩家 | 主面板 |
| `/ss qs start` | OP | 快速设置：**默认二合一 + 自动定价** |
| `/ss qs start both\|sell\|buy` | OP | 指定模式快速设置 |
| `/ss qs stop` | OP | 结束快速设置 |
| `/ssmanage` | OP | 商店管理 |

市场管理请用：`/market prices|reload|reset`

## 依赖

- `arc_inventory`（必须）
- `arc_core` 或 `umoney`（经济）
- `arc_market_economy`（自动定价必须；仅手动官方店时可无）

## 安装

将 `endstone_arc_sign_shop-1.0.6-*.whl` 放入服务器 `plugins` 目录后重启。数据目录：`plugins/ARCSignShop/`。

> 说明：`endstone.block.Sign` 目前仅在 [latest 文档](https://endstone.dev/latest/reference/python/block/#endstone.block.Sign) 出现，PyPI **0.11.9** 尚未导出。本插件在无 Sign 时回退为 `/data merge block` 写牌面；Endstone 正式放出 Sign 后会自动走原生 API。
