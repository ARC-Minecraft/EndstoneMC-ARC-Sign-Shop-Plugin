import os
import json
import random
import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple


MAIN_PATH = 'plugins/ARCSignShop'


class PriceManager:
    """官方定价管理器 - 管理统一价格配置、动态定价和每日波动"""

    PLACEHOLDER_SELL_PRICE = 99999  # 快速设置时未配置物品的临时出售价

    def __init__(self, plugin):
        self.plugin = plugin
        self.official_prices = {}  # item_type -> {'sell': float, 'buy': float, 'display_name'?, 'category'?}
        self.price_adjustments = {}  # item_type -> {'demand_sell_adjust': float, 'demand_buy_adjust': float, 'daily_adjust_percent': float, 'last_updated': str}
        self.config_path = Path(MAIN_PATH) / "official_prices.yml"
        self.category_order = []
        self._last_daily_reset_date = None
        self._last_recovery_time = None
        self._load_config()

    @property
    def _settings(self):
        return self.plugin.setting_manager

    def _safe_log(self, level: str, message: str):
        if hasattr(self.plugin, '_safe_log'):
            self.plugin._safe_log(level, message)
        else:
            print(f"[{level.upper()}] {message}")

    # ==================== 配置加载 ====================

    def _load_config(self):
        """加载官方定价配置文件"""
        self.config_path.parent.mkdir(exist_ok=True)

        if not self.config_path.exists():
            self._create_default_config()
            return

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self._parse_config(content)
            count = len(self.official_prices)
            self._safe_log('info', f"[ARCSignShop] Loaded official prices: {count} items from {self.config_path}")
            if count == 0:
                self._safe_log(
                    'warning',
                    f"[ARCSignShop] official_prices.yml exists but 0 items parsed "
                    f"(path={self.config_path}, bytes={len(content.encode('utf-8'))})"
                )
        except Exception as e:
            import traceback
            self._safe_log(
                'error',
                f"[ARCSignShop] Failed to load official_prices.yml: {e}\n{traceback.format_exc()}"
            )
            self.official_prices = {}

    def _create_default_config(self):
        """创建默认配置文件"""
        default_content = """# 官方定价配置文件
# 物品类型: 出售价(sell)和回收价(buy)
# sell: 玩家从系统商店购买的价格
# buy: 玩家出售给系统商店的价格
# display_name: 可选，商店列表中的显示名称（建议填中文）
# 注意: buy 必须小于 sell，否则回收功能会被自动暂停

prices:
  # ========== 矿物与宝石 ==========
  minecraft:diamond:
    display_name: 钻石
    sell: 10000
    buy: 5000
  minecraft:iron_ingot:
    display_name: 铁锭
    sell: 200
    buy: 100
  minecraft:gold_ingot:
    display_name: 金锭
    sell: 1000
    buy: 500
  minecraft:coal:
    display_name: 煤炭
    sell: 40
    buy: 20
  minecraft:emerald:
    display_name: 绿宝石
    sell: 8000
    buy: 4000
  minecraft:lapis_lazuli:
    display_name: 青金石
    sell: 300
    buy: 150
  minecraft:redstone:
    sell: 60
    buy: 30
  minecraft:netherite_ingot:
    sell: 100000
    buy: 50000
  minecraft:netherite_scrap:
    sell: 30000
    buy: 15000
  minecraft:quartz:
    sell: 80
    buy: 40
  minecraft:copper_ingot:
    sell: 50
    buy: 25
  minecraft:amethyst_shard:
    sell: 120
    buy: 60
  minecraft:ancient_debris:
    sell: 60000
    buy: 30000

  # ========== 矿石方块 ==========
  minecraft:diamond_block:
    sell: 90000
    buy: 45000
  minecraft:iron_block:
    sell: 1800
    buy: 900
  minecraft:gold_block:
    sell: 9000
    buy: 4500
  minecraft:emerald_block:
    sell: 72000
    buy: 36000
  minecraft:lapis_block:
    sell: 2700
    buy: 1350
  minecraft:redstone_block:
    sell: 540
    buy: 270
  minecraft:coal_block:
    sell: 360
    buy: 180
  minecraft:copper_block:
    sell: 450
    buy: 225
  minecraft:netherite_block:
    sell: 900000
    buy: 450000
  minecraft:obsidian:
    sell: 100
    buy: 50

  # ========== 工具与武器 ==========
  minecraft:diamond_sword:
    sell: 25000
    buy: 12500
  minecraft:diamond_pickaxe:
    sell: 30000
    buy: 15000
  minecraft:diamond_axe:
    sell: 30000
    buy: 15000
  minecraft:diamond_shovel:
    sell: 12000
    buy: 6000
  minecraft:diamond_hoe:
    sell: 25000
    buy: 12500
  minecraft:iron_sword:
    sell: 500
    buy: 250
  minecraft:iron_pickaxe:
    sell: 600
    buy: 300
  minecraft:iron_axe:
    sell: 600
    buy: 300
  minecraft:iron_shovel:
    sell: 300
    buy: 150
  minecraft:iron_hoe:
    sell: 500
    buy: 250
  minecraft:stone_sword:
    sell: 100
    buy: 50
  minecraft:stone_pickaxe:
    sell: 100
    buy: 50
  minecraft:stone_axe:
    sell: 100
    buy: 50
  minecraft:wooden_sword:
    sell: 20
    buy: 10
  minecraft:wooden_pickaxe:
    sell: 20
    buy: 10
  minecraft:wooden_axe:
    sell: 20
    buy: 10
  minecraft:bow:
    sell: 600
    buy: 300
  minecraft:crossbow:
    sell: 1000
    buy: 500
  minecraft:trident:
    sell: 80000
    buy: 40000
  minecraft:shears:
    sell: 200
    buy: 100
  minecraft:flint_and_steel:
    sell: 200
    buy: 100

  # ========== 防具 ==========
  minecraft:diamond_helmet:
    sell: 60000
    buy: 30000
  minecraft:diamond_chestplate:
    sell: 100000
    buy: 50000
  minecraft:diamond_leggings:
    sell: 85000
    buy: 42500
  minecraft:diamond_boots:
    sell: 50000
    buy: 25000
  minecraft:iron_helmet:
    sell: 1000
    buy: 500
  minecraft:iron_chestplate:
    sell: 1600
    buy: 800
  minecraft:iron_leggings:
    sell: 1400
    buy: 700
  minecraft:iron_boots:
    sell: 800
    buy: 400
  minecraft:netherite_helmet:
    sell: 150000
    buy: 75000
  minecraft:netherite_chestplate:
    sell: 250000
    buy: 125000
  minecraft:netherite_leggings:
    sell: 200000
    buy: 100000
  minecraft:netherite_boots:
    sell: 120000
    buy: 60000
  minecraft:shield:
    sell: 600
    buy: 300
  minecraft:elytra:
    sell: 200000
    buy: 100000
  minecraft:turtle_helmet:
    sell: 4000
    buy: 2000

  # ========== 食物 ==========
  minecraft:apple:
    sell: 30
    buy: 15
  minecraft:golden_apple:
    sell: 4000
    buy: 2000
  minecraft:enchanted_golden_apple:
    sell: 100000
    buy: 50000
  minecraft:bread:
    sell: 20
    buy: 10
  minecraft:cooked_porkchop:
    sell: 40
    buy: 20
  minecraft:cooked_beef:
    sell: 50
    buy: 25
  minecraft:cooked_chicken:
    sell: 40
    buy: 20
  minecraft:cooked_mutton:
    sell: 40
    buy: 20
  minecraft:cooked_cod:
    sell: 30
    buy: 15
  minecraft:cooked_salmon:
    sell: 30
    buy: 15
  minecraft:golden_carrot:
    sell: 3000
    buy: 1500
  minecraft:pumpkin_pie:
    sell: 50
    buy: 25
  minecraft:cake:
    sell: 100
    buy: 50
  minecraft:cookie:
    sell: 16
    buy: 8
  minecraft:melon_slice:
    sell: 10
    buy: 5
  minecraft:sweet_berries:
    sell: 10
    buy: 5
  minecraft:baked_potato:
    sell: 24
    buy: 12
  minecraft:mushroom_stew:
    sell: 60
    buy: 30
  minecraft:rabbit_stew:
    sell: 100
    buy: 50
  minecraft:beetroot_soup:
    sell: 50
    buy: 25

  # ========== 农业与种植 ==========
  minecraft:wheat:
    sell: 16
    buy: 8
  minecraft:wheat_seeds:
    sell: 6
    buy: 3
  minecraft:carrot:
    sell: 10
    buy: 5
  minecraft:potato:
    sell: 10
    buy: 5
  minecraft:beetroot:
    sell: 10
    buy: 5
  minecraft:pumpkin_seeds:
    sell: 10
    buy: 5
  minecraft:melon_seeds:
    sell: 10
    buy: 5
  minecraft:beetroot_seeds:
    sell: 10
    buy: 5
  minecraft:nether_wart:
    sell: 40
    buy: 20
  minecraft:sugar_cane:
    sell: 16
    buy: 8
  minecraft:cocoa_beans:
    sell: 20
    buy: 10

  # ========== 炼药与酿造 ==========
  minecraft:blaze_rod:
    sell: 600
    buy: 300
  minecraft:blaze_powder:
    sell: 300
    buy: 150
  minecraft:ghast_tear:
    sell: 1000
    buy: 500
  minecraft:magma_cream:
    sell: 200
    buy: 100
  minecraft:fermented_spider_eye:
    sell: 60
    buy: 30
  minecraft:spider_eye:
    sell: 20
    buy: 10
  minecraft:glass_bottle:
    sell: 10
    buy: 5
  minecraft:brewing_stand:
    sell: 1000
    buy: 500
  minecraft:cauldron:
    sell: 800
    buy: 400

  # ========== 红石与机械 ==========
  minecraft:redstone_torch:
    sell: 100
    buy: 50
  minecraft:repeater:
    sell: 160
    buy: 80
  minecraft:comparator:
    sell: 240
    buy: 120
  minecraft:piston:
    sell: 300
    buy: 150
  minecraft:sticky_piston:
    sell: 500
    buy: 250
  minecraft:observer:
    sell: 400
    buy: 200
  minecraft:hopper:
    sell: 1000
    buy: 500
  minecraft:dispenser:
    sell: 400
    buy: 200
  minecraft:dropper:
    sell: 300
    buy: 150
  minecraft:noteblock:
    sell: 200
    buy: 100
  minecraft:tnt:
    sell: 600
    buy: 300
  minecraft:lever:
    sell: 20
    buy: 10
  minecraft:stone_button:
    sell: 10
    buy: 5

  # ========== 建筑材料 ==========
  minecraft:dirt:
    sell: 2
    buy: 1
  minecraft:stone:
    sell: 10
    buy: 5
  minecraft:cobblestone:
    sell: 6
    buy: 3
  minecraft:stone_bricks:
    sell: 16
    buy: 8
  minecraft:oak_planks:
    sell: 10
    buy: 5
  minecraft:spruce_planks:
    sell: 10
    buy: 5
  minecraft:birch_planks:
    sell: 10
    buy: 5
  minecraft:glass:
    sell: 16
    buy: 8
  minecraft:sand:
    sell: 6
    buy: 3
  minecraft:sandstone:
    sell: 16
    buy: 8
  minecraft:bricks:
    sell: 20
    buy: 10
  minecraft:clay_ball:
    sell: 10
    buy: 5
  minecraft:nether_bricks:
    sell: 20
    buy: 10
  minecraft:quartz_block:
    sell: 720
    buy: 360
  minecraft:purpur_block:
    sell: 60
    buy: 30

  # ========== 装饰与杂项 ==========
  minecraft:torch:
    sell: 10
    buy: 5
  minecraft:lantern:
    sell: 100
    buy: 50
  minecraft:soul_lantern:
    sell: 100
    buy: 50
  minecraft:campfire:
    sell: 160
    buy: 80
  minecraft:bone_meal:
    sell: 10
    buy: 5
  minecraft:ink_sac:
    sell: 16
    buy: 8
  minecraft:glowstone_dust:
    sell: 40
    buy: 20
  minecraft:glow_ink_sac:
    sell: 80
    buy: 40
  minecraft:string:
    sell: 10
    buy: 5
  minecraft:feather:
    sell: 10
    buy: 5
  minecraft:leather:
    sell: 20
    buy: 10
  minecraft:slime_ball:
    sell: 40
    buy: 20
  minecraft:egg:
    sell: 10
    buy: 5
  minecraft:arrow:
    sell: 6
    buy: 3
  minecraft:bucket:
    sell: 200
    buy: 100

  # ========== 稀有与特殊物品 ==========
  minecraft:ender_pearl:
    sell: 400
    buy: 200
  minecraft:ender_eye:
    sell: 800
    buy: 400
  minecraft:nether_star:
    sell: 60000
    buy: 30000
  minecraft:totem_of_undying:
    sell: 100000
    buy: 50000
  minecraft:dragon_breath:
    sell: 10000
    buy: 5000
  minecraft:experience_bottle:
    sell: 100
    buy: 50
  minecraft:name_tag:
    sell: 1000
    buy: 500
  minecraft:lead:
    sell: 200
    buy: 100
  minecraft:saddle:
    sell: 600
    buy: 300
  minecraft:enchanted_book:
    sell: 2000
    buy: 1000
  minecraft:firework_rocket:
    sell: 40
    buy: 20
  minecraft:banner:
    sell: 100
    buy: 50

  # ========== 海洋相关 ==========
  minecraft:prismarine_shard:
    sell: 60
    buy: 30
  minecraft:prismarine_crystals:
    sell: 160
    buy: 80
  minecraft:nautilus_shell:
    sell: 2000
    buy: 1000
  minecraft:heart_of_the_sea:
    sell: 60000
    buy: 30000
  minecraft:scute:
    sell: 400
    buy: 200

  # ========== 下界相关 ==========
  minecraft:soul_sand:
    sell: 30
    buy: 15
  minecraft:netherrack:
    sell: 2
    buy: 1
  minecraft:basalt:
    sell: 10
    buy: 5
  minecraft:blackstone:
    sell: 16
    buy: 8
  minecraft:crying_obsidian:
    sell: 400
    buy: 200
  minecraft:respawn_anchor:
    sell: 24000
    buy: 12000

  # ========== 末地相关 ==========
  minecraft:end_stone:
    sell: 20
    buy: 10
  minecraft:chorus_fruit:
    sell: 30
    buy: 15
  minecraft:shulker_shell:
    sell: 4000
    buy: 2000
  minecraft:ender_chest:
    sell: 3000
    buy: 1500
  minecraft:end_rod:
    sell: 60
    buy: 30

  # ========== 染料 ==========
  minecraft:black_dye:
    sell: 20
    buy: 10
  minecraft:red_dye:
    sell: 20
    buy: 10
  minecraft:green_dye:
    sell: 20
    buy: 10
  minecraft:brown_dye:
    sell: 20
    buy: 10
  minecraft:blue_dye:
    sell: 20
    buy: 10
  minecraft:yellow_dye:
    sell: 20
    buy: 10
  minecraft:white_dye:
    sell: 20
    buy: 10
  minecraft:pink_dye:
    sell: 20
    buy: 10
  minecraft:orange_dye:
    sell: 20
    buy: 10
  minecraft:light_blue_dye:
    sell: 20
    buy: 10
  minecraft:magenta_dye:
    sell: 20
    buy: 10
  minecraft:lime_dye:
    sell: 20
    buy: 10
  minecraft:cyan_dye:
    sell: 20
    buy: 10
  minecraft:purple_dye:
    sell: 20
    buy: 10
  minecraft:light_gray_dye:
    sell: 20
    buy: 10
  minecraft:gray_dye:
    sell: 20
    buy: 10
"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                f.write(default_content)
            self._parse_config(default_content)
            self._safe_log('info', f"[ARCSignShop] Created default official_prices.yml ({len(self.official_prices)} items)")
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Failed to create default config: {e}")

    def _parse_config(self, content: str):
        """解析YAML配置（简化版，不依赖PyYAML）"""
        self.official_prices = {}
        self.category_order = []  # 分类显示顺序（来自 yml 分区注释）

        lines = content.split('\n')
        current_section = None
        current_item = None
        current_category = '其他'

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # 分区注释: # ========== 矿物与宝石 ==========
            if stripped.startswith('#'):
                if current_section == 'prices' and '====' in stripped:
                    name = stripped.lstrip('#').replace('=', '').strip()
                    if name:
                        current_category = name
                        if name not in self.category_order:
                            self.category_order.append(name)
                continue

            # 计算缩进层级
            indent = len(line) - len(line.lstrip())

            if stripped.startswith('prices:'):
                current_section = 'prices'
                continue

            if current_section == 'prices':
                # 物品类型行，如 "  minecraft:diamond:"（命名空间本身含冒号）
                if indent == 2 and ':' in stripped and not stripped.startswith(('sell:', 'buy:', 'display_name:', 'category:')):
                    if stripped.endswith(':'):
                        current_item = stripped[:-1].strip()
                    else:
                        # 兼容 "minecraft:diamond: 100" 这类行内写法
                        current_item = stripped.rsplit(':', 1)[0].strip()
                    if current_item and current_item not in self.official_prices:
                        self.official_prices[current_item] = {'category': current_category}
                    elif current_item:
                        self.official_prices[current_item].setdefault('category', current_category)
                # sell/buy/display_name/category 字段行
                elif indent == 4 and current_item:
                    if stripped.startswith('sell:'):
                        try:
                            price = float(stripped.split(':', 1)[1].strip())
                            self.official_prices[current_item]['sell'] = price
                        except (ValueError, IndexError):
                            pass
                    elif stripped.startswith('buy:'):
                        try:
                            price = float(stripped.split(':', 1)[1].strip())
                            self.official_prices[current_item]['buy'] = price
                        except (ValueError, IndexError):
                            pass
                    elif stripped.startswith('display_name:'):
                        value = stripped.split(':', 1)[1].strip()
                        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                            value = value[1:-1]
                        if value:
                            self.official_prices[current_item]['display_name'] = value
                    elif stripped.startswith('category:'):
                        value = stripped.split(':', 1)[1].strip()
                        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                            value = value[1:-1]
                        if value:
                            self.official_prices[current_item]['category'] = value
                            if value not in self.category_order:
                                self.category_order.append(value)

        # 兜底：有物品但未进 category_order 的分类
        for prices in self.official_prices.values():
            cat = prices.get('category') or '其他'
            prices['category'] = cat
            if cat not in self.category_order:
                self.category_order.append(cat)

        self._safe_log(
            'info',
            f"[ARCSignShop] Parsed {len(self.official_prices)} official prices "
            f"in {len(self.category_order)} categories"
        )

    def reload_config(self):
        """重新加载配置文件"""
        self.official_prices = {}
        self.category_order = []
        self._load_config()

    # ==================== 价格查询 ====================

    def has_official_price(self, item_type: str) -> bool:
        """检查物品是否有官方定价"""
        return item_type in self.official_prices

    def get_base_price(self, item_type: str, shop_type: str) -> Optional[int]:
        """获取物品基准价格"""
        if item_type not in self.official_prices:
            if shop_type == 'sell':
                return self.PLACEHOLDER_SELL_PRICE
            return None
        prices = self.official_prices[item_type]
        if shop_type == 'sell':
            return prices.get('sell')
        else:
            return prices.get('buy')

    def get_all_priced_items(self) -> Dict:
        """获取所有有官方定价的物品"""
        return dict(self.official_prices)

    def get_category_order(self) -> list:
        """获取分类显示顺序"""
        return list(getattr(self, 'category_order', []) or [])

    def get_items_by_category(self, category: str) -> Dict:
        """获取某一分类下的官方定价物品"""
        return {
            item_type: prices
            for item_type, prices in self.official_prices.items()
            if (prices.get('category') or '其他') == category
        }

    def get_category_counts(self) -> Dict[str, int]:
        """各分类物品数量"""
        counts: Dict[str, int] = {}
        for prices in self.official_prices.values():
            cat = prices.get('category') or '其他'
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    def get_item_display_name(self, item_type: str) -> str:
        """获取物品显示名称：优先 official_prices.yml 的 display_name，否则从类型名提取"""
        prices = self.official_prices.get(item_type) or {}
        configured = prices.get('display_name')
        if configured:
            return configured
        # minecraft:diamond -> Diamond
        name = item_type.split(':')[-1] if ':' in item_type else item_type
        return name.replace('_', ' ').title()

    # ==================== 动态定价 ====================

    def get_price_adjustment(self, item_type: str) -> Dict:
        """获取物品的当前价格调整状态"""
        if item_type not in self.price_adjustments:
            return {
                'demand_sell_adjust': 0.0,
                'demand_buy_adjust': 0.0,
                'daily_adjust_percent': 0.0,
                'sell_amount_accumulated': 0.0,
                'buy_amount_accumulated': 0.0,
                'sell_link_adjust': 0.0,
                'last_updated': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        return self.price_adjustments[item_type]

    def calculate_final_price(self, item_type: str, shop_type: str, discount_percent: float = 0.0) -> Optional[int]:
        """
        计算最终价格
        shop_type: 'sell'(玩家购买) 或 'buy'(玩家出售给商店)
        discount_percent: 商店级折扣百分比（负数=优惠，正数=加价）
        """
        base_price = self.get_base_price(item_type, shop_type)
        if base_price is None:
            return None

        adjustments = self.get_price_adjustment(item_type)

        if shop_type == 'sell':
            demand_adj = adjustments['demand_sell_adjust']
        else:
            # 回收价 = 需求降价 + 出售联动涨价
            demand_adj = adjustments['demand_buy_adjust'] + adjustments.get('sell_link_adjust', 0.0)

        daily_adj = adjustments['daily_adjust_percent'] / 100.0

        # 最终价格 = 基准价 * (1 + 需求调整 + 日波动) * (1 + 折扣/100)
        multiplier = (1.0 + demand_adj + daily_adj) * (1.0 + discount_percent / 100.0)
        final_price = round(base_price * multiplier)

        # 确保价格不低于1
        final_price = max(1, final_price)

        # 防御：回收价不得高于或等于出售价 → 禁用回收（只卖不收）
        # 当计算回收价时，同时计算出售价，若 buy >= sell 则返回 None 禁用回收
        if shop_type == 'buy':
            sell_price = self.calculate_final_price(item_type, 'sell', discount_percent)
            if sell_price is not None and final_price >= sell_price:
                return None

        return final_price

    def is_buy_disabled(self, item_type: str, discount_percent: float = 0.0) -> bool:
        """检查回收是否因价格反超而被禁用"""
        buy_price = self.calculate_final_price(item_type, 'buy', discount_percent)
        return buy_price is None

    def record_trade_volume(self, item_type: str, shop_type: str, quantity: int, db_manager, total_amount: float = 0):
        """记录交易量用于动态定价
        
        Args:
            item_type: 物品类型
            shop_type: 商店类型 ('sell'=玩家购买, 'buy'=玩家出售)
            quantity: 交易数量
            db_manager: 数据库管理器
            total_amount: 交易总金额（单价×数量），用于金额阈值触发涨价
        """
        if not self._settings.GetSettingBool('dynamic_pricing_enabled'):
            return

        try:
            # 记录交易流水（用于审计）
            trade_data = {
                'item_type': item_type,
                'trade_type': shop_type,  # 'sell'=玩家购买, 'buy'=玩家出售
                'quantity': quantity,
                'total_amount': total_amount,
                'trade_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            db_manager.insert("item_trade_volume", trade_data)

            # 累加交易金额到 price_adjustments 的累计字段
            current = self.get_price_adjustment(item_type)
            if shop_type == 'sell':
                current['sell_amount_accumulated'] = current.get('sell_amount_accumulated', 0.0) + total_amount
            else:
                current['buy_amount_accumulated'] = current.get('buy_amount_accumulated', 0.0) + total_amount
            current['last_updated'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.price_adjustments[item_type] = current

            # 持久化累计金额到数据库
            self._save_price_adjustment(item_type, db_manager)

        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Record trade volume error: {e}")

    def update_demand_pricing(self, item_type: str, db_manager):
        """根据累计交易金额更新需求驱动的价格调整
        
        涨价逻辑：出售交易累计金额每达到 sell_amount_per_percent 就涨价1%，然后减去已消耗金额
        降价逻辑：收购交易累计金额每达到 buy_amount_per_percent 就降价1%，然后减去已消耗金额
        联动逻辑：出售涨价时，回收价联动涨 sell_buy_link_ratio 比例（如0.5则出售涨1%回收联动涨0.5%）
        这样避免长期运行后累计金额数值溢出
        """
        if not self._settings.GetSettingBool('dynamic_pricing_enabled'):
            return

        try:
            sell_amount_per_percent = self._settings.GetSettingFloat('dynamic_pricing_sell_amount_per_percent', 10000)
            buy_amount_per_percent = self._settings.GetSettingFloat('dynamic_pricing_buy_amount_per_percent', 10000)
            max_sell_increase = self._settings.GetSettingFloat('dynamic_pricing_max_sell_increase', 0.50)
            max_buy_decrease = self._settings.GetSettingFloat('dynamic_pricing_max_buy_decrease', 0.30)
            sell_buy_link_ratio = self._settings.GetSettingFloat('dynamic_pricing_sell_buy_link_ratio', 0.5)

            current = self.get_price_adjustment(item_type)
            sell_accumulated = current.get('sell_amount_accumulated', 0.0)
            buy_accumulated = current.get('buy_amount_accumulated', 0.0)

            # 出售涨价：计算累计金额达到阈值的次数，每次涨1%
            if sell_amount_per_percent > 0 and sell_accumulated >= sell_amount_per_percent:
                sell_times = int(sell_accumulated / sell_amount_per_percent)
                demand_sell_adjust = min(
                    current.get('demand_sell_adjust', 0.0) + sell_times * 0.01,
                    max_sell_increase
                )
                # 减去已消耗的金额
                consumed_sell = sell_times * sell_amount_per_percent
                sell_accumulated -= consumed_sell
                current['demand_sell_adjust'] = demand_sell_adjust
                current['sell_amount_accumulated'] = sell_accumulated

                # 出售-回收联动：出售涨价时，回收价也联动涨价
                if sell_buy_link_ratio > 0:
                    current['sell_link_adjust'] = demand_sell_adjust * sell_buy_link_ratio

            # 收购降价：计算累计金额达到阈值的次数，每次降1%
            if buy_amount_per_percent > 0 and buy_accumulated >= buy_amount_per_percent:
                buy_times = int(buy_accumulated / buy_amount_per_percent)
                demand_buy_adjust = max(
                    current.get('demand_buy_adjust', 0.0) - buy_times * 0.01,
                    -max_buy_decrease
                )
                # 减去已消耗的金额
                consumed_buy = buy_times * buy_amount_per_percent
                buy_accumulated -= consumed_buy
                current['demand_buy_adjust'] = demand_buy_adjust
                current['buy_amount_accumulated'] = buy_accumulated

            current['last_updated'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.price_adjustments[item_type] = current

            # 持久化到数据库
            self._save_price_adjustment(item_type, db_manager)

        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Update demand pricing error: {e}")

    def _save_price_adjustment(self, item_type: str, db_manager):
        """保存价格调整到数据库"""
        try:
            adj = self.price_adjustments.get(item_type)
            if not adj:
                return

            existing = db_manager.query_one(
                "SELECT id FROM price_adjustments WHERE item_type = ?",
                (item_type,)
            )

            data = {
                'demand_sell_adjust': adj['demand_sell_adjust'],
                'demand_buy_adjust': adj['demand_buy_adjust'],
                'daily_adjust_percent': adj['daily_adjust_percent'],
                'sell_amount_accumulated': adj.get('sell_amount_accumulated', 0.0),
                'buy_amount_accumulated': adj.get('buy_amount_accumulated', 0.0),
                'sell_link_adjust': adj.get('sell_link_adjust', 0.0),
                'last_updated': adj['last_updated']
            }

            if existing:
                db_manager.update(
                    table='price_adjustments',
                    data=data,
                    where='item_type = ?',
                    params=(item_type,)
                )
            else:
                data['item_type'] = item_type
                db_manager.insert('price_adjustments', data)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Save price adjustment error: {e}")

    def load_price_adjustments_from_db(self, db_manager):
        """从数据库加载价格调整状态"""
        try:
            rows = db_manager.query_all("SELECT * FROM price_adjustments")
            if rows:
                for row in rows:
                    self.price_adjustments[row['item_type']] = {
                        'demand_sell_adjust': float(row.get('demand_sell_adjust', 0)),
                        'demand_buy_adjust': float(row.get('demand_buy_adjust', 0)),
                        'daily_adjust_percent': float(row.get('daily_adjust_percent', 0)),
                        'sell_amount_accumulated': float(row.get('sell_amount_accumulated', 0)),
                        'buy_amount_accumulated': float(row.get('buy_amount_accumulated', 0)),
                        'sell_link_adjust': float(row.get('sell_link_adjust', 0)),
                        'last_updated': row.get('last_updated', datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    }
                self._safe_log('info', f"[ARCSignShop] Loaded {len(rows)} price adjustments from DB")
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Load price adjustments from DB error: {e}")

    # ==================== 每日波动 ====================

    def check_and_apply_daily_fluctuation(self, db_manager):
        """检查并应用每日随机波动"""
        if not self._settings.GetSettingBool('daily_fluctuation_enabled'):
            return

        now = datetime.datetime.now()
        today = now.date()

        # 检查是否需要重置
        if self._last_daily_reset_date is None or self._last_daily_reset_date != today:
            reset_hour = self._settings.GetSettingInt('daily_fluctuation_reset_hour', 0)
            if now.hour >= reset_hour:
                self._apply_daily_fluctuation(db_manager)
                self._last_daily_reset_date = today

    def _apply_daily_fluctuation(self, db_manager):
        """应用每日随机波动"""
        item_count = self._settings.GetSettingInt('daily_fluctuation_item_count', 3)
        min_percent = self._settings.GetSettingFloat('daily_fluctuation_min_percent', -15)
        max_percent = self._settings.GetSettingFloat('daily_fluctuation_max_percent', 15)

        priced_items = list(self.official_prices.keys())
        if not priced_items:
            return

        # 随机选择物品
        selected_items = random.sample(priced_items, min(item_count, len(priced_items)))

        # 先重置所有物品的日波动
        for item_type in self.official_prices:
            if item_type not in self.price_adjustments:
                self.price_adjustments[item_type] = {
                    'demand_sell_adjust': 0.0,
                    'demand_buy_adjust': 0.0,
                    'daily_adjust_percent': 0.0,
                    'last_updated': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            else:
                self.price_adjustments[item_type]['daily_adjust_percent'] = 0.0

        # 为选中的物品设置随机波动
        for item_type in selected_items:
            fluctuation = random.uniform(min_percent, max_percent)
            fluctuation = round(fluctuation, 1)

            if item_type not in self.price_adjustments:
                self.price_adjustments[item_type] = {
                    'demand_sell_adjust': 0.0,
                    'demand_buy_adjust': 0.0,
                    'daily_adjust_percent': fluctuation,
                    'last_updated': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            else:
                self.price_adjustments[item_type]['daily_adjust_percent'] = fluctuation

            self._save_price_adjustment(item_type, db_manager)

            sign = "+" if fluctuation > 0 else ""
            self._safe_log('info', f"[ARCSignShop] Daily fluctuation: {item_type} {sign}{fluctuation}%")

        self._safe_log('info', f"[ARCSignShop] Applied daily fluctuation to {len(selected_items)} items")

    # ==================== 价格恢复 ====================

    def apply_price_recovery(self, db_manager):
        """每小时调用，价格向基准价回归（默认0.02%/小时，约两天恢复1%）"""
        if not self._settings.GetSettingBool('dynamic_pricing_enabled'):
            return

        recovery_rate = self._settings.GetSettingFloat('dynamic_pricing_recovery_rate_per_hour', 0.0002)
        if recovery_rate <= 0:
            return

        changed = False
        for item_type, adj in self.price_adjustments.items():
            # 需求调整向0回归
            if adj['demand_sell_adjust'] != 0:
                if adj['demand_sell_adjust'] > 0:
                    adj['demand_sell_adjust'] = max(0, adj['demand_sell_adjust'] - recovery_rate)
                else:
                    adj['demand_sell_adjust'] = min(0, adj['demand_sell_adjust'] + recovery_rate)
                changed = True

            if adj['demand_buy_adjust'] != 0:
                if adj['demand_buy_adjust'] > 0:
                    adj['demand_buy_adjust'] = max(0, adj['demand_buy_adjust'] - recovery_rate)
                else:
                    adj['demand_buy_adjust'] = min(0, adj['demand_buy_adjust'] + recovery_rate)
                changed = True

            # 出售-回收联动调整向0回归
            sell_link = adj.get('sell_link_adjust', 0.0)
            if sell_link != 0:
                if sell_link > 0:
                    adj['sell_link_adjust'] = max(0, sell_link - recovery_rate)
                else:
                    adj['sell_link_adjust'] = min(0, sell_link + recovery_rate)
                changed = True

        if changed:
            for item_type in self.price_adjustments:
                self._save_price_adjustment(item_type, db_manager)

    # ==================== 清理过期数据 ====================

    def cleanup_old_trade_volumes(self, db_manager, days: int = 7):
        """清理过期的交易量数据"""
        try:
            cutoff_time = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
            db_manager.execute(
                "DELETE FROM item_trade_volume WHERE trade_time < ?",
                (cutoff_time,)
            )
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Cleanup old trade volumes error: {e}")

    # ==================== 管理接口 ====================

    def reset_all_adjustments(self, db_manager):
        """重置所有动态价格调整"""
        self.price_adjustments = {}
        try:
            db_manager.execute("DELETE FROM price_adjustments")
            self._safe_log('info', "[ARCSignShop] All price adjustments reset")
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Reset price adjustments error: {e}")

    def get_price_info_string(self, item_type: str, discount_percent: float = 0.0) -> str:
        """获取物品价格信息字符串（用于UI显示）"""
        if item_type not in self.official_prices:
            return ""

        prices = self.official_prices[item_type]
        adj = self.get_price_adjustment(item_type)

        info_parts = []
        info_parts.append(f"Base Sell: {prices.get('sell', 'N/A')}")
        info_parts.append(f"Base Buy: {prices.get('buy', 'N/A')}")

        if adj['demand_sell_adjust'] != 0:
            info_parts.append(f"Demand Sell Adj: {adj['demand_sell_adjust']:+.1%}")
        if adj['demand_buy_adjust'] != 0:
            info_parts.append(f"Demand Buy Adj: {adj['demand_buy_adjust']:+.1%}")
        sell_link = adj.get('sell_link_adjust', 0.0)
        if sell_link != 0:
            info_parts.append(f"Sell-Buy Link Adj: {sell_link:+.1%}")
        if adj['daily_adjust_percent'] != 0:
            info_parts.append(f"Daily Fluctuation: {adj['daily_adjust_percent']:+.1f}%")
        if discount_percent != 0:
            info_parts.append(f"Shop Discount: {discount_percent:+.1f}%")

        final_sell = self.calculate_final_price(item_type, 'sell', discount_percent)
        final_buy = self.calculate_final_price(item_type, 'buy', discount_percent)
        if final_sell:
            info_parts.append(f"Final Sell: {final_sell}")
        if final_buy is not None:
            info_parts.append(f"Final Buy: {final_buy}")
        else:
            info_parts.append("Final Buy: SUSPENDED (buy >= sell)")

        return "\n".join(info_parts)

    def get_daily_fluctuation_summary(self) -> str:
        """获取今日波动摘要"""
        items = []
        for item_type, adj in self.price_adjustments.items():
            if adj['daily_adjust_percent'] != 0:
                name = self.get_item_display_name(item_type)
                sign = "+" if adj['daily_adjust_percent'] > 0 else ""
                items.append(f"{name}: {sign}{adj['daily_adjust_percent']:.1f}%")

        if not items:
            return "No daily fluctuations today"
        return "\n".join(items)