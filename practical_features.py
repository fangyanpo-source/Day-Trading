"""
實用功能增強模組 (Practical Features)
包含：移動停損、價格警報、快速操作
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Callable
import json

logger = logging.getLogger(__name__)


class TrailingStopManager:
    """移動停損管理器"""
    
    def __init__(self, default_trailing_pct: float = 0.02):
        """
        初始化移動停損管理器
        
        參數:
            default_trailing_pct: 預設移動停損百分比（如 0.02 = 2%）
        """
        self.default_trailing_pct = default_trailing_pct
        self.trailing_stops = {}  # {symbol: {'stop_price': float, 'highest_price': float}}
    
    def add_position(self, symbol: str, entry_price: float, trailing_pct: float = None):
        """
        新增持倉的移動停損
        
        參數:
            symbol: 股票代碼
            entry_price: 進場價格
            trailing_pct: 移動停損百分比（可選）
        """
        pct = trailing_pct if trailing_pct is not None else self.default_trailing_pct
        
        self.trailing_stops[symbol] = {
            'stop_price': entry_price * (1 - pct),
            'highest_price': entry_price,
            'entry_price': entry_price,  # ✅ 修正點：保留進場價，供 pnl_pct 正確計算損益
            'trailing_pct': pct,
            'triggered': False
        }
        
        logger.info(f"新增移動停損: {symbol} @ {entry_price:.2f}, 停損: {entry_price * (1 - pct):.2f}")
    
    def update(self, symbol: str, current_price: float) -> Dict:
        """
        更新移動停損
        
        參數:
            symbol: 股票代碼
            current_price: 當前價格
            
        返回:
            Dict: {
                'updated': bool,  # 是否更新了停損價
                'triggered': bool,  # 是否觸發停損
                'stop_price': float,  # 當前停損價
                'highest_price': float,  # 最高價
                'pnl_pct': float  # 損益百分比
            }
        """
        if symbol not in self.trailing_stops:
            return None
        
        stop_info = self.trailing_stops[symbol]
        
        # 已觸發就不再更新
        if stop_info['triggered']:
            return {
                'updated': False,
                'triggered': True,
                'stop_price': stop_info['stop_price'],
                'highest_price': stop_info['highest_price'],
                'pnl_pct': 0
            }
        
        updated = False
        
        # 如果創新高，更新移動停損
        if current_price > stop_info['highest_price']:
            stop_info['highest_price'] = current_price
            new_stop = current_price * (1 - stop_info['trailing_pct'])
            
            if new_stop > stop_info['stop_price']:
                stop_info['stop_price'] = new_stop
                updated = True
                logger.info(f"更新移動停損: {symbol} 停損價 → {new_stop:.2f}")
        
        # 檢查是否觸發停損
        triggered = current_price <= stop_info['stop_price']
        
        if triggered:
            stop_info['triggered'] = True
            logger.warning(f"觸發移動停損: {symbol} @ {current_price:.2f} (停損: {stop_info['stop_price']:.2f})")
        
        # ✅ 修正點：pnl_pct 應以「進場價」為基準計算損益百分比，
        # 原本以 stop_price 為基準，計算的是距停損線距離而非真實損益。
        entry_price = stop_info.get('entry_price', stop_info['highest_price'])
        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        return {
            'updated': updated,
            'triggered': triggered,
            'stop_price': stop_info['stop_price'],
            'highest_price': stop_info['highest_price'],
            'pnl_pct': pnl_pct
        }
    
    def remove_position(self, symbol: str):
        """移除持倉的移動停損"""
        if symbol in self.trailing_stops:
            del self.trailing_stops[symbol]
            logger.info(f"移除移動停損: {symbol}")
    
    def get_stop_info(self, symbol: str) -> Optional[Dict]:
        """取得移動停損資訊"""
        return self.trailing_stops.get(symbol)
    
    def get_all_stops(self) -> Dict:
        """取得所有移動停損資訊"""
        return self.trailing_stops.copy()


class PriceAlertManager:
    """價格警報管理器"""
    
    def __init__(self):
        self.alerts = {}  # {symbol: [alert_configs]}
        self.alert_history = []  # 觸發歷史
    
    def add_alert(self, 
                  symbol: str,
                  alert_type: str,
                  threshold: float,
                  direction: str = 'above',
                  callback: Callable = None,
                  message: str = None):
        """
        新增警報
        
        參數:
            symbol: 股票代碼
            alert_type: 警報類型 ('price', 'volume', 'rsi', 'ma_cross', etc.)
            threshold: 閾值
            direction: 方向 ('above', 'below', 'cross')
            callback: 觸發時的回調函數
            message: 自訂訊息
        """
        if symbol not in self.alerts:
            self.alerts[symbol] = []
        
        alert_id = f"{symbol}_{alert_type}_{len(self.alerts[symbol])}"
        
        alert = {
            'id': alert_id,
            'type': alert_type,
            'threshold': threshold,
            'direction': direction,
            'callback': callback,
            'message': message or f"{symbol} {alert_type} {direction} {threshold}",
            'triggered': False,
            'created_at': datetime.now(),
            'trigger_count': 0
        }
        
        self.alerts[symbol].append(alert)
        logger.info(f"新增警報: {alert['message']}")
        
        return alert_id
    
    def check_price_alert(self, symbol: str, current_price: float) -> List[Dict]:
        """檢查價格警報"""
        if symbol not in self.alerts:
            return []
        
        triggered_alerts = []
        
        for alert in self.alerts[symbol]:
            if alert['type'] != 'price' or alert['triggered']:
                continue
            
            should_trigger = False
            
            if alert['direction'] == 'above' and current_price > alert['threshold']:
                should_trigger = True
            elif alert['direction'] == 'below' and current_price < alert['threshold']:
                should_trigger = True
            
            if should_trigger:
                alert['triggered'] = True
                alert['trigger_count'] += 1
                alert['trigger_time'] = datetime.now()
                alert['trigger_price'] = current_price
                
                # 記錄歷史
                self.alert_history.append({
                    'alert': alert.copy(),
                    'trigger_time': datetime.now(),
                    'trigger_price': current_price
                })
                
                triggered_alerts.append(alert)
                
                logger.warning(f"警報觸發: {alert['message']} @ {current_price:.2f}")
                
                # 執行回調
                if alert['callback']:
                    try:
                        alert['callback'](symbol, current_price, alert)
                    except Exception as e:
                        logger.error(f"警報回調執行失敗: {e}")
        
        return triggered_alerts
    
    def check_volume_alert(self, symbol: str, current_volume: int, avg_volume: int) -> List[Dict]:
        """檢查成交量警報"""
        if symbol not in self.alerts:
            return []
        
        triggered_alerts = []
        
        for alert in self.alerts[symbol]:
            if alert['type'] != 'volume' or alert['triggered']:
                continue
            
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
            
            should_trigger = False
            
            if alert['direction'] == 'above' and volume_ratio > alert['threshold']:
                should_trigger = True
            
            if should_trigger:
                alert['triggered'] = True
                alert['trigger_count'] += 1
                alert['trigger_time'] = datetime.now()
                alert['trigger_volume'] = current_volume
                
                self.alert_history.append({
                    'alert': alert.copy(),
                    'trigger_time': datetime.now(),
                    'trigger_volume': current_volume,
                    'volume_ratio': volume_ratio
                })
                
                triggered_alerts.append(alert)
                
                logger.warning(f"成交量警報觸發: {alert['message']} (倍數: {volume_ratio:.2f})")
                
                if alert['callback']:
                    try:
                        alert['callback'](symbol, current_volume, alert)
                    except Exception as e:
                        logger.error(f"警報回調執行失敗: {e}")
        
        return triggered_alerts
    
    def remove_alert(self, alert_id: str) -> bool:
        """移除警報"""
        for symbol in self.alerts:
            self.alerts[symbol] = [a for a in self.alerts[symbol] if a['id'] != alert_id]
        
        logger.info(f"移除警報: {alert_id}")
        return True
    
    def clear_triggered_alerts(self, symbol: str = None):
        """清除已觸發的警報"""
        if symbol:
            if symbol in self.alerts:
                self.alerts[symbol] = [a for a in self.alerts[symbol] if not a['triggered']]
        else:
            for sym in self.alerts:
                self.alerts[sym] = [a for a in self.alerts[sym] if not a['triggered']]
        
        logger.info("清除已觸發的警報")
    
    def get_alerts(self, symbol: str = None) -> Dict:
        """取得警報列表"""
        if symbol:
            return {symbol: self.alerts.get(symbol, [])}
        return self.alerts.copy()
    
    def get_alert_history(self, limit: int = 50) -> List[Dict]:
        """取得警報觸發歷史"""
        return self.alert_history[-limit:]


class QuickActionsManager:
    """快速操作管理器"""
    
    def __init__(self):
        self.action_log = []
    
    def close_all_positions(self, positions: Dict, get_price_func: Callable, 
                           place_order_func: Callable) -> Dict:
        """
        全部平倉
        
        參數:
            positions: 持倉字典
            get_price_func: 取得價格的函數
            place_order_func: 下單函數
            
        返回:
            Dict: {
                'closed_count': int,
                'total_pnl': float,
                'errors': List[str]
            }
        """
        result = {
            'closed_count': 0,
            'total_pnl': 0,
            'errors': []
        }
        
        for symbol in list(positions.keys()):
            try:
                # 取得當前價格
                current_price = get_price_func(symbol)
                
                if current_price <= 0:
                    result['errors'].append(f"{symbol}: 無法取得價格")
                    continue
                
                # 計算損益
                position = positions[symbol]
                pnl = (current_price - position['price']) * position['qty']
                
                # 下單
                place_order_func(symbol, "Sell", position['qty'], current_price, "緊急平倉")
                
                result['closed_count'] += 1
                result['total_pnl'] += pnl
                
                logger.info(f"平倉: {symbol} @ {current_price:.2f}, 損益: {int(pnl):+,}")
                
            except Exception as e:
                result['errors'].append(f"{symbol}: {str(e)}")
                logger.error(f"平倉失敗 {symbol}: {e}")
        
        # 記錄操作
        self.action_log.append({
            'action': 'close_all',
            'time': datetime.now(),
            'result': result
        })
        
        return result
    
    def calculate_total_pnl(self, positions: Dict, get_price_func: Callable) -> Dict:
        """
        計算總損益
        
        返回:
            Dict: {
                'total_pnl': float,
                'total_pnl_pct': float,
                'details': List[Dict]
            }
        """
        total_pnl = 0
        total_cost = 0
        details = []
        
        for symbol, position in positions.items():
            try:
                current_price = get_price_func(symbol)
                
                if current_price <= 0:
                    continue
                
                cost = position['price'] * position['qty']
                value = current_price * position['qty']
                pnl = value - cost
                pnl_pct = (pnl / cost) * 100 if cost > 0 else 0
                
                total_pnl += pnl
                total_cost += cost
                
                details.append({
                    'symbol': symbol,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'cost': cost,
                    'value': value
                })
                
            except Exception as e:
                logger.error(f"計算損益失敗 {symbol}: {e}")
        
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
        
        return {
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'total_cost': total_cost,
            'details': sorted(details, key=lambda x: x['pnl'], reverse=True)
        }
    
    def get_action_log(self, limit: int = 20) -> List[Dict]:
        """取得操作日誌"""
        return self.action_log[-limit:]


class DailySummaryGenerator:
    """每日總結生成器"""
    
    def __init__(self):
        self.summaries = []
    
    def generate_summary(self, trades: List[Dict], positions: Dict = None) -> Dict:
        """
        生成每日總結
        
        參數:
            trades: 交易記錄列表
            positions: 當前持倉（可選）
            
        返回:
            Dict: 總結資料
        """
        if not trades:
            return None
        
        import pandas as pd
        df = pd.DataFrame(trades)
        
        # 過濾今日交易
        today = datetime.now().date()
        df['Date'] = pd.to_datetime(df['Time'], format='%H:%M:%S').apply(lambda x: today)
        today_trades = df[df['Date'] == today].copy()
        
        if len(today_trades) == 0:
            return None
        
        # 基本統計
        total_pnl = today_trades['PnL'].sum()
        win_trades = today_trades[today_trades['PnL'] > 0]
        lose_trades = today_trades[today_trades['PnL'] < 0]
        
        win_count = len(win_trades)
        lose_count = len(lose_trades)
        total_count = win_count + lose_count
        
        win_rate = (win_count / total_count * 100) if total_count > 0 else 0
        
        avg_win = win_trades['PnL'].mean() if len(win_trades) > 0 else 0
        avg_lose = lose_trades['PnL'].mean() if len(lose_trades) > 0 else 0
        
        # 最佳/最差交易
        best_trade = today_trades.loc[today_trades['PnL'].idxmax()] if len(today_trades) > 0 else None
        worst_trade = today_trades.loc[today_trades['PnL'].idxmin()] if len(today_trades) > 0 else None
        
        # 策略統計
        if 'Strategy' in today_trades.columns:
            strategy_stats = today_trades.groupby('Strategy').agg({
                'PnL': ['sum', 'count', lambda x: (x > 0).sum()]
            }).round(0)
        else:
            strategy_stats = None
        
        summary = {
            'date': today,
            'total_pnl': total_pnl,
            'total_trades': total_count,
            'win_rate': win_rate,
            'win_count': win_count,
            'lose_count': lose_count,
            'avg_win': avg_win,
            'avg_lose': avg_lose,
            'best_trade': {
                'symbol': best_trade['Symbol'],
                'pnl': best_trade['PnL']
            } if best_trade is not None else None,
            'worst_trade': {
                'symbol': worst_trade['Symbol'],
                'pnl': worst_trade['PnL']
            } if worst_trade is not None else None,
            'strategy_stats': strategy_stats.to_dict() if strategy_stats is not None else None,
            'positions_count': len(positions) if positions else 0
        }
        
        self.summaries.append(summary)
        
        return summary
    
    def format_summary(self, summary: Dict) -> str:
        """格式化總結為文字"""
        if not summary:
            return "今日無交易記錄"
        
        text = f"""
📊 今日交易總結
{'='*50}
交易日期: {summary['date'].strftime('%Y-%m-%d')}

📈 整體表現
- 總損益: {int(summary['total_pnl']):+,} 元
- 勝率: {summary['win_rate']:.1f}% ({summary['win_count']}勝{summary['lose_count']}敗)
- 平均獲利: {int(summary['avg_win']):+,} 元
- 平均虧損: {int(summary['avg_lose']):+,} 元
"""
        
        if summary['best_trade']:
            text += f"- 最佳交易: {int(summary['best_trade']['pnl']):+,} 元 ({summary['best_trade']['symbol']})\n"
        
        if summary['worst_trade']:
            text += f"- 最差交易: {int(summary['worst_trade']['pnl']):+,} 元 ({summary['worst_trade']['symbol']})\n"
        
        if summary['positions_count'] > 0:
            text += f"\n📊 持倉狀況\n- 當前持倉: {summary['positions_count']} 檔\n"
        
        text += f"\n⏰ {datetime.now().strftime('%H:%M:%S')}"
        
        return text
    
    def get_summaries(self, days: int = 7) -> List[Dict]:
        """取得最近幾天的總結"""
        return self.summaries[-days:]


# 使用範例
if __name__ == "__main__":
    print("實用功能增強模組")
    print("=" * 50)
    print()
    
    # 移動停損範例
    print("📊 移動停損範例")
    print("-" * 50)
    
    trailing_stop = TrailingStopManager(default_trailing_pct=0.02)
    trailing_stop.add_position('2330', 600.0)
    
    # 模擬價格變化
    prices = [605, 610, 615, 620, 618, 616]
    for price in prices:
        result = trailing_stop.update('2330', price)
        print(f"價格: {price:.2f}, 停損: {result['stop_price']:.2f}, "
              f"觸發: {'是' if result['triggered'] else '否'}")
    
    print()
    
    # 價格警報範例
    print("📊 價格警報範例")
    print("-" * 50)
    
    alert_manager = PriceAlertManager()
    
    def alert_callback(symbol, price, alert):
        print(f"⚠️ 警報回調: {symbol} @ {price:.2f}")
    
    alert_manager.add_alert('2330', 'price', 620, 'above', 
                           callback=alert_callback)
    alert_manager.add_alert('2330', 'price', 580, 'below')
    
    # 檢查警報
    triggered = alert_manager.check_price_alert('2330', 625)
    print(f"觸發警報數: {len(triggered)}")
