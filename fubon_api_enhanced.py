"""
增強版富邦證券API整合
支援實際交易、帳務查詢、風險控制
修正: 強化連線錯誤處理 (DNS/Connection Error)
"""

import json
import requests
import logging
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple
import pandas as pd
import ssl
import urllib3
import hashlib
import os

# 停用SSL警告（僅測試環境使用）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class FubonTradeAPIV2:
    """富邦證券API V2 增強版"""
    
    def __init__(self, config: Dict = None):
        """
        初始化API
        
        參數:
            config: 包含 id, pwd, cert_path, cert_pwd, api_url
        """
        self.config = config or {}
        self.session = None
        self.logged_in = False
        self.account_info = None
        self.last_error = None
        
        # API端點
        self.base_url = self.config.get('api_url', 'https://api.fubon.com')
        self.endpoints = {
            'login': '/api/v1/auth/login',
            'logout': '/api/v1/auth/logout',
            'balance': '/api/v1/account/balance',
            'positions': '/api/v1/account/positions',
            'orders': '/api/v1/trade/orders',
            'place_order': '/api/v1/trade/place',
            'cancel_order': '/api/v1/trade/cancel',
            'market_data': '/api/v1/market/snapshot',
            'kline': '/api/v1/market/kline',
            'order_status': '/api/v1/trade/order',
        }
    
    def _get_session(self):
        """建立SSL會話"""
        if self.session is None:
            cert_path = self.config.get('cert_path')
            
            if cert_path and cert_path.endswith('.pfx'):
                # 處理PFX憑證
                self.session = requests.Session()
                try:
                    self.session.cert = cert_path
                except Exception as e:
                    logger.warning(f"憑證載入可能有誤，將嘗試無憑證連線: {e}")
                self.session.verify = False  # 測試環境可關閉驗證
            else:
                self.session = requests.Session()
            
            # 設定請求頭
            self.session.headers.update({
                'User-Agent': 'FubonTradingSystem/2.0',
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            })
        
        return self.session
    
    def login(self, account_id: str = None, password: str = None, 
              cert_path: str = None, cert_pwd: str = None) -> bool:
        """
        登入富邦證券API
        
        返回:
            bool: 登入是否成功
        """
        try:
            # 使用參數或設定檔中的資料
            account_id = account_id or self.config.get('id')
            password = password or self.config.get('pwd')
            
            if not account_id or not password:
                logger.error("缺少帳號或密碼")
                return False
            
            # 建立登入請求
            login_data = {
                'account_id': account_id,
                'password': hashlib.sha256(password.encode()).hexdigest(),  # 實際使用API要求的方式
                'source': 'webapi',
                'timestamp': datetime.now().isoformat()
            }
            
            session = self._get_session()
            url = f"{self.base_url}{self.endpoints['login']}"
            
            logger.info(f"嘗試連線至: {self.base_url} ...")

            # 發送登入請求
            response = session.post(
                url,
                json=login_data,
                verify=False,  # 測試環境
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get('success'):
                    # 儲存登入token
                    token = result.get('token')
                    if token:
                        session.headers['Authorization'] = f'Bearer {token}'
                    
                    self.logged_in = True
                    self.last_error = None
                    
                    # 取得帳戶資訊
                    self._fetch_account_info()
                    
                    logger.info(f"✅ 登入成功 - 帳號: {account_id}")
                    return True
                else:
                    error_msg = result.get('message', '未知錯誤')
                    self.last_error = error_msg
                    logger.error(f"❌ 登入失敗: {error_msg}")
                    return False
            else:
                self.last_error = f"HTTP {response.status_code}"
                logger.error(f"❌ 登入HTTP錯誤: {response.status_code}")
                return False

        except requests.exceptions.ConnectionError as e:
            # 專門處理連線錯誤 (DNS 解析失敗, 拒絕連線等)
            error_msg = f"無法連線至伺服器 ({self.base_url})。請檢查網路或 API 網址是否正確。"
            logger.error(f"❌ 連線錯誤: {error_msg} 詳細: {e}")
            self.last_error = "伺服器連線失敗 (DNS/Network)"
            return False
            
        except requests.exceptions.Timeout:
            error_msg = "連線逾時"
            logger.error(f"❌ {error_msg}")
            self.last_error = error_msg
            return False

        except Exception as e:
            logger.error(f"❌ 登入異常: {e}")
            self.last_error = str(e)
            return False
    
    def _fetch_account_info(self):
        """取得帳戶資訊"""
        if not self.logged_in:
            return None
        
        try:
            session = self._get_session()
            url = f"{self.base_url}{self.endpoints['balance']}"
            
            response = session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    self.account_info = data.get('data', {})
                    
                    logger.info(f"帳戶餘額: {self.account_info.get('total_balance', 0):,}")
                    return self.account_info
            return None
            
        except Exception as e:
            logger.error(f"取得帳戶資訊失敗: {e}")
            return None
    
    def get_account_balance(self) -> Dict:
        """取得帳戶餘額詳情"""
        if not self.account_info:
            self._fetch_account_info()
        
        return self.account_info or {
            'total_balance': 0,
            'available_balance': 0,
            'margin': 0,
            'unrealized_pnl': 0,
            'realized_pnl': 0
        }
    
    def get_positions(self) -> List[Dict]:
        """取得目前持倉"""
        if not self.logged_in:
            return []
        
        try:
            session = self._get_session()
            url = f"{self.base_url}{self.endpoints['positions']}"
            
            response = session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    positions = data.get('data', [])
                    
                    logger.info(f"取得 {len(positions)} 個持倉")
                    return positions
            return []
            
        except Exception as e:
            logger.error(f"取得持倉失敗: {e}")
            return []
    
    def get_snapshot(self, symbol: str) -> Dict:
        """
        取得即時報價
        
        參數:
            symbol: 股票代碼 (如 '2330.TW')
        
        返回:
            報價字典
        """
        try:
            # 支援不同格式的股票代碼
            if not symbol.endswith('.TW'):
                symbol = f"{symbol}.TW"
            
            session = self._get_session()
            url = f"{self.base_url}{self.endpoints['market_data']}/{symbol}"
            
            response = session.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    return data.get('data', {})
            
            return {}
            
        except Exception as e:
            logger.error(f"取得報價失敗 {symbol}: {e}")
            return {}
    
    def place_order(self, 
                    symbol: str, 
                    side: str, 
                    quantity: int, 
                    price: float = None,
                    order_type: str = 'LIMIT',
                    time_in_force: str = 'DAY') -> Dict:
        """
        下單
        
        參數:
            symbol: 股票代碼
            side: 買賣方向 (BUY/SELL)
            quantity: 數量
            price: 價格 (市價單可為None)
            order_type: 訂單類型 (LIMIT/MARKET)
            time_in_force: 有效期限 (DAY/IOC/FOK)
        
        返回:
            下單結果
        """
        if not self.logged_in:
            return {'success': False, 'message': '未登入'}
        
        # 風險檢查
        risk_check = self._risk_check(symbol, side, quantity, price)
        if not risk_check['pass']:
            return {'success': False, 'message': risk_check['message']}
        
        try:
            # 格式化股票代碼
            if not symbol.endswith('.TW'):
                symbol = f"{symbol}.TW"
            
            order_data = {
                'symbol': symbol,
                'side': side.upper(),
                'quantity': quantity,
                'order_type': order_type.upper(),
                'time_in_force': time_in_force.upper(),
                'client_order_id': f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{symbol}",
            }
            
            if price is not None and order_type == 'LIMIT':
                order_data['price'] = price
            
            session = self._get_session()
            url = f"{self.base_url}{self.endpoints['place_order']}"
            
            response = session.post(url, json=order_data, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get('success'):
                    order_id = result.get('data', {}).get('order_id')
                    logger.info(f"✅ 下單成功 - {side} {symbol} {quantity}股 @ {price or '市價'} | 單號: {order_id}")
                    
                    # 記錄交易
                    self._log_trade(order_data, order_id)
                    
                    return {
                        'success': True,
                        'order_id': order_id,
                        'message': '下單成功'
                    }
                else:
                    error_msg = result.get('message', '下單失敗')
                    logger.error(f"❌ 下單失敗: {error_msg}")
                    return {'success': False, 'message': error_msg}
            else:
                logger.error(f"❌ 下單HTTP錯誤: {response.status_code}")
                return {'success': False, 'message': f'HTTP錯誤: {response.status_code}'}
                
        except Exception as e:
            logger.error(f"❌ 下單異常: {e}")
            return {'success': False, 'message': str(e)}
    
    def _risk_check(self, symbol: str, side: str, quantity: int, price: float) -> Dict:
        """風險檢查"""
        try:
            # 取得帳戶餘額
            balance_info = self.get_account_balance()
            available = balance_info.get('available_balance', 0)
            
            # 買單檢查資金是否足夠
            if side.upper() == 'BUY':
                max_amount = self.config.get('max_order_amount', 100000)
                
                order_amount = quantity * (price or 0)
                if price is None:  # 市價單用最新報價估算
                    snapshot = self.get_snapshot(symbol)
                    estimate_price = float(snapshot.get('price') or snapshot.get('closePrice') or 0)
                    order_amount = quantity * estimate_price
                
                if order_amount > max_amount:
                    return {
                        'pass': False,
                        'message': f'下單金額 {order_amount:,.0f} 超過單筆上限 {max_amount:,.0f}'
                    }
                
                if order_amount > available:
                    return {
                        'pass': False,
                        'message': f'資金不足，可用餘額: {available:,.0f}，需: {order_amount:,.0f}'
                    }
            
            # 賣單檢查是否有持倉
            elif side.upper() == 'SELL':
                positions = self.get_positions()
                position = next((p for p in positions if p['symbol'].startswith(symbol)), None)
                
                if position is None:
                    return {'pass': False, 'message': f'無 {symbol} 持倉'}
                
                available_qty = position.get('available_quantity', 0)
                if quantity > available_qty:
                    return {
                        'pass': False,
                        'message': f'持倉不足，可賣數量: {available_qty}，欲賣: {quantity}'
                    }
            
            return {'pass': True, 'message': '風險檢查通過'}
            
        except Exception as e:
            logger.error(f"風險檢查異常: {e}")
            return {'pass': True, 'message': '風險檢查跳過'}  # 錯誤時放行，由API端檢查
    
    def _log_trade(self, order_data: Dict, order_id: str):
        """記錄交易"""
        try:
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'order_id': order_id,
                'symbol': order_data['symbol'],
                'side': order_data['side'],
                'quantity': order_data['quantity'],
                'price': order_data.get('price', 'MARKET'),
                'order_type': order_data['order_type']
            }
            
            # 儲存到JSON檔案
            log_file = 'trade_log.json'
            logs = []
            
            if os.path.exists(log_file):
                with open(log_file, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
            
            logs.append(log_entry)
            
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(logs, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"交易記錄失敗: {e}")
    
    def cancel_order(self, order_id: str) -> bool:
        """取消訂單"""
        if not self.logged_in:
            return False
        
        try:
            session = self._get_session()
            url = f"{self.base_url}{self.endpoints['cancel_order']}/{order_id}"
            
            response = session.delete(url, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    logger.info(f"✅ 取消訂單成功: {order_id}")
                    return True
            
            logger.error(f"❌ 取消訂單失敗: {order_id}")
            return False
            
        except Exception as e:
            logger.error(f"取消訂單異常: {e}")
            return False
    
    def get_order_status(self, order_id: str) -> Dict:
        """查詢訂單狀態"""
        if not self.logged_in:
            return {}
        
        try:
            session = self._get_session()
            url = f"{self.base_url}{self.endpoints['order_status']}/{order_id}"
            
            response = session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    return data.get('data', {})
            
            return {}
            
        except Exception as e:
            logger.error(f"查詢訂單狀態失敗: {e}")
            return {}
    
    def get_order_history(self, days: int = 7) -> List[Dict]:
        """取得訂單歷史"""
        if not self.logged_in:
            return []
        
        try:
            session = self._get_session()
            url = f"{self.base_url}{self.endpoints['orders']}?days={days}"
            
            response = session.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    orders = data.get('data', [])
                    
                    # 轉換時間格式
                    for order in orders:
                        order['formatted_time'] = datetime.strptime(
                            order['order_time'], '%Y-%m-%dT%H:%M:%S.%fZ'
                        ).strftime('%Y-%m-%d %H:%M:%S')
                    
                    return orders
            
            return []
            
        except Exception as e:
            logger.error(f"取得訂單歷史失敗: {e}")
            return []
    
    def logout(self):
        """登出"""
        if self.session and self.logged_in:
            try:
                session = self._get_session()
                url = f"{self.base_url}{self.endpoints['logout']}"
                
                session.post(url, timeout=5)
                
            except Exception as e:
                logger.error(f"登出異常: {e}")
            
            finally:
                self.session = None
                self.logged_in = False
                logger.info("已登出")
    
    def __del__(self):
        """解構時自動登出"""
        self.logout()


class OrderManager:
    """訂單管理器"""
    
    def __init__(self, api_client):
        self.api = api_client
        self.pending_orders = []
        
    def place_order_with_retry(self, 
                              symbol: str, 
                              side: str, 
                              quantity: int, 
                              price: float = None,
                              max_retries: int = 3) -> Dict:
        """下單並重試"""
        
        for attempt in range(max_retries):
            try:
                result = self.api.place_order(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=price
                )
                
                if result['success']:
                    order_id = result['order_id']
                    self.pending_orders.append({
                        'order_id': order_id,
                        'symbol': symbol,
                        'side': side,
                        'quantity': quantity,
                        'price': price,
                        'status': 'PENDING',
                        'timestamp': datetime.now()
                    })
                    
                    return result
                else:
                    logger.warning(f"下單失敗 (嘗試 {attempt+1}/{max_retries}): {result['message']}")
                    
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(1)  # 等待1秒後重試
            
            except Exception as e:
                logger.error(f"下單異常 (嘗試 {attempt+1}/{max_retries}): {e}")
        
        return {'success': False, 'message': '下單失敗，已達最大重試次數'}
    
    def check_pending_orders(self):
        """檢查待處理訂單狀態"""
        completed = []
        
        for order in self.pending_orders[:]:  # 複製列表避免修改問題
            status = self.api.get_order_status(order['order_id'])
            
            if status.get('status') in ['FILLED', 'CANCELLED', 'REJECTED']:
                order['status'] = status['status']
                order['filled_quantity'] = status.get('filled_quantity', 0)
                order['avg_price'] = status.get('avg_price', 0)
                order['updated'] = datetime.now()
                
                # 移動到已完成
                completed.append(order)
                self.pending_orders.remove(order)
                
                logger.info(f"訂單 {order['order_id']} 狀態: {order['status']}")
        
        return completed


# 使用範例
if __name__ == "__main__":
    # 設定日誌
    logging.basicConfig(level=logging.INFO)
    
    # 從加密設定檔載入
    from config_manager import SecureConfigManager
    
    config_manager = SecureConfigManager()
    config = config_manager.load_config()
    
    if config:
        # 初始化API
        api = FubonTradeAPIV2(config)
        
        # 登入
        if api.login():
            print("=" * 50)
            print("🎯 富邦證券API測試")
            print("=" * 50)
            
            # 顯示帳戶資訊
            balance = api.get_account_balance()
            print(f"帳戶總資產: {balance.get('total_balance', 0):,}")
            print(f"可用餘額: {balance.get('available_balance', 0):,}")
            
            # 顯示持倉
            positions = api.get_positions()
            print(f"\n目前持倉 ({len(positions)} 個):")
            for pos in positions[:5]:  # 顯示前5個
                print(f"  {pos['symbol']}: {pos['quantity']}股 @ {pos['avg_price']:.2f}")
            
            # 取得報價
            snapshot = api.get_snapshot('2330')
            print(f"\n台積電報價: {snapshot.get('price', 'N/A')}")
            
            print("\n✅ API連線測試完成")
            
            # 登出
            api.logout()
    else:
        print("❌ 請先執行 config_manager.py 設定API")