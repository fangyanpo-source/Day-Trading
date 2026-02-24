"""
富邦 Neo SDK 完整整合模組 (基於官方文件 V1.0)
功能：
1. 完整的帳號登入與 Account 物件管理
2. 符合規定的 Order 物件下單 (支援 ROD/IOC/FOK, 市價/限價)
3. WebSocket 行情訂閱與即時數據解析 (Trades & Books)
4. 委託回報查詢
"""

import logging
import threading
import time
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Union, Any

# 嘗試匯入 SDK，若未安裝則提供 Mock 以防崩潰
try:
    from fubon_neo.sdk import FubonSDK, Order, Mode
    from fubon_neo.constant import (
        TimeInForce, OrderType, PriceType, MarketType, BSAction
    )
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False
    # 定義 Mock 類別以防 IDE 報錯
    FubonSDK = object
    Order = object
    TimeInForce = object
    OrderType = object
    PriceType = object
    MarketType = object
    BSAction = object

logger = logging.getLogger(__name__)

class FubonNeoWrapper:
    """
    富邦 Neo SDK 高階封裝器
    解決 Streamlit 環境下的 WebSocket 狀態管理與下單物件建構問題
    """
    def __init__(self, config: Dict = None):
        """
        初始化
        :param config: 設定字典 (可選)，相容舊版呼叫
        """
        self.config = config or {}
        self.sdk = None
        self.active_account = None
        self.accounts = []
        self.logged_in = False
        self.stock_ws = None
        self.last_error = None
        
        # 儲存即時報價數據 (Thread-safe dictionary)
        # 結構: { '2330': { 'price': 500, 'bid': 499, 'ask': 501, 'volume': 1000, 'time': ... } }
        self.market_data = {}
        self._ws_lock = threading.Lock()
        self.callbacks = [] # 外部註冊的回呼函數

    def login(self, user_id=None, password=None, cert_path=None, cert_pwd=None) -> bool:
        """
        系統登入
        對應文件 Page 1-2: login
        支援從 __init__ config 讀取或直接傳入參數
        """
        if not SDK_AVAILABLE:
            self.last_error = "fubon_neo SDK 未安裝"
            logger.error(self.last_error)
            return False

        # 參數優先，其次使用 config
        u_id = user_id or self.config.get('id')
        pwd = password or self.config.get('pwd')
        c_path = cert_path or self.config.get('cert_path')
        c_pwd = cert_pwd or self.config.get('cert_pwd')

        if not (u_id and pwd and c_path and c_pwd):
            self.last_error = "缺少登入必要資訊 (帳號/密碼/憑證)"
            return False

        try:
            self.sdk = FubonSDK()
            
            # 登入並取得帳號列表
            self.accounts = self.sdk.login(u_id, pwd, c_path, c_pwd)
            
            if self.accounts:
                self.active_account = self.accounts.data[0] # 預設使用第一個帳號 (API回傳結構通常包含 data)
                self.logged_in = True
                logger.info(f"SDK 登入成功，帳號: {self.active_account.account}")
                
                # 初始化行情連線 (Page 11)
                self._init_realtime()
                return True
            else:
                self.last_error = "登入成功但無可用帳號"
                logger.error(self.last_error)
                return False
                
        except Exception as e:
            self.last_error = f"SDK 登入異常: {str(e)}"
            logger.error(self.last_error)
            self.logged_in = False
            return False

    def _init_realtime(self):
        """
        初始化 WebSocket 行情
        對應文件 Page 11
        """
        try:
            # 初始化行情 (使用 Speed 模式以獲得低延遲)
            self.sdk.init_realtime(Mode.Speed)
            self.stock_ws = self.sdk.marketdata.websocket_client.stock
            
            # 註冊回呼
            self.stock_ws.on('message', self._handle_ws_message)
            self.stock_ws.on('connect', self._handle_ws_connect)
            self.stock_ws.on('disconnect', self._handle_ws_disconnect)
            self.stock_ws.on('error', self._handle_ws_error)
            
            self.stock_ws.connect()
            logger.info("WebSocket 行情連線啟動")
            
        except Exception as e:
            logger.error(f"行情初始化失敗: {e}")

    def _handle_ws_message(self, message):
        """
        處理 WebSocket 訊息
        解析 Trades (Page 18) 和 Books (Page 22)
        """
        try:
            # 訊息可能是字串或 JSON 物件
            import json
            data = json.loads(message) if isinstance(message, str) else message
            
            event = data.get('event')
            payload = data.get('data')
            
            if event == 'data':
                symbol = payload.get('symbol')
                channel = data.get('channel') # trades or books
                
                with self._ws_lock:
                    if symbol not in self.market_data:
                        self.market_data[symbol] = {}
                    
                    # 處理成交明細 (Trades)
                    if channel == 'trades':
                        self.market_data[symbol].update({
                            'price': payload.get('price'),
                            'volume': payload.get('volume'), # 總量
                            'size': payload.get('size'),     # 單量
                            'time': payload.get('time'),
                            'is_limit_up': payload.get('isLimitUpPrice', False),
                            'is_limit_down': payload.get('isLimitDownPrice', False)
                        })
                    
                    # 處理五檔報價 (Books)
                    elif channel == 'books':
                        bids = payload.get('bids', [])
                        asks = payload.get('asks', [])
                        if bids and len(bids) > 0:
                            self.market_data[symbol]['bid'] = bids[0].get('price')
                            self.market_data[symbol]['bid_size'] = bids[0].get('size')
                        if asks and len(asks) > 0:
                            self.market_data[symbol]['ask'] = asks[0].get('price')
                            self.market_data[symbol]['ask_size'] = asks[0].get('size')

        except Exception as e:
            # logger.debug(f"WS Parse Error: {e}") # 避免 log 洗版
            pass

    def _handle_ws_connect(self):
        logger.info("行情連線成功")

    def _handle_ws_disconnect(self, code, message):
        logger.warning(f"行情斷線: {code} {message}")

    def _handle_ws_error(self, error):
        logger.error(f"行情錯誤: {error}")

    def subscribe(self, symbols: List[str]):
        """
        訂閱股票行情 (Trades & Books)
        對應文件 Page 13
        """
        if not self.logged_in or not self.stock_ws:
            return
            
        try:
            # 訂閱成交明細
            self.stock_ws.subscribe({
                'channel': 'trades',
                'symbols': symbols
            })
            
            # 訂閱五檔
            self.stock_ws.subscribe({
                'channel': 'books',
                'symbols': symbols
            })
            logger.info(f"已訂閱行情: {symbols}")
        except Exception as e:
            logger.error(f"訂閱失敗: {e}")

    def get_snapshot(self, symbol: str) -> Dict:
        """從本地快取獲取最新報價 (非阻塞)"""
        with self._ws_lock:
            data = self.market_data.get(symbol, {}).copy()
        
        # 如果還沒有 WS 數據，返回空結構
        if not data:
            return {'price': 0, 'volume': 0, 'bid': 0, 'ask': 0}
        return data

    def place_order(self, symbol: str, action: str, quantity: int, 
                   price: float = None, order_type_str: str = 'ROD', **kwargs) -> Dict:
        """
        下單核心功能
        對應文件 Page 4-6: place_order & Order Object
        """
        if not self.logged_in or not self.active_account:
            return {'success': False, 'message': 'API未登入'}

        try:
            # 1. 設定買賣別 (BSAction)
            # action 可能是 "Buy", "Sell", "買進", "賣出"
            if str(action).lower() in ['buy', 'b', '買進']:
                bs_action = BSAction.Buy
            else:
                bs_action = BSAction.Sell
            
            # 2. 設定價格型態 (PriceType) 與 價格
            if price is None or float(price) == 0:
                price_type = PriceType.Market
                order_price = None # 市價單價格帶 None
            else:
                price_type = PriceType.Limit
                order_price = float(price)
                
            # 3. 設定委託條件 (TimeInForce)
            tif = TimeInForce.ROD
            if order_type_str == 'IOC':
                tif = TimeInForce.IOC
            elif order_type_str == 'FOK':
                tif = TimeInForce.FOK
                
            # 4. 建構 Order 物件 (文件 Page 4)
            order = Order(
                buy_sell=bs_action,
                symbol=symbol,
                price=order_price,
                quantity=int(quantity), # 單位是股數
                market_type=MarketType.Common, # 整股
                price_type=price_type,
                time_in_force=tif,
                order_type=OrderType.Stock # 現股
            )
            
            logger.info(f"送出委託: {symbol} {action} {quantity} @ {price}")
            
            # 5. 執行下單
            result = self.sdk.stock.place_order(self.active_account, order)
            
            # 6. 檢查結果 (文件 Page 5)
            # result 為 OrderResult 物件，order_no 為委託書號
            if result.is_success:
                order_no = result.data.order_no
                return {
                    'success': True, 
                    'order_id': order_no, 
                    'message': f"委託成功 單號:{order_no}"
                }
            else:
                return {
                    'success': False, 
                    'message': result.message
                }

        except Exception as e:
            logger.error(f"下單異常: {e}")
            return {'success': False, 'message': str(e)}

    def get_order_history(self, days=1) -> List[Dict]:
        """
        取得委託回報
        對應文件 Page 8: get_order_results
        """
        if not self.logged_in:
            return []
            
        try:
            results = self.sdk.stock.get_order_results(self.active_account)
            
            orders = []
            if results.is_success:
                for o in results.data:
                    # 解析 OrderResult (Page 8-11)
                    orders.append({
                        'order_id': o.order_no,
                        'symbol': o.stock_no,
                        'action': 'BUY' if o.buy_sell == BSAction.Buy else 'SELL',
                        'price': o.price,
                        'quantity': o.original_qty, # 原始委託股數
                        'filled_qty': o.filled_qty, # 成交股數
                        'status': str(o.status),    # 狀態碼
                        'time': o.date,             # 交易日期
                        'message': o.error_message if hasattr(o, 'error_message') else ''
                    })
            return orders
        except Exception as e:
            logger.error(f"查詢委託失敗: {e}")
            return []

    def cancel_order(self, order_id: str) -> Dict:
        """
        取消委託 (刪單)
        """
        if not self.logged_in:
             return {'success': False, 'message': '未登入'}
             
        try:
            # 假設 SDK 支援 cancel_order(account, order_no)
            res = self.sdk.stock.cancel_order(self.active_account, order_id)
            if res.is_success:
                return {'success': True, 'message': '刪單成功'}
            else:
                return {'success': False, 'message': res.message}
        except Exception as e:
             return {'success': False, 'message': str(e)}

    def get_account_balance(self) -> Dict:
        """
        取得帳戶餘額
        """
        # 實作需依賴 SDK 是否提供庫存查詢 API
        return {
            'available_balance': 0, 
            'total_balance': 0
        }
        
    def get_positions(self) -> List[Dict]:
        """
        查詢庫存
        """
        if not self.logged_in:
            return []
        try:
            # 嘗試取得庫存
            invs = self.sdk.stock.get_inventories(self.active_account)
            positions = []
            if invs.is_success:
                for i in invs.data:
                    positions.append({
                        'symbol': i.stock_no,
                        'quantity': int(i.today_qty), 
                        'avg_price': float(i.cost_price),
                        'pnl': float(i.profit_loss),
                        'market_value': float(i.make_money) # 假設欄位
                    })
            return positions
        except:
            return []

    # -----------------------------------------------------------------
    # 期權擴充介面
    # -----------------------------------------------------------------
    def get_futopt_intraday_candles(self, symbol: str, timeframe: str = '1', session: str = None):
        """
        查詢期權K線 (新增功能)
        """
        if not self.logged_in:
            return None
            
        try:
            restfutopt = self.sdk.marketdata.rest_client.futopt
            params = {'symbol': symbol, 'timeframe': str(timeframe)}
            if session:
                params['session'] = session

            resp = restfutopt.intraday.candles(**params)
            if resp and 'data' in resp:
                df = pd.DataFrame(resp['data'])
                df.rename(columns={
                    'date': 'Timestamp',
                    'open': 'Open',
                    'high': 'High',
                    'low': 'Low',
                    'close': 'Close',
                    'volume': 'Volume',
                    'average': 'Average'
                }, inplace=True)
                df['Timestamp'] = pd.to_datetime(df['Timestamp'])
                return df
        except Exception as e:
            logger.error(f"期權K線查詢異常: {e}")
        return None

    def logout(self):
        if self.sdk:
            try:
                self.sdk.logout()
            except:
                pass
        self.logged_in = False