# 檔案名稱: strategy_optimizer.py
import pandas as pd
import yfinance as yf
import itertools
import logging
from backtest_engine import TechnicalIndicators, BacktestEngine, StrategyFactory

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class StrategyOptimizer:
    """
    黃金參數煉丹爐：透過暴力網格搜尋找出勝率與獲利因子最高的指標參數組合
    """
    def __init__(self, symbol="2330.TW", period="60d", interval="5m"):
        self.symbol = symbol
        self.period = period
        self.interval = interval
        self.raw_data = self._download_data()

    def _download_data(self):
        logger.info(f"📥 正在下載 {self.symbol} ({self.interval}) 歷史資料供煉丹使用...")
        df = yf.download(self.symbol, period=self.period, interval=self.interval, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        return df

    def optimize_bollinger_macd(self):
        """
        針對「布林+MACD雙重確認策略 (strategy_13)」進行參數最佳化
        尋找最佳的 BB_period, BB_std, MACD_fast, MACD_slow 組合
        """
        if self.raw_data.empty: return

        logger.info("🔥 啟動八卦爐... 開始窮舉【布林+MACD】策略參數...")
        
        # 定義要測試的參數網格 (Grid)
        param_grid = {
            'bb_period': [15, 20, 25],
            'bb_std': [1.8, 2.0, 2.2],
            'macd_fast': [10, 12],
            'macd_slow': [24, 26],
            'macd_signal': [9]
        }

        # 展開所有排列組合
        keys = list(param_grid.keys())
        combinations = list(itertools.product(*[param_grid[k] for k in keys]))
        
        results = []
        total_runs = len(combinations)
        
        for idx, combo in enumerate(combinations):
            params = dict(zip(keys, combo))
            
            # 1. 根據這組參數重新計算技術指標
            df_test = TechnicalIndicators.add_all_indicators(self.raw_data.copy(), **params)
            
            # 2. 跑回測 (關閉 verbose 避免洗版)
            engine = BacktestEngine(df_test, initial_capital=1000000, verbose=False)
            summary = engine.run(StrategyFactory.strategy_13_bollinger_macd_combo)
            
            # 3. 記錄結果
            results.append({
                "參數組合": str(params),
                "總交易次數": summary["Total_Trades"],
                "勝率(%)": summary["Win_Rate"],
                "總淨利(NT$)": summary["Net_Profit"],
                "獲利因子": summary["Profit_Factor"],
                "夏普值": summary["Sharpe_Ratio"]
            })
            
            if (idx + 1) % 10 == 0:
                logger.info(f"⏳ 煉丹進度: {idx+1} / {total_runs} ...")

        # 整理成 DataFrame 並依照「獲利因子」排序
        df_results = pd.DataFrame(results)
        # 過濾掉交易次數太少 (缺乏統計意義) 的組合
        df_results = df_results[df_results["總交易次數"] >= 5]
        best_results = df_results.sort_values(by="獲利因子", ascending=False).head(5)

        logger.info(f"\n🏆 【{self.symbol}】布林+MACD 煉丹結果出爐 (Top 5)：\n" + best_results.to_string(index=False))
        return best_results

if __name__ == "__main__":
    # 週末您可以將 2330 改成您想做的股票，放著讓它跑幾分鐘
    optimizer = StrategyOptimizer(symbol="2603.TW", period="60d", interval="5m")
    
    # 執行布林MACD策略的參數尋優
    optimizer.optimize_bollinger_macd()