# 弧光木牌商店插件 (ARC Sign Shop Plugin)

[![版本](https://img.shields.io/badge/版本-1.0.7-blue.svg)](https://github.com/ARC-Minecraft/EndstoneMC-ARC-Sign-Shop-Plugin)
[![EndStone](https://img.shields.io/badge/EndStone-0.10+-green.svg)](https://github.com/EndstoneMC/endstone)

用木牌创建商店：右键开店/交易。牌面文字需 Endstone 0.12+，当前正式版下牌面保持空白，商店功能全靠右键交互（见文末说明）。

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

将 `endstone_arc_sign_shop-1.0.7-*.whl` 放入服务器 `plugins` 目录后重启。数据目录：`plugins/ARCSignShop/`。

## 关于牌面文字

`endstone.block.Sign` 只存在于 Endstone 的 `develop` 分支（[ee4106d](https://github.com/EndstoneMC/endstone/commit/ee4106dd3b18e7d6f2a57719dc3b1e392aadf452)，2026-08-10），它在 `v0.11` 分支切出之后才合入，因此正式版 **0.11.9** 及后续 0.11.x 补丁都不包含，预计随 0.12 发布。你在 [latest 文档](https://endstone.dev/latest/reference/python/block/#endstone.block.Sign) 看到的是开发版，对应正式版的是 [stable 文档](https://endstone.dev/stable/reference/python/block/)。

基岩版没有可写方块实体 NBT 的原生命令（`/data` 是 Java 版的），所以在 Sign 发布前无法写牌面。插件会自动探测该 API：装上带 Sign 的版本后无需改配置，牌面即开始显示商店信息。
