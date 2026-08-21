# 弧光木牌商店插件 (ARC Sign Shop Plugin)

[![版本](https://img.shields.io/badge/版本-0.2.0-blue.svg)](https://github.com/DEVILENMO/EndstoneMC-ARC-Sign-Shop-Plugin)
[![EndStone](https://img.shields.io/badge/EndStone-0.10+-green.svg)](https://github.com/EndstoneMC/endstone)

用木牌创建商店：右键开店/交易，牌面自动显示商店信息。

## 商店类型

| 类型 | 说明 |
|------|------|
| 玩家出售 | 玩家卖货 |
| 玩家收购 | 玩家收购 |
| 玩家交易 | 以物易物 |
| 官方出售 | OP：自动定价或手动定价（系统无限） |
| 官方收购 | OP：自动定价或手动定价（系统无限） |

### 官方定价方式

建官方出售/收购时先选：

- **自动定价**：依赖 [弧光市场经济](https://github.com/DEVILENMO/EndstoneMC-ARC-Market-Economy-Plugin)（`arc_market_economy`），动态价 + 日波动 + 成交调价
- **手动定价**：OP 自填固定单价，仍为系统无限店，不回调市场

## 木牌文案示例

```
[官方商店-收购]
物品：钻石
价格：100
库存：∞
```

## 指令

| 指令 | 权限 | 说明 |
|------|------|------|
| `/ss` | 玩家 | 主面板 |
| `/ss qs start [sell\|buy]` | OP | 快速设置官方**自动**定价店 |
| `/ss qs stop` | OP | 结束快速设置 |
| `/ssmanage` | OP | 商店管理；`prices` 等会转发市场经济 |

市场管理请用：`/market prices|reload|reset`

## 依赖

- `arc_inventory`（必须）
- `arc_core` 或 `umoney`（经济）
- `arc_market_economy`（自动定价必须；仅手动官方店时可无）

## 安装

1. 安装市场经济 + 木牌商店 wheel 到 `plugins`
2. 数据目录：`plugins/ARCSignShop/`
3. 官方价目在市场经济：`plugins/ARCMarketEconomy/official_prices.yml`
