# backtest_engine.py
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import yfinance as yf
import logging
import itertools

# ✅ 修正點 1：明確區分 datetime.time 與 time 模組，避免命名衝突
from datetime import datetime, time as dt_time
import time  # 標準 time 模組，供 time.sleep() / time.time() 使用

import warnings

# 忽略 pandas 警告
warnings.filterwarnings('ignore')

# 設定日誌格式
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


# =================================================================
# 第一部分：核心技術指標庫
# =================================================================
class TechnicalIndicators:
    @staticmethod
    def add_all_indicators(df, **kwargs):
        df = TechnicalIndicators.calc_ma(df,
            short_window=kwargs.get('ma_short', 5),
            mid_window=kwargs.get('ma_mid', 10),
            long_window=kwargs.get('ma_long', 20))
        df = TechnicalIndicators.calc_macd(df,
            fast=kwargs.get('macd_fast', 12),
            slow=kwargs.get('macd_slow', 26),
            signal=kwargs.get('macd_signal', 9))
        df = TechnicalIndicators.calc_kd(df, period=kwargs.get('kd_period', 9))
        df = TechnicalIndicators.calc_rsi(df, period=kwargs.get('rsi_period', 14))
        df = TechnicalIndicators.calc_bollinger_bands(df,
            period=kwargs.get('bb_period', 20),
            std_dev=kwargs.get('bb_std', 2.0))
        df = TechnicalIndicators.calc_vwap(df)
        df = TechnicalIndicators.calc_price_action(df)
        return df.dropna()

    @staticmethod
    def calc_ma(df, short_window=5, mid_window=10, long_window=20):
        df['SMA_5'] = df['Close'].rolling(window=short_window).mean()
        df['SMA_10'] = df['Close'].rolling(window=mid_window).mean()
        df['SMA_20'] = df['Close'].rolling(window=long_window).mean()
        df['Vol_MA_5'] = df['Volume'].rolling(window=short_window).mean()
        return df

    @staticmethod
    def calc_macd(df, fast=12, slow=26, signal=9):
        df['EMA_fast'] = df['Close'].ewm(span=fast, adjust=False).mean()
        df['EMA_slow'] = df['Close'].ewm(span=slow, adjust=False).mean()
        df['MACD_DIF'] = df['EMA_fast'] - df['EMA_slow']
        df['MACD_DEM'] = df['MACD_DIF'].ewm(span=signal, adjust=False).mean()
        df['MACD_OSC'] = df['MACD_DIF'] - df['MACD_DEM']
        return df

    @staticmethod
    def calc_kd(df, period=9):
        df['Min_Low'] = df['Low'].rolling(window=period).min()
        df['Max_High'] = df['High'].rolling(window=period).max()
        # ✅ 修正點：當 Max_High == Min_Low 時分母為 0，pandas 產生 inf 而非 NaN，
        # 需先將分母 0 替換為 NaN，再用 fillna(50) 同時處理 NaN 與 inf。
        denom = (df['Max_High'] - df['Min_Low']).replace(0, np.nan)
        df['RSV'] = ((df['Close'] - df['Min_Low']) / denom * 100).fillna(50).clip(0, 100)

        k, d = [], []
        for i, rsv in enumerate(df['RSV']):
            if i == 0:
                k.append(50); d.append(50)
            else:
                k.append(k[-1] * 2/3 + rsv * 1/3)
                d.append(d[-1] * 2/3 + k[-1] * 1/3)
        df['K'] = k
        df['D'] = d
        return df

    @staticmethod
    def calc_rsi(df, period=14):
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        # ✅ 修正點：loss 為 0 時 gain/0 = inf（動能純多方，RSI 應為 100），
        # gain 與 loss 均為 0 時結果為 NaN，fillna(50) 回退至中性值。
        rs = gain / loss.replace(0, np.nan)
        df['RSI'] = (100 - (100 / (1 + rs))).fillna(50)
        return df

    @staticmethod
    def calc_bollinger_bands(df, period=20, std_dev=2.0):
        df['BB_Mid'] = df['Close'].rolling(window=period).mean()
        df['BB_Std'] = df['Close'].rolling(window=period).std()
        df['BB_Upper'] = df['BB_Mid'] + (df['BB_Std'] * std_dev)
        df['BB_Lower'] = df['BB_Mid'] - (df['BB_Std'] * std_dev)
        return df

    @staticmethod
    def calc_vwap(df):
        """
        ✅ 修正點 2：VWAP 改為按日分組計算，避免跨日累積造成數值失真。
        原本使用全局 cumsum()，當 DataFrame 跨越多天時（如 period='60d'），
        VWAP 不會每天重置，導致指標數值持續偏移，影響策略判斷。
        """
        df['Typical_Price'] = (df['High'] + df['Low'] + df['Close']) / 3

        if hasattr(df.index, 'date'):
            # 有時間索引時，按照日期分組重置累積
            daily_groups = df.groupby(df.index.date)
            vwap_series = pd.Series(index=df.index, dtype=float)

            for _, group in daily_groups:
                cum_vol = group['Volume'].cumsum()
                cum_vol = cum_vol.replace(0, 1)  # 避免除以零
                vwap_series[group.index] = (
                    (group['Typical_Price'] * group['Volume']).cumsum() / cum_vol
                )
            df['VWAP'] = vwap_series
        else:
            # 無法判斷日期時，退回全局累積（回測單日資料的安全路徑）
            cum_vol = df['Volume'].cumsum().replace(0, 1)
            df['VWAP'] = (df['Typical_Price'] * df['Volume']).cumsum() / cum_vol

        return df

    @staticmethod
    def calc_price_action(df):
        df['Rolling_High_20'] = df['High'].rolling(window=20).max()
        df['Rolling_Low_20'] = df['Low'].rolling(window=20).min()
        df['ORB_High'] = df['High'].rolling(window=6).max()
        return df


# =================================================================
# 第二部分：回測引擎 (移動停利與分批出場機制)
# =================================================================
class BacktestEngine:
    def __init__(self, df, initial_capital=1000000, fee_rate=0.001425, tax_rate=0.0015,
                 slippage_ticks=1, force_close_time="13:25",
                 position_sizing="fixed_risk", risk_pct=0.02, verbose=True,
                 enable_scale_out=True, scale_out_target_pct=0.02,
                 enable_trailing_stop=True, trailing_activation_pct=0.03, trailing_drop_pct=0.015):
        """
        【高階防護參數】
        - enable_scale_out        : 啟動分批停利 (賣一半)
        - scale_out_target_pct    : 當獲利達 X% 時，觸發分批停利 (預設 2%)
        - enable_trailing_stop    : 啟動動態移動停利
        - trailing_activation_pct : 當獲利達 X% 時，啟動移動停利 (預設 3%)
        - trailing_drop_pct       : 從最高點回落 X% 時強制平倉 (預設 1.5%)
        """
        self.df = df
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.fee_rate = fee_rate
        self.tax_rate = tax_rate
        self.slippage_ticks = slippage_ticks

        self.position_sizing = position_sizing
        self.risk_pct = risk_pct

        self.enable_scale_out = enable_scale_out
        self.scale_out_target_pct = scale_out_target_pct
        self.enable_trailing_stop = enable_trailing_stop
        self.trailing_activation_pct = trailing_activation_pct
        self.trailing_drop_pct = trailing_drop_pct

        # ✅ 修正點 1：使用 dt_time 而非 time，避免與 time 模組衝突
        time_parts = force_close_time.split(":")
        self.force_close_time = dt_time(int(time_parts[0]), int(time_parts[1]))

        self.verbose = verbose

        self.position = 0
        self.entry_price = 0.0
        self.stop_loss_price = None
        self.highest_price_since_entry = 0.0
        self.lowest_price_since_entry = float('inf')
        self.scaled_out = False  # 記錄是否已經分批出場過

        self.trades = []
        self.equity_curve = []
        self.buy_markers = []
        self.sell_markers = []

    def _get_tick_size(self, price):
        if price < 10: return 0.01
        elif price < 50: return 0.05
        elif price < 100: return 0.1
        elif price < 500: return 0.5
        elif price < 1000: return 1.0
        else: return 5.0

    def _apply_slippage(self, action, current_price):
        tick_size = self._get_tick_size(current_price)
        slippage_amount = tick_size * self.slippage_ticks
        if action in ["BUY", "COVER"]: return current_price + slippage_amount
        elif action in ["SELL", "SHORT"]: return current_price - slippage_amount
        return current_price

    def _calculate_position_size(self, action, exec_price, stop_loss_price):
        """
        ✅ 修正點 3：確保所有執行路徑都有明確的 return 值，
        避免在 fixed_risk 模式下 stop_loss 為 None 或 risk_per_share == 0
        時，函式回傳 None，導致後續 execute_trade 發生 TypeError。
        """
        if self.position_sizing == "fixed_risk" and stop_loss_price:
            risk_amount = self.capital * self.risk_pct
            if action == "BUY" and exec_price > stop_loss_price:
                risk_per_share = exec_price - stop_loss_price
            elif action == "SHORT" and stop_loss_price > exec_price:
                risk_per_share = stop_loss_price - exec_price
            else:
                risk_per_share = 0

            if risk_per_share > 0:
                target_shares = int(risk_amount / risk_per_share)
                if action == "BUY":
                    max_shares = int(self.capital / (exec_price * (1 + self.fee_rate)))
                else:
                    max_shares = int((self.capital * 0.9) / exec_price)
                return min(target_shares, max_shares)

        elif self.position_sizing == "capital_pct":
            alloc_capital = self.capital * self.risk_pct
            if action == "BUY":
                return int(alloc_capital / (exec_price * (1 + self.fee_rate)))
            else:
                return int(alloc_capital / exec_price)

        # ✅ 兜底預設：固定風險未能計算時，以全部資金計算最大可買量
        if action == "BUY":
            return int(self.capital / (exec_price * (1 + self.fee_rate)))
        else:
            return int((self.capital * 0.9) / exec_price)

    def execute_trade(self, date, action, price, strategy_name="", stop_loss_price=None, qty_fraction=1.0):
        """支援 qty_fraction 進行分批平倉"""
        exec_price = self._apply_slippage(action, price)

        if action == "BUY" and self.position == 0:
            target_qty = self._calculate_position_size("BUY", exec_price, stop_loss_price)
            if target_qty is None or target_qty <= 0: return

            self.position = target_qty
            cost = self.position * exec_price
            self.capital -= (cost + cost * self.fee_rate)
            self.entry_price = exec_price

            self.stop_loss_price = stop_loss_price
            self.highest_price_since_entry = exec_price
            self.scaled_out = False

            self.buy_markers.append((date, exec_price))
            if self.verbose: logger.debug(f"[{date}] 🟢 做多 {self.position} 股 @ {exec_price:.2f}")

        elif action == "SELL" and self.position > 0:
            qty_to_sell = int(self.position * qty_fraction)
            if qty_to_sell <= 0: return

            revenue = qty_to_sell * exec_price
            fee = revenue * self.fee_rate
            tax = revenue * self.tax_rate
            net_revenue = revenue - fee - tax
            self.capital += net_revenue

            # ✅ 修正點 4：損益計算不再對進場成本重複加手續費。
            # 原寫法 cost_basis * (1 + self.fee_rate) 會造成進場費用被計算兩次：
            # 進場時已從 self.capital 扣過一次，此處不應再扣。
            cost_basis = qty_to_sell * self.entry_price
            pnl = net_revenue - cost_basis
            pnl_pct = pnl / cost_basis * 100
            self._record_trade(date, "LONG", strategy_name, exec_price, pnl, pnl_pct)

            self.position -= qty_to_sell
            self.sell_markers.append((date, exec_price))
            if self.verbose:
                logger.debug(f"[{date}] 🔴 平多 {qty_to_sell}股 @ {exec_price:.2f} (獲利: {pnl:.2f}) [{strategy_name}]")

            if self.position == 0:
                self.entry_price = 0.0
                self.stop_loss_price = None

        elif action == "SHORT" and self.position == 0:
            target_qty = self._calculate_position_size("SHORT", exec_price, stop_loss_price)
            if target_qty is None or target_qty <= 0: return

            self.position = -target_qty
            revenue = abs(self.position) * exec_price
            fee = revenue * self.fee_rate
            tax = revenue * self.tax_rate
            self.capital += (revenue - fee - tax)
            self.entry_price = exec_price

            self.stop_loss_price = stop_loss_price
            self.lowest_price_since_entry = exec_price
            self.scaled_out = False

            self.sell_markers.append((date, exec_price))
            if self.verbose: logger.debug(f"[{date}] 🔻 放空 {abs(self.position)} 股 @ {exec_price:.2f}")

        elif action == "COVER" and self.position < 0:
            qty_to_cover = int(abs(self.position) * qty_fraction)
            if qty_to_cover <= 0: return

            cost = qty_to_cover * exec_price
            fee = cost * self.fee_rate
            self.capital -= (cost + fee)

            # ✅ 放空損益：進場時收到的收益（扣費後）減去回補成本
            revenue_at_entry = qty_to_cover * self.entry_price * (1 - self.fee_rate - self.tax_rate)
            cost_at_exit = cost + fee
            pnl = revenue_at_entry - cost_at_exit
            pnl_pct = pnl / (qty_to_cover * self.entry_price) * 100

            self._record_trade(date, "SHORT", strategy_name, exec_price, pnl, pnl_pct)

            self.position += qty_to_cover  # 空單減少負數
            self.buy_markers.append((date, exec_price))
            if self.verbose:
                logger.debug(f"[{date}] 🔺 回補 {qty_to_cover}股 @ {exec_price:.2f} (獲利: {pnl:.2f}) [{strategy_name}]")

            if self.position == 0:
                self.entry_price = 0.0
                self.stop_loss_price = None

    def _record_trade(self, date, trade_type, strategy, exit_price, pnl, pnl_pct):
        self.trades.append({
            "exit_date": date, "type": trade_type, "strategy": strategy,
            "entry_price": self.entry_price, "exit_price": exit_price,
            "pnl": pnl, "pnl_pct": pnl_pct
        })

    def run(self, strategy_func, **kwargs):
        for i in range(len(self.df)):
            date = self.df.index[i]
            current_price = self.df.iloc[i]['Close']

            # ✅ 修正點 1：使用 dt_time 型別做時間比對
            current_time = date.time() if hasattr(date, 'time') else None
            current_equity = self.capital + (self.position * current_price)
            self.equity_curve.append(current_equity)

            # 1. 13:25 強制當沖平倉
            if current_time and current_time >= self.force_close_time:
                if self.position > 0: self.execute_trade(date, "SELL", current_price, "13:25 強制平倉")
                elif self.position < 0: self.execute_trade(date, "COVER", current_price, "13:25 強制回補")
                continue

            # 期末強制平倉
            if i == len(self.df) - 1:
                if self.position > 0: self.execute_trade(date, "SELL", current_price, "期末強制平倉")
                elif self.position < 0: self.execute_trade(date, "COVER", current_price, "期末強制回補")
                break

            # =========================================================
            # 高階防護網：移動停利、分批出場與洗價停損
            # =========================================================
            if self.position > 0:
                self.highest_price_since_entry = max(self.highest_price_since_entry, current_price)
                roi = (current_price - self.entry_price) / self.entry_price

                # A1. 獲利達標，分批出場 (賣出一半)，並把停損上移至成本價保本
                if self.enable_scale_out and not self.scaled_out and roi >= self.scale_out_target_pct:
                    self.execute_trade(date, "SELL", current_price, "第一階段停利 (賣出半倉)", qty_fraction=0.5)
                    self.scaled_out = True
                    self.stop_loss_price = max(self.stop_loss_price or 0, self.entry_price * 1.005)

                # A2. 移動停利 (Trailing Stop)：跟隨最高點回撤
                if self.enable_trailing_stop and roi >= self.trailing_activation_pct:
                    dynamic_stop = self.highest_price_since_entry * (1 - self.trailing_drop_pct)
                    self.stop_loss_price = max(self.stop_loss_price or 0, dynamic_stop)

                # A3. 觸發停損/移動停利線
                if self.stop_loss_price and current_price <= self.stop_loss_price:
                    self.execute_trade(date, "SELL", current_price, f"觸發防守線 ({self.stop_loss_price:.2f})")
                    continue

            elif self.position < 0:
                self.lowest_price_since_entry = min(self.lowest_price_since_entry, current_price)
                roi = (self.entry_price - current_price) / self.entry_price

                if self.enable_scale_out and not self.scaled_out and roi >= self.scale_out_target_pct:
                    self.execute_trade(date, "COVER", current_price, "第一階段停利 (回補半倉)", qty_fraction=0.5)
                    self.scaled_out = True
                    self.stop_loss_price = min(self.stop_loss_price or float('inf'), self.entry_price * 0.995)

                if self.enable_trailing_stop and roi >= self.trailing_activation_pct:
                    dynamic_stop = self.lowest_price_since_entry * (1 + self.trailing_drop_pct)
                    self.stop_loss_price = min(self.stop_loss_price or float('inf'), dynamic_stop)

                if self.stop_loss_price and current_price >= self.stop_loss_price:
                    self.execute_trade(date, "COVER", current_price, f"觸發防守線 ({self.stop_loss_price:.2f})")
                    continue

            # =========================================================
            # 一般策略運算
            # =========================================================
            history_slice = self.df.iloc[:i+1]

            result = strategy_func(history_slice, current_price, self.position, **kwargs)
            if len(result) == 3:
                action, reason, new_stop_loss = result
            else:
                action, reason = result
                new_stop_loss = None

            if action:
                self.execute_trade(date, action, current_price, reason, new_stop_loss)

        return self.get_summary()

    def get_summary(self):
        if not self.trades:
            return {
                "Total_Trades": 0, "Win_Rate": 0, "Total_Return_Pct": 0,
                "Net_Profit": 0, "Profit_Factor": 0, "Max_Drawdown_%": 0, "Sharpe_Ratio": 0
            }

        df_trades = pd.DataFrame(self.trades)
        win_rate = len(df_trades[df_trades['pnl'] > 0]) / len(df_trades) * 100
        final_equity = self.equity_curve[-1]
        total_return = (final_equity - self.initial_capital) / self.initial_capital * 100
        net_profit = final_equity - self.initial_capital

        gross_profit = df_trades[df_trades['pnl'] > 0]['pnl'].sum()
        gross_loss = abs(df_trades[df_trades['pnl'] <= 0]['pnl'].sum())
        profit_factor = (gross_profit / gross_loss) if gross_loss != 0 else float('inf')

        equity_series = pd.Series(self.equity_curve, index=self.df.index)
        roll_max = equity_series.cummax()
        drawdowns = (equity_series - roll_max) / roll_max
        max_drawdown = drawdowns.min() * 100

        try:
            daily_equity = equity_series.resample('D').last().dropna()
            daily_returns = daily_equity.pct_change().dropna()
            if daily_returns.std() != 0:
                sharpe_ratio = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
            else:
                sharpe_ratio = 0
        except Exception:
            sharpe_ratio = 0

        self.drawdowns = drawdowns

        return {
            "Total_Trades": len(df_trades),
            "Win_Rate": round(win_rate, 2),
            "Total_Return_Pct": round(total_return, 2),
            "Net_Profit": round(net_profit, 2),
            "Profit_Factor": round(profit_factor, 2),
            "Max_Drawdown_%": round(max_drawdown, 2),
            "Sharpe_Ratio": round(sharpe_ratio, 2)
        }

    def print_report(self):
        summary = self.get_summary()
        logger.info("=========================================")
        logger.info("📊 真實日內當沖回測報告 (含滑價與稅金)")
        logger.info("=========================================")
        logger.info(f"💰 總報酬率: {summary['Total_Return_Pct']}% (淨利: {summary['Net_Profit']:,.0f})")
        logger.info(f"📈 勝率 (Win Rate): {summary['Win_Rate']}% (總交易: {summary['Total_Trades']} 次)")
        logger.info("--- 🛡️ 進階風險指標 ---")
        logger.info(f"⚖️ 獲利因子 (Profit Factor): {summary['Profit_Factor']} (>1.5為及格)")
        logger.info(f"📉 最大連續虧損 (MDD): {summary['Max_Drawdown_%']}%")
        logger.info(f"🌟 年化夏普值 (Sharpe Ratio): {summary['Sharpe_Ratio']}")
        logger.info("=========================================")

    def plot_results(self, title="Intraday Backtest Results"):
        if not self.verbose: return
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 12), gridspec_kw={'height_ratios': [3, 1, 1]})
        fig.suptitle(title, fontsize=16)

        ax1.plot(self.df.index, self.df['Close'], label='Close Price', color='black', alpha=0.6)
        if self.buy_markers:
            bx, by = zip(*self.buy_markers)
            ax1.scatter(bx, by, marker='^', color='red', s=120, label='BUY / COVER', zorder=5)
        if self.sell_markers:
            sx, sy = zip(*self.sell_markers)
            ax1.scatter(sx, sy, marker='v', color='green', s=120, label='SELL / SHORT', zorder=5)

        ax1.set_ylabel('Price')
        ax1.legend(loc='best')
        ax1.grid(True, alpha=0.3)

        ax2.plot(self.df.index, self.equity_curve, color='blue', label='Equity Curve')
        ax2.set_ylabel('Capital ($)')
        ax2.legend(loc='best')
        ax2.grid(True, alpha=0.3)

        if hasattr(self, 'drawdowns'):
            ax3.plot(self.df.index, self.drawdowns * 100, color='red', label='Drawdown (%)')
            ax3.fill_between(self.df.index, self.drawdowns * 100, 0, color='red', alpha=0.3)
            ax3.set_ylabel('Drawdown (%)')
            ax3.legend(loc='lower right')
            ax3.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.show()


# =================================================================
# 第三部分：批量回測器
# =================================================================
class BatchBacktester:
    def __init__(self, symbols, initial_capital=1000000):
        self.symbols = symbols
        self.initial_capital = initial_capital

    def run_batch(self, strategy_func, period="60d", interval="5m", position_sizing="fixed_risk", **kwargs):
        logger.info(f"🚀 開始執行日內批量回測 ({interval} K線)，共 {len(self.symbols)} 檔標的...")
        results = []
        for sym in self.symbols:
            try:
                df = yf.download(sym, period=period, interval=interval, progress=False)
                if df.empty: continue
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)

                df = TechnicalIndicators.add_all_indicators(df, **kwargs)
                engine = BacktestEngine(
                    df, initial_capital=self.initial_capital,
                    position_sizing=position_sizing, verbose=False
                )
                summary = engine.run(strategy_func, **kwargs)
                results.append({
                    "Symbol": sym,
                    "Total_Return_%": summary["Total_Return_Pct"],
                    "Win_Rate_%": summary["Win_Rate"],
                    "Profit_Factor": summary["Profit_Factor"],
                    "MDD_%": summary["Max_Drawdown_%"],
                    "Trades": summary["Total_Trades"]
                })
            except Exception as e:
                logger.error(f"[{sym}] 回測失敗: {e}")

        if not results:
            logger.warning("❌ 所有標的皆回測失敗或無資料，請檢查網路與參數！")
            return pd.DataFrame()

        results_df = pd.DataFrame(results).sort_values(by="Profit_Factor", ascending=False)
        logger.info("\n🏆 批量回測總結排行榜 (依獲利因子排序)：\n" + results_df.to_string(index=False))
        return results_df


# =================================================================
# 第四部分：策略兵工廠 (含五檔微結構過濾)
# =================================================================
class StrategyFactory:

    @staticmethod
    def _is_book_favorable(action, book_data, ratio_threshold=1.5):
        """
        五檔掛單微結構過濾器 (Order Book Imbalance)
        - backtest_engine 傳入的 book_data 預設為 None (回測直接放行)
        - 實盤 realtime_engine 可傳入真實 Redis 五檔資料進行過濾
        """
        if not book_data: return True  # 回測環境無五檔，直接放行

        bids = sum(b.get('size', 0) for b in book_data.get('bids', []))
        asks = sum(a.get('size', 0) for a in book_data.get('asks', []))

        if asks == 0 and action == "BUY": return True
        if bids == 0 and action == "SHORT": return True

        if action == "BUY" and bids > asks * ratio_threshold: return True
        if action == "SHORT" and asks > bids * ratio_threshold: return True

        return False

    # ---------------- 🟢 做多策略 (Long Strategies) ----------------

    @staticmethod
    def strategy_01_momentum_breakout(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 5: return None, "", None
        curr = df.iloc[-1]
        if position == 0:
            if current_price > curr['BB_Upper'] and curr['Volume'] > curr['Vol_MA_5'] * 1.5:
                if StrategyFactory._is_book_favorable("BUY", book_data):
                    return "BUY", "動能帶量突破(五檔確認)", curr['SMA_10']
        elif position > 0:
            if current_price < curr['SMA_5']: return "SELL", "跌破5MA出場", None
        return None, "", None

    @staticmethod
    def strategy_02_orb_breakout(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 6: return None, "", None
        curr = df.iloc[-1]
        if position == 0:
            if current_price > curr['ORB_High']:
                if StrategyFactory._is_book_favorable("BUY", book_data):
                    return "BUY", "ORB 開盤高點突破", curr['SMA_10']
        elif position > 0:
            if current_price < curr['SMA_10']: return "SELL", "跌破均線出場", None
        return None, "", None

    @staticmethod
    def strategy_03_gap_play(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 5: return None, "", None
        last = df.iloc[-2]
        curr = df.iloc[-1]
        if position == 0:
            if curr['Open'] > last['High'] * 1.01 and curr['Volume'] > last['Volume'] * 1.2:
                return "BUY", "強勢跳空缺口", last['High']
        elif position > 0:
            if current_price < curr['Open'] * 0.99: return "SELL", "缺口回補停損", None
        return None, "", None

    @staticmethod
    def strategy_04_mean_reversion_long(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 20: return None, "", None
        curr = df.iloc[-1]
        if position == 0:
            if curr['RSI'] < 30 and current_price <= curr['BB_Lower']:
                return "BUY", "超賣均值回歸", current_price * 0.98
        elif position > 0:
            if curr['RSI'] > 50 or current_price > curr['BB_Mid']: return "SELL", "回歸中值出場", None
        return None, "", None

    @staticmethod
    def strategy_05_vwap_bounce(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 5: return None, "", None
        last = df.iloc[-2]
        curr = df.iloc[-1]
        if position == 0:
            if last['Close'] < last['VWAP'] and current_price > curr['VWAP']:
                if StrategyFactory._is_book_favorable("BUY", book_data):
                    return "BUY", "強勢站上 VWAP", curr['VWAP'] * 0.995
        elif position > 0:
            if current_price < curr['VWAP'] * 0.995: return "SELL", "跌破 VWAP 停損", None
        return None, "", None

    @staticmethod
    def strategy_06_fast_ma_cross(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 10: return None, "", None
        last = df.iloc[-2]
        curr = df.iloc[-1]
        if position == 0:
            if last['SMA_5'] <= last['SMA_10'] and curr['SMA_5'] > curr['SMA_10']:
                return "BUY", "5MA 金叉 10MA", curr['SMA_10'] * 0.99
        elif position > 0:
            if curr['SMA_5'] < curr['SMA_10']: return "SELL", "均線死叉出場", None
        return None, "", None

    # ---------------- 🔴 做空策略 (Short Strategies) ----------------

    @staticmethod
    def strategy_07_trend_weakness_short(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 10: return None, "", None
        last = df.iloc[-2]
        curr = df.iloc[-1]
        if position == 0:
            if curr['SMA_5'] < curr['SMA_10'] and current_price < curr['VWAP']:
                if StrategyFactory._is_book_favorable("SHORT", book_data):
                    return "SHORT", "空方弱勢做空", curr['VWAP'] * 1.005
        elif position < 0:
            if current_price > curr['SMA_10']: return "COVER", "站上短均線回補", None
        return None, "", None

    @staticmethod
    def strategy_08_rebound_fail_short(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 20: return None, "", None
        curr = df.iloc[-1]
        last_high = df.iloc[-5:-1]['High'].max()
        prev_high = df.iloc[-15:-5]['High'].max()
        if position == 0:
            if last_high < prev_high and current_price < curr['SMA_20']:
                return "SHORT", "反彈不過高(M頭)", prev_high * 1.01
        elif position < 0:
            if current_price > curr['SMA_10']: return "COVER", "站回短均回補", None
        return None, "", None

    @staticmethod
    def strategy_09_mean_reversion_short(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 20: return None, "", None
        curr = df.iloc[-1]
        if position == 0:
            bias = (current_price - curr['SMA_20']) / curr['SMA_20']
            if bias > 0.05 and curr['RSI'] > 75:
                return "SHORT", "正乖離+超買放空", current_price * 1.02
        elif position < 0:
            if curr['RSI'] < 50 or current_price <= curr['SMA_20']: return "COVER", "回歸中值回補", None
        return None, "", None

    @staticmethod
    def strategy_10_rsi_divergence_short(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 20: return None, "", None
        curr = df.iloc[-1]
        if position == 0:
            if current_price >= curr['Rolling_High_20'] and curr['RSI'] < 70:
                return "SHORT", "價格創高但指標背離", current_price * 1.015
        elif position < 0:
            if curr['RSI'] < 40: return "COVER", "動能釋放完畢", None
        return None, "", None

    # ---------------- ⚖️ 多空雙向/複合策略 ----------------

    @staticmethod
    def strategy_11_macd_cross_dual(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 30: return None, "", None
        last = df.iloc[-2]
        curr = df.iloc[-1]
        if position == 0:
            if last['MACD_OSC'] <= 0 and curr['MACD_OSC'] > 0:
                return "BUY", "MACD 金叉做多", current_price * 0.985
            if last['MACD_OSC'] >= 0 and curr['MACD_OSC'] < 0:
                return "SHORT", "MACD 死叉做空", current_price * 1.015
        elif position > 0 and curr['MACD_OSC'] < 0: return "SELL", "MACD轉弱平倉", None
        elif position < 0 and curr['MACD_OSC'] > 0: return "COVER", "MACD轉強回補", None
        return None, "", None

    @staticmethod
    def strategy_12_kd_cross_dual(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 15: return None, "", None
        last = df.iloc[-2]
        curr = df.iloc[-1]
        if position == 0:
            if last['K'] <= last['D'] and curr['K'] > curr['D'] and curr['K'] < 30:
                return "BUY", "KD 低檔金叉", current_price * 0.985
            if last['K'] >= last['D'] and curr['K'] < curr['D'] and curr['K'] > 70:
                return "SHORT", "KD 高檔死叉", current_price * 1.015
        elif position > 0 and curr['K'] < curr['D']: return "SELL", "KD 死叉平多", None
        elif position < 0 and curr['K'] > curr['D']: return "COVER", "KD 金叉平空", None
        return None, "", None

    @staticmethod
    def strategy_13_bollinger_macd_combo(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 30: return None, "", None
        curr = df.iloc[-1]
        if position == 0:
            if current_price > curr['BB_Upper'] and curr['MACD_OSC'] > 0:
                if StrategyFactory._is_book_favorable("BUY", book_data):
                    return "BUY", "布林突破+MACD確認", curr['BB_Mid']
            if current_price < curr['BB_Lower'] and curr['MACD_OSC'] < 0:
                if StrategyFactory._is_book_favorable("SHORT", book_data):
                    return "SHORT", "跌破布林+MACD確認", curr['BB_Mid']
        elif position > 0 and (current_price < curr['BB_Mid'] or curr['MACD_OSC'] < 0):
            return "SELL", "均值回歸平多", None
        elif position < 0 and (current_price > curr['BB_Mid'] or curr['MACD_OSC'] > 0):
            return "COVER", "均值回歸平空", None
        return None, "", None

    @staticmethod
    def strategy_14_rolling_breakout_dual(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 25: return None, "", None
        curr = df.iloc[-1]
        last_high = df.iloc[-21:-1]['High'].max()
        last_low = df.iloc[-21:-1]['Low'].min()
        if position == 0:
            if current_price > last_high: return "BUY", "創 20 日新高做多", curr['SMA_20']
            if current_price < last_low: return "SHORT", "創 20 日新低做空", curr['SMA_20']
        elif position > 0 and current_price < curr['SMA_20']: return "SELL", "跌破 20MA 出場", None
        elif position < 0 and current_price > curr['SMA_20']: return "COVER", "突破 20MA 回補", None
        return None, "", None

    @staticmethod
    def strategy_15_rsi_contrarian_dual(df, current_price, position, book_data=None, **kwargs):
        if len(df) < 15: return None, "", None
        last = df.iloc[-2]
        curr = df.iloc[-1]
        if position == 0:
            if last['RSI'] < 30 and curr['RSI'] >= 30:
                return "BUY", "RSI 見底反轉", current_price * 0.98
            if last['RSI'] > 70 and curr['RSI'] <= 70:
                return "SHORT", "RSI 見頂反轉", current_price * 1.02
        elif position > 0 and curr['RSI'] > 60: return "SELL", "動能滿足平多", None
        elif position < 0 and curr['RSI'] < 40: return "COVER", "動能滿足平空", None
        return None, "", None


if __name__ == "__main__":
    pass