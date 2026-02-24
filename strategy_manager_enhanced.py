"""
增強版策略管理器 - 包含策略分類與日誌整合
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import logging
from log_manager import get_log_manager

class EnhancedStrategyManager:
    """增強版策略管理器"""
    
    def __init__(self):
        self.log_manager = get_log_manager()
        self.strategies = self._initialize_strategies()
        self.active_strategies = []
        self.strategy_performance = {}
        
    def _initialize_strategies(self) -> Dict:
        """初始化策略庫"""
        return {
            # ========== 做多策略 ==========
            'strength_screener': {
                'category': 'long',
                'name': '強勢股選股策略',
                'description': '前一日漲幅前100，排除ETF，成交量≥2000張，震幅≥4%',
                'params': {
                    'min_volume': 2000,
                    'min_amplitude': 4.0,
                    'rank_cutoff': 100
                }
            },
            'opening_range_breakout': {
                'category': 'long',
                'name': '開盤區間突破做多',
                'description': '開盤30分鐘內突破區間上緣',
                'params': {
                    'timeframe': '30min',
                    'volume_multiplier': 1.5
                }
            },
            'volume_gap_up': {
                'category': 'long',
                'name': '放量跳空做多',
                'description': '向上跳空缺口+成交量放大',
                'params': {
                    'gap_threshold': 0.01,
                    'volume_ratio': 1.2
                }
            },
            
            # ========== 做空策略 ==========
            'weakness_screener': {
                'category': 'short',
                'name': '弱勢股選股策略',
                'description': '前一日跌幅前100，排除ETF，成交量≥1000張，震幅≥4%',
                'params': {
                    'min_volume': 1000,
                    'min_amplitude': 4.0,
                    'rank_cutoff': 100
                }
            },
            'mean_reversion_short': {
                'category': 'short',
                'name': '均值回歸做空',
                'description': '股價偏離移動平均線過遠時回歸',
                'params': {
                    'ma_period': 20,
                    'deviation_threshold': 0.05,
                    'rsi_overbought': 70
                }
            },
            'vwap_rejection': {
                'category': 'short',
                'name': 'VWAP反轉做空',
                'description': '價格反彈至VWAP受阻回落',
                'params': {
                    'vwap_period': 'daily',
                    'rejection_threshold': 0.02
                }
            },
            
            # ========== 中性策略 ==========
            'momentum_breakout': {
                'category': 'neutral',
                'name': '動量突破策略',
                'description': '突破關鍵價位（前高/前低）',
                'params': {
                    'lookback_period': 20,
                    'breakout_threshold': 0.01
                }
            },
            'volume_price_confirmation': {
                'category': 'neutral',
                'name': '量價確認策略',
                'description': '價格與成交量同步確認方向',
                'params': {
                    'volume_threshold': 1.2,
                    'confirmation_period': 3
                }
            },
            'fast_ma_crossover': {
                'category': 'neutral',
                'name': '快速均線交叉',
                'description': '快速MA與慢速MA交叉',
                'params': {
                    'fast_ma': 5,
                    'slow_ma': 20
                }
            },
            'gap_trading': {
                'category': 'neutral',
                'name': '缺口交易策略',
                'description': '交易跳空缺口的回補',
                'params': {
                    'gap_threshold': 0.01,
                    'target_ratio': 0.5
                }
            },
            'rsi_divergence': {
                'category': 'neutral',
                'name': 'RSI背離策略',
                'description': '價格與RSI指標出現背離',
                'params': {
                    'rsi_period': 14,
                    'divergence_lookback': 5
                }
            }
        }
    
    def set_active_strategies(self, strategy_list: List[str]):
        """設定啟用的策略"""
        self.active_strategies = strategy_list
        self.log_manager.logger.info(f"啟用策略: {strategy_list}")
    
    def get_strategies_by_category(self, category: str) -> Dict:
        """根據類別取得策略"""
        return {k: v for k, v in self.strategies.items() 
                if v['category'] == category}
    
    def get_long_strategies(self) -> Dict:
        """取得做多策略"""
        return self.get_strategies_by_category('long')
    
    def get_short_strategies(self) -> Dict:
        """取得做空策略"""
        return self.get_strategies_by_category('short')
    
    def get_neutral_strategies(self) -> Dict:
        """取得中性策略"""
        return self.get_strategies_by_category('neutral')
    
    def generate_signal(self, symbol: str, price_data: pd.DataFrame, 
                       current_price: float) -> Dict:
        """產生交易信號"""
        signals = []
        
        for strategy_id in self.active_strategies:
            if strategy_id in self.strategies:
                signal = self._execute_strategy(
                    strategy_id, symbol, price_data, current_price
                )
                if signal:
                    signals.append(signal)
        
        if signals:
            # 選擇最佳信號（最高信心度）
            best_signal = max(signals, key=lambda x: x.get('confidence', 0))
            
            # 記錄策略決策過程
            self._log_strategy_decision(symbol, signals, best_signal)
            
            return best_signal
        
        return None
    
    def _execute_strategy(self, strategy_id: str, symbol: str, 
                         price_data: pd.DataFrame, current_price: float) -> Optional[Dict]:
        """執行單一策略"""
        strategy_info = self.strategies[strategy_id]
        
        try:
            if strategy_id == 'momentum_breakout':
                return self._momentum_breakout(symbol, price_data, current_price)
            elif strategy_id == 'mean_reversion_short':
                return self._mean_reversion_short(symbol, price_data, current_price)
            elif strategy_id == 'volume_price_confirmation':
                return self._volume_price_confirmation(symbol, price_data, current_price)
            elif strategy_id == 'fast_ma_crossover':
                return self._fast_ma_crossover(symbol, price_data, current_price)
            elif strategy_id == 'gap_trading':
                return self._gap_trading(symbol, price_data, current_price)
            elif strategy_id == 'rsi_divergence':
                return self._rsi_divergence(symbol, price_data, current_price)
        except Exception as e:
            self.log_manager.logger.error(f"策略執行錯誤 {strategy_id}: {e}")
            return None
        
        return None
    
    def _momentum_breakout(self, symbol: str, price_data: pd.DataFrame, 
                          current_price: float) -> Dict:
        """動量突破策略"""
        lookback = 20
        if len(price_data) < lookback:
            return None
        
        high_20 = price_data['high'].rolling(window=lookback).max().iloc[-1]
        low_20 = price_data['low'].rolling(window=lookback).min().iloc[-1]
        
        # 計算突破強度
        if current_price > high_20 * 1.01:
            return {
                'strategy': 'momentum_breakout',
                'action': 'Buy',
                'confidence': 0.7,
                'price': current_price,
                'reason': f'突破{lookback}日高點 {high_20:.2f}',
                'stop_loss': low_20,
                'take_profit': current_price * 1.05
            }
        elif current_price < low_20 * 0.99:
            return {
                'strategy': 'momentum_breakout',
                'action': 'Sell',
                'confidence': 0.6,
                'price': current_price,
                'reason': f'跌破{lookback}日低點 {low_20:.2f}',
                'stop_loss': high_20,
                'take_profit': current_price * 0.95
            }
        
        return None
    
    def _mean_reversion_short(self, symbol: str, price_data: pd.DataFrame, 
                             current_price: float) -> Dict:
        """均值回歸做空策略"""
        if len(price_data) < 20:
            return None
        
        ma_20 = price_data['close'].rolling(window=20).mean().iloc[-1]
        deviation = (current_price - ma_20) / ma_20
        
        if deviation > 0.05:  # 價格高於MA 5%以上
            return {
                'strategy': 'mean_reversion_short',
                'action': 'Sell',
                'confidence': 0.65,
                'price': current_price,
                'reason': f'價格偏高於20MA {deviation:.1%}，預期回歸',
                'stop_loss': current_price * 1.02,
                'take_profit': ma_20
            }
        
        return None
    
    def _log_strategy_decision(self, symbol: str, signals: List[Dict], 
                              selected_signal: Dict):
        """記錄策略決策過程"""
        decision_log = {
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'total_signals': len(signals),
            'signals': signals,
            'selected_signal': selected_signal,
            'selection_criteria': 'highest_confidence'
        }
        
        # 儲存到策略決策日誌
        log_file = f"logs/strategy_decisions/{datetime.now().strftime('%Y%m%d')}.json"
        import os
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        import json
        decisions = []
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                decisions = json.load(f)
        
        decisions.append(decision_log)
        
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(decisions, f, ensure_ascii=False, indent=2)
    
    def update_strategy_performance(self, strategy: str, pnl: float, 
                                   success: bool = True):
        """更新策略績效"""
        if strategy not in self.strategy_performance:
            self.strategy_performance[strategy] = {
                'total_trades': 0,
                'winning_trades': 0,
                'total_pnl': 0,
                'avg_pnl': 0,
                'win_rate': 0
            }
        
        perf = self.strategy_performance[strategy]
        perf['total_trades'] += 1
        perf['total_pnl'] += pnl
        
        if success:
            perf['winning_trades'] += 1
        
        perf['avg_pnl'] = perf['total_pnl'] / perf['total_trades']
        perf['win_rate'] = perf['winning_trades'] / perf['total_trades'] * 100
        
        # 記錄策略績效更新
        self.log_manager.logger.info(
            f"策略績效更新 - {strategy}: PNL={pnl:.2f}, 勝率={perf['win_rate']:.1f}%"
        )
    
    def get_strategy_report(self) -> pd.DataFrame:
        """取得策略績效報告"""
        report_data = []
        for strategy, perf in self.strategy_performance.items():
            report_data.append({
                'strategy': strategy,
                'category': self.strategies.get(strategy, {}).get('category', 'unknown'),
                'total_trades': perf['total_trades'],
                'winning_trades': perf['winning_trades'],
                'win_rate': f"{perf['win_rate']:.1f}%",
                'total_pnl': f"{perf['total_pnl']:.2f}",
                'avg_pnl': f"{perf['avg_pnl']:.2f}"
            })
        
        return pd.DataFrame(report_data)