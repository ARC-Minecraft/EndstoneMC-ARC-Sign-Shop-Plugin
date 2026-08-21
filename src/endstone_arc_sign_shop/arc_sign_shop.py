import datetime
import os
import json
import math
import re

from endstone.command import Command, CommandSender
from endstone.event import event_handler, PlayerInteractEvent, BlockBreakEvent
from endstone.plugin import Plugin
from endstone.form import ActionForm, ModalForm, Label, TextInput
from endstone.block import Block, Sign

from .DatabaseManager import DatabaseManager
from .LanguageManager import LanguageManager
from .SettingManager import SettingManager


class ARCSignShopPlugin(Plugin):
    prefix = "ARCSignShopPlugin"
    api_version = "0.10"
    load = "POSTWORLD"
    depend = ["arc_inventory"]

    commands = {
        "ss": {
            "description": "Sign shop commands",
            "usages": ["/ss", "/ss qs start", "/ss qs start both", "/ss qs start sell", "/ss qs start buy", "/ss qs stop"],
            "permissions": ["arc_sign_shop.command.ss"],
        },
        "ssmanage": {
            "description": "Manage sign shops, op only.",
            "usages": ["/ssmanage"]
        }
    }

    permissions = {
        "arc_sign_shop.command.ss": {
            "description": "Allow users to access sign shop interface",
            "default": True
        }
    }

    def __init__(self):
        super().__init__()
        self.setting_shop_player = {}  # 玩家名 -> 商店设置数据
        self.quick_setup_players = {}  # 玩家名 -> 'both'|'sell'|'buy'（默认 both）
        self.CHUNK_SIZE = 16  # 区块大小，用于优化查询
    
    def _safe_log(self, level: str, message: str):
        """
        安全的日志记录方法，在logger未初始化时使用print
        :param level: 日志级别 (info, warning, error)
        :param message: 日志消息
        """
        if hasattr(self, 'logger') and self.logger is not None:
            if level.lower() == 'info':
                self.logger.info(message)
            elif level.lower() == 'warning':
                self.logger.warning(message)
            elif level.lower() == 'error':
                self.logger.error(message)
            else:
                self.logger.info(message)
        else:
            # 如果logger未初始化，使用print
            print(f"[{level.upper()}] {message}")

    def on_load(self) -> None:
        self._safe_log('info', "[ARCSignShop] on_load is called!")
        
        # 初始化语言管理器
        self.language_manager = LanguageManager("CN")
        
        # 初始化设置管理器
        self.setting_manager = SettingManager()
        
        # 背包管理：优先在 on_enable 挂载 arc_inventory；此处先占位
        self.inventory_manager = None
        
        # 初始化默认配置
        self._init_default_settings()
        
        # 初始化数据库管理器
        db_path = os.path.join("plugins", "ARCSignShop", "sign_shop.db")
        self.db_manager = DatabaseManager(db_path)
        
        # 创建商店相关表
        self._create_shop_tables()
        
        # 官方自动定价由 arc_market_economy 提供

    def on_enable(self) -> None:
        self._safe_log('info', "[ARCSignShop] on_enable is called!")
        self.register_events(self)

        # 背包：强制使用弧光背包管理器（不再内嵌回退）
        self._init_inventory_manager()

        # 初始化经济插件 - 检查 arc_core 优先，然后 umoney
        self._init_economy_plugin()

        # 注册定时任务
        self._register_scheduled_tasks()

    def _init_inventory_manager(self, log_failure: bool = True) -> None:
        """强制挂载 arc_inventory；未安装则禁用背包相关功能。"""
        if self.inventory_manager is not None:
            return
        try:
            inv_plugin = self.server.plugin_manager.get_plugin("arc_inventory")
            if inv_plugin is not None:
                mgr = None
                if hasattr(inv_plugin, "api_get_inventory_manager"):
                    mgr = inv_plugin.api_get_inventory_manager()
                if mgr is None:
                    mgr = getattr(inv_plugin, "inventory_manager", None)
                if mgr is not None:
                    self.inventory_manager = mgr
                    self._safe_log(
                        "info",
                        "[ARCSignShop] Using arc_inventory for backpack operations.",
                    )
                    return
        except Exception as e:
            self._safe_log(
                "error",
                f"[ARCSignShop] Failed to load arc_inventory: {e}",
            )
        if log_failure:
            self._safe_log(
                "error",
                "[ARCSignShop] arc_inventory is REQUIRED. "
                "Install endstone_arc_inventory and restart; shop item operations are disabled until then.",
            )

    def _require_inventory_manager(self, player=None) -> bool:
        """背包管理器可用时返回 True；启动时未挂上则现场再解析一次。"""
        if self.inventory_manager is None:
            self._init_inventory_manager(log_failure=False)
        if self.inventory_manager is not None:
            return True
        msg = "§c[木牌商店] 未安装弧光背包管理器 (arc_inventory)，无法操作物品。请联系管理员安装后重启。"
        if player is not None:
            try:
                player.send_message(msg)
            except Exception:
                pass
        self._safe_log("error", "[ARCSignShop] inventory_manager unavailable")
        return False

    def _give_items_to_player(self, player, item_info: dict) -> int:
        """发放物品并返回实际入包数量。"""
        if not self._require_inventory_manager(player):
            return 0
        try:
            return int(self.inventory_manager.give_item_count(player, item_info) or 0)
        except Exception as e:
            self._safe_log("error", f"[ARCSignShop] give_item_count failed: {e}")
            return 0

    def on_disable(self) -> None:
        self._safe_log('info', "[ARCSignShop] on_disable is called!")
        
        # 取消所有定时任务
        self._cancel_scheduled_tasks()
        
        # 关闭数据库连接
        if hasattr(self, 'db_manager'):
            self.db_manager.close()

    # ==================== 定时任务 ====================

    def _register_scheduled_tasks(self):
        """定价相关定时任务已迁至 arc_market_economy。"""
        self._safe_log('info', "[ARCSignShop] No local market scheduled tasks (handled by arc_market_economy)")

    def _cancel_scheduled_tasks(self):
        """取消所有定时任务"""
        try:
            scheduler = self.server.scheduler
            scheduler.cancel_tasks(self)
            self._safe_log('info', "[ARCSignShop] All scheduled tasks cancelled")
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Failed to cancel scheduled tasks: {e}")




    def _init_default_settings(self) -> None:
        """初始化默认配置"""
        # 交易税率 (默认5%)
        tax_rate = self.setting_manager.GetSetting("trade_tax_rate")
        if tax_rate is None:
            self.setting_manager.SetSetting("trade_tax_rate", "0.05")
            self._safe_log('info', "[ARCSignShop] Set default trade tax rate: 5%")
        
        # 最大商店数量限制 (默认50)
        max_shops = self.setting_manager.GetSetting("max_shops_per_player")
        if max_shops is None:
            self.setting_manager.SetSetting("max_shops_per_player", "50")
            self._safe_log('info', "[ARCSignShop] Set default max shops per player: 50")
        
        # 是否启用交易税 (默认启用)
        tax_enabled = self.setting_manager.GetSetting("trade_tax_enabled")
        if tax_enabled is None:
            self.setting_manager.SetSetting("trade_tax_enabled", "true")
            self._safe_log('info', "[ARCSignShop] Trade tax enabled by default")


    def _init_economy_plugin(self) -> None:
        """初始化经济插件 - 检查 arc_core 优先，然后 umoney"""
        try:
            self.economy_plugin = self.server.plugin_manager.get_plugin('arc_core')
            if self.economy_plugin is not None:
                self._safe_log('info', "[ARCSignShop] Using ARC Core economy system for money rewards.")
            else:
                self.economy_plugin = self.server.plugin_manager.get_plugin('umoney')
                if self.economy_plugin is not None:
                    self._safe_log('info', "[ARCSignShop] Using UMoney economy system for money rewards.")
                else:
                    self._safe_log('warning', "[ARCSignShop] No supported economy plugin found (arc_core or umoney). Money rewards will not be available.")
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Failed to load economy plugin: {e}. Money rewards will not be available.")

    def _get_player_money(self, player_name: str) -> int:
        """获取玩家金钱数量"""
        if not self.economy_plugin:
            return 0
        
        try:
            money = self.economy_plugin.api_get_player_money(player_name)
            if money is None:
                return 0
            return int(money)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Failed to get player money for {player_name}: {e}")
        
        return 0

    def _change_player_money(self, player_name: str, amount: int) -> bool:
        """改变玩家金钱数量。
        arc_core 返回 bool；umoney 返回 None（成功无返回值，且不允许变动量为 0）。
        """
        if not self.economy_plugin:
            return False

        # umoney 不允许 money_to_change 为 0；零变动视为成功
        if int(amount) == 0:
            return True
        
        try:
            result = self.economy_plugin.api_change_player_money(player_name, int(amount))
            # None = umoney 成功无返回值；bool = arc_core
            if result is None:
                return True
            return bool(result)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Failed to change player money for {player_name}: {e}")
        
        return False


    def _get_market(self):
        """获取弧光市场经济插件；未安装返回 None。"""
        try:
            return self.server.plugin_manager.get_plugin("arc_market_economy")
        except Exception:
            return None

    def _require_market(self, player=None):
        mkt = self._get_market()
        if mkt is not None:
            return mkt
        msg = self.language_manager.GetText("SHOP_MARKET_REQUIRED")
        if player is not None:
            try:
                player.send_message(msg)
            except Exception:
                pass
        return None


    def _mkt_final_price(self, item_type, side, discount_percent=0.0):
        mkt = self._get_market()
        if not mkt:
            return None
        return mkt.api_get_final_price(item_type, side, discount_percent)

    def _mkt_display_name(self, item_type):
        mkt = self._get_market()
        if not mkt:
            return item_type or "?"
        return mkt.api_get_display_name(item_type)

    def _mkt_adjustment(self, item_type):
        mkt = self._get_market()
        if not mkt:
            return {
                'demand_sell_adjust': 0.0, 'demand_buy_adjust': 0.0,
                'daily_adjust_percent': 0.0, 'sell_link_adjust': 0.0,
            }
        return mkt.api_get_adjustment(item_type)

    def _mkt_list_items(self):
        mkt = self._get_market()
        return mkt.api_list_priced_items() if mkt else {}

    def _mkt_category_counts(self):
        mkt = self._get_market()
        return mkt.api_get_category_counts() if mkt else {}

    def _mkt_categories(self):
        mkt = self._get_market()
        return mkt.api_get_categories() if mkt else []

    def _mkt_items_by_category(self, category):
        mkt = self._get_market()
        return mkt.api_get_items_by_category(category) if mkt else {}

    def _mkt_base_price(self, item_type, side):
        mkt = self._get_market()
        return mkt.api_get_base_price(item_type, side) if mkt else None

    def _notify_market_trade(self, shop_data, quantity, total_amount):
        """成交成功后通知市场经济插件（仅官方自动定价）。"""
        try:
            if shop_data.get('pricing_mode') != 'official':
                return
            mkt = self._get_market()
            if not mkt:
                return
            mkt.api_on_trade(
                shop_data.get('item_type', ''),
                shop_data.get('shop_type', 'sell'),
                int(quantity),
                float(total_amount or 0),
                source="sign_shop",
            )
        except Exception as e:
            self._safe_log('warning', f"[ARCSignShop] notify market trade failed: {e}")

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        match command.name:
            case "ss":
                return self._handle_ss_command(sender, args)
            case "ssmanage":
                return self._handle_shop_manage_command(sender, args)
        return True

    def _handle_ss_command(self, sender: CommandSender, args: list[str]) -> bool:
        if not (hasattr(sender, 'location') and hasattr(sender, 'send_form')):
            sender.send_message(self.language_manager.GetText("PLAYER_ONLY_COMMAND"))
            return True
        if args and args[0].lower() == "qs":
            return self._handle_quick_setup_command(sender, args[1:])
        self._show_shop_main_panel(sender)
        return True

    def _handle_quick_setup_command(self, player, args: list[str]) -> bool:
        if not getattr(player, 'is_op', False):
            player.send_message(self.language_manager.GetText("QS_OP_ONLY"))
            return True
        if not args:
            player.send_message(self.language_manager.GetText("QS_USAGE"))
            return True
        action = args[0].lower()
        if action == "start":
            if not self._require_market(player):
                return True
            mode = "both"
            if len(args) > 1 and args[1].lower() in ("both", "sell", "buy"):
                mode = args[1].lower()
            self.quick_setup_players[player.name] = mode
            self.setting_shop_player.pop(player.name, None)
            mode_key = {
                "both": "QS_MODE_BOTH",
                "sell": "QS_MODE_SELL",
                "buy": "QS_MODE_BUY",
            }.get(mode, "QS_MODE_BOTH")
            mode_text = self.language_manager.GetText(mode_key)
            player.send_message(
                self.language_manager.GetText("QS_START_SUCCESS").format(mode_text).replace('\\n', '\n')
            )
            return True
        if action == "stop":
            if player.name not in self.quick_setup_players:
                player.send_message(self.language_manager.GetText("QS_NOT_ACTIVE"))
                return True
            self.quick_setup_players.pop(player.name, None)
            player.send_message(self.language_manager.GetText("QS_STOP_SUCCESS"))
            return True
        player.send_message(self.language_manager.GetText("QS_USAGE"))
        return True

    def _get_held_item_info(self, player):
        """读取玩家主手物品，返回与 arc_inventory 一致的 item_info dict。"""
        try:
            inventory = player.inventory
            if self._require_inventory_manager(player):
                held_slot = getattr(inventory, 'held_item_slot', None)
                if held_slot is not None:
                    for inv_item in self.inventory_manager.get_inventory_items(player):
                        if inv_item.get('slot_index') == held_slot:
                            return inv_item
            held_stack = getattr(inventory, 'item_in_main_hand', None)
            if held_stack and getattr(held_stack, 'type', None) and getattr(held_stack, 'amount', 0) > 0:
                item_type_id = held_stack.type.id
                return {
                    'type': item_type_id,
                    'name': item_type_id,
                    'count': held_stack.amount,
                    'data': getattr(held_stack, 'data', 0) or 0,
                    'enchants': {},
                    'lore': [],
                }
        except Exception as e:
            self._safe_log('warning', f"[ARCSignShop] Read held item failed: {e}")
        return None

    def _resolve_official_item_type(self, item_type_id: str):
        """将手持物品类型解析为 official_prices.yml 中的键。"""
        if not item_type_id:
            return None
        held_keys = self._official_item_type_match_keys(item_type_id)
        for official_type in (self._get_market().api_list_priced_items() if self._get_market() else {}):
            if held_keys & self._official_item_type_match_keys(official_type):
                return official_type
        return None

    def _normalize_item_type_id(self, item_type_id: str) -> str:
        """补全物品类型 ID（如 diamond -> minecraft:diamond）。"""
        if not item_type_id:
            return item_type_id
        if ':' in item_type_id:
            return item_type_id
        return f'minecraft:{item_type_id}'

    def _handle_quick_setup_interact(self, player, block) -> None:
        """快速设置：手持物品右键木牌，默认创建官方自动定价二合一商店。"""
        if not self._require_market(player):
            return
        held_item = self._get_held_item_info(player)
        if not held_item:
            player.send_message(self.language_manager.GetText("QS_NO_HELD_ITEM"))
            return

        held_type = held_item.get('type', '')
        item_type = self._resolve_official_item_type(held_type)
        if not item_type:
            item_type = self._normalize_item_type_id(held_type)
        if not item_type:
            player.send_message(self.language_manager.GetText("QS_NO_HELD_ITEM"))
            return

        shop_type = self.quick_setup_players.get(player.name, "both")
        if shop_type not in ("both", "sell", "buy"):
            shop_type = "both"

        mkt = self._get_market()
        was_missing = not (mkt and mkt.api_has_price(item_type))
        if mkt and hasattr(mkt, "api_ensure_item"):
            mkt.api_ensure_item(item_type, sell=0, buy=0)

        # 二合一口价快照用出售价；允许 0（待配置）
        price_side = "sell" if shop_type == "both" else shop_type
        unit_price = self._mkt_final_price(item_type, price_side, 0)
        if unit_price is None:
            if shop_type == "buy":
                # 回收暂停时仍可用出售价占位，避免无法建店
                unit_price = self._mkt_final_price(item_type, "sell", 0)
            if unit_price is None:
                unit_price = 0

        display_name = (
            held_item.get('name')
            if was_missing and held_item.get('name')
            else self._mkt_display_name(item_type)
        )
        item_info = {
            'type': item_type,
            'name': display_name,
            'count': 1,
            'data': 0,
            'enchants': {},
            'lore': [],
        }
        self.setting_shop_player[player.name] = {
            'item_info': item_info,
            'unit_price': unit_price,
            'shop_type': shop_type,
            'budget': 0,
            'is_infinite': True,
            'pricing_mode': 'official',
            'discount_percent': 0.0,
            'create_time': datetime.datetime.now(),
        }
        self._handle_shop_creation(player, block)
        self.setting_shop_player.pop(player.name, None)
        if player.name in self.quick_setup_players:
            if was_missing:
                player.send_message(
                    self.language_manager.GetText("QS_PLACEHOLDER_PRICE").format(display_name)
                )
            player.send_message(self.language_manager.GetText("QS_CONTINUE_HINT"))

    # 数据库
    def _create_shop_tables(self) -> None:
        """创建商店相关数据表"""
        
        # 创建商店表
        shop_fields = {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "shop_uuid": "TEXT NOT NULL UNIQUE",  # 商店唯一标识
            "owner_xuid": "TEXT NOT NULL",  # 店主XUID（主要标识符）
            "owner_name": "TEXT NOT NULL",  # 店主名称（用于显示）
            "shop_type": "TEXT NOT NULL DEFAULT 'sell'",  # 商店类型：'sell'出售, 'buy'收购, 'both'出售+回收(官方)
            "x": "INTEGER NOT NULL",  # 按钮X坐标
            "y": "INTEGER NOT NULL",  # 按钮Y坐标
            "z": "INTEGER NOT NULL",  # 按钮Z坐标
            "dimension": "TEXT NOT NULL",  # 维度
            "chunk_x": "INTEGER NOT NULL",  # 区块X坐标（用于优化查询）
            "chunk_z": "INTEGER NOT NULL",  # 区块Z坐标（用于优化查询）
            "item_type": "TEXT NOT NULL",  # 物品类型
            "item_data": "TEXT NOT NULL",  # 物品数据（JSON格式）
            "quantity": "INTEGER NOT NULL",  # 商品数量
            "unit_price": "REAL NOT NULL",  # 单价
            "stock": "INTEGER NOT NULL",  # 库存（出售商店为剩余库存，收购商店为资金余额）
            "collected_items": "TEXT",  # 收购商店收集的物品（JSON格式）
            "is_active": "INTEGER NOT NULL DEFAULT 1",  # 是否激活
            "create_time": "TEXT NOT NULL",  # 创建时间
            "last_purchase_time": "TEXT",  # 最后购买时间
            "is_infinite": "INTEGER NOT NULL DEFAULT 0"  # 是否无限商店（系统/官方商店）
        }
        
        if self.db_manager.create_table("sign_shops", shop_fields):
            self._safe_log('info', "[ARCSignShop] Sign shops table created successfully")
        else:
            self._safe_log('error', "[ARCSignShop] Failed to create sign shops table")
        
        # 创建交易记录表
        transaction_fields = {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "shop_id": "INTEGER NOT NULL",  # 商店ID
            "buyer_xuid": "TEXT NOT NULL",  # 买家XUID（主要标识符）
            "buyer_name": "TEXT NOT NULL",  # 买家名称（用于显示）
            "quantity": "INTEGER NOT NULL",  # 购买数量
            "unit_price": "REAL NOT NULL",  # 购买时的单价
            "total_price": "REAL NOT NULL",  # 总价
            "transaction_time": "TEXT NOT NULL"  # 交易时间
        }
        
        if self.db_manager.create_table("shop_transactions", transaction_fields):
            self._safe_log('info', "[ARCSignShop] Shop transactions table created successfully")
        else:
            self._safe_log('error', "[ARCSignShop] Failed to create shop transactions table")
        
        # 创建区块索引表（用于快速查询）
        chunk_index_fields = {
            "chunk_x": "INTEGER NOT NULL",
            "chunk_z": "INTEGER NOT NULL", 
            "dimension": "TEXT NOT NULL",
            "shop_count": "INTEGER NOT NULL DEFAULT 0",
            "PRIMARY KEY": "(chunk_x, chunk_z, dimension)"
        }
        
        if self.db_manager.create_table("chunk_index", chunk_index_fields):
            self._safe_log('info', "[ARCSignShop] Chunk index table created successfully")
        else:
            self._safe_log('error', "[ARCSignShop] Failed to create chunk index table")

        # 创建交易量追踪表（用于动态定价）
        trade_volume_fields = {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "item_type": "TEXT NOT NULL",  # 物品类型
            "trade_type": "TEXT NOT NULL",  # 交易类型：'sell'玩家购买, 'buy'玩家出售
            "quantity": "INTEGER NOT NULL",  # 交易数量
            "total_amount": "REAL NOT NULL DEFAULT 0",  # 交易总金额（单价×数量）
            "trade_time": "TEXT NOT NULL"  # 交易时间
        }
        
        if False and self.db_manager.create_table("item_trade_volume", trade_volume_fields):
            self._safe_log('info', "[ARCSignShop] Item trade volume table created successfully")
        else:
            self._safe_log('error', "[ARCSignShop] Failed to create item trade volume table")
        
        # 创建价格调整表（用于动态定价和每日波动）
        price_adjustment_fields = {
            "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
            "item_type": "TEXT NOT NULL UNIQUE",  # 物品类型
            "demand_sell_adjust": "REAL NOT NULL DEFAULT 0",  # 需求驱动的出售价调整（正数=涨价）
            "demand_buy_adjust": "REAL NOT NULL DEFAULT 0",  # 需求驱动的回收价调整（负数=降价）
            "daily_adjust_percent": "REAL NOT NULL DEFAULT 0",  # 每日波动百分比
            "sell_amount_accumulated": "REAL NOT NULL DEFAULT 0",  # 出售交易累计金额（未消耗部分）
            "buy_amount_accumulated": "REAL NOT NULL DEFAULT 0",  # 收购交易累计金额（未消耗部分）
            "sell_link_adjust": "REAL NOT NULL DEFAULT 0",  # 出售涨价联动到回收价的调整（正数=涨价）
            "last_updated": "TEXT NOT NULL"  # 最后更新时间
        }
        
        if False and self.db_manager.create_table("price_adjustments", price_adjustment_fields):
            self._safe_log('info', "[ARCSignShop] Price adjustments table created successfully")
        else:
            self._safe_log('error', "[ARCSignShop] Failed to create price adjustments table")

        # 迁移：为已有表添加 is_infinite 列（若不存在）
        self._migrate_add_is_infinite_column()
        
        # 迁移：为已有表添加 pricing_mode 和 discount_percent 列（若不存在）
        self._migrate_add_pricing_columns()
        
        # 迁移：为 item_trade_volume 表添加 total_amount 列（若不存在）
        self._migrate_add_trade_amount_column()
        
        # 迁移：为 price_adjustments 表添加累计金额列（若不存在）
        self._migrate_add_accumulated_columns()

        # 迁移：系统商店统一为 SYSTEM 店主；售罄店保持可管理以便补货
        self._migrate_system_shop_owner_and_reactivate()

    def _migrate_system_shop_owner_and_reactivate(self) -> None:
        """系统商店不绑定个人创建者；此前因售罄停用的商店恢复为可管理"""
        try:
            self.db_manager.execute(
                "UPDATE sign_shops SET owner_xuid = ?, owner_name = ? WHERE is_infinite != 0 AND owner_xuid != ?",
                (self.SYSTEM_OWNER_XUID, self.SYSTEM_OWNER_NAME, self.SYSTEM_OWNER_XUID)
            )
            self.db_manager.execute(
                "UPDATE sign_shops SET is_active = 1 WHERE is_active = 0"
            )
            self._safe_log('info', "[ARCSignShop] Migrated: system shop owners + reactivated depleted shops")
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Migrate system owner / reactivate error: {str(e)}")

    def _migrate_add_is_infinite_column(self) -> None:
        """为 sign_shops 表添加 is_infinite 列（兼容旧数据库）"""
        try:
            rows = self.db_manager.query_all("PRAGMA table_info(sign_shops)")
            if rows is None:
                return
            column_names = [row['name'] for row in rows]
            if 'is_infinite' not in column_names:
                self.db_manager.execute(
                    "ALTER TABLE sign_shops ADD COLUMN is_infinite INTEGER NOT NULL DEFAULT 0"
                )
                self._safe_log('info', "[ARCSignShop] Migrated: added is_infinite column to sign_shops")
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Migrate is_infinite column error: {str(e)}")

    def _migrate_add_pricing_columns(self) -> None:
        """为 sign_shops 表添加 pricing_mode 和 discount_percent 列（兼容旧数据库）"""
        try:
            rows = self.db_manager.query_all("PRAGMA table_info(sign_shops)")
            if rows is None:
                return
            column_names = [row['name'] for row in rows]
            if 'pricing_mode' not in column_names:
                self.db_manager.execute(
                    "ALTER TABLE sign_shops ADD COLUMN pricing_mode TEXT NOT NULL DEFAULT 'manual'"
                )
                self._safe_log('info', "[ARCSignShop] Migrated: added pricing_mode column to sign_shops")
            if 'discount_percent' not in column_names:
                self.db_manager.execute(
                    "ALTER TABLE sign_shops ADD COLUMN discount_percent REAL NOT NULL DEFAULT 0"
                )
                self._safe_log('info', "[ARCSignShop] Migrated: added discount_percent column to sign_shops")
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Migrate pricing columns error: {str(e)}")

    def _migrate_add_trade_amount_column(self) -> None:
        """为 item_trade_volume 表添加 total_amount 列（兼容旧数据库）"""
        try:
            rows = self.db_manager.query_all("PRAGMA table_info(item_trade_volume)")
            if rows is None:
                return
            column_names = [row['name'] for row in rows]
            if 'total_amount' not in column_names:
                self.db_manager.execute(
                    "ALTER TABLE item_trade_volume ADD COLUMN total_amount REAL NOT NULL DEFAULT 0"
                )
                self._safe_log('info', "[ARCSignShop] Migrated: added total_amount column to item_trade_volume")
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Migrate total_amount column error: {str(e)}")

    def _migrate_add_accumulated_columns(self) -> None:
        """为 price_adjustments 表添加累计金额列和联动调整列（兼容旧数据库）"""
        try:
            rows = self.db_manager.query_all("PRAGMA table_info(price_adjustments)")
            if rows is None:
                return
            column_names = [row['name'] for row in rows]
            if 'sell_amount_accumulated' not in column_names:
                self.db_manager.execute(
                    "ALTER TABLE price_adjustments ADD COLUMN sell_amount_accumulated REAL NOT NULL DEFAULT 0"
                )
                self._safe_log('info', "[ARCSignShop] Migrated: added sell_amount_accumulated column to price_adjustments")
            if 'buy_amount_accumulated' not in column_names:
                self.db_manager.execute(
                    "ALTER TABLE price_adjustments ADD COLUMN buy_amount_accumulated REAL NOT NULL DEFAULT 0"
                )
                self._safe_log('info', "[ARCSignShop] Migrated: added buy_amount_accumulated column to price_adjustments")
            if 'sell_link_adjust' not in column_names:
                self.db_manager.execute(
                    "ALTER TABLE price_adjustments ADD COLUMN sell_link_adjust REAL NOT NULL DEFAULT 0"
                )
                self._safe_log('info', "[ARCSignShop] Migrated: added sell_link_adjust column to price_adjustments")
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Migrate accumulated columns error: {str(e)}")

    # 无限商店库存/预算常量（表示无限）
    UNLIMITED_STOCK = 2147483647
    # 系统商店哨兵店主（不绑定创建者个人）
    SYSTEM_OWNER_XUID = "SYSTEM"
    SYSTEM_OWNER_NAME = "SYSTEM"

    # 事件监听器
    @event_handler
    def on_player_interact(self, event: PlayerInteractEvent):
        """处理玩家交互事件"""
        try:
            player = event.player
            block = event.block

            # 检查block是否为None
            if block is None:
                return

            # 快速设置模式：手持物品右键按钮，直接创建官方自动定价二合一商店
            if player.name in self.quick_setup_players:
                if event.action != PlayerInteractEvent.Action.RIGHT_CLICK_BLOCK:
                    return
                if not self._is_sign_block(block):
                    player.send_message(self.language_manager.GetText("SHOP_NOT_SIGN").format(block.type))
                    return
                self._handle_quick_setup_interact(player, block)
                event.is_cancelled = True
                return

            # 检查玩家是否处于商店设置状态（仅右键绑定按钮）
            if player.name in self.setting_shop_player:
                if event.action != PlayerInteractEvent.Action.RIGHT_CLICK_BLOCK:
                    return
                if not self._is_sign_block(block):
                    # 提示玩家当前交互的不是按钮
                    player.send_message(self.language_manager.GetText("SHOP_NOT_SIGN").format(block.type))
                    return
                else:
                    self._handle_shop_creation(player, block)
                    event.is_cancelled = True
                return
            else:
                # 检查是否是按钮交互
                if not self._is_sign_block(block):
                    return
                
                # 通过区块索引快速检查该位置是否有商店
                shop_data = self._get_shop_at_position_optimized(block.x, block.y, block.z, block.dimension.name)
                if not shop_data:
                    return

                # 左键：店主/OP 弹出删除确认；他人阻止破坏
                # （Bedrock 左键按钮会先走 Interact，若不区分会误开商店详情/管理页）
                if event.action == PlayerInteractEvent.Action.LEFT_CLICK_BLOCK:
                    if not shop_data['is_active']:
                        return
                    is_owner = self._is_player_shop_owner(player, shop_data)
                    is_op = getattr(player, 'is_op', False)
                    if is_owner or is_op:
                        self._show_break_delete_confirm_panel(player, shop_data)
                    else:
                        player.send_message(
                            self.language_manager.GetText("SHOP_BREAK_PROTECTED").format(
                                self._get_shop_owner_display(shop_data)
                            )
                        )
                    event.is_cancelled = True
                    return

                # 右键：打开商店详情
                if event.action == PlayerInteractEvent.Action.RIGHT_CLICK_BLOCK:
                    self._show_shop_detail_panel(player, shop_data)
                    event.is_cancelled = True
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Player interact error: {str(e)}")

    @event_handler
    def on_block_break(self, event: BlockBreakEvent):
        """处理方块破坏事件（商店保护）"""
        try:
            player = event.player
            block = event.block
            
            # 检查block是否为None
            if block is None:
                return
            
            # 检查是否是按钮破坏
            if not self._is_sign_block(block):
                return
            
            # 检查该位置是否有商店
            shop_data = self._get_shop_at_position_optimized(block.x, block.y, block.z, block.dimension.name)
            if not shop_data:
                return  # 没有商店，允许正常破坏
            
            # 检查商店是否有效
            if not shop_data['is_active']:
                return  # 商店已失效，允许破坏
            
            # 检查是否是店主或OP
            is_owner = self._is_player_shop_owner(player, shop_data)
            is_op = getattr(player, 'is_op', False)
            if is_owner or is_op:
                # 店主或OP破坏按钮，显示删除确认面板
                self._show_break_delete_confirm_panel(player, shop_data)
                event.is_cancelled = True
                return
            else:
                # 非店主破坏按钮，阻止破坏并提示
                player.send_message(
                    self.language_manager.GetText("SHOP_BREAK_PROTECTED").format(
                        self._get_shop_owner_display(shop_data)
                    )
                )
                event.is_cancelled = True
                return
                
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Block break error: {str(e)}")

    # 商店管理系统
    def _show_shop_main_panel(self, player):
        """显示商店主面板"""
        try:
            main_panel = ActionForm(
                title=self.language_manager.GetText("SHOP_MAIN_PANEL_TITLE"),
                content=self.language_manager.GetText("SHOP_MAIN_PANEL_CONTENT")
            )
            
            # 创建商店按钮
            main_panel.add_button(
                self.language_manager.GetText("SHOP_CREATE_BUTTON"),
                on_click=lambda sender: self._show_shop_type_selection_panel(sender)
            )
            
            # 我的商店按钮
            main_panel.add_button(
                self.language_manager.GetText("SHOP_MY_SHOPS_BUTTON"),
                on_click=lambda sender: self._show_my_shops_panel(sender)
            )
            
            # OP 专属：管理全部商店 / 按命名空间批量删除
            if getattr(player, 'is_op', False):
                main_panel.add_button(
                    self.language_manager.GetText("SHOP_MANAGE_ALL_SHOPS_BUTTON"),
                    on_click=lambda sender: self._show_all_shops_panel(sender)
                )
                main_panel.add_button(
                    self.language_manager.GetText("SHOP_MANAGE_DELNS_BUTTON"),
                    on_click=lambda sender: self._show_namespace_delete_panel(sender)
                )
            
            # 附近商店按钮
            main_panel.add_button(
                self.language_manager.GetText("SHOP_NEARBY_BUTTON"), 
                on_click=lambda sender: self._show_nearby_shops_panel(sender)
            )
            
            # 关闭按钮
            main_panel.add_button(
                self.language_manager.GetText("SHOP_CLOSE_BUTTON"),
                on_click=lambda sender: None
            )
            
            player.send_form(main_panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show main panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_PANEL_ERROR"))

    def _show_shop_type_selection_panel(self, player):
        """显示商店类型：玩家出售/收购/交易，OP 另有官方商店（默认二合一自动定价）。"""
        try:
            type_panel = ActionForm(
                title=self.language_manager.GetText("SHOP_TYPE_SELECT_TITLE"),
                content=self.language_manager.GetText("SHOP_TYPE_SELECT_CONTENT")
            )
            type_panel.add_button(
                self.language_manager.GetText("SHOP_TYPE_SELL_BUTTON"),
                on_click=lambda sender: self._show_item_selection_panel(sender, "sell")
            )
            type_panel.add_button(
                self.language_manager.GetText("SHOP_TYPE_BUY_BUTTON"),
                on_click=lambda sender: self._show_item_selection_panel(sender, "buy")
            )
            type_panel.add_button(
                self.language_manager.GetText("SHOP_TYPE_BARTER_BUTTON"),
                on_click=lambda sender: self._show_item_selection_panel(sender, "barter_give")
            )
            if getattr(player, 'is_op', False):
                type_panel.add_button(
                    self.language_manager.GetText("SHOP_TYPE_OFFICIAL_BUTTON"),
                    on_click=lambda sender: self._show_official_pricing_mode_panel(sender)
                )
            type_panel.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_shop_main_panel(sender)
            )
            player.send_form(type_panel)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show shop type selection panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_PANEL_ERROR"))

    def _show_official_pricing_mode_panel(self, player):
        """官方商店：自动定价默认二合一；手动定价可选仅出售/仅回收无限店。"""
        try:
            panel = ActionForm(
                title=self.language_manager.GetText("SHOP_OFFICIAL_PRICING_MODE_TITLE"),
                content=self.language_manager.GetText("SHOP_OFFICIAL_PRICING_MODE_CONTENT")
            )
            mkt = self._get_market()
            if mkt is not None:
                panel.add_button(
                    self.language_manager.GetText("SHOP_OFFICIAL_PRICING_AUTO_BUTTON"),
                    on_click=lambda sender: self._show_official_price_item_selection(sender, "both")
                )
            else:
                panel.add_button(
                    self.language_manager.GetText("SHOP_OFFICIAL_PRICING_AUTO_DISABLED"),
                    on_click=lambda sender: sender.send_message(
                        self.language_manager.GetText("SHOP_MARKET_REQUIRED")
                    )
                )
            panel.add_button(
                self.language_manager.GetText("SHOP_OFFICIAL_PRICING_MANUAL_BUTTON"),
                on_click=lambda sender: self._show_official_manual_type_panel(sender)
            )
            panel.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_shop_type_selection_panel(sender)
            )
            player.send_form(panel)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Official pricing mode panel error: {e}")
            player.send_message(self.language_manager.GetText("SHOP_PANEL_ERROR"))

    def _show_official_manual_type_panel(self, player):
        """手动定价系统店：仅出售或仅回收（固定单价无限）。"""
        try:
            panel = ActionForm(
                title=self.language_manager.GetText("SHOP_OFFICIAL_MANUAL_TYPE_TITLE"),
                content=self.language_manager.GetText("SHOP_OFFICIAL_MANUAL_TYPE_CONTENT")
            )
            panel.add_button(
                self.language_manager.GetText("SHOP_TYPE_OFFICIAL_SELL_BUTTON"),
                on_click=lambda sender: self._show_item_selection_panel(sender, "sell_infinite")
            )
            panel.add_button(
                self.language_manager.GetText("SHOP_TYPE_OFFICIAL_BUY_BUTTON"),
                on_click=lambda sender: self._show_item_selection_panel(sender, "buy_infinite")
            )
            panel.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_official_pricing_mode_panel(sender)
            )
            player.send_form(panel)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Official manual type panel error: {e}")
            player.send_message(self.language_manager.GetText("SHOP_PANEL_ERROR"))

    def _show_item_selection_panel(self, player, shop_type="sell", give_item=None):
        """显示物品选择面板（含以物易物：先选给出物 A，再选收取物 B）"""
        try:
            if not self._require_inventory_manager(player):
                return
            # 获取玩家背包中的物品
            inventory_items = self.inventory_manager.get_inventory_items(player)
            
            if shop_type == "barter_give":
                title = self.language_manager.GetText("SHOP_BARTER_GIVE_SELECT_TITLE")
                content = self.language_manager.GetText("SHOP_BARTER_GIVE_SELECT_CONTENT")
                no_items_text = self.language_manager.GetText("SHOP_BARTER_NO_GIVE_ITEMS")
                back_click = lambda sender: self._show_shop_type_selection_panel(sender)
            elif shop_type == "barter_cost":
                title = self.language_manager.GetText("SHOP_BARTER_COST_SELECT_TITLE")
                content = self.language_manager.GetText("SHOP_BARTER_COST_SELECT_CONTENT").format(
                    (give_item or {}).get('name', '?'), (give_item or {}).get('count', 0)
                )
                no_items_text = self.language_manager.GetText("SHOP_BARTER_NO_COST_ITEMS")
                back_click = lambda sender: self._show_item_selection_panel(sender, "barter_give")
            else:
                title = self.language_manager.GetText("SHOP_ITEM_SELECT_TITLE")
                content = self.language_manager.GetText("SHOP_ITEM_SELECT_CONTENT")
                no_items_text = self.language_manager.GetText("SHOP_NO_ITEMS")
                back_click = lambda sender: self._show_shop_type_selection_panel(sender)

            if not inventory_items:
                no_items_panel = ActionForm(
                    title=title,
                    content=no_items_text
                )
                no_items_panel.add_button(
                    self.language_manager.GetText("SHOP_BACK_BUTTON"),
                    on_click=back_click
                )
                player.send_form(no_items_panel)
                return
            
            # 创建物品选择面板
            item_select_panel = ActionForm(
                title=title,
                content=content
            )
            
            # 为每个物品添加按钮
            for item_info in inventory_items:
                item_name = item_info['name']
                item_count = item_info['count']
                
                # 构建按钮文本，包含附魔和Lore信息
                button_text = f"{item_name} x{item_count}"
                
                # 添加附魔信息
                if item_info.get('enchants'):
                    button_text += f" §b[{self.language_manager.GetText('SHOP_ENCHANT_TAG')}]"
                
                # 添加Lore信息
                if item_info.get('lore'):
                    button_text += f" §d[{self.language_manager.GetText('SHOP_LORE_TAG')}]"
                
                if shop_type == "barter_give":
                    item_select_panel.add_button(
                        button_text,
                        on_click=lambda sender, item=item_info: self._show_item_selection_panel(sender, "barter_cost", give_item=item)
                    )
                elif shop_type == "barter_cost":
                    item_select_panel.add_button(
                        button_text,
                        on_click=lambda sender, item=item_info: self._show_barter_ratio_panel(sender, give_item, item)
                    )
                else:
                    item_select_panel.add_button(
                        button_text,
                        on_click=lambda sender, item=item_info: self._show_price_setting_panel(sender, item, shop_type)
                    )
            
            # 返回按钮
            item_select_panel.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=back_click
            )
            
            player.send_form(item_select_panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show item selection panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_PANEL_ERROR"))

    def _show_barter_ratio_panel(self, player, give_item, cost_item):
        """设置以物易物比例：交出 x 个 A，收取 y 个 B"""
        try:
            if not give_item or not cost_item:
                player.send_message(self.language_manager.GetText("SHOP_PANEL_ERROR"))
                return

            info_text = self.language_manager.GetText("SHOP_BARTER_RATIO_INFO").format(
                give_item.get('name', '?'), give_item.get('count', 0),
                cost_item.get('name', '?'), cost_item.get('count', 0)
            )
            controls = [
                Label(text=info_text),
                TextInput(
                    label=self.language_manager.GetText("SHOP_BARTER_GIVE_AMOUNT_LABEL"),
                    placeholder=self.language_manager.GetText("SHOP_BARTER_GIVE_AMOUNT_PLACEHOLDER"),
                    default_value="1"
                ),
                TextInput(
                    label=self.language_manager.GetText("SHOP_BARTER_COST_AMOUNT_LABEL"),
                    placeholder=self.language_manager.GetText("SHOP_BARTER_COST_AMOUNT_PLACEHOLDER"),
                    default_value="1"
                ),
                TextInput(
                    label=self.language_manager.GetText("SHOP_DISPLAY_NAME_LABEL"),
                    placeholder=self.language_manager.GetText("SHOP_DISPLAY_NAME_PLACEHOLDER"),
                    default_value=str(give_item.get('name', '') or '')
                ),
            ]

            def process_barter_setup(sender, json_str: str):
                try:
                    data = json.loads(json_str)
                    give_str = data[1] if len(data) > 1 else ''
                    cost_str = data[2] if len(data) > 2 else ''
                    custom_name = str(data[3] if len(data) > 3 else '').strip()
                    try:
                        give_amount = int(float(give_str))
                        cost_amount = int(float(cost_str))
                        if give_amount <= 0 or cost_amount <= 0:
                            raise ValueError("Amounts must be positive")
                    except ValueError:
                        result_form = ActionForm(
                            title=self.language_manager.GetText("SHOP_RESULT_TITLE"),
                            content=self.language_manager.GetText("SHOP_BARTER_INVALID_RATIO")
                        )
                        result_form.add_button(
                            self.language_manager.GetText("SHOP_BACK_BUTTON"),
                            on_click=lambda s: self._show_barter_ratio_panel(s, give_item, cost_item)
                        )
                        sender.send_form(result_form)
                        return

                    shop_item_info = dict(give_item)
                    shop_item_info['name'] = custom_name if custom_name else give_item.get('name', give_item.get('type', 'Unknown'))
                    cost_item_info = dict(cost_item)
                    # 创建时只上架给出物 A；比例与收取物写入 item_data
                    shop_item_info['barter_give_amount'] = give_amount
                    shop_item_info['barter_cost_amount'] = cost_amount
                    shop_item_info['barter_cost_item'] = {
                        'type': cost_item_info.get('type'),
                        'name': cost_item_info.get('name', cost_item_info.get('type', 'Unknown')),
                        'data': cost_item_info.get('data', 0),
                        'enchants': cost_item_info.get('enchants') or {},
                        'lore': cost_item_info.get('lore') or [],
                    }
                    if cost_item_info.get('nbt_b64'):
                        shop_item_info['barter_cost_item']['nbt_b64'] = cost_item_info['nbt_b64']

                    self.setting_shop_player[sender.name] = {
                        'item_info': shop_item_info,
                        'unit_price': 0,
                        'shop_type': 'barter',
                        'budget': 0,
                        'is_infinite': False,
                        'create_time': datetime.datetime.now()
                    }

                    instruction_content = self.language_manager.GetText("SHOP_BARTER_SETUP_INSTRUCTION").format(
                        shop_item_info['name'], give_amount,
                        shop_item_info['barter_cost_item']['name'], cost_amount,
                        shop_item_info.get('count', 0)
                    ).replace('\\n', '\n')
                    instruction_form = ActionForm(
                        title=self.language_manager.GetText("SHOP_SETUP_TITLE"),
                        content=instruction_content,
                        on_close=lambda s: None
                    )
                    sender.send_form(instruction_form)
                except Exception as e:
                    self._safe_log('error', f"[ARCSignShop] Process barter setup error: {str(e)}")
                    error_form = ActionForm(
                        title=self.language_manager.GetText("SHOP_RESULT_TITLE"),
                        content=self.language_manager.GetText("SHOP_PANEL_ERROR")
                    )
                    error_form.add_button(
                        self.language_manager.GetText("SHOP_BACK_BUTTON"),
                        on_click=lambda s: self._show_barter_ratio_panel(s, give_item, cost_item)
                    )
                    sender.send_form(error_form)

            ratio_panel = ModalForm(
                title=self.language_manager.GetText("SHOP_BARTER_RATIO_TITLE"),
                controls=controls,
                on_submit=process_barter_setup
            )
            player.send_form(ratio_panel)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show barter ratio panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_PANEL_ERROR"))

    def _get_barter_trade_config(self, item_data: dict):
        """从商店 item_data 解析以物易物配置：给出 x 个 A，收取 y 个 B"""
        give_amount = max(1, int(item_data.get('barter_give_amount', 1) or 1))
        cost_amount = max(1, int(item_data.get('barter_cost_amount', 1) or 1))
        cost_item = item_data.get('barter_cost_item') or {}
        return give_amount, cost_amount, cost_item

    def _format_barter_ratio_text(self, item_data: dict) -> str:
        """格式化以物易物比例展示文案"""
        give_amount, cost_amount, cost_item = self._get_barter_trade_config(item_data)
        return self.language_manager.GetText("SHOP_BARTER_RATIO_DISPLAY").format(
            give_amount, item_data.get('name', '?'),
            cost_amount, cost_item.get('name', '?')
        )

    def _show_price_setting_panel(self, player, item_info, shop_type="sell"):
        """显示价格设置面板（支持 sell/buy/sell_infinite/buy_infinite）"""
        try:
            controls = []
            is_infinite = shop_type in ("sell_infinite", "buy_infinite")
            base_type = "sell" if shop_type in ("sell", "sell_infinite") else "buy"
            
            if shop_type in ("sell", "sell_infinite"):
                # 出售商店（含无限出售）
                item_info_text = self.language_manager.GetText("SHOP_PRICE_SELL_ITEM_INFO").format(item_info['name'], item_info['count'])
                if is_infinite:
                    item_info_text += "\n" + self.language_manager.GetText("SHOP_INFINITE_SELL_TAG")
                if item_info.get('enchants'):
                    item_info_text += "\n" + self.language_manager.GetText("SHOP_MANAGE_ENCHANTS")
                    for enchant_id, level in item_info['enchants'].items():
                        item_info_text += "\n" + self.language_manager.GetText("SHOP_MANAGE_ENCHANT_LINE").format(enchant_id, level)
                if item_info.get('lore'):
                    item_info_text += "\n" + self.language_manager.GetText("SHOP_MANAGE_LORE")
                    for lore_line in item_info['lore']:
                        item_info_text += "\n  " + lore_line
                item_label = Label(text=item_info_text)
                controls.append(item_label)
                name_input = TextInput(
                    label=self.language_manager.GetText("SHOP_DISPLAY_NAME_LABEL"),
                    placeholder=self.language_manager.GetText("SHOP_DISPLAY_NAME_PLACEHOLDER"),
                    default_value=str(item_info.get('name', '') or '')
                )
                controls.append(name_input)
                price_input = TextInput(
                    label=self.language_manager.GetText("SHOP_PRICE_INPUT_LABEL"),
                    placeholder=self.language_manager.GetText("SHOP_PRICE_INPUT_PLACEHOLDER"),
                    default_value="10"
                )
                controls.append(price_input)
                
            else:  # buy 或 buy_infinite
                # 收购商店（含无限收购）
                buy_info_text = self.language_manager.GetText("SHOP_PRICE_BUY_ITEM_INFO").format(item_info['name'])
                if is_infinite:
                    buy_info_text += "\n" + self.language_manager.GetText("SHOP_INFINITE_BUY_TAG")
                if item_info.get('enchants'):
                    buy_info_text += "\n" + self.language_manager.GetText("SHOP_MANAGE_ENCHANTS")
                    for enchant_id, level in item_info['enchants'].items():
                        buy_info_text += "\n" + self.language_manager.GetText("SHOP_MANAGE_ENCHANT_LINE").format(enchant_id, level)
                if item_info.get('lore'):
                    buy_info_text += "\n" + self.language_manager.GetText("SHOP_MANAGE_LORE")
                    for lore_line in item_info['lore']:
                        buy_info_text += "\n  " + lore_line
                buy_label = Label(text=buy_info_text)
                controls.append(buy_label)
                name_input = TextInput(
                    label=self.language_manager.GetText("SHOP_DISPLAY_NAME_LABEL"),
                    placeholder=self.language_manager.GetText("SHOP_DISPLAY_NAME_PLACEHOLDER"),
                    default_value=str(item_info.get('name', '') or '')
                )
                controls.append(name_input)
                price_input = TextInput(
                    label=self.language_manager.GetText("SHOP_BUY_PRICE_INPUT_LABEL"),
                    placeholder=self.language_manager.GetText("SHOP_BUY_PRICE_INPUT_PLACEHOLDER"),
                    default_value="10"
                )
                controls.append(price_input)
                if not is_infinite:
                    budget_input = TextInput(
                        label=self.language_manager.GetText("SHOP_BUY_BUDGET_LABEL"),
                        placeholder=self.language_manager.GetText("SHOP_BUY_BUDGET_PLACEHOLDER"),
                        default_value="1000"
                    )
                    controls.append(budget_input)
            
            def process_shop_creation(sender, json_str: str):
                try:
                    data = json.loads(json_str)
                    # controls: [Label, display_name, price, (budget?)]
                    custom_name = str(data[1] if len(data) > 1 else '').strip()
                    price_str = data[2] if len(data) > 2 else ''
                    try:
                        unit_price = int(float(price_str))
                        if unit_price <= 0:
                            raise ValueError("Price must be positive")
                    except ValueError:
                        result_form = ActionForm(
                            title=self.language_manager.GetText("SHOP_RESULT_TITLE"),
                            content=self.language_manager.GetText("SHOP_INVALID_PRICE")
                        )
                        result_form.add_button(
                            self.language_manager.GetText("SHOP_BACK_BUTTON"),
                            on_click=lambda s: self._show_price_setting_panel(s, item_info, shop_type)
                        )
                        sender.send_form(result_form)
                        return
                    
                    budget = 0
                    if base_type == "buy" and not is_infinite:
                        budget_str = data[3] if len(data) > 3 else ''
                        try:
                            budget = int(float(budget_str))
                            if budget <= 0:
                                raise ValueError("Budget must be positive")
                            if budget < unit_price:
                                raise ValueError("Budget must be at least equal to unit price")
                        except ValueError:
                            result_form = ActionForm(
                                title=self.language_manager.GetText("SHOP_RESULT_TITLE"),
                                content=self.language_manager.GetText("SHOP_INVALID_BUDGET")
                            )
                            result_form.add_button(
                                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                                on_click=lambda s: self._show_price_setting_panel(s, item_info, shop_type)
                            )
                            sender.send_form(result_form)
                            return
                        player_money = self._get_player_money(sender.name)
                        if player_money < int(budget):
                            result_form = ActionForm(
                                title=self.language_manager.GetText("SHOP_RESULT_TITLE"),
                                content=self.language_manager.GetText("SHOP_INSUFFICIENT_FUNDS_FOR_BUDGET").format(int(budget), player_money)
                            )
                            result_form.add_button(
                                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                                on_click=lambda s: self._show_price_setting_panel(s, item_info, shop_type)
                            )
                            sender.send_form(result_form)
                            return

                    shop_item_info = dict(item_info)
                    shop_item_info['name'] = custom_name if custom_name else item_info.get('name', item_info.get('type', 'Unknown'))
                    
                    shop_data = {
                        'item_info': shop_item_info,
                        'unit_price': unit_price,
                        'shop_type': base_type,
                        'budget': budget,
                        'is_infinite': is_infinite,
                        'create_time': datetime.datetime.now()
                    }
                    self.setting_shop_player[sender.name] = shop_data
                    
                    if base_type == "sell":
                        instruction_content = self.language_manager.GetText("SHOP_SETUP_INSTRUCTION").format(
                            shop_item_info['name'], shop_item_info['count'], unit_price
                        ).replace('\\n', '\n')
                    else:
                        instruction_content = self.language_manager.GetText("SHOP_BUY_SETUP_INSTRUCTION").format(
                            shop_item_info['name'], unit_price, int(budget), int(budget / unit_price) if budget else "∞"
                        ).replace('\\n', '\n')
                    if is_infinite:
                        instruction_content += "\n\n" + self.language_manager.GetText("SHOP_INFINITE_SETUP_HINT")
                    instruction_form = ActionForm(
                        title=self.language_manager.GetText("SHOP_SETUP_TITLE"),
                        content=instruction_content,
                        on_close=lambda s: None
                    )
                    sender.send_form(instruction_form)
                    
                except Exception as e:
                    self._safe_log('error', f"[ARCSignShop] Process shop creation error: {str(e)}")
                    error_form = ActionForm(
                        title=self.language_manager.GetText("SHOP_RESULT_TITLE"),
                        content=self.language_manager.GetText("SHOP_PANEL_ERROR")
                    )
                    error_form.add_button(
                        self.language_manager.GetText("SHOP_BACK_BUTTON"),
                        on_click=lambda s: self._show_shop_main_panel(s)
                    )
                    sender.send_form(error_form)
            
            title = self.language_manager.GetText("SHOP_BUY_PRICE_PANEL_TITLE" if base_type == "buy" else "SHOP_PRICE_PANEL_TITLE")
            if is_infinite:
                title = self.language_manager.GetText("SHOP_INFINITE_TITLE_PREFIX") + title
            price_panel = ModalForm(
                title=title,
                controls=controls,
                on_submit=process_shop_creation
            )
            
            player.send_form(price_panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show price setting panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_PANEL_ERROR"))

    # ==================== 官方定价模式 ====================

    def _with_trade_direction(self, shop_data, trade_type: str) -> dict:
        """复制商店数据并覆盖交易方向（用于二合一商店的单次买卖）。"""
        data = dict(shop_data)
        data['shop_type'] = trade_type
        return data

    def _show_official_mode_selection_panel(self, player):
        """兼容旧入口：官方自动定价统一为二合一。"""
        self._show_official_price_item_selection(player, "both")

    def _official_item_type_match_keys(self, item_type_id: str) -> set:
        """兼容 minecraft:diamond / diamond 的匹配键集合"""
        if not item_type_id:
            return set()
        keys = {item_type_id}
        if ':' in item_type_id:
            keys.add(item_type_id.split(':', 1)[1])
        else:
            keys.add(f'minecraft:{item_type_id}')
        return keys

    def _get_official_inventory_match_keys(self, player) -> set:
        """读取玩家背包，返回可用于匹配官方定价物品的类型键集合"""
        match_keys = set()
        try:
            if not self._require_inventory_manager(player):
                return match_keys
            for inv_item in self.inventory_manager.get_inventory_items(player):
                item_type_id = inv_item.get('type')
                if item_type_id:
                    match_keys.update(self._official_item_type_match_keys(item_type_id))
        except Exception as inv_e:
            self._safe_log('warning', f"[ARCSignShop] Official inventory read failed: {inv_e}")
        return match_keys

    def _priced_item_in_inventory(self, item_type: str, inv_match_keys: set) -> bool:
        if not item_type or not inv_match_keys:
            return False
        return bool(self._official_item_type_match_keys(item_type) & inv_match_keys)

    def _format_official_item_button(self, item_type: str, prices: dict, shop_type: str) -> str:
        """官方选物列表按钮文案"""
        display_name = self._mkt_display_name(item_type)
        if shop_type == "both":
            sell_final = self._mkt_final_price(item_type, 'sell', 0)
            buy_final = self._mkt_final_price(item_type, 'buy', 0)
            sell_base = prices.get('sell', 0)
            buy_base = prices.get('buy', 0)
            sell_text = f"{sell_final}" if sell_final is not None else f"{sell_base}"
            buy_text = f"{buy_final}" if buy_final is not None else self.language_manager.GetText("SHOP_BUY_SUSPENDED")
            return (
                f"{display_name} - "
                f"{self.language_manager.GetText('SHOP_OFFICIAL_SELL_PRICE')}{sell_text} "
                f"{self.language_manager.GetText('SHOP_OFFICIAL_BUY_PRICE')}{buy_text}"
            )
        if shop_type == "sell":
            price = prices.get('sell', 0)
            final_price = self._mkt_final_price(item_type, 'sell', 0)
            adj = self._mkt_adjustment(item_type)
            price_text = f"{price}"
            if adj['daily_adjust_percent'] != 0 or adj['demand_sell_adjust'] != 0:
                price_text = f"{final_price}({price})"
            return f"{display_name} - {self.language_manager.GetText('SHOP_OFFICIAL_SELL_PRICE')}{price_text}"
        price = prices.get('buy', 0)
        final_price = self._mkt_final_price(item_type, 'buy', 0)
        adj = self._mkt_adjustment(item_type)
        price_text = f"{price}"
        if adj['daily_adjust_percent'] != 0 or adj['demand_buy_adjust'] != 0:
            price_text = f"{final_price}({price})"
        return f"{display_name} - {self.language_manager.GetText('SHOP_OFFICIAL_BUY_PRICE')}{price_text}"

    def _show_official_price_item_selection(self, player, shop_type="both", from_mode_panel=False):
        """官方定价：先选分类（含背包内物品），再进入该类物品列表；默认二合一。"""
        mkt = self._require_market(player)
        if not mkt:
            return
        try:
            back_handler = lambda sender: self._show_official_pricing_mode_panel(sender)
            priced_items = self._mkt_list_items()
            if not priced_items:
                no_items_panel = ActionForm(
                    title=self.language_manager.GetText("SHOP_OFFICIAL_PRICE_TITLE"),
                    content=self.language_manager.GetText("SHOP_OFFICIAL_NO_ITEMS")
                )
                no_items_panel.add_button(
                    self.language_manager.GetText("SHOP_BACK_BUTTON"),
                    on_click=back_handler
                )
                player.send_form(no_items_panel)
                return

            inv_match_keys = self._get_official_inventory_match_keys(player)
            inventory_items = {
                t: p for t, p in priced_items.items()
                if self._priced_item_in_inventory(t, inv_match_keys)
            }
            category_counts = self._mkt_category_counts()
            category_order = self._mkt_categories()

            category_panel = ActionForm(
                title=self.language_manager.GetText("SHOP_OFFICIAL_CATEGORY_TITLE"),
                content=self.language_manager.GetText("SHOP_OFFICIAL_CATEGORY_CONTENT")
            )

            # 背包内物品单独一类，置顶
            if inventory_items:
                category_panel.add_button(
                    self.language_manager.GetText("SHOP_OFFICIAL_CATEGORY_INVENTORY").format(len(inventory_items)),
                    on_click=lambda sender: self._show_official_category_items(
                        sender, shop_type, "__inventory__", from_mode_panel, inventory_items
                    )
                )

            for category in category_order:
                count = category_counts.get(category, 0)
                if count <= 0:
                    continue
                category_panel.add_button(
                    self.language_manager.GetText("SHOP_OFFICIAL_CATEGORY_ITEM").format(category, count),
                    on_click=lambda sender, cat=category: self._show_official_category_items(
                        sender, shop_type, cat, from_mode_panel
                    )
                )

            category_panel.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=back_handler
            )
            player.send_form(category_panel)

        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show official price item selection error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_PANEL_ERROR"))

    def _show_official_category_items(self, player, shop_type, category, from_mode_panel=False, preloaded_items=None):
        """显示某一分类（或背包内物品）下的官方定价物品列表"""
        try:
            if category == "__inventory__":
                items = preloaded_items if preloaded_items is not None else {}
                if not items:
                    inv_match_keys = self._get_official_inventory_match_keys(player)
                    items = {
                        t: p for t, p in self._mkt_list_items().items()
                        if self._priced_item_in_inventory(t, inv_match_keys)
                    }
                title = self.language_manager.GetText("SHOP_OFFICIAL_CATEGORY_INVENTORY_TITLE")
                content = self.language_manager.GetText("SHOP_OFFICIAL_CATEGORY_INVENTORY_CONTENT")
            else:
                items = self._mkt_items_by_category(category)
                title = self.language_manager.GetText("SHOP_OFFICIAL_CATEGORY_ITEMS_TITLE").format(category)
                content = self.language_manager.GetText("SHOP_OFFICIAL_CATEGORY_ITEMS_CONTENT").format(category)

            item_panel = ActionForm(title=title, content=content)

            if not items:
                item_panel.add_button(
                    self.language_manager.GetText("SHOP_OFFICIAL_CATEGORY_EMPTY"),
                    on_click=lambda sender: self._show_official_price_item_selection(sender, shop_type, from_mode_panel)
                )
            else:
                for item_type, prices in items.items():
                    button_text = self._format_official_item_button(item_type, prices, shop_type)
                    item_panel.add_button(
                        button_text,
                        on_click=lambda sender, it=item_type, pr=prices: self._show_official_discount_panel(
                            sender, it, pr, shop_type
                        )
                    )

            item_panel.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_official_price_item_selection(sender, shop_type, from_mode_panel)
            )
            player.send_form(item_panel)

        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show official category items error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_PANEL_ERROR"))

    def _show_official_discount_panel(self, player, item_type, prices, shop_type="sell"):
        """显示官方定价折扣设置面板"""
        try:
            display_name = self._mkt_display_name(item_type)
            adj = self._mkt_adjustment(item_type)

            sell_base = prices.get('sell', 0)
            buy_base = prices.get('buy', 0)
            sell_final = self._mkt_final_price(item_type, 'sell', 0)
            buy_final = self._mkt_final_price(item_type, 'buy', 0)

            if shop_type == "both":
                info_text = self.language_manager.GetText("SHOP_OFFICIAL_DISCOUNT_INFO_BOTH").format(
                    display_name, sell_base, sell_final, buy_base,
                    buy_final if buy_final is not None else self.language_manager.GetText("SHOP_BUY_SUSPENDED")
                )
                base_price = sell_base
            elif shop_type == "sell":
                info_text = self.language_manager.GetText("SHOP_OFFICIAL_DISCOUNT_INFO_SELL").format(
                    display_name, sell_base, sell_final
                )
                base_price = sell_base
            else:
                if buy_final is None:
                    info_text = self.language_manager.GetText("SHOP_BUY_SUSPENDED_DETAIL")
                else:
                    info_text = self.language_manager.GetText("SHOP_OFFICIAL_DISCOUNT_INFO_BUY").format(
                        display_name, buy_base, buy_final
                    )
                base_price = buy_base

            # 显示动态定价信息
            if shop_type in ("sell", "both") and adj['demand_sell_adjust'] != 0:
                info_text += "\n" + self.language_manager.GetText("SHOP_OFFICIAL_DEMAND_ADJUST").format(
                    f"{adj['demand_sell_adjust']:+.1%}"
                )
            if shop_type in ("buy", "both") and adj['demand_buy_adjust'] != 0:
                info_text += "\n" + self.language_manager.GetText("SHOP_OFFICIAL_DEMAND_ADJUST").format(
                    f"{adj['demand_buy_adjust']:+.1%}"
                )

            if adj['daily_adjust_percent'] != 0:
                info_text += "\n" + self.language_manager.GetText("SHOP_OFFICIAL_DAILY_FLUCTUATION").format(
                    f"{adj['daily_adjust_percent']:+.1f}%"
                )

            info_label = Label(text=info_text)
            name_input = TextInput(
                label=self.language_manager.GetText("SHOP_DISPLAY_NAME_LABEL"),
                placeholder=self.language_manager.GetText("SHOP_DISPLAY_NAME_PLACEHOLDER"),
                default_value=display_name
            )
            discount_input = TextInput(
                label=self.language_manager.GetText("SHOP_OFFICIAL_DISCOUNT_LABEL"),
                placeholder=self.language_manager.GetText("SHOP_OFFICIAL_DISCOUNT_PLACEHOLDER"),
                default_value="0"
            )

            def process_official_shop_creation(sender, json_str: str):
                try:
                    data = json.loads(json_str)
                    # controls: [Label, display_name, discount]
                    custom_name = str(data[1] if len(data) > 1 else '').strip()
                    discount_str = data[2] if len(data) > 2 else '0'
                    try:
                        discount_percent = float(discount_str)
                        if discount_percent < -90 or discount_percent > 100:
                            raise ValueError("Discount out of range")
                    except ValueError:
                        result_form = ActionForm(
                            title=self.language_manager.GetText("SHOP_RESULT_TITLE"),
                            content=self.language_manager.GetText("SHOP_OFFICIAL_INVALID_DISCOUNT")
                        )
                        result_form.add_button(
                            self.language_manager.GetText("SHOP_BACK_BUTTON"),
                            on_click=lambda s: self._show_official_discount_panel(s, item_type, prices, shop_type)
                        )
                        sender.send_form(result_form)
                        return

                    # 计算最终价格（二合一用出售价作为 unit_price 快照；允许 0=待配置）
                    if shop_type == "both":
                        sell_price = self._mkt_final_price(item_type, 'sell', discount_percent)
                        buy_price = self._mkt_final_price(item_type, 'buy', discount_percent)
                        if sell_price is None:
                            calculated_price = None
                        else:
                            calculated_price = sell_price
                        setup_buy_price = buy_price
                    else:
                        calculated_price = self._mkt_final_price(item_type, shop_type, discount_percent)
                        setup_buy_price = None

                    if calculated_price is None:
                        result_form = ActionForm(
                            title=self.language_manager.GetText("SHOP_RESULT_TITLE"),
                            content=self.language_manager.GetText("SHOP_OFFICIAL_PRICE_ERROR")
                        )
                        result_form.add_button(
                            self.language_manager.GetText("SHOP_BACK_BUTTON"),
                            on_click=lambda s: self._show_official_discount_panel(s, item_type, prices, shop_type)
                        )
                        sender.send_form(result_form)
                        return

                    shop_display_name = custom_name if custom_name else display_name

                    # 构造物品信息（官方定价模式不需要从背包取物品）
                    item_info = {
                        'type': item_type,
                        'name': shop_display_name,
                        'count': 1,
                        'data': 0,
                        'enchants': {},
                        'lore': []
                    }

                    shop_data = {
                        'item_info': item_info,
                        'unit_price': calculated_price,
                        'shop_type': shop_type,
                        'budget': 0,
                        'is_infinite': True,
                        'pricing_mode': 'official',
                        'discount_percent': discount_percent,
                        'create_time': datetime.datetime.now()
                    }
                    self.setting_shop_player[sender.name] = shop_data

                    # 显示设置说明
                    discount_text = f" ({discount_percent:+.0f}%)" if discount_percent != 0 else ""
                    if shop_type == "both":
                        buy_display = setup_buy_price if setup_buy_price is not None else self.language_manager.GetText("SHOP_BUY_SUSPENDED")
                        instruction_content = self.language_manager.GetText("SHOP_OFFICIAL_SETUP_BOTH").format(
                            shop_display_name, calculated_price, buy_display, discount_text
                        ).replace('\\n', '\n')
                    elif shop_type == "sell":
                        instruction_content = self.language_manager.GetText("SHOP_OFFICIAL_SETUP_SELL").format(
                            shop_display_name, calculated_price, base_price, discount_text
                        ).replace('\\n', '\n')
                    else:
                        instruction_content = self.language_manager.GetText("SHOP_OFFICIAL_SETUP_BUY").format(
                            shop_display_name, calculated_price, base_price, discount_text
                        ).replace('\\n', '\n')

                    instruction_form = ActionForm(
                        title=self.language_manager.GetText("SHOP_SETUP_TITLE"),
                        content=instruction_content,
                        on_close=lambda s: None
                    )
                    sender.send_form(instruction_form)

                except Exception as e:
                    self._safe_log('error', f"[ARCSignShop] Process official shop creation error: {str(e)}")
                    error_form = ActionForm(
                        title=self.language_manager.GetText("SHOP_RESULT_TITLE"),
                        content=self.language_manager.GetText("SHOP_PANEL_ERROR")
                    )
                    error_form.add_button(
                        self.language_manager.GetText("SHOP_BACK_BUTTON"),
                        on_click=lambda s: self._show_shop_main_panel(s)
                    )
                    sender.send_form(error_form)

            if shop_type == "both":
                title = self.language_manager.GetText("SHOP_OFFICIAL_DISCOUNT_TITLE_BOTH")
            elif shop_type == "sell":
                title = self.language_manager.GetText("SHOP_OFFICIAL_DISCOUNT_TITLE_SELL")
            else:
                title = self.language_manager.GetText("SHOP_OFFICIAL_DISCOUNT_TITLE_BUY")
            discount_panel = ModalForm(
                title=title,
                controls=[info_label, name_input, discount_input],
                on_submit=process_official_shop_creation
            )

            player.send_form(discount_panel)

        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show official discount panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_PANEL_ERROR"))

    def _get_shop_display_price(self, shop_data) -> str:
        """获取商店的显示价格（官方定价模式返回动态价格，手动定价返回unit_price；以物易物返回比例）"""
        shop_type = shop_data.get('shop_type', 'sell')
        if shop_type == 'barter':
            try:
                item_data = json.loads(shop_data.get('item_data') or '{}')
                return self._format_barter_ratio_text(item_data)
            except Exception:
                return self.language_manager.GetText("SHOP_TYPE_TAG_BARTER")
        pricing_mode = shop_data.get('pricing_mode', 'manual')
        if pricing_mode == 'official':
            item_type = shop_data.get('item_type', '')
            discount_percent = float(shop_data.get('discount_percent', 0) or 0)
            if shop_type == 'both':
                sell_price = self._mkt_final_price(item_type, 'sell', discount_percent)
                buy_price = self._mkt_final_price(item_type, 'buy', discount_percent)
                sell_text = f"{sell_price}" if sell_price is not None else "?"
                buy_text = f"{buy_price}" if buy_price is not None else self.language_manager.GetText("SHOP_BUY_SUSPENDED")
                return self.language_manager.GetText("SHOP_DISPLAY_PRICE_BOTH").format(sell_text, buy_text)
            final_price = self._mkt_final_price(item_type, shop_type, discount_percent)
            if final_price is not None:
                return f"§d{final_price}§r"
            else:
                # 回收价反超出售价，回收已暂停
                if shop_type == 'buy':
                    return self.language_manager.GetText("SHOP_BUY_SUSPENDED")
        return shop_data.get('unit_price', 0)

    def _is_shop_infinite(self, shop_data) -> bool:
        """判断商店是否为无限商店（系统商店）；兼容 SQLite 中 0/1、字符串等类型"""
        if not shop_data:
            return False
        v = shop_data.get('is_infinite', 0)
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        try:
            return int(v) != 0
        except (TypeError, ValueError):
            return bool(v)

    def _is_player_shop_owner(self, player, shop_data) -> bool:
        """玩家是否为该店店主（系统商店无个人店主）"""
        if not shop_data or self._is_shop_infinite(shop_data):
            return False
        return str(player.unique_id) == str(shop_data.get('owner_xuid', ''))

    def _get_shop_owner_display(self, shop_data) -> str:
        """界面显示的「店主」：系统商店为官方，不显示创建者个人名（资金与其无关）"""
        if self._is_shop_infinite(shop_data):
            return self.language_manager.GetText("SHOP_OWNER_SYSTEM")
        return shop_data.get('owner_name', '')

    def _get_shop_type_manage_line(self, shop_data) -> str:
        """管理/详情用：一行说明是出售还是收购（含系统无限说明）"""
        shop_type = shop_data.get('shop_type', 'sell')
        is_infinite = self._is_shop_infinite(shop_data)
        pricing_mode = shop_data.get('pricing_mode', 'manual')
        if shop_type == 'barter':
            if is_infinite:
                return self.language_manager.GetText("SHOP_TYPE_MANAGE_BARTER_INFINITE")
            return self.language_manager.GetText("SHOP_TYPE_MANAGE_BARTER")
        if pricing_mode == 'official':
            if shop_type == 'both':
                return self.language_manager.GetText("SHOP_TYPE_MANAGE_BOTH_OFFICIAL")
            if shop_type == 'sell':
                return self.language_manager.GetText("SHOP_TYPE_MANAGE_SELL_OFFICIAL")
            return self.language_manager.GetText("SHOP_TYPE_MANAGE_BUY_OFFICIAL")
        if shop_type == 'sell':
            if is_infinite:
                return self.language_manager.GetText("SHOP_TYPE_MANAGE_SELL_INFINITE")
            return self.language_manager.GetText("SHOP_TYPE_MANAGE_SELL")
        if is_infinite:
            return self.language_manager.GetText("SHOP_TYPE_MANAGE_BUY_INFINITE")
        return self.language_manager.GetText("SHOP_TYPE_MANAGE_BUY")

    def _get_shop_type_short_tag(self, shop_data) -> str:
        """列表按钮用短标签：出售 / 收购 / 易物"""
        shop_type = shop_data.get('shop_type', 'sell')
        is_infinite = self._is_shop_infinite(shop_data)
        pricing_mode = shop_data.get('pricing_mode', 'manual')
        if shop_type == 'barter':
            return self.language_manager.GetText("SHOP_TYPE_TAG_BARTER_INFINITE") if is_infinite else self.language_manager.GetText("SHOP_TYPE_TAG_BARTER")
        if pricing_mode == 'official':
            if shop_type == 'both':
                return self.language_manager.GetText("SHOP_TYPE_TAG_BOTH_OFFICIAL")
            if shop_type == 'sell':
                return self.language_manager.GetText("SHOP_TYPE_TAG_SELL_OFFICIAL")
            return self.language_manager.GetText("SHOP_TYPE_TAG_BUY_OFFICIAL")
        if shop_type == 'sell':
            return self.language_manager.GetText("SHOP_TYPE_TAG_SELL_INFINITE") if is_infinite else self.language_manager.GetText("SHOP_TYPE_TAG_SELL")
        return self.language_manager.GetText("SHOP_TYPE_TAG_BUY_INFINITE") if is_infinite else self.language_manager.GetText("SHOP_TYPE_TAG_BUY")

    def _get_shop_type_plain_headline(self, shop_data) -> str:
        """管理面板顶部用：无 § 色码，避免部分客户端正文里看不清类型"""
        shop_type = shop_data.get('shop_type', 'sell')
        is_infinite = self._is_shop_infinite(shop_data)
        pricing_mode = shop_data.get('pricing_mode', 'manual')
        if shop_type == 'barter':
            sys_tag = self.language_manager.GetText("SHOP_TYPE_PLAIN_SYSTEM_TAG") if is_infinite else ""
            return self.language_manager.GetText("SHOP_TYPE_PLAIN_BARTER").format(sys_tag)
        if pricing_mode == 'official':
            official_tag = self.language_manager.GetText("SHOP_TYPE_PLAIN_OFFICIAL_TAG")
            if shop_type == 'both':
                return self.language_manager.GetText("SHOP_TYPE_PLAIN_BOTH").format(official_tag)
            if shop_type == 'sell':
                return self.language_manager.GetText("SHOP_TYPE_PLAIN_SELL").format(official_tag)
            return self.language_manager.GetText("SHOP_TYPE_PLAIN_BUY").format(official_tag)
        sys_tag = self.language_manager.GetText("SHOP_TYPE_PLAIN_SYSTEM_TAG") if is_infinite else ""
        if shop_type == 'sell':
            return self.language_manager.GetText("SHOP_TYPE_PLAIN_SELL").format(sys_tag)
        return self.language_manager.GetText("SHOP_TYPE_PLAIN_BUY").format(sys_tag)

    def _get_shop_manage_title_suffix(self, shop_data) -> str:
        """表单标题用短后缀，与正文类型一致（窗口标题不易被截断）"""
        shop_type = shop_data.get('shop_type', 'sell')
        is_infinite = self._is_shop_infinite(shop_data)
        pricing_mode = shop_data.get('pricing_mode', 'manual')
        if shop_type == 'barter':
            return self.language_manager.GetText("SHOP_MANAGE_TITLE_BARTER_INFINITE") if is_infinite else self.language_manager.GetText("SHOP_MANAGE_TITLE_BARTER")
        if pricing_mode == 'official':
            if shop_type == 'both':
                return self.language_manager.GetText("SHOP_MANAGE_TITLE_BOTH_OFFICIAL")
            if shop_type == 'sell':
                return self.language_manager.GetText("SHOP_MANAGE_TITLE_SELL_OFFICIAL")
            return self.language_manager.GetText("SHOP_MANAGE_TITLE_BUY_OFFICIAL")
        if shop_type == 'sell':
            return self.language_manager.GetText("SHOP_MANAGE_TITLE_SELL_INFINITE") if is_infinite else self.language_manager.GetText("SHOP_MANAGE_TITLE_SELL")
        return self.language_manager.GetText("SHOP_MANAGE_TITLE_BUY_INFINITE") if is_infinite else self.language_manager.GetText("SHOP_MANAGE_TITLE_BUY")

    def _shop_item_transaction_payload(self, item_data: dict, count: int) -> dict:
        """从商店 JSON item_data 构造背包校验/发放用的完整字段（含 NBT，避免丢失附魔书等标签）。"""
        payload = {
            'type': item_data['type'],
            'name': item_data.get('name', item_data['type']),
            'count': count,
            'data': item_data.get('data', 0),
            'enchants': item_data.get('enchants') or {},
            'lore': item_data.get('lore') or [],
        }
        nbt_b64 = item_data.get('nbt_b64')
        if nbt_b64:
            payload['nbt_b64'] = nbt_b64
        return payload

    def _show_shop_detail_panel(self, player, shop_data):
        """显示商店详情面板"""
        try:
            item_data = json.loads(shop_data['item_data'])
            shop_type = shop_data.get('shop_type', 'sell')
            is_infinite = self._is_shop_infinite(shop_data)
            
            shop_info = self.language_manager.GetText("SHOP_DETAIL_OWNER").format(self._get_shop_owner_display(shop_data)) + "\n"
            shop_info += self.language_manager.GetText("SHOP_DETAIL_TYPE").format(self._get_shop_type_plain_headline(shop_data)) + "\n"
            shop_info += self._get_shop_type_manage_line(shop_data) + "\n"
            shop_info += self.language_manager.GetText("SHOP_DETAIL_ITEM").format(item_data.get('name', 'Unknown')) + "\n"
            if shop_type == "barter":
                give_amount, cost_amount, cost_item = self._get_barter_trade_config(item_data)
                shop_info += self.language_manager.GetText("SHOP_DETAIL_BARTER_COST_ITEM").format(cost_item.get('name', '?')) + "\n"
                shop_info += self.language_manager.GetText("SHOP_DETAIL_BARTER_RATIO").format(
                    give_amount, item_data.get('name', '?'), cost_amount, cost_item.get('name', '?')
                ) + "\n"
                if is_infinite:
                    shop_info += self.language_manager.GetText("SHOP_DETAIL_STOCK").format(self.language_manager.GetText("SHOP_DETAIL_INFINITE_STOCK")) + "\n"
                else:
                    shop_info += self.language_manager.GetText("SHOP_DETAIL_STOCK").format(shop_data['stock']) + "\n"
            elif shop_type == "both":
                if is_infinite:
                    shop_info += self.language_manager.GetText("SHOP_DETAIL_STOCK").format(self.language_manager.GetText("SHOP_DETAIL_INFINITE_STOCK")) + "\n"
                    shop_info += self.language_manager.GetText("SHOP_DETAIL_BUDGET").format(self.language_manager.GetText("SHOP_DETAIL_INFINITE_BUDGET")) + "\n"
                else:
                    shop_info += self.language_manager.GetText("SHOP_DETAIL_STOCK").format(shop_data['stock']) + "\n"
            elif is_infinite:
                shop_info += (self.language_manager.GetText("SHOP_DETAIL_STOCK").format(self.language_manager.GetText("SHOP_DETAIL_INFINITE_STOCK")) + "\n") if shop_type == "sell" else (self.language_manager.GetText("SHOP_DETAIL_BUDGET").format(self.language_manager.GetText("SHOP_DETAIL_INFINITE_BUDGET")) + "\n")
            else:
                shop_info += (self.language_manager.GetText("SHOP_DETAIL_STOCK").format(shop_data['stock']) + "\n") if shop_type == "sell" else (self.language_manager.GetText("SHOP_DETAIL_BUDGET").format(shop_data['stock']) + "\n")
            if shop_type != "barter":
                shop_info += self.language_manager.GetText("SHOP_DETAIL_PRICE").format(self._get_shop_display_price(shop_data)) + "\n"
            
            # 官方定价模式：显示动态价格信息
            pricing_mode = shop_data.get('pricing_mode', 'manual')
            if pricing_mode == 'official':
                discount_percent = shop_data.get('discount_percent', 0.0)
                item_type = shop_data.get('item_type', '')
                if shop_type == 'both':
                    sell_price = self._mkt_final_price(item_type, 'sell', discount_percent)
                    buy_price = self._mkt_final_price(item_type, 'buy', discount_percent)
                    sell_base = self._mkt_base_price(item_type, 'sell')
                    buy_base = self._mkt_base_price(item_type, 'buy')
                    if sell_base is not None and sell_price is not None:
                        shop_info += self.language_manager.GetText("SHOP_DETAIL_BOTH_SELL_PRICE").format(sell_base, sell_price) + "\n"
                    if buy_base is not None:
                        buy_show = buy_price if buy_price is not None else self.language_manager.GetText("SHOP_BUY_SUSPENDED")
                        shop_info += self.language_manager.GetText("SHOP_DETAIL_BOTH_BUY_PRICE").format(buy_base, buy_show) + "\n"
                else:
                    display_price = self._mkt_final_price(item_type, shop_type, discount_percent)
                    if display_price is not None and display_price != shop_data['unit_price']:
                        shop_info += self.language_manager.GetText("SHOP_DETAIL_CURRENT_PRICE").format(display_price) + "\n"
                    elif display_price is None and shop_type == 'buy':
                        # 回收价反超出售价，回收已暂停
                        shop_info += self.language_manager.GetText("SHOP_BUY_SUSPENDED_DETAIL") + "\n"
                    adj = self._mkt_adjustment(item_type)
                    base_price = self._mkt_base_price(item_type, shop_type)
                    if base_price is not None:
                        shop_info += self.language_manager.GetText("SHOP_DETAIL_BASE_PRICE").format(base_price) + "\n"
                    if adj['demand_sell_adjust'] != 0 or adj['demand_buy_adjust'] != 0:
                        if shop_type == 'sell' and adj['demand_sell_adjust'] != 0:
                            shop_info += self.language_manager.GetText("SHOP_OFFICIAL_DEMAND_ADJUST").format(f"{adj['demand_sell_adjust']:+.1%}") + "\n"
                        elif shop_type == 'buy' and adj['demand_buy_adjust'] != 0:
                            shop_info += self.language_manager.GetText("SHOP_OFFICIAL_DEMAND_ADJUST").format(f"{adj['demand_buy_adjust']:+.1%}") + "\n"
                    if adj['daily_adjust_percent'] != 0:
                        shop_info += self.language_manager.GetText("SHOP_OFFICIAL_DAILY_FLUCTUATION").format(f"{adj['daily_adjust_percent']:+.1f}%") + "\n"
                if discount_percent != 0:
                    shop_info += self.language_manager.GetText("SHOP_OFFICIAL_DISCOUNT_DISPLAY").format(f"{discount_percent:+.0f}%") + "\n"
            
            # 添加附魔信息
            if item_data.get('enchants'):
                shop_info += "\n" + self.language_manager.GetText("SHOP_MANAGE_ENCHANTS")
                for enchant_id, level in item_data['enchants'].items():
                    shop_info += "\n" + self.language_manager.GetText("SHOP_MANAGE_ENCHANT_LINE").format(enchant_id, level)
            
            # 添加Lore信息
            if item_data.get('lore'):
                shop_info += "\n" + self.language_manager.GetText("SHOP_MANAGE_LORE")
                for lore_line in item_data['lore']:
                    shop_info += "\n  " + lore_line
            
            detail_panel = ActionForm(
                title=self.language_manager.GetText("SHOP_DETAIL_TITLE"),
                content=shop_info
            )
            
            # 交易按钮：系统/无限商店任何人（含创建者）都可交易，便于管理员自测；
            # 玩家商店仍禁止店主买自己的店。
            is_owner = self._is_player_shop_owner(player, shop_data)
            is_op = getattr(player, 'is_op', False)
            if shop_type == "barter":
                give_amount_for_trade, _, _ = self._get_barter_trade_config(item_data)
                can_trade = is_infinite or int(shop_data['stock']) >= give_amount_for_trade
            else:
                can_trade = (is_infinite or shop_data['stock'] > 0)
            show_trade = can_trade and (is_infinite or not is_owner)
            if show_trade:
                if shop_type == "both":
                    # 二合一：让玩家选择购买还是回收
                    detail_panel.add_button(
                        self.language_manager.GetText("SHOP_BOTH_BUY_FROM_SHOP_BUTTON"),
                        on_click=lambda sender: self._show_purchase_panel(sender, self._with_trade_direction(shop_data, 'sell'))
                    )
                    detail_panel.add_button(
                        self.language_manager.GetText("SHOP_BOTH_SELL_TO_SHOP_BUTTON"),
                        on_click=lambda sender: self._show_purchase_panel(sender, self._with_trade_direction(shop_data, 'buy'))
                    )
                elif shop_type == "barter":
                    detail_panel.add_button(
                        self.language_manager.GetText("SHOP_BARTER_TRADE_BUTTON"),
                        on_click=lambda sender: self._show_purchase_panel(sender, shop_data)
                    )
                elif shop_type == "sell":
                    # 出售商店 - 显示购买按钮
                    detail_panel.add_button(
                        self.language_manager.GetText("SHOP_BUY_BUTTON"),
                        on_click=lambda sender: self._show_purchase_panel(sender, shop_data)
                    )
                else:
                    # 收购商店 - 显示出售按钮
                    detail_panel.add_button(
                        self.language_manager.GetText("SHOP_SELL_BUTTON"),
                        on_click=lambda sender: self._show_purchase_panel(sender, shop_data)
                    )
            # 管理按钮：店主始终可管；系统商店 OP 也可管（与购买并存）
            if is_owner or (is_infinite and is_op):
                detail_panel.add_button(
                    self.language_manager.GetText("SHOP_MANAGE_BUTTON"),
                    on_click=lambda sender: self._show_shop_manage_panel(sender, shop_data)
                )
            
            # 关闭按钮
            detail_panel.add_button(
                self.language_manager.GetText("SHOP_CLOSE_BUTTON"),
                on_click=lambda sender: None
            )
            
            player.send_form(detail_panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show shop detail error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_PANEL_ERROR"))

    def _show_purchase_panel(self, player, shop_data):
        """显示购买面板"""
        try:
            item_data = json.loads(shop_data['item_data'])
            shop_type = shop_data.get('shop_type', 'sell')
            is_infinite = self._is_shop_infinite(shop_data)
            type_headline = f"{self._get_shop_type_plain_headline(shop_data)}\n\n"
            
            # 官方定价模式：使用动态计算价格
            pricing_mode = shop_data.get('pricing_mode', 'manual')
            discount_percent = 0.0
            item_type = shop_data.get('item_type', '')
            if pricing_mode == 'official':
                discount_percent = shop_data.get('discount_percent', 0.0)
                display_price = self._mkt_final_price(item_type, shop_type, discount_percent)
                if display_price is None:
                    display_price = shop_data['unit_price']
            else:
                display_price = shop_data['unit_price']

            give_amount = cost_amount = 1
            cost_item = {}
            max_lots = self.UNLIMITED_STOCK
            if shop_type == "barter":
                give_amount, cost_amount, cost_item = self._get_barter_trade_config(item_data)
                max_lots = self.UNLIMITED_STOCK if is_infinite else max(0, int(shop_data['stock']) // give_amount)
                purchase_info = type_headline + self.language_manager.GetText("SHOP_PURCHASE_BARTER_INFO").format(
                    item_data.get('name', 'Unknown'),
                    self.language_manager.GetText("SHOP_STOCK_INFINITE") if is_infinite else str(shop_data['stock']),
                    give_amount, item_data.get('name', '?'),
                    cost_amount, cost_item.get('name', '?'),
                    max_lots if not is_infinite else self.language_manager.GetText("SHOP_STOCK_INFINITE")
                ) + "\n"
            elif shop_type == "sell":
                purchase_info = type_headline + self.language_manager.GetText("SHOP_PURCHASE_SELL_INFO").format(item_data.get('name', 'Unknown'), self.language_manager.GetText("SHOP_STOCK_INFINITE") if is_infinite else str(shop_data['stock']), display_price) + "\n"
            else:
                purchase_info = type_headline + self.language_manager.GetText("SHOP_PURCHASE_BUY_INFO").format(item_data.get('name', 'Unknown'), self.language_manager.GetText("SHOP_STOCK_INFINITE") if is_infinite else str(shop_data['stock']), display_price) + "\n"
            
            # 官方定价模式：显示价格组成信息
            if pricing_mode == 'official' and shop_type != "barter":
                adj = self._mkt_adjustment(item_type)
                base_price = self._mkt_base_price(item_type, shop_type)
                if base_price is not None and display_price != base_price:
                    purchase_info += self.language_manager.GetText("SHOP_OFFICIAL_PRICE_BREAKDOWN").format(base_price, display_price) + "\n"
                if adj['demand_sell_adjust'] != 0 or adj['demand_buy_adjust'] != 0:
                    if shop_type == 'sell' and adj['demand_sell_adjust'] != 0:
                        purchase_info += self.language_manager.GetText("SHOP_OFFICIAL_DEMAND_ADJUST").format(f"{adj['demand_sell_adjust']:+.1%}") + "\n"
                    elif shop_type == 'buy' and adj['demand_buy_adjust'] != 0:
                        purchase_info += self.language_manager.GetText("SHOP_OFFICIAL_DEMAND_ADJUST").format(f"{adj['demand_buy_adjust']:+.1%}") + "\n"
                if adj['daily_adjust_percent'] != 0:
                    purchase_info += self.language_manager.GetText("SHOP_OFFICIAL_DAILY_FLUCTUATION").format(f"{adj['daily_adjust_percent']:+.1f}%") + "\n"
                if discount_percent != 0:
                    purchase_info += self.language_manager.GetText("SHOP_OFFICIAL_DISCOUNT_DISPLAY").format(f"{discount_percent:+.0f}%") + "\n"
            
            # 添加附魔信息
            if item_data.get('enchants'):
                purchase_info += "\n" + self.language_manager.GetText("SHOP_MANAGE_ENCHANTS")
                for enchant_id, level in item_data['enchants'].items():
                    purchase_info += "\n" + self.language_manager.GetText("SHOP_MANAGE_ENCHANT_LINE").format(enchant_id, level)
            
            # 添加Lore信息
            if item_data.get('lore'):
                purchase_info += "\n" + self.language_manager.GetText("SHOP_MANAGE_LORE")
                for lore_line in item_data['lore']:
                    purchase_info += "\n  " + lore_line
            
            # 添加税收信息（以物易物不收钱，不显示税金）
            if shop_type != "barter":
                tax_rate = self._get_tax_rate()
                if tax_rate > 0:
                    tax_percent = int(tax_rate * 100)
                    purchase_info += "\n\n" + self.language_manager.GetText("SHOP_TAX_RATE_DISPLAY").format(tax_percent)
            
            item_label = Label(text=purchase_info)
            
            if shop_type == "barter":
                quantity_placeholder = self.language_manager.GetText("SHOP_STOCK_INFINITE") if is_infinite else str(max_lots)
                quantity_input = TextInput(
                    label=self.language_manager.GetText("SHOP_BARTER_LOTS_LABEL"),
                    placeholder=quantity_placeholder,
                    default_value="1"
                )
            elif shop_type == "sell":
                quantity_placeholder = self.language_manager.GetText("SHOP_STOCK_INFINITE") if is_infinite else str(shop_data['stock'])
                quantity_input = TextInput(
                    label=self.language_manager.GetText("SHOP_QUANTITY_LABEL"),
                    placeholder=quantity_placeholder,
                    default_value="1"
                )
            else:
                quantity_placeholder = self.language_manager.GetText("SHOP_STOCK_INFINITE") if is_infinite else str(shop_data['stock'])
                quantity_input = TextInput(
                    label=self.language_manager.GetText("SHOP_SELL_QUANTITY_LABEL"),
                    placeholder=quantity_placeholder,
                    default_value="1"
                )
            
            def process_purchase(sender, json_str: str):
                try:
                    data = json.loads(json_str)
                    quantity_str = data[1]
                    try:
                        quantity = int(quantity_str)
                        if quantity <= 0:
                            raise ValueError("Quantity must be positive")
                        if shop_type == "barter":
                            if not is_infinite and quantity > max_lots:
                                raise ValueError("Not enough stock for lots")
                        else:
                            if not is_infinite and quantity > shop_data['stock']:
                                raise ValueError("Not enough stock")
                            if shop_type == "buy" and not is_infinite and quantity * display_price > shop_data['stock']:
                                raise ValueError("Not enough budget")
                    except ValueError as e:
                        result_form = ActionForm(
                            title=self.language_manager.GetText("SHOP_RESULT_TITLE"),
                            content=self.language_manager.GetText("SHOP_INVALID_QUANTITY")
                        )
                        result_form.add_button(
                            self.language_manager.GetText("SHOP_BACK_BUTTON"),
                            on_click=lambda s: self._show_purchase_panel(s, shop_data)
                        )
                        sender.send_form(result_form)
                        return
                    
                    # 执行购买
                    success, message = self._execute_purchase(sender, shop_data, quantity)
                    
                    result_form = ActionForm(
                        title=self.language_manager.GetText("SHOP_RESULT_TITLE"),
                        content=message,
                        on_close=lambda s: None
                    )
                    sender.send_form(result_form)
                    
                except Exception as e:
                    self._safe_log('error', f"[ARCSignShop] Process purchase error: {str(e)}")
                    error_form = ActionForm(
                        title=self.language_manager.GetText("SHOP_RESULT_TITLE"),
                        content=self.language_manager.GetText("SHOP_PANEL_ERROR"),
                        on_close=lambda s: None
                    )
                    sender.send_form(error_form)
            
            # 根据商店类型选择标题，并附带类型后缀（与「管理商店」一致）
            if shop_type == "barter":
                panel_title = self.language_manager.GetText("SHOP_BARTER_TRADE_TITLE")
            elif shop_type == "sell":
                panel_title = self.language_manager.GetText("SHOP_PURCHASE_TITLE")
            else:
                panel_title = self.language_manager.GetText("SHOP_SELL_TITLE")
            panel_title = f"{panel_title}{self._get_shop_manage_title_suffix(shop_data)}"
            
            purchase_panel = ModalForm(
                title=panel_title,
                controls=[item_label, quantity_input],
                on_submit=process_purchase
            )
            
            player.send_form(purchase_panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show purchase panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_PANEL_ERROR"))

    # 商店操作相关方法
    def _handle_shop_creation(self, player, block):
        """处理商店创建（含无限商店）"""
        try:
            if player.name not in self.setting_shop_player:
                return
            if not self._require_inventory_manager(player):
                return
            
            shop_data = self.setting_shop_player[player.name]
            item_info = shop_data['item_info']
            unit_price = shop_data['unit_price']
            shop_type = shop_data.get('shop_type', 'sell')
            budget = shop_data.get('budget', 0)
            is_infinite = shop_data.get('is_infinite', False)
            pricing_mode = shop_data.get('pricing_mode', 'manual')
            discount_percent = shop_data.get('discount_percent', 0.0)
            
            # 检查该位置是否已有商店
            existing_shop = self._get_shop_at_position(block.x, block.y, block.z, block.dimension.name)
            if existing_shop:
                player.send_message(self.language_manager.GetText("SHOP_ALREADY_EXISTS"))
                return
            
            if shop_type in ("sell", "barter"):
                # 出售/以物易物：创建时从背包扣除给出物 A
                create_item = dict(item_info)
                create_item.pop('barter_cost_item', None)
                if not is_infinite and not self.inventory_manager.has_item(player, create_item):
                    player.send_message(self.language_manager.GetText("SHOP_ITEM_NOT_FOUND"))
                    del self.setting_shop_player[player.name]
                    return
            else:
                if not is_infinite:
                    player_money = self._get_player_money(player.name)
                    if player_money < int(budget):
                        player.send_message(self.language_manager.GetText("SHOP_INSUFFICIENT_FUNDS_FOR_BUDGET").format(int(budget), player_money))
                        del self.setting_shop_player[player.name]
                        return
            
            shop_uuid = self._generate_shop_uuid()
            chunk_x, chunk_z = self._get_chunk_coords(block.x, block.z)
            
            if is_infinite:
                quantity = self.UNLIMITED_STOCK
                stock = self.UNLIMITED_STOCK
            elif shop_type in ("sell", "barter"):
                quantity = item_info['count']
                stock = item_info['count']
            else:
                quantity = int(budget / unit_price)
                stock = int(budget)
            
            new_shop = {
                'shop_uuid': shop_uuid,
                'owner_xuid': self.SYSTEM_OWNER_XUID if is_infinite else str(player.unique_id),
                'owner_name': self.SYSTEM_OWNER_NAME if is_infinite else player.name,
                'shop_type': shop_type,
                'x': block.x,
                'y': block.y,
                'z': block.z,
                'dimension': block.dimension.name,
                'chunk_x': chunk_x,
                'chunk_z': chunk_z,
                'item_type': item_info['type'],
                'item_data': json.dumps(item_info),
                'quantity': quantity,
                'unit_price': int(unit_price),
                'stock': stock,
                'is_infinite': 1 if is_infinite else 0,
                'pricing_mode': pricing_mode,
                'discount_percent': discount_percent,
                'create_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            operation_success = False
            remove_payload = dict(item_info)
            remove_payload.pop('barter_cost_item', None)
            if is_infinite:
                operation_success = True  # 无限商店不扣物品/预算
            elif shop_type in ("sell", "barter"):
                operation_success = self.inventory_manager.remove_item(player, remove_payload)
                if not operation_success:
                    player.send_message(self.language_manager.GetText("SHOP_ITEM_REMOVE_FAILED"))
            else:
                operation_success = self._change_player_money(player.name, -int(budget))
                if not operation_success:
                    player.send_message(self.language_manager.GetText("SHOP_BUDGET_DEDUCT_FAILED"))
            
            if operation_success:
                # 插入商店数据
                if self.db_manager.insert("sign_shops", new_shop):
                    # 更新区块索引
                    self._update_chunk_index(chunk_x, chunk_z, block.dimension.name, 1)
                    
                    if pricing_mode == 'official':
                        if shop_type == 'both':
                            player.send_message(self.language_manager.GetText("SHOP_OFFICIAL_CREATED_SUCCESS_BOTH").format(item_info['name'], unit_price, discount_percent))
                        else:
                            player.send_message(self.language_manager.GetText("SHOP_OFFICIAL_CREATED_SUCCESS").format(item_info['name'], unit_price, discount_percent))
                    elif is_infinite:
                        player.send_message(self.language_manager.GetText("SHOP_INFINITE_CREATED_SUCCESS").format(item_info['name'], unit_price))
                    elif shop_type == "barter":
                        give_amount, cost_amount, cost_item = self._get_barter_trade_config(item_info)
                        player.send_message(self.language_manager.GetText("SHOP_BARTER_CREATED_SUCCESS").format(
                            item_info['name'], item_info['count'],
                            give_amount, item_info['name'],
                            cost_amount, cost_item.get('name', '?')
                        ))
                    elif shop_type == "sell":
                        player.send_message(self.language_manager.GetText("SHOP_CREATED_SUCCESS").format(
                            item_info['name'], item_info['count'], unit_price
                        ))
                    else:
                        player.send_message(self.language_manager.GetText("SHOP_BUY_CREATED_SUCCESS").format(
                            item_info['name'], unit_price, int(budget), quantity
                        ))
                    self._safe_log('info', f"[ARCSignShop] Shop created by {player.name} at ({block.x}, {block.y}, {block.z})")
                    self._update_shop_sign_text(block=block, shop_data=new_shop)
                else:
                    # 如果创建失败，根据商店类型进行回滚（无限商店未扣物品/预算，无需回滚）
                    if not is_infinite:
                        if shop_type in ("sell", "barter"):
                            self.inventory_manager.give_item(player, remove_payload)
                        else:
                            self._change_player_money(player.name, int(budget))
                    player.send_message(self.language_manager.GetText("SHOP_CREATE_FAILED"))
            else:
                player.send_message(self.language_manager.GetText("SHOP_ITEM_REMOVE_FAILED"))
            
            # 清除设置状态
            del self.setting_shop_player[player.name]
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Handle shop creation error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_CREATE_FAILED"))
            if player.name in self.setting_shop_player:
                del self.setting_shop_player[player.name]

    def _execute_purchase(self, player, shop_data, quantity):
        """执行购买操作（支持出售商店、收购商店、以物易物和税收）"""
        try:
            shop_type = shop_data.get('shop_type', 'sell')

            # 检查当前商店状态
            current_shop = self._get_shop_by_id(shop_data['id'])
            if not current_shop or not current_shop['is_active']:
                return False, self.language_manager.GetText("SHOP_NOT_AVAILABLE")

            # 以物易物不依赖经济插件
            if shop_type == "barter":
                return self._execute_barter_trade(player, current_shop, quantity)

            pricing_mode = shop_data.get('pricing_mode', 'manual')
            
            # 官方定价模式：使用动态计算价格
            if pricing_mode == 'official':
                discount_percent = shop_data.get('discount_percent', 0.0)
                item_type = shop_data.get('item_type', '')
                final_unit_price = self._mkt_final_price(item_type, shop_type, discount_percent)
                if final_unit_price is None:
                    if shop_type == 'buy':
                        return False, self.language_manager.GetText("SHOP_BUY_SUSPENDED_MSG")
                    return False, self.language_manager.GetText("SHOP_OFFICIAL_PRICE_ERROR")
                unit_price = final_unit_price
            else:
                unit_price = shop_data['unit_price']
            
            base_price = int(quantity * unit_price)
            tax_amount = self._calculate_tax(base_price)
            total_price = base_price + tax_amount
            
            # 检查经济插件是否可用
            if not self.economy_plugin:
                return False, self.language_manager.GetText("SHOP_CORE_PLUGIN_NOT_FOUND")
            
            if shop_type == "sell":
                return self._execute_sell_shop_purchase(player, current_shop, quantity, base_price, tax_amount, total_price, unit_price)
            else:  # buy
                return self._execute_buy_shop_purchase(player, current_shop, quantity, base_price, tax_amount, total_price, unit_price)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Execute purchase error: {str(e)}")
            return False, self.language_manager.GetText("SHOP_PURCHASE_ERROR")

    def _execute_barter_trade(self, player, shop_data, lots):
        """执行以物易物：玩家交出 lots*Y 个 B，获得 lots*X 个 A"""
        try:
            if not self._require_inventory_manager(player):
                return False, self.language_manager.GetText("SHOP_PURCHASE_ERROR")
            item_data = json.loads(shop_data['item_data'])
            give_amount, cost_amount, cost_item = self._get_barter_trade_config(item_data)
            if not cost_item.get('type'):
                return False, self.language_manager.GetText("SHOP_BARTER_CONFIG_ERROR")

            lots = int(lots)
            if lots <= 0:
                return False, self.language_manager.GetText("SHOP_INVALID_QUANTITY")

            give_total = lots * give_amount
            cost_total = lots * cost_amount
            is_infinite = self._is_shop_infinite(shop_data)

            if not is_infinite and shop_data['stock'] < give_total:
                return False, self.language_manager.GetText("SHOP_INSUFFICIENT_STOCK")

            cost_payload = self._shop_item_transaction_payload(cost_item, cost_total)
            if not self.inventory_manager.has_item(player, cost_payload):
                return False, self.language_manager.GetText("SHOP_BARTER_NOT_ENOUGH_COST").format(
                    cost_total, cost_item.get('name', '?')
                )

            if not self.inventory_manager.remove_item(player, cost_payload):
                return False, self.language_manager.GetText("SHOP_ITEM_REMOVE_FAILED")

            give_payload = self._shop_item_transaction_payload(item_data, give_total)
            given_qty = self.inventory_manager.give_item_count(player, give_payload)
            if given_qty < give_total:
                # 发货不足：收回已发部分并退还全部代价物
                if given_qty > 0:
                    try:
                        self.inventory_manager.remove_item(
                            player, self._shop_item_transaction_payload(item_data, given_qty)
                        )
                    except Exception:
                        pass
                self.inventory_manager.give_item(player, cost_payload)
                return False, self.language_manager.GetText("SHOP_INVENTORY_FULL")

            update_data = {
                'last_purchase_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            if not is_infinite:
                new_stock = shop_data['stock'] - give_total
                collected_items = []
                if shop_data.get('collected_items'):
                    try:
                        collected_items = json.loads(shop_data['collected_items'])
                    except Exception:
                        collected_items = []
                collected_item = {
                    'type': cost_item['type'],
                    'name': cost_item.get('name', cost_item['type']),
                    'count': cost_total,
                    'data': cost_item.get('data', 0),
                    'enchants': cost_item.get('enchants') or {},
                    'lore': cost_item.get('lore') or [],
                    'collect_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                if cost_item.get('nbt_b64'):
                    collected_item['nbt_b64'] = cost_item['nbt_b64']
                collected_items.append(collected_item)
                update_data['stock'] = new_stock
                update_data['collected_items'] = json.dumps(collected_items)

            self.db_manager.update(
                table='sign_shops',
                data=update_data,
                where='id = ?',
                params=(shop_data['id'],)
            )

            self._record_transaction(shop_data['id'], player, lots, 0, 0, 0)

            if not is_infinite:
                try:
                    owner_player = self.server.get_player(shop_data['owner_name'])
                    if owner_player:
                        owner_player.send_message(
                            self.language_manager.GetText("SHOP_BARTER_NOTIFICATION").format(
                                player.name,
                                cost_total, cost_item.get('name', '?'),
                                give_total, item_data.get('name', '?')
                            )
                        )
                except Exception as e:
                    self._safe_log('error', f"[ARCSignShop] Notify barter owner error: {str(e)}")

            updated = self._get_shop_by_id(shop_data['id'])
            self._refresh_shop_sign_by_data(updated or shop_data)

            return True, self.language_manager.GetText("SHOP_BARTER_SUCCESS").format(
                cost_total, cost_item.get('name', '?'),
                give_total, item_data.get('name', '?')
            )
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Execute barter trade error: {str(e)}")
            return False, self.language_manager.GetText("SHOP_PURCHASE_ERROR")

    def _execute_sell_shop_purchase(self, player, shop_data, quantity, base_price, tax_amount, total_price, unit_price=None):
        """执行出售商店的购买操作（含无限商店）"""
        try:
            if not self._require_inventory_manager(player):
                return False, self.language_manager.GetText("SHOP_PURCHASE_ERROR")
            if unit_price is None:
                unit_price = shop_data['unit_price']
            buyer_money = self._get_player_money(player.name)
            if buyer_money < total_price:
                return False, self.language_manager.GetText("SHOP_INSUFFICIENT_FUNDS").format(total_price, buyer_money)
            
            is_infinite = self._is_shop_infinite(shop_data)
            if not is_infinite and shop_data['stock'] < quantity:
                return False, self.language_manager.GetText("SHOP_INSUFFICIENT_STOCK")
            
            # 先尝试发放物品，按“实际发放数量”结算，避免背包满导致部分到账但全额退款的漏洞
            item_data = json.loads(shop_data['item_data'])
            purchase_item = self._shop_item_transaction_payload(item_data, quantity)
            given_qty = self.inventory_manager.give_item_count(player, purchase_item)

            if given_qty <= 0:
                return False, self.language_manager.GetText("SHOP_ITEM_GIVE_FAILED")

            # 按实际发放数量重新计算费用/税
            actual_base_price = int(given_qty * unit_price)
            actual_tax_amount = self._calculate_tax(actual_base_price)
            actual_total_price = actual_base_price + actual_tax_amount

            # 买家扣款
            if not self._change_player_money(player.name, -actual_total_price):
                # 扣款失败：尝试把已发物品收回
                try:
                    rollback_item = self._shop_item_transaction_payload(item_data, given_qty)
                    self.inventory_manager.remove_item(player, rollback_item)
                except Exception:
                    pass
                return False, self.language_manager.GetText("SHOP_PAYMENT_FAILED")

            # 店主收款（系统/无限商店不收款）
            if not is_infinite and not self._change_player_money(shop_data['owner_name'], actual_base_price):
                # 店主收款失败：退还买家并回收物品
                self._change_player_money(player.name, actual_total_price)
                try:
                    rollback_item = self._shop_item_transaction_payload(item_data, given_qty)
                    self.inventory_manager.remove_item(player, rollback_item)
                except Exception:
                    pass
                return False, self.language_manager.GetText("SHOP_OWNER_PAYMENT_FAILED")

            # 更新库存（非无限商店按实际发放数量扣库存）
            update_data = {
                'last_purchase_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            if not is_infinite:
                new_stock = shop_data['stock'] - int(given_qty)
                update_data['stock'] = new_stock

            self.db_manager.update(
                table='sign_shops',
                data=update_data,
                where='id = ?',
                params=(shop_data['id'],)
            )

            # 记录交易（按实际数量）
            self._record_transaction(
                shop_data['id'],
                player,
                int(given_qty),
                unit_price,
                actual_total_price,
                actual_tax_amount
            )

            # 通知店主（按实际数量）
            self._notify_shop_owner(shop_data, player.name, int(given_qty), item_data['name'], actual_base_price, "sell")

            updated = self._get_shop_by_id(shop_data['id'])
            self._refresh_shop_sign_by_data(updated or shop_data)
            self._notify_market_trade(shop_data, int(given_qty), actual_base_price)

            # 若实际发放少于输入数量，给出明确提示
            if int(given_qty) < int(quantity):
                msg = self._get_purchase_success_message(int(given_qty), item_data['name'], actual_total_price, actual_tax_amount)
                msg += "\n" + self.language_manager.GetText("SHOP_PARTIAL_PURCHASE_NOTICE").format(given_qty, quantity)
                return True, msg

            return True, self._get_purchase_success_message(int(given_qty), item_data['name'], actual_total_price, actual_tax_amount)
                
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Execute sell shop purchase error: {str(e)}")
            return False, self.language_manager.GetText("SHOP_PURCHASE_ERROR")

    def _execute_buy_shop_purchase(self, player, shop_data, quantity, base_price, tax_amount, total_price, unit_price=None):
        """执行收购商店的购买操作（玩家出售物品给收购商店，含无限商店）"""
        try:
            if not self._require_inventory_manager(player):
                return False, self.language_manager.GetText("SHOP_PURCHASE_ERROR")
            if unit_price is None:
                unit_price = shop_data['unit_price']
            is_infinite = self._is_shop_infinite(shop_data)
            if not is_infinite and shop_data['stock'] < base_price:
                return False, self.language_manager.GetText("SHOP_INSUFFICIENT_BUDGET")
            
            item_data = json.loads(shop_data['item_data'])
            required_item = self._shop_item_transaction_payload(item_data, quantity)

            if not self.inventory_manager.has_item(player, required_item):
                return False, self.language_manager.GetText("SHOP_PLAYER_NO_ITEMS")
            
            if not self.inventory_manager.remove_item(player, required_item):
                return False, self.language_manager.GetText("SHOP_ITEM_REMOVE_FAILED")
            
            player_income = base_price - tax_amount
            if not self._change_player_money(player.name, player_income):
                self.inventory_manager.give_item(player, required_item)
                return False, self.language_manager.GetText("SHOP_PAYMENT_FAILED")
            
            update_data = {
                'last_purchase_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            if not is_infinite:
                new_budget = shop_data['stock'] - base_price
                collected_items = []
                if shop_data.get('collected_items'):
                    try:
                        collected_items = json.loads(shop_data['collected_items'])
                    except Exception:
                        collected_items = []
                collected_item = {
                    'type': item_data['type'],
                    'name': item_data['name'],
                    'count': quantity,
                    'data': item_data.get('data', 0),
                    'enchants': item_data.get('enchants', {}),
                    'lore': item_data.get('lore', []),
                    'collect_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                if item_data.get('nbt_b64'):
                    collected_item['nbt_b64'] = item_data['nbt_b64']
                collected_items.append(collected_item)
                update_data['stock'] = new_budget
                update_data['collected_items'] = json.dumps(collected_items)
            
            self.db_manager.update(
                table='sign_shops',
                data=update_data,
                where='id = ?',
                params=(shop_data['id'],)
            )
            
            # 记录交易（注意：对收购商店，玩家是卖家）
            self._record_transaction(shop_data['id'], player, quantity, unit_price, base_price, tax_amount, is_buy_shop=True)
            
            # 通知店主（系统商店不通知创建者）
            self._notify_shop_owner(shop_data, player.name, quantity, item_data['name'], base_price, "buy")

            updated = self._get_shop_by_id(shop_data['id'])
            self._refresh_shop_sign_by_data(updated or shop_data)
            self._notify_market_trade(shop_data, quantity, base_price)
            
            return True, self._get_sell_success_message(quantity, item_data['name'], player_income, tax_amount)
                
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Execute buy shop purchase error: {str(e)}")
            return False, self.language_manager.GetText("SHOP_PURCHASE_ERROR")

    # 交易辅助方法
    def _record_transaction(self, shop_id, player, quantity, unit_price, total_price, tax_amount, is_buy_shop=False):
        """记录交易"""
        try:
            transaction_data = {
                'shop_id': shop_id,
                'buyer_xuid': str(player.unique_id),
                'buyer_name': player.name,
                'quantity': quantity,
                'unit_price': unit_price,
                'total_price': total_price,
                'transaction_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            self.db_manager.insert("shop_transactions", transaction_data)
            self._sky_eye_log_shop_trade(
                player,
                shop_id=shop_id,
                quantity=quantity,
                unit_price=unit_price,
                total_price=total_price,
                tax_amount=tax_amount,
                is_buy_shop=is_buy_shop,
            )
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Record transaction error: {str(e)}")

    def _sky_eye_log_shop_trade(
        self,
        player,
        *,
        shop_id,
        quantity,
        unit_price,
        total_price,
        tax_amount=0,
        is_buy_shop=False,
    ):
        """写入弧光核心天眼（若已安装且已开启）。"""
        try:
            core = self.server.plugin_manager.get_plugin("arc_core")
            if core is None:
                return
            logger = getattr(core, "api_sky_eye_log", None)
            if not callable(logger):
                return
            shop_data = self._get_shop_by_id(shop_id) or {}
            item_data = {}
            try:
                item_data = json.loads(shop_data.get("item_data") or "{}")
            except Exception:
                item_data = {}
            item_name = item_data.get("name") or shop_data.get("item_type") or "?"
            shop_type = shop_data.get("shop_type") or ("buy" if is_buy_shop else "sell")
            detail = (
                f"shop_id={shop_id};type={shop_type};item={item_name};qty={quantity}"
                f";unit={unit_price};total={total_price};tax={tax_amount}"
            )
            owner_name = str(shop_data.get("owner_name") or "")
            logger(
                "ShopTrade",
                player=player,
                detail=detail,
                target_name=owner_name,
                target_type="shop_owner",
            )
        except Exception:
            pass

    def _notify_shop_owner(self, shop_data, buyer_name, quantity, item_name, amount, shop_type):
        """通知店主（系统/无限商店不通知创建者，资金与创建者无关）"""
        try:
            if self._is_shop_infinite(shop_data):
                return
            owner_player = self.server.get_player(shop_data['owner_name'])
            if owner_player:
                if shop_type == "sell":
                    message = self.language_manager.GetText("SHOP_SALE_NOTIFICATION").format(
                        buyer_name, quantity, item_name, amount
                    )
                else:
                    message = self.language_manager.GetText("SHOP_BUY_NOTIFICATION").format(
                        buyer_name, quantity, item_name, amount
                    )
                owner_player.send_message(message)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Notify shop owner error: {str(e)}")

    def _get_purchase_success_message(self, quantity, item_name, total_price, tax_amount):
        """获取购买成功消息"""
        if tax_amount > 0:
            tax_percent = int(self._get_tax_rate() * 100)
            return self.language_manager.GetText("SHOP_PURCHASE_SUCCESS_WITH_TAX").format(
                quantity, item_name, total_price, tax_amount
            ) + "\n" + self.language_manager.GetText("SHOP_TAX_INFO").format(tax_percent, tax_amount)
        else:
            return self.language_manager.GetText("SHOP_PURCHASE_SUCCESS").format(
                quantity, item_name, total_price
            )

    def _get_sell_success_message(self, quantity, item_name, income, tax_amount):
        """获取出售成功消息"""
        if tax_amount > 0:
            tax_percent = int(self._get_tax_rate() * 100)
            return self.language_manager.GetText("SHOP_SELL_SUCCESS_WITH_TAX").format(
                quantity, item_name, income, tax_amount
            ) + "\n" + self.language_manager.GetText("SHOP_TAX_INFO").format(tax_percent, tax_amount)
        else:
            return self.language_manager.GetText("SHOP_SELL_SUCCESS").format(
                quantity, item_name, income
            )

    def _rollback_sell_transaction(self, player, shop_data, total_price, base_price, is_infinite=False):
        """回滚出售交易（系统商店未给店主加钱，不得扣店主）"""
        try:
            self._change_player_money(player.name, total_price)
            if not is_infinite:
                self._change_player_money(shop_data['owner_name'], -base_price)
                self.db_manager.update(
                    table='sign_shops',
                    data={'stock': shop_data['stock']},
                    where='id = ?',
                    params=(shop_data['id'],)
                )
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Rollback transaction error: {str(e)}")

    # 辅助方法
    def _is_sign_block(self, block: Block) -> bool:
        """检查是否为木牌方块（站立/墙上/悬挂等）。"""
        if block is None or block.type is None:
            return False
        try:
            type_id = block.type.id if hasattr(block.type, 'id') else str(block.type)
            type_id = str(type_id).lower()
            return 'sign' in type_id
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Error checking sign block: {str(e)}")
            return False

    def _truncate_sign_line(self, text: str, max_len: int = 15) -> str:
        text = (text or "").replace('\n', ' ').strip()
        if len(text) <= max_len:
            return text
        return text[: max_len - 1] + "…"

    def _build_sign_lines(self, shop_data) -> list:
        """生成木牌四行文案。"""
        shop_type = shop_data.get('shop_type', 'sell')
        pricing_mode = shop_data.get('pricing_mode', 'manual')
        is_infinite = self._is_shop_infinite(shop_data)
        try:
            item_data = json.loads(shop_data.get('item_data') or '{}')
        except Exception:
            item_data = {}
        item_name = item_data.get('name') or shop_data.get('item_type', '?')
        stock = shop_data.get('stock', 0)
        stock_text = "∞" if is_infinite else str(stock)

        if shop_type == 'barter':
            give_amount, cost_amount, cost_item = self._get_barter_trade_config(item_data)
            cost_name = (cost_item or {}).get('name', '?')
            title = self.language_manager.GetText("SIGN_TITLE_BARTER")
            line2 = self.language_manager.GetText("SIGN_LINE_ITEM").format(self._truncate_sign_line(f"{item_name}↔{cost_name}", 12))
            line3 = self.language_manager.GetText("SIGN_LINE_RATIO").format(give_amount, cost_amount)
            line4 = self.language_manager.GetText("SIGN_LINE_STOCK").format(stock_text)
            return [title, line2, line3, line4]

        if pricing_mode == 'official' or is_infinite:
            if shop_type == 'both':
                title = self.language_manager.GetText("SIGN_TITLE_OFFICIAL_BOTH")
            elif shop_type == 'sell':
                title = self.language_manager.GetText("SIGN_TITLE_OFFICIAL_SELL")
            else:
                title = self.language_manager.GetText("SIGN_TITLE_OFFICIAL_BUY")
        else:
            title = self.language_manager.GetText(
                "SIGN_TITLE_PLAYER_SELL" if shop_type == 'sell' else "SIGN_TITLE_PLAYER_BUY"
            )
        price_text = self._get_shop_display_price(shop_data)
        # strip color codes for sign plain text
        if isinstance(price_text, str):
            price_text = re.sub(r'§.', '', price_text)
        line2 = self.language_manager.GetText("SIGN_LINE_ITEM").format(self._truncate_sign_line(str(item_name)))
        line3 = self.language_manager.GetText("SIGN_LINE_PRICE").format(price_text)
        line4 = self.language_manager.GetText("SIGN_LINE_STOCK").format(stock_text)
        return [title, line2, line3, line4]

    def _update_shop_sign_text(self, block: Block = None, shop_data=None, x=None, y=None, z=None, dimension=None) -> bool:
        """把商店信息写到木牌正面，并打蜡防止玩家编辑。"""
        try:
            if block is None:
                # 通过坐标在线找方块较困难，创建时一般直接传 block
                return False
            if not self._is_sign_block(block):
                return False
            if shop_data is None:
                shop_data = self._get_shop_at_position_optimized(
                    block.x, block.y, block.z, block.dimension.name
                )
            if not shop_data:
                return False

            state = block.capture_state()
            if not isinstance(state, Sign):
                self._safe_log('warning', f"[ARCSignShop] capture_state is not Sign: {type(state)}")
                return False

            lines = self._build_sign_lines(shop_data)
            front = state.get_side(Sign.Side.FRONT)
            for i in range(4):
                front.set_line(i, lines[i] if i < len(lines) else "")
            try:
                state.waxed = True
            except Exception:
                pass
            ok = state.update(force=False, apply_physics=False)
            if not ok:
                ok = state.update(force=True, apply_physics=False)
            return bool(ok)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Update sign text error: {str(e)}")
            return False

    def _refresh_shop_sign_by_data(self, shop_data) -> None:
        """交易/改库存后按坐标刷新木牌（需玩家附近或同维度可用）。"""
        try:
            if not shop_data:
                return
            # 尝试从在线玩家所在世界取方块
            dim_name = shop_data.get('dimension')
            x, y, z = shop_data.get('x'), shop_data.get('y'), shop_data.get('z')
            for player in list(getattr(self.server, 'online_players', []) or []):
                try:
                    loc = player.location
                    if getattr(loc.dimension, 'name', None) != dim_name:
                        continue
                    block = loc.dimension.get_block_at(int(x), int(y), int(z))
                    if block is not None:
                        self._update_shop_sign_text(block=block, shop_data=shop_data)
                        return
                except Exception:
                    continue
        except Exception as e:
            self._safe_log('warning', f"[ARCSignShop] Refresh sign by data failed: {e}")

    def _get_shop_at_position(self, x: int, y: int, z: int, dimension: str):
        """获取指定位置的商店（直接查询，用于API接口）"""
        try:
            return self.db_manager.query_one(
                "SELECT * FROM sign_shops WHERE x = ? AND y = ? AND z = ? AND dimension = ? AND is_active = 1",
                (x, y, z, dimension)
            )
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Get shop at position error: {str(e)}")
            return None

    def _get_shop_at_position_optimized(self, x: int, y: int, z: int, dimension: str):
        """获取指定位置的商店（优化版本，先查区块索引）"""
        try:
            # 1. 计算区块坐标
            chunk_x, chunk_z = self._get_chunk_coords(x, z)
            
            # 2. 检查该区块是否有商店
            chunk_has_shops = self.db_manager.query_one(
                "SELECT COUNT(*) as count FROM chunk_index WHERE chunk_x = ? AND chunk_z = ? AND dimension = ? AND shop_count > 0",
                (chunk_x, chunk_z, dimension)
            )
            
            # 3. 如果区块没有商店，直接返回None
            if not chunk_has_shops or chunk_has_shops['count'] == 0:
                return None
            
            # 4. 如果区块有商店，再精确查询该位置的商店
            return self.db_manager.query_one(
                "SELECT * FROM sign_shops WHERE x = ? AND y = ? AND z = ? AND dimension = ? AND is_active = 1",
                (x, y, z, dimension)
            )
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Get shop at position optimized error: {str(e)}")
            return None

    def _get_shop_by_id(self, shop_id: int):
        """根据ID获取商店"""
        try:
            return self.db_manager.query_one(
                "SELECT * FROM sign_shops WHERE id = ?",
                (shop_id,)
            )
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Get shop by id error: {str(e)}")
            return None

    def _get_chunk_coords(self, x: int, z: int) -> tuple:
        """获取区块坐标"""
        return x // self.CHUNK_SIZE, z // self.CHUNK_SIZE

    def _update_chunk_index(self, chunk_x: int, chunk_z: int, dimension: str, delta: int):
        """更新区块索引"""
        try:
            # 先尝试获取现有记录
            existing = self.db_manager.query_one(
                "SELECT shop_count FROM chunk_index WHERE chunk_x = ? AND chunk_z = ? AND dimension = ?",
                (chunk_x, chunk_z, dimension)
            )
            
            if existing:
                # 更新现有记录
                new_count = max(0, existing['shop_count'] + delta)
                self.db_manager.update(
                    table='chunk_index',
                    data={'shop_count': new_count},
                    where='chunk_x = ? AND chunk_z = ? AND dimension = ?',
                    params=(chunk_x, chunk_z, dimension)
                )
            else:
                # 创建新记录
                self.db_manager.insert("chunk_index", {
                    'chunk_x': chunk_x,
                    'chunk_z': chunk_z,
                    'dimension': dimension,
                    'shop_count': max(0, delta)
                })
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Update chunk index error: {str(e)}")

    def _generate_shop_uuid(self) -> str:
        """生成商店UUID"""
        import uuid
        return str(uuid.uuid4())

    def _calculate_tax(self, amount: int) -> int:
        """计算交易税（整数）"""
        try:
            tax_enabled = self.setting_manager.GetSetting("trade_tax_enabled")
            if tax_enabled and tax_enabled.lower() == "true":
                tax_rate = float(self.setting_manager.GetSetting("trade_tax_rate") or "0.05")
                return int(amount * tax_rate)
            return 0
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Calculate tax error: {str(e)}")
            return 0

    def _get_tax_rate(self) -> float:
        """获取税率"""
        try:
            return float(self.setting_manager.GetSetting("trade_tax_rate") or "0.05")
        except Exception:
            return 0.05

    def _handle_shop_manage_command(self, sender: CommandSender, args: list[str]) -> bool:
        """处理商店管理命令"""
        if not sender.is_op:
            sender.send_message(self.language_manager.GetText("NO_PERMISSION"))
            return True
        
        if not args:
            sender.send_message(self.language_manager.GetText("SHOP_MANAGE_USAGE"))
            return True
        
        command = args[0].lower()
        
        if command == "list":
            # 列出所有商店
            shops = self.db_manager.query_all("SELECT * FROM sign_shops WHERE is_active = 1")
            sender.send_message(self.language_manager.GetText("SHOP_MANAGE_ACTIVE_COUNT").format(len(shops)))
            
        elif command == "clear":
            # 清除所有商店（危险操作）
            self.db_manager.execute("DELETE FROM sign_shops")
            self.db_manager.execute("DELETE FROM shop_transactions") 
            self.db_manager.execute("DELETE FROM chunk_index")
            sender.send_message(self.language_manager.GetText("SHOP_MANAGE_CLEAR_SUCCESS"))
            
        elif command == "reload":
            # 重新加载配置
            sender.send_message(self.language_manager.GetText("SHOP_MANAGE_RELOAD_SUCCESS"))
            
        elif command == "prices":
            # 查看官方定价概览
            self._handle_prices_command(sender)
            
        elif command == "pricereload":
            # 重新加载官方定价配置
            mkt = self._require_market(sender if hasattr(sender, 'send_message') else None)
            if mkt: mkt.api_reload_prices()
            sender.send_message(self.language_manager.GetText("SHOP_MANAGE_PRICERELOAD_SUCCESS"))
            
        elif command == "pricereset":
            # 重置所有动态价格调整
            mkt = self._get_market()
            if mkt: mkt.api_reset_adjustments()
            sender.send_message(self.language_manager.GetText("SHOP_MANAGE_PRICERESET_SUCCESS"))

        elif command == "delns":
            # 按命名空间批量删除商店
            if hasattr(sender, 'send_form'):
                if len(args) >= 2:
                    namespace = args[1].strip()
                    if not namespace:
                        sender.send_message(self.language_manager.GetText("SHOP_MANAGE_DELNS_USAGE"))
                    else:
                        self._show_namespace_delete_confirm_panel(sender, namespace)
                else:
                    self._show_namespace_delete_panel(sender)
            else:
                sender.send_message(self.language_manager.GetText("PLAYER_ONLY_COMMAND"))
            
        else:
            sender.send_message(self.language_manager.GetText("SHOP_MANAGE_USAGE"))
            
        return True

    def _handle_prices_command(self, sender: CommandSender):
        """处理 /ssmanage prices：转发市场经济状态。"""
        mkt = self._require_market(sender if hasattr(sender, 'send_message') else None)
        if not mkt:
            return
        status = mkt.api_get_market_status()
        dyn = "§a启用" if status.get("dynamic_pricing_enabled") else "§c禁用"
        daily = "§a启用" if status.get("daily_fluctuation_enabled") else "§c禁用"
        content = self.language_manager.GetText("SHOP_MANAGE_PRICES_CONTENT").format(
            status.get("item_count", 0), dyn, daily
        )
        sender.send_message(content.replace("\\n", "\n"))
        sender.send_message(self.language_manager.GetText("SHOP_MANAGE_PRICES_MARKET_HINT"))
        priced_items = mkt.api_list_priced_items()
        for item_type, prices in list(priced_items.items())[:40]:
            display_name = mkt.api_get_display_name(item_type)
            sell_price = prices.get('sell', 'N/A')
            buy_price = prices.get('buy', 'N/A')
            adj = mkt.api_get_adjustment(item_type)
            line = f"§f{display_name}: §a出售{sell_price} §b收购{buy_price}"
            if adj.get('daily_adjust_percent', 0) != 0:
                sign = "+" if adj['daily_adjust_percent'] > 0 else ""
                line += f" §7(波动{sign}{adj['daily_adjust_percent']:.1f}%)"
            sender.send_message(line)

    def _get_item_namespace(self, item_type: str):
        """从 item_type 提取命名空间；无冒号或空命名空间返回 None"""
        if not item_type or not isinstance(item_type, str):
            return None
        if ':' not in item_type:
            return None
        namespace = item_type.split(':', 1)[0].strip()
        return namespace or None

    def _collect_shop_namespaces(self, exclude_minecraft: bool = True):
        """统计商店命名空间及数量，默认排除 minecraft。返回 [(namespace, count), ...]"""
        shops = self.db_manager.query_all("SELECT item_type FROM sign_shops") or []
        counts = {}
        for shop in shops:
            namespace = self._get_item_namespace(shop.get('item_type', ''))
            if not namespace:
                continue
            if exclude_minecraft and namespace.lower() == 'minecraft':
                continue
            counts[namespace] = counts.get(namespace, 0) + 1
        return sorted(counts.items(), key=lambda x: (-x[1], x[0].lower()))

    def _get_shops_by_namespace(self, namespace: str):
        """获取指定命名空间下的全部商店"""
        if not namespace:
            return []
        return self.db_manager.query_all(
            "SELECT * FROM sign_shops WHERE item_type LIKE ?",
            (f"{namespace}:%",)
        ) or []

    def _refund_shop_assets_to_owner(self, shop_data) -> None:
        """删除前向店主退还库存/预算/已收购物品（无限商店跳过）"""
        if self._is_shop_infinite(shop_data):
            return
        item_data = json.loads(shop_data['item_data'])
        shop_type = shop_data.get('shop_type', 'sell')
        owner_name = shop_data['owner_name']
        owner_player = self.server.get_player(owner_name)
        if shop_type in ("sell", "barter"):
            if shop_data['stock'] > 0 and owner_player:
                return_item = self._shop_item_transaction_payload(item_data, shop_data['stock'])
                given = self._give_items_to_player(owner_player, return_item)
                if given < int(shop_data['stock']):
                    self._safe_log(
                        "warning",
                        f"[ARCSignShop] Refund stock partial: want={shop_data['stock']} given={given} "
                        f"owner={owner_name} shop_id={shop_data.get('id')}",
                    )
            if shop_type == "barter" and owner_player:
                collected_items = []
                if shop_data.get('collected_items'):
                    try:
                        collected_items = json.loads(shop_data['collected_items'])
                    except Exception:
                        collected_items = []
                for item in collected_items:
                    self._give_items_to_player(owner_player, item)
        else:
            if shop_data['stock'] > 0:
                self._change_player_money(owner_name, shop_data['stock'])
            collected_items = []
            if shop_data.get('collected_items'):
                try:
                    collected_items = json.loads(shop_data['collected_items'])
                except Exception:
                    collected_items = []
            if owner_player:
                for item in collected_items:
                    self._give_items_to_player(owner_player, item)

    def _show_namespace_delete_panel(self, player):
        """显示按命名空间批量删除面板（OP）"""
        try:
            if not getattr(player, 'is_op', False):
                player.send_message(self.language_manager.GetText("NO_PERMISSION"))
                return

            namespaces = self._collect_shop_namespaces(exclude_minecraft=True)
            if not namespaces:
                empty_panel = ActionForm(
                    title=self.language_manager.GetText("SHOP_MANAGE_DELNS_TITLE"),
                    content=self.language_manager.GetText("SHOP_MANAGE_DELNS_EMPTY")
                )
                empty_panel.add_button(
                    self.language_manager.GetText("SHOP_BACK_BUTTON"),
                    on_click=lambda sender: self._show_shop_main_panel(sender)
                )
                player.send_form(empty_panel)
                return

            panel = ActionForm(
                title=self.language_manager.GetText("SHOP_MANAGE_DELNS_TITLE"),
                content=self.language_manager.GetText("SHOP_MANAGE_DELNS_CONTENT").format(len(namespaces)).replace('\\n', '\n')
            )
            for namespace, count in namespaces:
                panel.add_button(
                    self.language_manager.GetText("SHOP_MANAGE_DELNS_BUTTON_LINE").format(namespace, count),
                    on_click=lambda sender, ns=namespace: self._show_namespace_delete_confirm_panel(sender, ns)
                )
            panel.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_shop_main_panel(sender)
            )
            player.send_form(panel)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show namespace delete panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_MANAGE_DELNS_PANEL_ERROR"))

    def _show_namespace_delete_confirm_panel(self, player, namespace: str):
        """确认按命名空间批量删除"""
        try:
            if not getattr(player, 'is_op', False):
                player.send_message(self.language_manager.GetText("NO_PERMISSION"))
                return

            namespace = (namespace or "").strip()
            shops = self._get_shops_by_namespace(namespace)
            if not shops:
                player.send_message(self.language_manager.GetText("SHOP_MANAGE_DELNS_NOT_FOUND").format(namespace))
                if hasattr(player, 'send_form'):
                    self._show_namespace_delete_panel(player)
                return

            confirm_panel = ActionForm(
                title=self.language_manager.GetText("SHOP_MANAGE_DELNS_CONFIRM_TITLE"),
                content=self.language_manager.GetText("SHOP_MANAGE_DELNS_CONFIRM_CONTENT").format(
                    namespace, len(shops)
                ).replace('\\n', '\n')
            )
            confirm_panel.add_button(
                self.language_manager.GetText("SHOP_MANAGE_DELNS_CONFIRM_BUTTON"),
                on_click=lambda sender, ns=namespace: self._execute_delete_shops_by_namespace(sender, ns)
            )
            confirm_panel.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_namespace_delete_panel(sender)
            )
            player.send_form(confirm_panel)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show namespace delete confirm panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_MANAGE_DELNS_PANEL_ERROR"))

    def _execute_delete_shops_by_namespace(self, player, namespace: str):
        """执行按命名空间批量删除商店"""
        try:
            if not getattr(player, 'is_op', False):
                player.send_message(self.language_manager.GetText("NO_PERMISSION"))
                return

            namespace = (namespace or "").strip()
            shops = self._get_shops_by_namespace(namespace)
            if not shops:
                player.send_message(self.language_manager.GetText("SHOP_MANAGE_DELNS_NOT_FOUND").format(namespace))
                self._show_namespace_delete_panel(player)
                return

            deleted = 0
            for shop in shops:
                try:
                    self._refund_shop_assets_to_owner(shop)
                    self.db_manager.delete(
                        table='sign_shops',
                        where='id = ?',
                        params=(shop['id'],)
                    )
                    self._update_chunk_index(shop['chunk_x'], shop['chunk_z'], shop['dimension'], -1)
                    deleted += 1
                except Exception as shop_err:
                    self._safe_log(
                        'error',
                        f"[ARCSignShop] Delete shop {shop.get('id')} under namespace {namespace} error: {shop_err}"
                    )

            self._safe_log(
                'info',
                f"[ARCSignShop] OP {player.name} deleted {deleted} shops under namespace '{namespace}'"
            )
            result_form = ActionForm(
                title=self.language_manager.GetText("SHOP_MANAGE_DELNS_TITLE"),
                content=self.language_manager.GetText("SHOP_MANAGE_DELNS_SUCCESS").format(namespace, deleted)
            )
            result_form.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_namespace_delete_panel(sender)
            )
            player.send_form(result_form)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Execute delete shops by namespace error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_MANAGE_DELNS_PANEL_ERROR"))

    def _show_all_shops_panel(self, player):
        """显示全部商店面板（OP 管理用）"""
        try:
            if not getattr(player, 'is_op', False):
                player.send_message(self.language_manager.GetText("NO_PERMISSION"))
                return
            all_shops = self.db_manager.query_all(
                "SELECT * FROM sign_shops WHERE is_active = 1 ORDER BY create_time DESC"
            )
            if not all_shops:
                no_shops_panel = ActionForm(
                    title=self.language_manager.GetText("SHOP_ALL_SHOPS_TITLE"),
                    content=self.language_manager.GetText("SHOP_NO_ACTIVE_SHOPS")
                )
                no_shops_panel.add_button(
                    self.language_manager.GetText("SHOP_BACK_BUTTON"),
                    on_click=lambda sender: self._show_shop_main_panel(sender)
                )
                player.send_form(no_shops_panel)
                return
            panel = ActionForm(
                title=self.language_manager.GetText("SHOP_MANAGE_ALL_SHOPS_BUTTON"),
                content=self.language_manager.GetText("SHOP_ALL_SHOPS_CONTENT").format(len(all_shops))
            )
            for shop in all_shops[:50]:
                item_data = json.loads(shop['item_data'])
                is_infinite = self._is_shop_infinite(shop)
                stock_text = self.language_manager.GetText("SHOP_STOCK_INFINITE") if is_infinite else shop['stock']
                display_price = self._get_shop_display_price(shop)
                stock_label = (
                    self.language_manager.GetText('SHOP_STOCK_LABEL')
                    if shop.get('shop_type', 'sell') in ('sell', 'barter')
                    else self.language_manager.GetText('SHOP_BUDGET_LABEL')
                )
                price_label = (
                    self.language_manager.GetText('SHOP_BARTER_RATIO_LABEL')
                    if shop.get('shop_type', 'sell') == 'barter'
                    else self.language_manager.GetText('SHOP_UNIT_PRICE_LABEL')
                )
                button_text = f"{self._get_shop_type_short_tag(shop)} {item_data['name']} - {self._get_shop_owner_display(shop)} - {stock_label}:{stock_text} - {price_label}:{display_price}"
                panel.add_button(
                    button_text,
                    on_click=lambda sender, s=shop: self._show_shop_manage_panel(sender, s, from_all_shops=True)
                )
            panel.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_shop_main_panel(sender)
            )
            player.send_form(panel)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show all shops panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_ALL_SHOPS_PANEL_ERROR"))

    def _show_my_shops_panel(self, player):
        """显示我的商店面板"""
        try:
            my_shops = self.db_manager.query_all(
                "SELECT * FROM sign_shops WHERE owner_xuid = ? AND is_active = 1 ORDER BY create_time DESC",
                (str(player.unique_id),)
            )
            
            if not my_shops:
                no_shops_panel = ActionForm(
                    title=self.language_manager.GetText("SHOP_MY_SHOPS_TITLE"),
                    content=self.language_manager.GetText("SHOP_NO_MY_SHOPS")
                )
                no_shops_panel.add_button(
                    self.language_manager.GetText("SHOP_BACK_BUTTON"),
                    on_click=lambda sender: self._show_shop_main_panel(sender)
                )
                player.send_form(no_shops_panel)
                return
            
            # 显示商店列表
            my_shops_panel = ActionForm(
                title=self.language_manager.GetText("SHOP_MY_SHOPS_TITLE"),
                content=self.language_manager.GetText("SHOP_MY_SHOPS_CONTENT").format(len(my_shops))
            )
            
            for shop in my_shops:
                item_data = json.loads(shop['item_data'])
                stock_text = self.language_manager.GetText("SHOP_STOCK_INFINITE") if self._is_shop_infinite(shop) else shop['stock']
                display_price = self._get_shop_display_price(shop)
                price_label = (
                    self.language_manager.GetText('SHOP_BARTER_RATIO_LABEL')
                    if shop.get('shop_type', 'sell') == 'barter'
                    else self.language_manager.GetText('SHOP_UNIT_PRICE_LABEL')
                )
                button_text = f"{self._get_shop_type_short_tag(shop)} {item_data['name']} - {self.language_manager.GetText('SHOP_STOCK_LABEL')}:{stock_text} - {price_label}:{display_price}"
                if item_data.get('enchants'):
                    button_text += f" §b[{self.language_manager.GetText('SHOP_ENCHANT_TAG')}]"
                if item_data.get('lore'):
                    button_text += f" §d[{self.language_manager.GetText('SHOP_LORE_TAG')}]"
                my_shops_panel.add_button(
                    button_text,
                    on_click=lambda sender, s=shop: self._show_shop_manage_panel(sender, s)
                )
            
            my_shops_panel.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_shop_main_panel(sender)
            )
            
            player.send_form(my_shops_panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show my shops error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_ALL_SHOPS_PANEL_ERROR"))

    def _show_nearby_shops_panel(self, player):
        """显示附近商店面板"""
        try:
            player_loc = player.location
            chunk_x, chunk_z = self._get_chunk_coords(int(player_loc.x), int(player_loc.z))
            
            # 搜索附近9个区块的商店
            nearby_shops = []
            for dx in [-1, 0, 1]:
                for dz in [-1, 0, 1]:
                    search_chunk_x = chunk_x + dx
                    search_chunk_z = chunk_z + dz
                    
                    chunk_shops = self.db_manager.query_all(
                        "SELECT * FROM sign_shops WHERE chunk_x = ? AND chunk_z = ? AND dimension = ? AND is_active = 1",
                        (search_chunk_x, search_chunk_z, player_loc.dimension.name)
                    )
                    nearby_shops.extend(chunk_shops)
            
            if not nearby_shops:
                no_shops_panel = ActionForm(
                    title=self.language_manager.GetText("SHOP_NEARBY_SHOPS_TITLE"),
                    content=self.language_manager.GetText("SHOP_NO_NEARBY_SHOPS")
                )
                no_shops_panel.add_button(
                    self.language_manager.GetText("SHOP_BACK_BUTTON"),
                    on_click=lambda sender: self._show_shop_main_panel(sender)
                )
                player.send_form(no_shops_panel)
                return
            
            # 显示附近商店
            nearby_panel = ActionForm(
                title=self.language_manager.GetText("SHOP_NEARBY_SHOPS_TITLE"),
                content=self.language_manager.GetText("SHOP_NEARBY_SHOPS_CONTENT").format(len(nearby_shops))
            )
            
            for shop in nearby_shops[:20]:  # 最多显示20个
                item_data = json.loads(shop['item_data'])
                distance = math.sqrt(
                    (shop['x'] - player_loc.x) ** 2 + 
                    (shop['z'] - player_loc.z) ** 2
                )
                button_text = f"{self._get_shop_type_short_tag(shop)} {item_data['name']} - {self._get_shop_owner_display(shop)} - {distance:.1f}{self.language_manager.GetText('SHOP_BLOCKS_UNIT')}"
                
                # 添加附魔和Lore标识
                if item_data.get('enchants'):
                    button_text += f" §b[{self.language_manager.GetText('SHOP_ENCHANT_TAG')}]"
                if item_data.get('lore'):
                    button_text += f" §d[{self.language_manager.GetText('SHOP_LORE_TAG')}]"
                
                nearby_panel.add_button(
                    button_text,
                    on_click=lambda sender, s=shop: self._show_shop_detail_panel(sender, s)
                )
            
            nearby_panel.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_shop_main_panel(sender)
            )
            
            player.send_form(nearby_panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show nearby shops error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_NEARBY_SHOPS_PANEL_ERROR"))

    def _show_shop_manage_panel(self, player, shop_data, from_all_shops=False):
        """显示商店管理面板（from_all_shops 为 True 时返回至「管理全部商店」）"""
        try:
            item_data = json.loads(shop_data['item_data'])
            shop_type = shop_data.get('shop_type', 'sell')
            is_infinite = self._is_shop_infinite(shop_data)
            stock_text = self.language_manager.GetText("SHOP_STOCK_INFINITE") if is_infinite else shop_data['stock']
            
            if shop_type == "barter":
                price_label = self.language_manager.GetText("SHOP_BARTER_RATIO_LABEL")
            elif shop_type == "both":
                price_label = self.language_manager.GetText("SHOP_PRICE_BOTH_LABEL")
            elif shop_type == "sell":
                price_label = self.language_manager.GetText("SHOP_PRICE_SELL_LABEL")
            else:
                price_label = self.language_manager.GetText("SHOP_PRICE_BUY_LABEL")
            is_op_player = getattr(player, 'is_op', False)
            op_hint = self.language_manager.GetText("SHOP_OP_MANAGE_HINT") if is_op_player else ""
            # 无 § 的短标题置顶，避免正文里只注意到物品与单价
            if shop_type == "both":
                stock_line = f"{self.language_manager.GetText('SHOP_STOCK_LABEL')}: {stock_text}\n{self.language_manager.GetText('SHOP_BUDGET_BALANCE_LABEL')}: {stock_text}"
            elif shop_type in ("sell", "barter"):
                stock_line = f"{self.language_manager.GetText('SHOP_STOCK_LABEL')}: {stock_text}"
            else:
                stock_line = f"{self.language_manager.GetText('SHOP_BUDGET_BALANCE_LABEL')}: {stock_text}"
            manage_info = f"""{op_hint}{self.language_manager.GetText('SHOP_MANAGE_INFO_LABEL')}
————————————
{self._get_shop_type_plain_headline(shop_data)}
————————————
{self._get_shop_type_manage_line(shop_data)}

{self.language_manager.GetText('SHOP_DETAIL_ITEM')}: {item_data['name']}
{stock_line}
{price_label}: {self._get_shop_display_price(shop_data)}
{self.language_manager.GetText('SHOP_MANAGE_POSITION')}: ({shop_data['x']}, {shop_data['y']}, {shop_data['z']})
{self.language_manager.GetText('SHOP_MANAGE_CREATE_TIME')}: {shop_data['create_time']}"""
            
            # 添加附魔信息
            if item_data.get('enchants'):
                manage_info += f"\n\n{self.language_manager.GetText('SHOP_MANAGE_ENCHANTS')}:"
                for enchant_id, level in item_data['enchants'].items():
                    manage_info += f"\n  {enchant_id} [{self.language_manager.GetText('SHOP_MANAGE_LEVEL')} {level}]"
            
            # 添加Lore信息
            if item_data.get('lore'):
                manage_info += f"\n\n{self.language_manager.GetText('SHOP_MANAGE_LORE')}:"
                for lore_line in item_data['lore']:
                    manage_info += f"\n  {lore_line}"
            
            # 收购/以物易物商店显示收集的物品信息
            if shop_type in ("buy", "barter"):
                collected_items = []
                if shop_data.get('collected_items'):
                    try:
                        collected_items = json.loads(shop_data['collected_items'])
                    except:
                        collected_items = []
                
                total_collected = sum(item['count'] for item in collected_items)
                manage_info += f"\n\n{self.language_manager.GetText('SHOP_COLLECTED_ITEMS_TOTAL')}: {total_collected}"
            
            manage_title = f"{self.language_manager.GetText('SHOP_MANAGE_SHOP_TITLE')}{self._get_shop_manage_title_suffix(shop_data)}"
            manage_panel = ActionForm(
                title=manage_title,
                content=manage_info
            )
            
            # 根据商店类型显示不同的按钮（无限商店不显示补充库存/收取物品）
            if not is_infinite:
                if shop_type in ("sell", "barter"):
                    # 任意时刻可补货（未售罄也可），数量由玩家自行填写
                    manage_panel.add_button(
                        self.language_manager.GetText("SHOP_RESTOCK_BUTTON"),
                        on_click=lambda sender: self._show_restock_panel(sender, shop_data, from_all_shops)
                    )
                if shop_type in ("buy", "barter"):
                    collected_items = []
                    if shop_data.get('collected_items'):
                        try:
                            collected_items = json.loads(shop_data['collected_items'])
                        except Exception:
                            collected_items = []
                    if collected_items:
                        manage_panel.add_button(
                            self.language_manager.GetText("SHOP_COLLECT_ITEMS_BUTTON"),
                            on_click=lambda sender: self._show_collect_items_panel(sender, shop_data, from_all_shops)
                        )

            # 官方自动定价店：可关闭/开启出售或回收（二合一 ↔ 单功能）
            pricing_mode = shop_data.get('pricing_mode', 'manual')
            if pricing_mode == 'official' and shop_type in ('both', 'sell', 'buy'):
                if shop_type == 'both':
                    manage_panel.add_button(
                        self.language_manager.GetText("SHOP_DISABLE_SELL_BUTTON"),
                        on_click=lambda sender: self._change_official_trade_mode(
                            sender, shop_data, 'buy', from_all_shops
                        )
                    )
                    manage_panel.add_button(
                        self.language_manager.GetText("SHOP_DISABLE_BUY_BUTTON"),
                        on_click=lambda sender: self._change_official_trade_mode(
                            sender, shop_data, 'sell', from_all_shops
                        )
                    )
                elif shop_type == 'sell':
                    manage_panel.add_button(
                        self.language_manager.GetText("SHOP_ENABLE_BUY_BUTTON"),
                        on_click=lambda sender: self._change_official_trade_mode(
                            sender, shop_data, 'both', from_all_shops
                        )
                    )
                else:  # buy
                    manage_panel.add_button(
                        self.language_manager.GetText("SHOP_ENABLE_SELL_BUTTON"),
                        on_click=lambda sender: self._change_official_trade_mode(
                            sender, shop_data, 'both', from_all_shops
                        )
                    )
            
            # 删除商店按钮
            manage_panel.add_button(
                self.language_manager.GetText("SHOP_DELETE_SHOP_BUTTON"),
                on_click=lambda sender: self._show_delete_shop_panel(sender, shop_data, from_all_shops)
            )
            
            manage_panel.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_all_shops_panel(sender) if from_all_shops else self._show_my_shops_panel(sender)
            )
            
            player.send_form(manage_panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show shop manage panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_MANAGE_PANEL_ERROR"))

    def _change_official_trade_mode(self, player, shop_data, new_type: str, from_all_shops=False):
        """官方店在 both / sell / buy 间切换（关闭或重新开启出售/回收）。"""
        try:
            if new_type not in ("both", "sell", "buy"):
                player.send_message(self.language_manager.GetText("SHOP_TRADE_MODE_ERROR"))
                return
            if shop_data.get("pricing_mode", "manual") != "official":
                player.send_message(self.language_manager.GetText("SHOP_TRADE_MODE_OFFICIAL_ONLY"))
                return
            old_type = shop_data.get("shop_type", "sell")
            if old_type == new_type:
                self._show_shop_manage_panel(player, shop_data, from_all_shops)
                return
            self.db_manager.update(
                table="sign_shops",
                data={"shop_type": new_type},
                where="id = ?",
                params=(shop_data["id"],),
            )
            updated = self._get_shop_by_id(shop_data["id"])
            if not updated:
                player.send_message(self.language_manager.GetText("SHOP_TRADE_MODE_ERROR"))
                return
            self._refresh_shop_sign_by_data(updated)
            msg_key = {
                ("both", "sell"): "SHOP_TRADE_MODE_DISABLED_BUY",
                ("both", "buy"): "SHOP_TRADE_MODE_DISABLED_SELL",
                ("sell", "both"): "SHOP_TRADE_MODE_ENABLED_BUY",
                ("buy", "both"): "SHOP_TRADE_MODE_ENABLED_SELL",
            }.get((old_type, new_type), "SHOP_TRADE_MODE_CHANGED")
            result = ActionForm(
                title=self.language_manager.GetText("SHOP_TRADE_MODE_TITLE"),
                content=self.language_manager.GetText(msg_key),
            )
            result.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda s, sd=updated: self._show_shop_manage_panel(s, sd, from_all_shops),
            )
            player.send_form(result)
            self._safe_log(
                "info",
                f"[ARCSignShop] Shop {shop_data['id']} trade mode {old_type} -> {new_type} by {player.name}",
            )
        except Exception as e:
            self._safe_log("error", f"[ARCSignShop] Change official trade mode error: {e}")
            player.send_message(self.language_manager.GetText("SHOP_TRADE_MODE_ERROR"))

    def _convert_shop_to_infinite(self, player, shop_data, from_all_shops=False):
        """将商店转换为无限商店（系统商店），仅 OP 可用"""
        try:
            if not getattr(player, 'is_op', False):
                player.send_message(self.language_manager.GetText("NO_PERMISSION"))
                return
            if self._is_shop_infinite(shop_data):
                result_form = ActionForm(
                    title=self.language_manager.GetText("SHOP_CONVERT_INFINITE_TITLE"),
                    content=self.language_manager.GetText("SHOP_ALREADY_INFINITE")
                )
                result_form.add_button(
                    self.language_manager.GetText("SHOP_BACK_BUTTON"),
                    on_click=lambda s: self._show_shop_manage_panel(s, shop_data, from_all_shops)
                )
                player.send_form(result_form)
                return
            self.db_manager.update(
                table='sign_shops',
                data={
                    'is_infinite': 1,
                    'stock': self.UNLIMITED_STOCK,
                    'quantity': self.UNLIMITED_STOCK,
                    'owner_xuid': self.SYSTEM_OWNER_XUID,
                    'owner_name': self.SYSTEM_OWNER_NAME,
                },
                where='id = ?',
                params=(shop_data['id'],)
            )
            updated = self._get_shop_by_id(shop_data['id'])
            if updated:
                shop_data = updated
            result_form = ActionForm(
                title=self.language_manager.GetText("SHOP_CONVERT_INFINITE_TITLE"),
                content=self.language_manager.GetText("SHOP_CONVERT_INFINITE_SUCCESS")
            )
            result_form.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda s: self._show_shop_manage_panel(s, shop_data, from_all_shops)
            )
            player.send_form(result_form)
            self._safe_log('info', f"[ARCSignShop] Shop {shop_data['id']} converted to infinite by {player.name}")
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Convert to infinite error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_CONVERT_INFINITE_ERROR"))

    def _show_restock_panel(self, player, shop_data, from_all_shops=False):
        """显示补充库存面板（from_all_shops 用于返回至管理面板时保持来源）"""
        try:
            item_data = json.loads(shop_data['item_data'])
            restock_title = f"{self.language_manager.GetText('SHOP_RESTOCK_TITLE')}{self._get_shop_manage_title_suffix(shop_data)}"
            restock_info = f"{self._get_shop_type_plain_headline(shop_data)}\n\n{self.language_manager.GetText('SHOP_RESTOCK_FOR_ITEM').format(item_data['name'])}\n{self.language_manager.GetText('SHOP_CURRENT_STOCK')}: {shop_data['stock']}"
            
            # 添加附魔信息
            if item_data.get('enchants'):
                restock_info += f"\n\n{self.language_manager.GetText('SHOP_MANAGE_ENCHANTS')}:"
                for enchant_id, level in item_data['enchants'].items():
                    restock_info += f"\n  {enchant_id} [{self.language_manager.GetText('SHOP_MANAGE_LEVEL')} {level}]"
            
            # 添加Lore信息
            if item_data.get('lore'):
                restock_info += f"\n\n{self.language_manager.GetText('SHOP_MANAGE_LORE')}:"
                for lore_line in item_data['lore']:
                    restock_info += f"\n  {lore_line}"
            
            restock_label = Label(text=restock_info)
            
            quantity_input = TextInput(
                label=self.language_manager.GetText("SHOP_RESTOCK_QUANTITY_LABEL"),
                placeholder=self.language_manager.GetText("SHOP_RESTOCK_QUANTITY_PLACEHOLDER"),
                default_value=""
            )
            
            def process_restock(sender, json_str: str):
                try:
                    data = json.loads(json_str)
                    quantity_str = data[1]
                    
                    try:
                        quantity = int(quantity_str)
                        if quantity <= 0:
                            raise ValueError("Quantity must be positive")
                    except ValueError:
                        error_form = ActionForm(
                            title=restock_title,
                            content=self.language_manager.GetText("SHOP_INVALID_QUANTITY")
                        )
                        error_form.add_button(
                            self.language_manager.GetText("SHOP_BACK_BUTTON"),
                            on_click=lambda s: self._show_restock_panel(s, shop_data, from_all_shops)
                        )
                        sender.send_form(error_form)
                        return
                    
                    # 检查玩家是否有足够的物品
                    required_item = self._shop_item_transaction_payload(item_data, quantity)

                    if not self._require_inventory_manager(sender):
                        return
                    if self.inventory_manager.has_item(sender, required_item) and self.inventory_manager.remove_item(sender, required_item):
                        # 更新库存（可随时补货；同步抬高 quantity 上限记录）
                        new_stock = shop_data['stock'] + quantity
                        new_quantity = max(int(shop_data.get('quantity') or 0), new_stock)
                        self.db_manager.update(
                            table='sign_shops',
                            data={'stock': new_stock, 'quantity': new_quantity, 'is_active': 1},
                            where='id = ?',
                            params=(shop_data['id'],)
                        )
                        updated_shop = self._get_shop_by_id(shop_data['id']) or {
                            **shop_data, 'stock': new_stock, 'quantity': new_quantity, 'is_active': 1
                        }
                        self._refresh_shop_sign_by_data(updated_shop)
                        
                        success_form = ActionForm(
                            title=restock_title,
                            content=self.language_manager.GetText("SHOP_RESTOCK_SUCCESS").format(quantity, item_data['name'])
                        )
                        success_form.add_button(
                            self.language_manager.GetText("SHOP_BACK_BUTTON"),
                            on_click=lambda s, shop=updated_shop: self._show_shop_manage_panel(s, shop, from_all_shops)
                        )
                        sender.send_form(success_form)
                    else:
                        error_form = ActionForm(
                            title=restock_title,
                            content=self.language_manager.GetText("SHOP_NOT_ENOUGH_ITEMS")
                        )
                        error_form.add_button(
                            self.language_manager.GetText("SHOP_BACK_BUTTON"),
                            on_click=lambda s: self._show_restock_panel(s, shop_data, from_all_shops)
                        )
                        sender.send_form(error_form)
                
                except Exception as e:
                    self._safe_log('error', f"[ARCSignShop] Process restock error: {str(e)}")
                    error_form = ActionForm(
                        title=restock_title,
                        content=self.language_manager.GetText("SHOP_RESTOCK_ERROR")
                    )
                    error_form.add_button(
                        self.language_manager.GetText("SHOP_BACK_BUTTON"),
                        on_click=lambda s: self._show_shop_manage_panel(s, shop_data, from_all_shops)
                    )
                    sender.send_form(error_form)
            
            restock_panel = ModalForm(
                title=restock_title,
                controls=[restock_label, quantity_input],
                on_submit=process_restock
            )
            
            player.send_form(restock_panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show restock panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_RESTOCK_PANEL_ERROR"))

    def _show_delete_shop_panel(self, player, shop_data, from_all_shops=False):
        """显示删除商店确认面板（from_all_shops 为 True 时删除后返回「管理全部商店」）"""
        try:
            item_data = json.loads(shop_data['item_data'])
            shop_type = shop_data.get('shop_type', 'sell')
            is_infinite = self._is_shop_infinite(shop_data)
            stock_display = self.language_manager.GetText('SHOP_STOCK_INFINITE') if is_infinite else shop_data['stock']
            stock_line = (
                f"{self.language_manager.GetText('SHOP_REMAINING_STOCK')}: {stock_display}"
                if shop_type in ('sell', 'barter')
                else f"{self.language_manager.GetText('SHOP_REMAINING_BUDGET')}: {stock_display}"
            )
            delete_title = f"{self.language_manager.GetText('SHOP_DELETE_SHOP_TITLE')}{self._get_shop_manage_title_suffix(shop_data)}"
            confirm_content = f"""{self._get_shop_type_plain_headline(shop_data)}

{self.language_manager.GetText('SHOP_CONFIRM_DELETE')}

{self.language_manager.GetText('SHOP_DETAIL_ITEM')}: {item_data['name']}
{stock_line}"""
            
            # 添加附魔信息
            if item_data.get('enchants'):
                confirm_content += f"\n\n{self.language_manager.GetText('SHOP_MANAGE_ENCHANTS')}:"
                for enchant_id, level in item_data['enchants'].items():
                    confirm_content += f"\n  {enchant_id} [{self.language_manager.GetText('SHOP_MANAGE_LEVEL')} {level}]"
            
            # 添加Lore信息
            if item_data.get('lore'):
                confirm_content += f"\n\n{self.language_manager.GetText('SHOP_MANAGE_LORE')}:"
                for lore_line in item_data['lore']:
                    confirm_content += f"\n  {lore_line}"
            
            if is_infinite:
                confirm_content += f"\n\n{self.language_manager.GetText('SHOP_DELETE_INFINITE_NOTICE')}"
            elif shop_type == 'barter':
                confirm_content += f"\n\n{self.language_manager.GetText('SHOP_DELETE_BARTER_NOTICE')}"
            elif shop_type == 'sell':
                confirm_content += f"\n\n{self.language_manager.GetText('SHOP_DELETE_SELL_NOTICE')}"
            else:
                confirm_content += f"\n\n{self.language_manager.GetText('SHOP_DELETE_BUY_NOTICE')}"
            
            confirm_panel = ActionForm(
                title=delete_title,
                content=confirm_content
            )
            
            confirm_panel.add_button(
                self.language_manager.GetText("SHOP_CONFIRM_DELETE_BUTTON"),
                on_click=lambda sender: self._execute_delete_shop(sender, shop_data, from_all_shops)
            )
            
            confirm_panel.add_button(
                self.language_manager.GetText("SHOP_CANCEL_BUTTON"),
                on_click=lambda sender: self._show_shop_manage_panel(sender, shop_data, from_all_shops)
            )
            
            player.send_form(confirm_panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show delete shop panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_DELETE_PANEL_ERROR"))

    def _show_break_delete_confirm_panel(self, player, shop_data):
        """破坏按钮时直接显示删除确认面板（含商店基本信息、确认/取消）"""
        try:
            item_data = json.loads(shop_data['item_data'])
            shop_type = shop_data.get('shop_type', 'sell')
            is_infinite = self._is_shop_infinite(shop_data)
            stock_display = self.language_manager.GetText('SHOP_STOCK_INFINITE') if is_infinite else shop_data['stock']
            stock_line = (
                f"{self.language_manager.GetText('SHOP_REMAINING_STOCK')}: {stock_display}"
                if shop_type in ('sell', 'barter')
                else f"{self.language_manager.GetText('SHOP_REMAINING_BUDGET')}: {stock_display}"
            )
            confirm_title = f"{self.language_manager.GetText('SHOP_DELETE_SHOP_TITLE')}{self._get_shop_manage_title_suffix(shop_data)}"
            price_line = (
                f"{self.language_manager.GetText('SHOP_BARTER_RATIO_LABEL')}: {self._get_shop_display_price(shop_data)}"
                if shop_type == 'barter'
                else f"{self.language_manager.GetText('SHOP_UNIT_PRICE_LABEL')}: {shop_data['unit_price']}"
            )
            confirm_content = f"""{self._get_shop_type_plain_headline(shop_data)}

{self.language_manager.GetText('SHOP_CONFIRM_DELETE')}

{self.language_manager.GetText('SHOP_DETAIL_ITEM')}: {item_data['name']}
{stock_line}
{price_line}"""

            # 添加附魔信息
            if item_data.get('enchants'):
                confirm_content += f"\n\n{self.language_manager.GetText('SHOP_MANAGE_ENCHANTS')}:"
                for enchant_id, level in item_data['enchants'].items():
                    confirm_content += f"\n  {enchant_id} [{self.language_manager.GetText('SHOP_MANAGE_LEVEL')} {level}]"

            # 添加Lore信息
            if item_data.get('lore'):
                confirm_content += f"\n\n{self.language_manager.GetText('SHOP_MANAGE_LORE')}:"
                for lore_line in item_data['lore']:
                    confirm_content += f"\n  {lore_line}"

            if is_infinite:
                confirm_content += f"\n\n{self.language_manager.GetText('SHOP_DELETE_INFINITE_NOTICE')}"
            elif shop_type == 'barter':
                confirm_content += f"\n\n{self.language_manager.GetText('SHOP_DELETE_BARTER_NOTICE')}"
            elif shop_type == 'sell':
                confirm_content += f"\n\n{self.language_manager.GetText('SHOP_DELETE_SELL_NOTICE')}"
            else:
                confirm_content += f"\n\n{self.language_manager.GetText('SHOP_DELETE_BUY_NOTICE')}"

            confirm_panel = ActionForm(
                title=confirm_title,
                content=confirm_content
            )

            confirm_panel.add_button(
                self.language_manager.GetText("SHOP_CONFIRM_DELETE_BUTTON"),
                on_click=lambda sender: self._execute_break_delete(sender, shop_data)
            )

            confirm_panel.add_button(
                self.language_manager.GetText("SHOP_CANCEL_BUTTON"),
                on_click=lambda sender: None
            )

            player.send_form(confirm_panel)

        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show break delete confirm panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_DELETE_PANEL_ERROR"))

    def _execute_break_delete(self, player, shop_data):
        """执行破坏按钮触发的删除操作，删除后仅显示结果不返回任何列表"""
        try:
            self._handle_shop_removal_by_owner(player, shop_data)

            item_data = json.loads(shop_data['item_data'])
            shop_type = shop_data.get('shop_type', 'sell')
            is_infinite = self._is_shop_infinite(shop_data)
            delete_title = f"{self.language_manager.GetText('SHOP_DELETE_SHOP_TITLE')}{self._get_shop_manage_title_suffix(shop_data)}"

            if is_infinite:
                result_content = self.language_manager.GetText("SHOP_SYSTEM_DELETE_SUCCESS")
            elif shop_type in ('sell', 'barter'):
                result_content = self.language_manager.GetText("SHOP_DELETE_SELL_RETURN").format(shop_data['stock'], item_data['name'])
            else:
                result_content = self.language_manager.GetText("SHOP_DELETE_BUY_RETURN").format(shop_data['stock'])

            result_form = ActionForm(
                title=delete_title,
                content=result_content
            )
            result_form.add_button(
                self.language_manager.GetText("SHOP_CLOSE_BUTTON"),
                on_click=lambda sender: None
            )
            player.send_form(result_form)

        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Execute break delete error: {str(e)}")
            delete_title = f"{self.language_manager.GetText('SHOP_DELETE_SHOP_TITLE')}{self._get_shop_manage_title_suffix(shop_data)}"
            error_form = ActionForm(
                title=delete_title,
                content=self.language_manager.GetText("SHOP_DELETE_ERROR")
            )
            error_form.add_button(
                self.language_manager.GetText("SHOP_CLOSE_BUTTON"),
                on_click=lambda sender: None
            )
            player.send_form(error_form)

    def _handle_shop_removal_by_owner(self, player, shop_data):
        """处理店主破坏商店按钮（删除商店）"""
        try:
            item_data = json.loads(shop_data['item_data'])
            shop_type = shop_data.get('shop_type', 'sell')
            is_infinite = self._is_shop_infinite(shop_data)
            
            if not is_infinite:
                if shop_type in ("sell", "barter"):
                    if shop_data['stock'] > 0:
                        return_item = self._shop_item_transaction_payload(item_data, shop_data['stock'])
                        given = self._give_items_to_player(player, return_item)
                        player.send_message(self.language_manager.GetText("SHOP_REMOVED_BY_OWNER_SELL").format(
                            given, item_data['name']
                        ))
                        if given < int(shop_data['stock']):
                            self._safe_log(
                                "warning",
                                f"[ARCSignShop] Owner break refund partial: want={shop_data['stock']} given={given} "
                                f"shop_id={shop_data.get('id')}",
                            )
                    if shop_type == "barter":
                        collected_items = []
                        if shop_data.get('collected_items'):
                            try:
                                collected_items = json.loads(shop_data['collected_items'])
                            except Exception:
                                collected_items = []
                        if collected_items:
                            total_items = 0
                            for item in collected_items:
                                total_items += self._give_items_to_player(player, item)
                            player.send_message(self.language_manager.GetText("SHOP_BREAK_DELETE_SUCCESS").format(len(collected_items), total_items))
                else:
                    if shop_data['stock'] > 0:
                        self._change_player_money(player.name, shop_data['stock'])
                        player.send_message(self.language_manager.GetText("SHOP_REMOVED_BY_OWNER_BUY").format(
                            shop_data['stock']
                        ))
                    collected_items = []
                    if shop_data.get('collected_items'):
                        try:
                            collected_items = json.loads(shop_data['collected_items'])
                        except Exception:
                            collected_items = []
                    if collected_items:
                        total_items = 0
                        for item in collected_items:
                            total_items += self._give_items_to_player(player, item)
                        player.send_message(self.language_manager.GetText("SHOP_BREAK_DELETE_SUCCESS").format(len(collected_items), total_items))
            else:
                player.send_message(self.language_manager.GetText("SHOP_SYSTEM_DELETED"))
            
            # 删除商店记录
            self.db_manager.delete(
                table='sign_shops',
                where='id = ?',
                params=(shop_data['id'],)
            )
            
            # 更新区块索引
            self._update_chunk_index(shop_data['chunk_x'], shop_data['chunk_z'], shop_data['dimension'], -1)
            
            self._safe_log('info', f"[ARCSignShop] Shop removed by owner {player.name} at ({shop_data['x']}, {shop_data['y']}, {shop_data['z']})")
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Handle shop removal by owner error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_REMOVAL_ERROR"))

    def _show_collect_items_panel(self, player, shop_data, from_all_shops=False):
        """显示收取物品面板（from_all_shops 用于返回至管理面板时保持来源）"""
        try:
            collect_title = f"{self.language_manager.GetText('SHOP_COLLECT_ITEMS_TITLE')}{self._get_shop_manage_title_suffix(shop_data)}"
            collected_items = []
            if shop_data.get('collected_items'):
                try:
                    collected_items = json.loads(shop_data['collected_items'])
                except Exception:
                    collected_items = []
            
            if not collected_items:
                no_items_panel = ActionForm(
                    title=collect_title,
                    content=f"{self._get_shop_type_plain_headline(shop_data)}\n\n{self.language_manager.GetText('SHOP_NO_COLLECTED_ITEMS')}"
                )
                no_items_panel.add_button(
                    self.language_manager.GetText("SHOP_BACK_BUTTON"),
                    on_click=lambda sender: self._show_shop_manage_panel(sender, shop_data, from_all_shops)
                )
                player.send_form(no_items_panel)
                return
            
            collect_panel = ActionForm(
                title=collect_title,
                content=f"{self._get_shop_type_plain_headline(shop_data)}\n\n{self.language_manager.GetText('SHOP_COLLECTED_ITEMS_COUNT').format(len(collected_items))}"
            )
            
            for i, item in enumerate(collected_items):
                button_text = f"{item['name']} x{item['count']} - {item['collect_time']}"
                if item.get('enchants'):
                    button_text += f" §b[{self.language_manager.GetText('SHOP_ENCHANT_TAG')}]"
                if item.get('lore'):
                    button_text += f" §d[{self.language_manager.GetText('SHOP_LORE_TAG')}]"
                collect_panel.add_button(
                    button_text,
                    on_click=lambda sender, item_data=item, item_index=i: self._collect_single_item(sender, shop_data, item_data, item_index, from_all_shops)
                )
            
            collect_panel.add_button(
                self.language_manager.GetText("SHOP_COLLECT_ALL_BUTTON"),
                on_click=lambda sender: self._collect_all_items(sender, shop_data, from_all_shops)
            )
            
            collect_panel.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_shop_manage_panel(sender, shop_data, from_all_shops)
            )
            
            player.send_form(collect_panel)
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Show collect items panel error: {str(e)}")
            player.send_message(self.language_manager.GetText("SHOP_COLLECT_PANEL_ERROR"))

    def _collect_single_item(self, player, shop_data, item_data, item_index, from_all_shops=False):
        """收取单个物品"""
        try:
            collect_title = f"{self.language_manager.GetText('SHOP_COLLECT_ITEMS_TITLE')}{self._get_shop_manage_title_suffix(shop_data)}"
            if self._give_items_to_player(player, item_data) >= int(item_data.get('count', 0) or 0):
                collected_items = []
                if shop_data.get('collected_items'):
                    try:
                        collected_items = json.loads(shop_data['collected_items'])
                    except Exception:
                        collected_items = []
                if item_index < len(collected_items):
                    collected_items.pop(item_index)
                self.db_manager.update(
                    table='sign_shops',
                    data={'collected_items': json.dumps(collected_items)},
                    where='id = ?',
                    params=(shop_data['id'],)
                )
                success_form = ActionForm(
                    title=collect_title,
                    content=self.language_manager.GetText("SHOP_COLLECT_SINGLE_SUCCESS").format(item_data['count'], item_data['name'])
                )
                success_form.add_button(
                    self.language_manager.GetText("SHOP_BACK_BUTTON"),
                    on_click=lambda sender: self._show_collect_items_panel(sender, shop_data, from_all_shops)
                )
                player.send_form(success_form)
            else:
                error_form = ActionForm(
                    title=collect_title,
                    content=self.language_manager.GetText("SHOP_INVENTORY_FULL_COLLECT")
                )
                error_form.add_button(
                    self.language_manager.GetText("SHOP_BACK_BUTTON"),
                    on_click=lambda sender: self._show_collect_items_panel(sender, shop_data, from_all_shops)
                )
                player.send_form(error_form)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Collect single item error: {str(e)}")
            collect_title = f"{self.language_manager.GetText('SHOP_COLLECT_ITEMS_TITLE')}{self._get_shop_manage_title_suffix(shop_data)}"
            error_form = ActionForm(
                title=collect_title,
                content=self.language_manager.GetText("SHOP_COLLECT_ITEM_ERROR")
            )
            error_form.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_collect_items_panel(sender, shop_data, from_all_shops)
            )
            player.send_form(error_form)

    def _collect_all_items(self, player, shop_data, from_all_shops=False):
        """一键收取所有物品"""
        try:
            collect_title = f"{self.language_manager.GetText('SHOP_COLLECT_ITEMS_TITLE')}{self._get_shop_manage_title_suffix(shop_data)}"
            collected_items = []
            if shop_data.get('collected_items'):
                try:
                    collected_items = json.loads(shop_data['collected_items'])
                except Exception:
                    collected_items = []
            if not collected_items:
                no_items_panel = ActionForm(
                    title=collect_title,
                    content=f"{self._get_shop_type_plain_headline(shop_data)}\n\n{self.language_manager.GetText('SHOP_NO_COLLECTED_ITEMS')}"
                )
                no_items_panel.add_button(
                    self.language_manager.GetText("SHOP_BACK_BUTTON"),
                    on_click=lambda sender: self._show_shop_manage_panel(sender, shop_data, from_all_shops)
                )
                player.send_form(no_items_panel)
                return
            success_count = 0
            failed_items = []
            for item in collected_items:
                if self._give_items_to_player(player, item) >= int(item.get('count', 0) or 0):
                    success_count += 1
                else:
                    failed_items.append(item)
            if success_count > 0:
                self.db_manager.update(
                    table='sign_shops',
                    data={'collected_items': json.dumps(failed_items)},
                    where='id = ?',
                    params=(shop_data['id'],)
                )
            if success_count == len(collected_items):
                result_content = self.language_manager.GetText("SHOP_COLLECT_ALL_SUCCESS").format(success_count)
            elif success_count > 0:
                result_content = self.language_manager.GetText("SHOP_COLLECT_PARTIAL_SUCCESS").format(success_count, len(failed_items))
            else:
                result_content = self.language_manager.GetText("SHOP_INVENTORY_FULL_COLLECT_ALL")
            result_form = ActionForm(
                title=collect_title,
                content=result_content
            )
            result_form.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_shop_manage_panel(sender, shop_data, from_all_shops)
            )
            player.send_form(result_form)
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Collect all items error: {str(e)}")
            collect_title = f"{self.language_manager.GetText('SHOP_COLLECT_ITEMS_TITLE')}{self._get_shop_manage_title_suffix(shop_data)}"
            error_form = ActionForm(
                title=collect_title,
                content=self.language_manager.GetText("SHOP_COLLECT_ITEM_ERROR")
            )
            error_form.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=lambda sender: self._show_shop_manage_panel(sender, shop_data, from_all_shops)
            )
            player.send_form(error_form)

    def _execute_delete_shop(self, player, shop_data, from_all_shops=False):
        """执行删除商店操作（from_all_shops 为 True 时删除后返回「管理全部商店」；返还物品/资金给店主）"""
        try:
            item_data = json.loads(shop_data['item_data'])
            shop_type = shop_data.get('shop_type', 'sell')
            is_infinite = self._is_shop_infinite(shop_data)
            delete_title = f"{self.language_manager.GetText('SHOP_DELETE_SHOP_TITLE')}{self._get_shop_manage_title_suffix(shop_data)}"
            owner_name = shop_data['owner_name']
            owner_player = self.server.get_player(owner_name)  # 店主（在线才可返还物品）
            
            if not is_infinite:
                if shop_type in ("sell", "barter"):
                    if shop_data['stock'] > 0 and owner_player:
                        return_item = self._shop_item_transaction_payload(item_data, shop_data['stock'])
                        given = self._give_items_to_player(owner_player, return_item)
                        if given < int(shop_data['stock']):
                            self._safe_log(
                                "warning",
                                f"[ARCSignShop] Delete refund partial: want={shop_data['stock']} given={given} "
                                f"owner={owner_name} shop_id={shop_data.get('id')}",
                            )
                    if shop_type == "barter":
                        collected_items = []
                        if shop_data.get('collected_items'):
                            try:
                                collected_items = json.loads(shop_data['collected_items'])
                            except Exception:
                                collected_items = []
                        for item in collected_items:
                            if owner_player:
                                self._give_items_to_player(owner_player, item)
                else:
                    if shop_data['stock'] > 0:
                        self._change_player_money(owner_name, shop_data['stock'])
                    collected_items = []
                    if shop_data.get('collected_items'):
                        try:
                            collected_items = json.loads(shop_data['collected_items'])
                        except Exception:
                            collected_items = []
                    for item in collected_items:
                        if owner_player:
                            self._give_items_to_player(owner_player, item)
            
            self.db_manager.delete(
                table='sign_shops',
                where='id = ?',
                params=(shop_data['id'],)
            )
            self._update_chunk_index(shop_data['chunk_x'], shop_data['chunk_z'], shop_data['dimension'], -1)
            
            if is_infinite:
                result_content = self.language_manager.GetText("SHOP_SYSTEM_DELETE_SUCCESS")
            elif shop_type in ("sell", "barter"):
                result_content = self.language_manager.GetText("SHOP_DELETE_SELL_RETURN").format(shop_data['stock'], item_data['name'])
            else:
                result_content = self.language_manager.GetText("SHOP_DELETE_BUY_RETURN").format(shop_data['stock'])
            
            go_back = lambda s: self._show_all_shops_panel(s) if from_all_shops else self._show_my_shops_panel(s)
            result_form = ActionForm(
                title=delete_title,
                content=result_content
            )
            result_form.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=go_back
            )
            player.send_form(result_form)
            self._safe_log('info', f"[ARCSignShop] Shop deleted by {player.name} at ({shop_data['x']}, {shop_data['y']}, {shop_data['z']})")
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Execute delete shop error: {str(e)}")
            go_back = lambda s: self._show_all_shops_panel(s) if from_all_shops else self._show_my_shops_panel(s)
            delete_title = f"{self.language_manager.GetText('SHOP_DELETE_SHOP_TITLE')}{self._get_shop_manage_title_suffix(shop_data)}"
            error_form = ActionForm(
                title=delete_title,
                content=self.language_manager.GetText("SHOP_DELETE_ERROR")
            )
            error_form.add_button(
                self.language_manager.GetText("SHOP_BACK_BUTTON"),
                on_click=go_back
            )
            player.send_form(error_form)

    # API 接口方法
    def api_get_shop_at_position(self, x: int, y: int, z: int, dimension: str) -> dict:
        """获取指定位置的商店信息（API接口）"""
        return self._get_shop_at_position(x, y, z, dimension)
    
    def api_get_player_shops(self, player_xuid: str) -> list:
        """获取玩家的所有商店（API接口）"""
        try:
            return self.db_manager.query_all(
                "SELECT * FROM sign_shops WHERE owner_xuid = ? AND is_active = 1 ORDER BY create_time DESC",
                (player_xuid,)
            )
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Get player shops error: {str(e)}")
            return []
    
    def api_get_nearby_shops(self, x: int, z: int, dimension: str, radius: int = 1) -> list:
        """获取指定位置附近的商店（基于区块，用于浏览功能）"""
        try:
            chunk_x, chunk_z = self._get_chunk_coords(x, z)
            nearby_shops = []
            
            # 搜索指定半径内的区块
            for dx in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    search_chunk_x = chunk_x + dx
                    search_chunk_z = chunk_z + dz
                    
                    chunk_shops = self.db_manager.query_all(
                        "SELECT * FROM sign_shops WHERE chunk_x = ? AND chunk_z = ? AND dimension = ? AND is_active = 1",
                        (search_chunk_x, search_chunk_z, dimension)
                    )
                    nearby_shops.extend(chunk_shops)
            
            return nearby_shops
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Get nearby shops error: {str(e)}")
            return []
    
    def api_get_all_active_shops(self) -> list:
        """获取所有活跃的商店"""
        try:
            return self.db_manager.query_all(
                "SELECT * FROM sign_shops WHERE is_active = 1 ORDER BY create_time DESC"
            )
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] Get all active shops error: {str(e)}")
            return []
    
    def api_purchase_from_shop(self, shop_id: int, buyer_xuid: str, quantity: int) -> tuple[bool, str]:
        """从商店购买商品（API接口）"""
        try:
            # 获取商店信息
            shop_data = self._get_shop_by_id(shop_id)
            if not shop_data:
                return False, self.language_manager.GetText("SHOP_API_NOT_FOUND")
            
            # 通过xuid查找买家
            buyer_player = None
            for player in self.server.online_players:
                if str(player.unique_id) == buyer_xuid:
                    buyer_player = player
                    break
            
            if not buyer_player:
                return False, self.language_manager.GetText("SHOP_API_BUYER_OFFLINE")
            
            # 执行购买
            return self._execute_purchase(buyer_player, shop_data, quantity)
            
        except Exception as e:
            self._safe_log('error', f"[ARCSignShop] API purchase error: {str(e)}")
            return False, self.language_manager.GetText("SHOP_API_PURCHASE_ERROR")
