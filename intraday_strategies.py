"""
日內交易策略模組 - V11.7 (動態加減碼版)
更新內容：
1. 布林+MACD策略改為多時間框架（60分K趨勢 + 5分K進場）
2. 新增動態加碼與減碼（移動停利）邏輯
"""

import pandas as pd
import numpy as np
import logging
from datetime import datetime, time

logger = logging.getLogger(__name__)

class StrategyManager:
    """
    策略管理器：負責管理與執行所有交易策略
    """
    def __init__(self):
        # 定義可用策略清單 (整合新舊所有策略)
        self.strategies = {
            # --- 空方策略 ---
            'bearish_reversal': {
                'name': '空方轉弱策略',
                'desc': 'VWAP跌破 / 均線死叉 / 開盤不過高 / 布林墓碑'
            },
            'lower_high_reversal': {
                'name': '反彈不過前高 (123法則)',
                'desc': '高點降低 + 頸線跌破 + 量縮反彈'
            },
            'optimized_short': {
                'name': '量縮不過高 (優化版)',
                'desc': '近期高點<前高 + 量縮 + 跌破頸線 + 追空濾網'
            },
            'chip_divergence': {
                'name': '籌碼/指標背離',
                'desc': '價格創高但 RSI/量能 背離'
            },
            
            # --- 多方策略 ---
            'momentum_breakout': {
                'name': '動能突破策略',
                'desc': '價量齊揚突破前高 / 均線多頭排列'
            },
            'opening_range': {
                'name': '開盤區間突破 (ORB)',
                'desc': '突破開盤30分鐘高點'
            },
            'gap_trading': {
                'name': '跳空缺口交易',
                'desc': '開盤跳空後的回補或續攻'
            },
            'volume_price': {
                'name': '量價策略',
                'desc': '爆量長紅或量縮回檔'
            },
            
            # --- 震盪/均值策略 ---
            'mean_reversion': {
                'name': '均值回歸',
                'desc': '布林通道逆勢操作 / RSI 超買超賣'
            },
            'vwap': {
                'name': 'VWAP 均價策略',
                'desc': '回測 VWAP 不破做多 / 反彈不過做空'
            },
            'fast_ma': {
                'name': '快速均線策略',
                'desc': '5MA / 10MA 短線交叉'
            },
            
            # --- 複合策略 ---
            'bollinger_macd': {
                'name': '布林+MACD雙重確認(多時間框架)',
                'desc': '60分K趨勢 + 5分K觸軌 + MACD交叉'
            }
        }
        # 預設啟用策略
        self.active_strategies = list(self.strategies.keys())

    def get_strategy_list(self):
        return list(self.strategies.keys())

    def get_strategy_info(self):
        return {k: v['name'] for k, v in self.strategies.items()}

    def set_active_strategies(self, strategies):
        self.active_strategies = strategies

    def evaluate_all(self, symbol, df_60, df_5, current_price):
        """一次評估所有啟用策略，回傳信號列表"""
        signals = []
        for strat in self.active_strategies:
            sig = self.evaluate_strategy(strat, symbol, df_60, df_5, current_price)
            if sig:
                signals.append(sig)
        return signals

    def evaluate_strategy(self, strategy_name, symbol, df_60, df_5, current_price):
        """執行單一策略邏輯"""
        # 對於需要多時間框架的策略，直接傳入兩個 DataFrame
        if strategy_name == 'bollinger_macd':
            return self._check_bollinger_macd(df_60, df_5, current_price)

        # 其他策略仍維持原有邏輯（合併資料，優先使用5分K）
        if df_5 is not None and not df_5.empty and len(df_5) >= 30:
            df = self._calculate_indicators(df_5.copy())
        elif df_60 is not None and not df_60.empty and len(df_60) > 30:
            df = self._calculate_indicators(df_60.copy())
        else:
            return None

        # 策略分派
        if strategy_name == 'bearish_reversal':
            return self._check_bearish_reversal(df, current_price)
        elif strategy_name == 'lower_high_reversal':
            return self._check_lower_high(df, current_price)
        elif strategy_name == 'optimized_short':
            return self._check_short_strategy_optimized(df, current_price)
        elif strategy_name == 'chip_divergence':
            return self._check_divergence(df, current_price)
        elif strategy_name == 'momentum_breakout':
            return self._check_momentum_breakout(df, current_price)
        elif strategy_name == 'opening_range':
            return self._check_orb(df, current_price)
        elif strategy_name == 'gap_trading':
            return self._check_gap_trading(df, current_price)
        elif strategy_name == 'mean_reversion':
            return self._check_mean_reversion(df, current_price)
        elif strategy_name == 'vwap':
             return self._check_vwap_strategy(df, current_price)
        elif strategy_name == 'fast_ma':
             return self._check_fast_ma(df, current_price)
        
        return None

    # -----------------------------------------------------------
    # 技術指標計算核心（V11.5 修正版）
    # -----------------------------------------------------------
    def _calculate_indicators(self, df):
        # 確保有 volume 欄位，若無則補 0
        if 'volume' not in df.columns:
            df['volume'] = 0

        # 移動平均線
        df['MA5'] = df['close'].rolling(window=5).mean()
        df['MA9'] = df['close'].rolling(window=9).mean()
        df['MA10'] = df['close'].rolling(window=10).mean()
        df['MA20'] = df['close'].rolling(window=20).mean()
        df['MA21'] = df['close'].rolling(window=21).mean() # 輔助空方策略
        
        # VWAP (簡易當日累計，假設 df 是當日或近期連續資料)
        # Typical Price = (High + Low + Close) / 3
        df['Typical_Price'] = (df['high'] + df['low'] + df['close']) / 3
        
        # 避免除以 0
        cum_vol = df['volume'].cumsum()
        cum_vol = cum_vol.replace(0, 1)  
        df['VWAP'] = (df['Typical_Price'] * df['volume']).cumsum() / cum_vol
        
        # Bollinger Bands (12MA, 2std) 使用母體標準差 ddof=0
        df['MA12'] = df['close'].rolling(window=12).mean()
        df['STD12'] = df['close'].rolling(window=12).std(ddof=0)   # <--- 修正處
        df['BB_Upper'] = df['MA12'] + (df['STD12'] * 2)
        df['BB_Lower'] = df['MA12'] - (df['STD12'] * 2)
        
        # RSI (14)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # MACD (6,19,6)
        df['EMA6'] = df['close'].ewm(span=6, adjust=False).mean()
        df['EMA19'] = df['close'].ewm(span=19, adjust=False).mean()
        df['DIF'] = df['EMA6'] - df['EMA19']
        df['DEM'] = df['DIF'].ewm(span=6, adjust=False).mean()
        df['MACD_hist'] = (df['DIF'] - df['DEM']) * 2   # 柱狀體
        
        return df

    # -----------------------------------------------------------
    # 核心策略邏輯庫（原有策略保持不變）
    # -----------------------------------------------------------
    
    def _check_bearish_reversal(self, df, current_price):
        """
        策略 1: 關鍵放空策略 (尋找轉弱訊號)
        """
        reasons = []
        confidence = 0.0
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        
        # 1. 均線死叉 (9MA 跌破 21MA)
        if prev_row['MA9'] >= prev_row['MA21'] and last_row['MA9'] < last_row['MA21']:
            reasons.append("9MA/21MA 死叉")
            confidence += 0.3
        elif last_row['MA9'] < last_row['MA21'] and current_price < last_row['MA9']:
            pass 
            
        # 2. VWAP 跌破
        if prev_row['close'] >= prev_row['VWAP'] and current_price < last_row['VWAP']:
            reasons.append("跌破 VWAP")
            confidence += 0.4
            
        # 3. 開盤高點不過
        day_high = df['high'].tail(50).max()
        day_open = df.iloc[0]['open'] if len(df) < 100 else df.iloc[-60]['open']
        
        if current_price < day_open and current_price < day_high * 0.985:
            reasons.append("開盤衝高失敗(轉弱)")
            confidence += 0.3

        # 4. 布林高檔乖離 (墓碑線)
        if prev_row['high'] > prev_row['BB_Upper']:
            upper_shadow = prev_row['high'] - max(prev_row['open'], prev_row['close'])
            body = abs(prev_row['close'] - prev_row['open'])
            if upper_shadow > body * 1.5 and current_price < prev_row['low']:
                reasons.append("布林上軌墓碑線確認")
                confidence += 0.3

        if confidence >= 0.3:
            return {
                'action': 'Sell',
                'strategy': '空方轉弱',
                'reason': " + ".join(reasons),
                'confidence': min(confidence, 1.0),
                'price': current_price
            }
        return None
        
    def _check_lower_high(self, df, current_price):
        """
        策略 2: 反彈不過前高 (Lower High)
        """
        recent_df = df.tail(40).copy().reset_index(drop=True)
        peaks = []
        
        for i in range(2, len(recent_df) - 2):
            curr_h = recent_df.loc[i, 'high']
            if (curr_h > recent_df.loc[i-1, 'high'] and 
                curr_h > recent_df.loc[i-2, 'high'] and
                curr_h > recent_df.loc[i+1, 'high'] and
                curr_h > recent_df.loc[i+2, 'high']):
                peaks.append((i, curr_h, recent_df.loc[i, 'volume']))
        
        if len(peaks) >= 2:
            p1_idx, p1_price, p1_vol = peaks[-2]
            p2_idx, p2_price, p2_vol = peaks[-1]
            
            if p2_price < p1_price:
                valley_price = recent_df.loc[p1_idx:p2_idx, 'low'].min()
                
                if current_price < valley_price:
                    msg_list = [f"M頭跌破頸線({valley_price:.1f})"]
                    conf = 0.6
                    
                    if p2_vol < p1_vol * 0.9:
                        msg_list.append("量縮反彈")
                        conf += 0.2
                    
                    return {
                        'action': 'Sell',
                        'strategy': '反彈不過前高',
                        'reason': " + ".join(msg_list),
                        'confidence': min(conf, 1.0),
                        'price': current_price,
                        'stop_loss': p2_price
                    }
        return None

    def _check_short_strategy_optimized(self, df, current_price):
        """
        策略 4: 量縮不過高 (優化版)
        """
        if len(df) < 30: return None
        d = df.copy()
        
        d['p_high'] = d['high'].rolling(12).max().shift(5)
        d['recent_high'] = d['high'].rolling(5).max()
        
        d['vol_ma_past'] = d['volume'].rolling(12).mean().shift(5)
        d['vol_ma_recent'] = d['volume'].rolling(5).mean()
        
        d['neckline'] = d['low'].rolling(5).min().shift(1)
        
        last = d.iloc[-1]
        
        if last['recent_high'] < last['p_high']:
            if last['vol_ma_recent'] < last['vol_ma_past'] * 0.8:
                if current_price < last['neckline']:
                    drawdown = (last['p_high'] - current_price) / last['p_high']
                    if drawdown <= 0.04:
                        return {
                            'action': 'Sell',
                            'strategy': '量縮不過高(優化)',
                            'reason': '形態不過高 + 量縮 + 破線',
                            'confidence': 0.8,
                            'price': current_price
                        }
        return None

    def _check_divergence(self, df, current_price):
        """
        策略 3: 籌碼/指標背離 (價格創高 RSI 創低)
        """
        recent_df = df.tail(40).reset_index(drop=True)
        peaks = []
        
        for i in range(2, len(recent_df) - 2):
            if (recent_df.loc[i, 'high'] > recent_df.loc[i-1, 'high'] and 
                recent_df.loc[i, 'high'] > recent_df.loc[i+1, 'high']):
                peaks.append(i)
                
        if len(peaks) >= 2:
            p1_idx = peaks[-2]
            p2_idx = peaks[-1]
            
            price1 = recent_df.loc[p1_idx, 'high']
            price2 = recent_df.loc[p2_idx, 'high']
            rsi1 = recent_df.loc[p1_idx, 'RSI']
            rsi2 = recent_df.loc[p2_idx, 'RSI']
            
            if price2 > price1 and rsi2 < rsi1:
                current_rsi = recent_df.iloc[-1]['RSI']
                if current_rsi < 70 and current_price < price2:
                    return {
                        'action': 'Sell',
                        'strategy': '指標背離',
                        'reason': f"價創高({price2:.1f})但RSI背離({rsi2:.1f}<{rsi1:.1f})",
                        'confidence': 0.75,
                        'price': current_price
                    }
        return None

    # --- 多方與其他策略 ---
    def _check_momentum_breakout(self, df, current_price):
        last = df.iloc[-1]
        if last['close'] > last['BB_Upper']:
            vol_ma5 = df['volume'].rolling(5).mean().iloc[-2]
            if last['volume'] > vol_ma5 * 1.5:
                return {
                    'action': 'Buy',
                    'strategy': '動能突破',
                    'reason': '帶量突破布林上軌',
                    'confidence': 0.8,
                    'price': current_price
                }
        return None

    def _check_gap_trading(self, df, current_price):
        return None

    def _check_mean_reversion(self, df, current_price):
        last = df.iloc[-1]
        if last['RSI'] < 30 and last['low'] <= last['BB_Lower']:
            return {
                'action': 'Buy',
                'strategy': '均值回歸',
                'reason': 'RSI超賣且觸及布林下軌',
                'confidence': 0.7,
                'price': current_price
            }
        return None

    def _check_orb(self, df, current_price):
        return None
        
    def _check_vwap_strategy(self, df, current_price):
        last = df.iloc[-1]
        if abs(current_price - last['VWAP']) / last['VWAP'] < 0.005 and current_price > last['VWAP']:
            return {
                'action': 'Buy',
                'strategy': 'VWAP支撐',
                'reason': '回測VWAP有撐',
                'confidence': 0.6,
                'price': current_price
            }
        return None
        
    def _check_fast_ma(self, df, current_price):
        last = df.iloc[-1]
        prev = df.iloc[-2]
        if prev['MA5'] <= prev['MA10'] and last['MA5'] > last['MA10']:
            return {
                'action': 'Buy',
                'strategy': '快速均線',
                'reason': '5MA 金叉 10MA',
                'confidence': 0.6,
                'price': current_price
            }
        return None

    # -----------------------------------------------------------
    # 布林+MACD雙重確認策略（多時間框架版）
    # -----------------------------------------------------------
    def _check_bollinger_macd(self, df_60, df_5, current_price):
        """
        布林 + MACD 雙重確認策略（多時間框架版）
        做多條件：
            - 60分K MACD 柱狀體 > 0（多頭動能）
            - 5分K 價格觸及或跌破下軌
            - 5分K MACD 金叉 或 柱體翻正（以上一根已收盤K線為準）
        做空條件：
            - 60分K MACD 柱狀體 < 0（空頭動能）
            - 5分K 價格觸及或突破上軌
            - 5分K MACD 死叉 或 柱體翻負
        """
        # 確保有足夠數據（至少 60 根，讓 EMA19 穩定）
        if len(df_60) < 60 or len(df_5) < 60:
            return None

        # 計算兩者的技術指標
        df_60 = self._calculate_indicators(df_60.copy())
        df_5 = self._calculate_indicators(df_5.copy())

        # 取得60分K的最新MACD柱狀體（判斷趨勢）
        macd_hist_60 = df_60.iloc[-1]['MACD_hist']

        # 取得5分K的已收盤K線（索引 -2 為上一根，-3 為上上根）
        prev2 = df_5.iloc[-2]
        prev3 = df_5.iloc[-3]
        last_close = df_5.iloc[-1]['close']

        reasons = []
        confidence = 0.0
        action = None

        # --- 做多條件（趨勢多頭 + 5分K訊號）---
        if macd_hist_60 > 0:  # 60分K為多頭動能
            price_below_lower = current_price <= prev2['BB_Lower'] or last_close <= prev2['BB_Lower']
            macd_bull_cross = (prev3['DIF'] <= prev3['DEM']) and (prev2['DIF'] > prev2['DEM'])
            macd_bull_hist = (prev3['MACD_hist'] < 0) and (prev2['MACD_hist'] > 0)

            if price_below_lower and (macd_bull_cross or macd_bull_hist):
                reasons.append("60分K多頭趨勢")
                reasons.append("價格觸及下軌")
                if macd_bull_cross:
                    reasons.append("5分K MACD金叉(確認)")
                    confidence += 0.4
                if macd_bull_hist:
                    reasons.append("5分K柱體翻正(確認)")
                    confidence += 0.3
                if current_price < prev2['BB_Lower']:
                    confidence += 0.1
                action = 'Buy'

        # --- 做空條件（趨勢空頭 + 5分K訊號）---
        elif macd_hist_60 < 0:  # 60分K為空頭動能
            price_above_upper = current_price >= prev2['BB_Upper'] or last_close >= prev2['BB_Upper']
            macd_bear_cross = (prev3['DIF'] >= prev3['DEM']) and (prev2['DIF'] < prev2['DEM'])
            macd_bear_hist = (prev3['MACD_hist'] > 0) and (prev2['MACD_hist'] < 0)

            if price_above_upper and (macd_bear_cross or macd_bear_hist):
                reasons.append("60分K空頭趨勢")
                reasons.append("價格觸及上軌")
                if macd_bear_cross:
                    reasons.append("5分K MACD死叉(確認)")
                    confidence += 0.4
                if macd_bear_hist:
                    reasons.append("5分K柱體翻負(確認)")
                    confidence += 0.3
                if current_price > prev2['BB_Upper']:
                    confidence += 0.1
                action = 'Sell'

        if action and confidence >= 0.3:
            return {
                'action': action,
                'strategy': '布林+MACD(多時間框架)',
                'reason': " + ".join(reasons),
                'confidence': min(confidence, 1.0),
                'price': current_price,
                'stop_loss': prev2['BB_Lower'] if action == 'Buy' else prev2['BB_Upper']
            }
        return None

    # -----------------------------------------------------------
    # 新增：動態加碼/減碼檢查
    # -----------------------------------------------------------
    def _check_add_position(self, symbol, df_60, df_5, current_price, position, settings=None):
        """
        檢查是否應該加碼
        position: 當前持倉 dict，包含 price, qty, highest_price 等
        settings: 包含啟用開關、門檻、加碼比例等
        """
        if not position:
            return None
        if settings is None:
            settings = {}

        enable = settings.get('enable_add_position', False)
        if not enable:
            return None

        entry_price = position['price']
        pnl_pct = (current_price - entry_price) / entry_price
        threshold = settings.get('add_threshold', 2.0) / 100

        # 獲利需超過門檻才考慮加碼
        if pnl_pct < threshold:
            return None

        # 計算技術指標（使用5分K）
        df = self._calculate_indicators(df_5.copy())
        last = df.iloc[-1]
        prev = df.iloc[-2]

        # 範例加碼條件：突破布林上軌且 MACD 柱狀體擴大（可自訂）
        if last['close'] > last['BB_Upper'] and last['MACD_hist'] > prev['MACD_hist'] * 1.2:
            return {
                'action': 'Add',
                'strategy': '動態加碼',
                'reason': f'突破上軌+MACD動能增強 (獲利{pnl_pct*100:.1f}%)',
                'confidence': 0.7,
                'price': current_price,
                'add_ratio': settings.get('add_ratio', 0.5)  # 加碼比例
            }
        return None

    def _check_reduce_position(self, symbol, df_5, current_price, position, settings=None):
        """
        檢查是否應該減碼（移動停利或部分獲利了結）
        """
        if not position:
            return None
        if settings is None:
            settings = {}

        enable = settings.get('enable_trailing_stop', True)
        if not enable:
            return None

        entry_price = position['price']
        highest = position.get('highest_price', entry_price)
        pnl_pct = (current_price - entry_price) / entry_price

        # 更新最高價應由外部進行，此處僅讀取
        # 計算回檔幅度
        drawdown = (highest - current_price) / highest if highest > 0 else 0

        # 移動停利：當最高獲利超過 activation 且回檔超過 drawdown 時，減碼
        activation = settings.get('trailing_activation', 3.0) / 100
        trailing_drawdown = settings.get('trailing_drawdown', 1.0) / 100
        reduce_ratio = settings.get('reduce_ratio', 0.5)

        if pnl_pct > activation and drawdown > trailing_drawdown:
            return {
                'action': 'Reduce',
                'strategy': '移動停利',
                'reason': f'最高獲利{(highest-entry_price)/entry_price*100:.1f}%，回檔{drawdown*100:.1f}%',
                'confidence': 0.9,
                'price': current_price,
                'reduce_ratio': reduce_ratio
            }

        # 固定停利：當獲利超過固定百分比時，部分獲利了結（僅一次）
        fixed_take_profit = settings.get('fixed_take_profit', 5.0) / 100
        if pnl_pct > fixed_take_profit and not position.get('partial_taken', False):
            return {
                'action': 'Reduce',
                'strategy': '部分獲利',
                'reason': f'獲利{pnl_pct*100:.1f}%，部分出場',
                'confidence': 0.8,
                'price': current_price,
                'reduce_ratio': reduce_ratio,
                'mark_taken': True
            }
        return None

    # -----------------------------------------------------------
    # 兼容舊版介面
    # -----------------------------------------------------------
    def get_best_signal(self, symbol, df_60, df_5, current_price):
        signals = self.evaluate_all(symbol, df_60, df_5, current_price)
        if not signals: return None
        return sorted(signals, key=lambda x: x['confidence'], reverse=True)[0]
    
    def generate_signal(self, symbol, df_60, price):
        return self.get_best_signal(symbol, df_60, df_60, price)
    
    def get_consensus_signal(self, symbol, df_60, df_5, current_price):
        signals = self.evaluate_all(symbol, df_60, df_5, current_price)
        if not signals: return None
        
        buys = [s for s in signals if s['action'] == 'Buy']
        sells = [s for s in signals if s['action'] == 'Sell']
        
        if len(buys) >= 2:
            return buys[0] 
        elif len(sells) >= 2:
            return sells[0] 
            
        return None