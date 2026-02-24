"""
交易日誌管理器
功能：記錄系統運作、交易信號、選股結果、績效分析等重要資訊
"""

import logging
import logging.handlers
import os
import json
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import csv
import sys

class TradingLogManager:
    """交易日誌管理器"""
    
    def __init__(self, log_dir: str = "logs", max_days: int = 30):
        """
        初始化日誌管理器
        
        Args:
            log_dir: 日誌檔案目錄
            max_days: 保留天數
        """
        self.log_dir = log_dir
        self.max_days = max_days
        
        # 確保日誌目錄存在
        os.makedirs(log_dir, exist_ok=True)
        os.makedirs(os.path.join(log_dir, "daily"), exist_ok=True)
        os.makedirs(os.path.join(log_dir, "signals"), exist_ok=True)
        os.makedirs(os.path.join(log_dir, "trades"), exist_ok=True)
        os.makedirs(os.path.join(log_dir, "screening"), exist_ok=True)
        os.makedirs(os.path.join(log_dir, "performance"), exist_ok=True)
        
        # 初始化logging
        self._setup_logging()
        
        # 當前交易日
        self.trading_date = datetime.now().strftime("%Y%m%d")
        
        # 初始化日誌檔案
        self._init_daily_log()
        
        # 清理舊日誌
        self._cleanup_old_logs()
    
    def _setup_logging(self):
        """設定logging配置"""
        # 創建logger
        self.logger = logging.getLogger("TradingSystem")
        self.logger.setLevel(logging.INFO)
        
        # 避免重複添加handler
        if not self.logger.handlers:
            # 控制台輸出
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_format = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            console_handler.setFormatter(console_format)
            self.logger.addHandler(console_handler)
            
            # 檔案輸出（每日輪替）
            log_file = os.path.join(self.log_dir, "trading_system.log")
            file_handler = logging.handlers.TimedRotatingFileHandler(
                log_file, when='midnight', interval=1, backupCount=self.max_days
            )
            file_handler.setLevel(logging.INFO)
            file_format = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_format)
            self.logger.addHandler(file_handler)
    
    def _init_daily_log(self):
        """初始化每日日誌"""
        daily_log_file = os.path.join(
            self.log_dir, "daily", f"daily_log_{self.trading_date}.json"
        )
        
        if not os.path.exists(daily_log_file):
            daily_log = {
                "trading_date": self.trading_date,
                "system_start_time": datetime.now().isoformat(),
                "market_condition": "unknown",
                "trading_mode": "simulation",
                "total_capital": 0,
                "watchlist": [],
                "strategies_enabled": [],
                "risk_parameters": {},
                "daily_summary": {
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "total_pnl": 0,
                    "max_profit": 0,
                    "max_loss": 0,
                    "largest_winner": None,
                    "largest_loser": None
                }
            }
            self._save_json(daily_log_file, daily_log)
    
    def _cleanup_old_logs(self):
        """清理超過保留天數的日誌"""
        cutoff_date = datetime.now() - timedelta(days=self.max_days)
        cutoff_str = cutoff_date.strftime("%Y%m%d")
        
        for subdir in ["daily", "signals", "trades", "screening", "performance"]:
            subdir_path = os.path.join(self.log_dir, subdir)
            if os.path.exists(subdir_path):
                for filename in os.listdir(subdir_path):
                    file_path = os.path.join(subdir_path, filename)
                    # 從檔名提取日期（假設格式為 prefix_YYYYMMDD.suffix）
                    try:
                        if subdir == "daily":
                            date_str = filename.split("_")[-1].split(".")[0]
                        elif subdir in ["signals", "trades"]:
                            date_str = filename.split("_")[0]
                        elif subdir == "screening":
                            date_str = filename.split("_")[-2]
                        else:
                            date_str = filename.split("_")[-1].split(".")[0]
                        
                        if date_str < cutoff_str:
                            os.remove(file_path)
                            self.logger.info(f"刪除舊日誌: {filename}")
                    except:
                        pass
    
    def _save_json(self, filepath: str, data: Dict):
        """儲存JSON檔案"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    
    def _save_csv(self, filepath: str, data: List[Dict], fieldnames: List[str] = None):
        """儲存CSV檔案"""
        if not data:
            return
        
        if fieldnames is None:
            fieldnames = data[0].keys()
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
    
    # ==================== 公開方法 ====================
    
    def log_system_start(self, config: Dict):
        """記錄系統啟動"""
        self.logger.info(f"系統啟動 - 交易日期: {self.trading_date}")
        self.logger.info(f"交易模式: {config.get('trading_mode', 'simulation')}")
        self.logger.info(f"總資金: {config.get('total_capital', 0)}")
        self.logger.info(f"啟用策略: {config.get('enabled_strategies', [])}")
        
        # 更新每日日誌
        daily_log_file = os.path.join(
            self.log_dir, "daily", f"daily_log_{self.trading_date}.json"
        )
        daily_log = self._load_json(daily_log_file)
        daily_log.update({
            "system_start_time": datetime.now().isoformat(),
            "trading_mode": config.get('trading_mode', 'simulation'),
            "total_capital": config.get('total_capital', 0),
            "strategies_enabled": config.get('enabled_strategies', []),
            "risk_parameters": config.get('risk_parameters', {})
        })
        self._save_json(daily_log_file, daily_log)
    
    def log_system_stop(self, reason: str = "正常關閉"):
        """記錄系統關閉"""
        self.logger.info(f"系統關閉 - 原因: {reason}")
        
        daily_log_file = os.path.join(
            self.log_dir, "daily", f"daily_log_{self.trading_date}.json"
        )
        daily_log = self._load_json(daily_log_file)
        daily_log.update({
            "system_stop_time": datetime.now().isoformat(),
            "shutdown_reason": reason
        })
        self._save_json(daily_log_file, daily_log)
    
    def log_watchlist_update(self, watchlist: List[str], source: str):
        """記錄監控清單更新"""
        self.logger.info(f"監控清單更新 - 來源: {source}, 數量: {len(watchlist)}")
        
        daily_log_file = os.path.join(
            self.log_dir, "daily", f"daily_log_{self.trading_date}.json"
        )
        daily_log = self._load_json(daily_log_file)
        daily_log["watchlist"] = watchlist
        daily_log["watchlist_source"] = source
        daily_log["watchlist_update_time"] = datetime.now().isoformat()
        self._save_json(daily_log_file, daily_log)
    
    def log_screening_result(self, strategy: str, candidates: List[Dict], params: Dict):
        """記錄選股結果"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screening_file = os.path.join(
            self.log_dir, "screening", f"screening_{strategy}_{timestamp}.json"
        )
        
        screening_data = {
            "screening_time": datetime.now().isoformat(),
            "strategy": strategy,
            "parameters": params,
            "candidates_count": len(candidates),
            "candidates": candidates
        }
        
        self._save_json(screening_file, screening_data)
        self.logger.info(f"選股記錄 - 策略: {strategy}, 候選股數: {len(candidates)}")
    
    def log_signal_generated(self, symbol: str, signal: Dict):
        """記錄信號產生"""
        signal_file = os.path.join(
            self.log_dir, "signals", f"{self.trading_date}_signals.csv"
        )
        
        signal_data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": symbol,
            "action": signal.get('action', ''),
            "strategy": signal.get('strategy', ''),
            "confidence": signal.get('confidence', 0),
            "price": signal.get('price', 0),
            "reason": signal.get('reason', ''),
            "stop_loss": signal.get('stop_loss', 0),
            "take_profit": signal.get('take_profit', 0)
        }
        
        # 讀取現有信號記錄或建立新檔案
        signals = []
        if os.path.exists(signal_file):
            try:
                df = pd.read_csv(signal_file)
                signals = df.to_dict('records')
            except:
                pass
        
        signals.append(signal_data)
        self._save_csv(signal_file, signals)
        
        self.logger.info(f"信號產生 - {symbol} {signal.get('action')} @ {signal.get('price')}")
    
    def log_trade_executed(self, trade: Dict):
        """記錄交易執行"""
        trade_file = os.path.join(
            self.log_dir, "trades", f"{self.trading_date}_trades.csv"
        )
        
        trade_data = {
            "execution_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "symbol": trade.get('symbol', ''),
            "action": trade.get('action', ''),
            "quantity": trade.get('quantity', 0),
            "price": trade.get('price', 0),
            "order_type": trade.get('order_type', 'LIMIT'),
            "strategy": trade.get('strategy', ''),
            "reason": trade.get('reason', ''),
            "commission": trade.get('commission', 0),
            "tax": trade.get('tax', 0),
            "net_pnl": trade.get('pnl', 0),
            "trade_mode": trade.get('mode', 'simulation')
        }
        
        # 讀取現有交易記錄或建立新檔案
        trades = []
        if os.path.exists(trade_file):
            try:
                df = pd.read_csv(trade_file)
                trades = df.to_dict('records')
            except:
                pass
        
        trades.append(trade_data)
        self._save_csv(trade_file, trades)
        
        # 更新每日摘要
        self._update_daily_summary(trade_data)
        
        self.logger.info(f"交易執行 - {trade.get('symbol')} {trade.get('action')} {trade.get('quantity')}股 @ {trade.get('price')}")
    
    def log_position_update(self, positions: List[Dict]):
        """記錄持倉更新"""
        position_file = os.path.join(
            self.log_dir, "daily", f"positions_{self.trading_date}.json"
        )
        
        position_data = {
            "update_time": datetime.now().isoformat(),
            "total_positions": len(positions),
            "total_value": sum(p.get('market_value', 0) for p in positions),
            "total_unrealized_pnl": sum(p.get('unrealized_pnl', 0) for p in positions),
            "positions": positions
        }
        
        self._save_json(position_file, position_data)
        self.logger.info(f"持倉更新 - 總持倉數: {len(positions)}, 總市值: {position_data['total_value']}")
    
    def log_performance_metrics(self, metrics: Dict):
        """記錄績效指標"""
        perf_file = os.path.join(
            self.log_dir, "performance", f"performance_{self.trading_date}.json"
        )
        
        perf_data = {
            "calculation_time": datetime.now().isoformat(),
            **metrics
        }
        
        self._save_json(perf_file, perf_data)
        self.logger.info(f"績效記錄 - 總損益: {metrics.get('total_pnl', 0)}")
    
    def log_error(self, error_type: str, error_msg: str, details: Dict = None):
        """記錄錯誤"""
        error_log = {
            "timestamp": datetime.now().isoformat(),
            "error_type": error_type,
            "error_message": error_msg,
            "details": details or {}
        }
        
        error_file = os.path.join(
            self.log_dir, "daily", f"errors_{self.trading_date}.json"
        )
        
        errors = []
        if os.path.exists(error_file):
            try:
                with open(error_file, 'r', encoding='utf-8') as f:
                    errors = json.load(f)
            except:
                pass
        
        errors.append(error_log)
        self._save_json(error_file, errors)
        
        self.logger.error(f"錯誤記錄 - {error_type}: {error_msg}")
    
    def log_market_condition(self, condition: Dict):
        """記錄市場狀況"""
        market_file = os.path.join(
            self.log_dir, "daily", f"market_{self.trading_date}.json"
        )
        
        market_data = {
            "update_time": datetime.now().isoformat(),
            **condition
        }
        
        self._save_json(market_file, market_data)
        
        daily_log_file = os.path.join(
            self.log_dir, "daily", f"daily_log_{self.trading_date}.json"
        )
        daily_log = self._load_json(daily_log_file)
        daily_log["market_condition"] = condition.get('condition', 'unknown')
        self._save_json(daily_log_file, daily_log)
        
        self.logger.info(f"市場狀況更新 - {condition.get('condition', 'unknown')}")
    
    # ==================== 輔助方法 ====================
    
    def _load_json(self, filepath: str) -> Dict:
        """載入JSON檔案"""
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _update_daily_summary(self, trade: Dict):
        """更新每日摘要"""
        daily_log_file = os.path.join(
            self.log_dir, "daily", f"daily_log_{self.trading_date}.json"
        )
        daily_log = self._load_json(daily_log_file)
        
        summary = daily_log.get("daily_summary", {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "total_pnl": 0,
            "max_profit": 0,
            "max_loss": 0,
            "largest_winner": None,
            "largest_loser": None
        })
        
        summary["total_trades"] += 1
        pnl = trade.get("net_pnl", 0)
        summary["total_pnl"] += pnl
        
        if pnl > 0:
            summary["winning_trades"] += 1
            if pnl > summary["max_profit"]:
                summary["max_profit"] = pnl
                summary["largest_winner"] = {
                    "symbol": trade.get("symbol"),
                    "pnl": pnl,
                    "time": trade.get("execution_time")
                }
        elif pnl < 0:
            summary["losing_trades"] += 1
            if pnl < summary["max_loss"]:
                summary["max_loss"] = pnl
                summary["largest_loser"] = {
                    "symbol": trade.get("symbol"),
                    "pnl": pnl,
                    "time": trade.get("execution_time")
                }
        
        daily_log["daily_summary"] = summary
        self._save_json(daily_log_file, daily_log)
    
    def get_daily_summary(self) -> Dict:
        """取得當日摘要"""
        daily_log_file = os.path.join(
            self.log_dir, "daily", f"daily_log_{self.trading_date}.json"
        )
        daily_log = self._load_json(daily_log_file)
        return daily_log.get("daily_summary", {})
    
    def get_todays_signals(self) -> pd.DataFrame:
        """取得今日所有信號"""
        signal_file = os.path.join(
            self.log_dir, "signals", f"{self.trading_date}_signals.csv"
        )
        if os.path.exists(signal_file):
            return pd.read_csv(signal_file)
        return pd.DataFrame()
    
    def get_todays_trades(self) -> pd.DataFrame:
        """取得今日所有交易"""
        trade_file = os.path.join(
            self.log_dir, "trades", f"{self.trading_date}_trades.csv"
        )
        if os.path.exists(trade_file):
            return pd.read_csv(trade_file)
        return pd.DataFrame()
    
    def export_daily_report(self) -> Dict:
        """匯出每日報告"""
        report = {
            "trading_date": self.trading_date,
            "summary": self.get_daily_summary(),
            "signals_count": 0,
            "trades_count": 0,
            "final_positions": [],
            "performance_metrics": {}
        }
        
        # 信號統計
        signals_df = self.get_todays_signals()
        if not signals_df.empty:
            report["signals_count"] = len(signals_df)
            report["signals_by_action"] = signals_df['action'].value_counts().to_dict()
            report["signals_by_strategy"] = signals_df['strategy'].value_counts().to_dict()
        
        # 交易統計
        trades_df = self.get_todays_trades()
        if not trades_df.empty:
            report["trades_count"] = len(trades_df)
            report["trades_by_action"] = trades_df['action'].value_counts().to_dict()
            report["trades_by_strategy"] = trades_df['strategy'].value_counts().to_dict()
        
        # 績效指標
        perf_file = os.path.join(
            self.log_dir, "performance", f"performance_{self.trading_date}.json"
        )
        if os.path.exists(perf_file):
            with open(perf_file, 'r', encoding='utf-8') as f:
                report["performance_metrics"] = json.load(f)
        
        return report

# 單例模式
_log_manager_instance = None

def get_log_manager(log_dir: str = "logs") -> TradingLogManager:
    """取得日誌管理器實例（單例模式）"""
    global _log_manager_instance
    if _log_manager_instance is None:
        _log_manager_instance = TradingLogManager(log_dir)
    return _log_manager_instance

def log_system_start(config: Dict):
    """記錄系統啟動（便利函數）"""
    log_manager = get_log_manager()
    log_manager.log_system_start(config)

def log_signal(symbol: str, signal: Dict):
    """記錄信號（便利函數）"""
    log_manager = get_log_manager()
    log_manager.log_signal_generated(symbol, signal)

def log_trade(trade: Dict):
    """記錄交易（便利函數）"""
    log_manager = get_log_manager()
    log_manager.log_trade_executed(trade)

def log_error(error_type: str, error_msg: str, details: Dict = None):
    """記錄錯誤（便利函數）"""
    log_manager = get_log_manager()
    log_manager.log_error(error_type, error_msg, details)