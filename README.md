# 弧光木牌商店插件 (ARC Sign Shop Plugin)

[![版本](https://img.shields.io/badge/版本-0.1.0-blue.svg)](https://github.com/DEVILENMO/EndstoneMC-ARC-Sign-Shop-Plugin)
[![EndStone](https://img.shields.io/badge/EndStone-0.10+-green.svg)](https://github.com/EndstoneMC/endstone)

基于按钮商店改造的 **木牌商店**：右键木牌开店/交易，牌面自动显示商店信息。

## 商店类型（仅此五类）

| 类型 | 说明 |
|------|------|
| 玩家出售 | 玩家卖货给其他玩家 |
| 玩家收购 | 玩家收购其他玩家的物品 |
| 玩家交易 | 以物易物（物品 B 换物品 A） |
| 官方出售 | OP / 官方定价，系统无限出售 |
| 官方收购 | OP / 官方定价，系统无限回收 |

## 木牌文案示例

```
[官方商店-收购]
物品：钻石
价格：100
库存：∞
```

建店与交易后会自动刷新正面四行文字，并打蜡防止玩家手改。

## 指令

| 指令 | 权限 | 说明 |
|------|------|------|
| `/ss` | 所有玩家 | 打开木牌商店主面板 |
| `/ss qs start [sell\|buy]` | OP | 快速设置官方出售/收购（默认 sell） |
| `/ss qs stop` | OP | 结束快速设置 |
| `/ssmanage` | OP | 管理与定价命令 |

快速设置：手持物品 → 右键木牌 → 建成官方商店。未在 `official_prices.yml` 配置的物品暂以 **99999** 作为售价占位。

## 依赖

- `arc_inventory`（必须）
- `arc_core` 或 `umoney`（经济，优先 arc_core）

## 安装

1. 将 wheel 放入服务器 `plugins`
2. 重启后数据目录：`plugins/ARCSignShop/`
3. 官方价目：`plugins/ARCSignShop/official_prices.yml`

## 与按钮商店关系

独立插件，不替换 `arc_button_shop`。入口命令为 `/ss`，数据表为 `sign_shops`。
