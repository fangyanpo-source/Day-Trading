"""
智能倉位管理系統 (Position Sizer)
根據風險參數計算最佳倉位大小
"""

import logging
from typing import Dict, Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class PositionSizer:
    """倉位計算器"""
    
    def __init__(self, 
                 total_capital: float,
                 risk_per_trade_pct: float = 0.02,
                 max_position_pct: float = 0.20):
        """
        初始化倉位計算器
        
        參數:
            total_capital: 總資金
            risk_per_trade_pct: 每筆交易風險（佔總資金百分比）
            max_position_pct: 單一倉位上限（佔總資金百分比）
        """
        self.total_capital = total_capital
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_position_pct = max_position_pct
        
        # 風險金額
        self.risk_amount = total_capital * risk_per_trade_pct
        self.max_position_value = total_capital * max_position_pct
    
    def calculate_position_by_risk(self,
                                   entry_price: float,
                                   stop_loss: float) -> Dict:
        """
        根據固定風險百分比計算倉位
        
        方法：風險金額 / 每股風險 = 股數
        
        參數:
            entry_price: 進場價格
            stop_loss: 停損價格
            
        返回:
            Dict: {
                'shares': 股數,
                'value': 倉位價值,
                'risk': 風險金額,
                'position_pct': 佔資金百分比
            }
        """
        
        # 計算每股風險
        risk_per_share = abs(entry_price - stop_loss)
        
        if risk_per_share == 0:
            logger.warning("停損距離為0，無法計算倉位")
            return None
        
        # 計算股數
        shares = int(self.risk_amount / risk_per_share)
        
        # 考慮台股交易單位（1張 = 1000股）
        shares = (shares // 1000) * 1000  # 調整為1000的倍數
        
        # 檢查是否超過最大倉位
        position_value = shares * entry_price
        
        if position_value > self.max_position_value:
            # 調整為最大倉位
            shares = int(self.max_position_value / entry_price)
            shares = (shares // 1000) * 1000
            position_value = shares * entry_price
            logger.info(f"倉位受限於最大值，調整為 {shares} 股")
        
        position_pct = (position_value / self.total_capital) * 100
        actual_risk = shares * risk_per_share
        
        return {
            'shares': shares,
            'lots': shares // 1000,  # 張數
            'value': position_value,
            'risk': actual_risk,
            'risk_pct': (actual_risk / self.total_capital) * 100,
            'position_pct': position_pct,
            'risk_per_share': risk_per_share
        }
    
    def calculate_position_by_kelly(self,
                                    win_rate: float,
                                    avg_win: float,
                                    avg_loss: float,
                                    entry_price: float) -> Dict:
        """
        使用 Kelly 公式計算最佳倉位
        
        Kelly% = W - [(1-W) / R]
        其中：
        W = 勝率
        R = 平均獲利 / 平均虧損（賠率）
        
        參數:
            win_rate: 勝率（0-1之間）
            avg_win: 平均獲利金額
            avg_loss: 平均虧損金額（正數）
            entry_price: 進場價格
            
        返回:
            Dict: 倉位資訊
        """
        
        if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
            logger.warning("Kelly 公式參數不合理")
            return None
        
        # 計算賠率
        payout_ratio = avg_win / avg_loss
        
        # Kelly 公式
        kelly_pct = win_rate - ((1 - win_rate) / payout_ratio)
        
        # Kelly 公式可能產生負值（表示不該下注）
        if kelly_pct <= 0:
            logger.warning(f"Kelly% 為負 ({kelly_pct:.2%})，策略不具優勢")
            return None
        
        # 使用 Half Kelly（更保守）
        kelly_pct = kelly_pct / 2
        
        # 限制在合理範圍內
        kelly_pct = min(kelly_pct, self.max_position_pct)
        
        # 計算倉位
        position_value = self.total_capital * kelly_pct
        shares = int(position_value / entry_price)
        shares = (shares // 1000) * 1000
        
        actual_value = shares * entry_price
        position_pct = (actual_value / self.total_capital) * 100
        
        return {
            'shares': shares,
            'lots': shares // 1000,
            'value': actual_value,
            'kelly_pct': kelly_pct * 100,
            'position_pct': position_pct,
            'payout_ratio': payout_ratio
        }
    
    def calculate_position_by_atr(self,
                                  entry_price: float,
                                  atr: float,
                                  atr_multiplier: float = 2.0) -> Dict:
        """
        使用 ATR（平均真實波幅）計算倉位
        
        停損距離 = ATR × 倍數
        
        參數:
            entry_price: 進場價格
            atr: 平均真實波幅
            atr_multiplier: ATR 倍數（通常 2-3）
            
        返回:
            Dict: 倉位資訊
        """
        
        # 計算停損距離
        stop_distance = atr * atr_multiplier
        stop_loss = entry_price - stop_distance
        
        # 使用固定風險法計算
        result = self.calculate_position_by_risk(entry_price, stop_loss)
        
        if result:
            result['atr'] = atr
            result['atr_multiplier'] = atr_multiplier
            result['stop_loss'] = stop_loss
        
        return result
    
    def calculate_position_simple(self,
                                  entry_price: float,
                                  position_pct: float = 0.10) -> Dict:
        """
        簡單固定百分比倉位
        
        參數:
            entry_price: 進場價格
            position_pct: 倉位百分比（佔總資金）
            
        返回:
            Dict: 倉位資訊
        """
        
        position_value = self.total_capital * position_pct
        shares = int(position_value / entry_price)
        shares = (shares // 1000) * 1000
        
        actual_value = shares * entry_price
        actual_pct = (actual_value / self.total_capital) * 100
        
        return {
            'shares': shares,
            'lots': shares // 1000,
            'value': actual_value,
            'position_pct': actual_pct
        }


class PortfolioManager:
    """投資組合管理器"""
    
    def __init__(self, total_capital: float):
        """
        初始化投資組合管理器
        
        參數:
            total_capital: 總資金
        """
        self.total_capital = total_capital
        self.positions = {}  # {symbol: position_info}
        self.available_capital = total_capital
    
    def add_position(self, 
                    symbol: str,
                    shares: int,
                    entry_price: float,
                    stop_loss: float = None):
        """新增倉位"""
        
        value = shares * entry_price
        
        if value > self.available_capital:
            logger.warning(f"資金不足，無法開倉 {symbol}")
            return False
        
        self.positions[symbol] = {
            'shares': shares,
            'entry_price': entry_price,
            'current_price': entry_price,
            'stop_loss': stop_loss,
            'value': value,
            'pnl': 0,
            'pnl_pct': 0
        }
        
        self.available_capital -= value
        logger.info(f"新增倉位 {symbol}: {shares}股 @ {entry_price}")
        
        return True
    
    def update_position_price(self, symbol: str, current_price: float):
        """更新倉位價格"""
        
        if symbol not in self.positions:
            return False
        
        pos = self.positions[symbol]
        pos['current_price'] = current_price
        pos['value'] = pos['shares'] * current_price
        pos['pnl'] = (current_price - pos['entry_price']) * pos['shares']
        pos['pnl_pct'] = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
        
        return True
    
    def close_position(self, symbol: str, exit_price: float):
        """平倉"""
        
        if symbol not in self.positions:
            logger.warning(f"找不到倉位 {symbol}")
            return None
        
        pos = self.positions[symbol]
        pnl = (exit_price - pos['entry_price']) * pos['shares']
        
        # 釋放資金
        self.available_capital += exit_price * pos['shares']
        
        # 記錄後移除
        closed_position = pos.copy()
        closed_position['exit_price'] = exit_price
        closed_position['final_pnl'] = pnl
        
        del self.positions[symbol]
        
        logger.info(f"平倉 {symbol}: 損益 {int(pnl):+,} 元")
        
        return closed_position
    
    def get_portfolio_summary(self) -> Dict:
        """取得投資組合總覽"""
        
        total_value = self.available_capital
        total_pnl = 0
        
        for symbol, pos in self.positions.items():
            total_value += pos['value']
            total_pnl += pos['pnl']
        
        total_return_pct = ((total_value - self.total_capital) / self.total_capital) * 100
        
        return {
            'total_capital': self.total_capital,
            'total_value': total_value,
            'available_capital': self.available_capital,
            'invested_capital': total_value - self.available_capital,
            'total_pnl': total_pnl,
            'total_return_pct': total_return_pct,
            'position_count': len(self.positions),
            'capital_usage_pct': ((total_value - self.available_capital) / self.total_capital) * 100
        }
    
    def check_risk_limits(self) -> Dict[str, bool]:
        """檢查風險限制"""
        
        checks = {
            'max_positions': len(self.positions) <= 10,  # 最多10個倉位
            'capital_usage': ((self.total_capital - self.available_capital) / self.total_capital) <= 0.80,  # 資金使用不超過80%
        }
        
        # 檢查單一倉位是否過大
        for symbol, pos in self.positions.items():
            position_pct = (pos['value'] / self.total_capital)
            if position_pct > 0.25:  # 單一倉位不超過25%
                checks[f'{symbol}_oversized'] = False
        
        return checks


# 使用範例
if __name__ == "__main__":
    print("智能倉位管理系統")
    print("=" * 50)
    print()
    
    # 範例 1: 固定風險法
    print("📊 範例 1: 固定風險法")
    print("-" * 50)
    sizer = PositionSizer(
        total_capital=1000000,    # 100萬資金
        risk_per_trade_pct=0.02,  # 每筆風險2%
        max_position_pct=0.20     # 單一倉位最多20%
    )
    
    result = sizer.calculate_position_by_risk(
        entry_price=600.0,
        stop_loss=590.0
    )
    
    if result:
        print(f"進場價格: {600.0}")
        print(f"停損價格: {590.0}")
        print(f"建議股數: {result['shares']} 股 ({result['lots']} 張)")
        print(f"倉位價值: {int(result['value']):,} 元")
        print(f"風險金額: {int(result['risk']):,} 元 ({result['risk_pct']:.2f}%)")
        print(f"倉位佔比: {result['position_pct']:.2f}%")
    
    print()
    
    # 範例 2: Kelly 公式
    print("📊 範例 2: Kelly 公式")
    print("-" * 50)
    
    result = sizer.calculate_position_by_kelly(
        win_rate=0.60,      # 60% 勝率
        avg_win=15000,      # 平均獲利 1.5萬
        avg_loss=10000,     # 平均虧損 1萬
        entry_price=600.0
    )
    
    if result:
        print(f"勝率: 60%")
        print(f"賠率: {result['payout_ratio']:.2f}")
        print(f"Kelly%: {result['kelly_pct']:.2f}%")
        print(f"建議股數: {result['shares']} 股 ({result['lots']} 張)")
        print(f"倉位價值: {int(result['value']):,} 元")
        print(f"倉位佔比: {result['position_pct']:.2f}%")
    
    print()
    
    # 範例 3: 投資組合管理
    print("📊 範例 3: 投資組合管理")
    print("-" * 50)
    
    portfolio = PortfolioManager(total_capital=1000000)
    
    # 開倉
    portfolio.add_position('2330', 2000, 600.0, 590.0)
    portfolio.add_position('2454', 1000, 1200.0, 1180.0)
    
    # 更新價格
    portfolio.update_position_price('2330', 615.0)
    portfolio.update_position_price('2454', 1190.0)
    
    # 查看總覽
    summary = portfolio.get_portfolio_summary()
    
    print(f"總資金: {int(summary['total_capital']):,} 元")
    print(f"總市值: {int(summary['total_value']):,} 元")
    print(f"總損益: {int(summary['total_pnl']):+,} 元")
    print(f"報酬率: {summary['total_return_pct']:+.2f}%")
    print(f"持倉數: {summary['position_count']}")
    print(f"資金使用率: {summary['capital_usage_pct']:.1f}%")
