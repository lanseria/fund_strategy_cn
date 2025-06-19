# ----------------------------------------------------------------------------------
# 实战项目: 锚定低点回归策略
# ----------------------------------------------------------------------------------

import backtrader as bt
import akshare as ak
import pandas as pd
import quantstats as qs
import numpy as np

# ==================================================================================
# 第1步：参数配置
# ==================================================================================
# --- 基础配置 ---
FUND_SYMBOL = '007301'          # 基金代码
BENCHMARK_SYMBOL = 'sh000300'   # 基准指数代码
START_DATE = '20200812'         # 回测开始日期
END_DATE = '20250127'           # 回测结束日期
INITIAL_CASH = 100000.0         # 初始资金
COMMISSION_RATE = 0.0015        # 手续费率

# --- 策略参数 ---
INITIAL_PROFIT_TARGET = 0.15      # 初始阶段止盈目标 (15%)
CYCLE_PROFIT_TARGET = 0.10        # 循环阶段止盈目标 (10%)
CYCLE_STOP_LOSS = 0.05            # 循环阶段止损目标 (5%)
REBUY_TRIGGER_FROM_LOW = 0.03     # 从历史低点反弹多少后触发买入 (3%)

# ==================================================================================
# 第2步：数据获取与整合 (代码与之前版本相同)
# ==================================================================================
def get_fund_and_benchmark_data(fund_symbol, benchmark_symbol, start, end):
    # ... (此函数代码与之前完全相同，此处省略以保持简洁) ...
    print("开始下载基金和基准数据...")
    try:
        fund_nav_df = ak.fund_open_fund_info_em(symbol=fund_symbol, indicator="单位净值走势")
        fund_nav_df['净值日期'] = pd.to_datetime(fund_nav_df['净值日期'])
        fund_nav_df = fund_nav_df.set_index('净值日期')
        fund_nav_df = fund_nav_df[['单位净值']]
        fund_nav_df.columns = ['close']
        fund_nav_df['close'] = pd.to_numeric(fund_nav_df['close'])
    except Exception as e:
        print(f"获取基金 {fund_symbol} 数据失败: {e}")
        return None, None
    try:
        benchmark_df = ak.stock_zh_index_daily(symbol=benchmark_symbol)
        benchmark_df['date'] = pd.to_datetime(benchmark_df['date'])
        benchmark_df = benchmark_df.set_index('date')
        benchmark_df = benchmark_df[['close']]
    except Exception as e:
        print(f"获取基准 {benchmark_symbol} 数据失败: {e}")
        return None, None
    
    data = fund_nav_df.copy().sort_index()
    data['open'] = data['high'] = data['low'] = data['close']
    data['volume'] = 1000
    data['openinterest'] = 0
    data = data[start:end]
    benchmark_df = benchmark_df[start:end]
    print("数据下载和整合完成。")
    return data, benchmark_df['close']
# ==================================================================================
# 第3步：策略定义 - 锚定低点回归策略
# ==================================================================================
class AnchorLowStrategy(bt.Strategy):
    params = (
        ('initial_profit', INITIAL_PROFIT_TARGET),
        ('cycle_profit', CYCLE_PROFIT_TARGET),
        ('cycle_loss', CYCLE_STOP_LOSS),
        ('rebuy_trigger', REBUY_TRIGGER_FROM_LOW),
    )

    def __init__(self):
        self.order = None
        # 核心状态变量
        self.strategy_phase = 1  # 1: 初始阶段, 2: 循环阶段
        self.historical_low = float('inf') # 初始化历史最低价为无穷大

    def notify_order(self, order):
        # ... (此函数代码与之前相同，此处省略以保持简洁) ...
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Completed]:
            # 只有卖出成交才可能改变策略阶段
            if order.issell():
                if self.strategy_phase == 1:
                    print(f"*** 初始阶段完成，策略进入循环阶段！ ***")
                    self.strategy_phase = 2
            # 打印日志
            if order.isbuy():
                print(f"\n--- 交易执行: 买入 (BUY) ---\n"
                      f"日期: {self.data.datetime.date(0)}, 价格: {order.executed.price:.4f}")
            elif order.issell():
                print(f"\n--- 交易执行: 卖出 (SELL) ---\n"
                      f"日期: {self.data.datetime.date(0)}, 价格: {order.executed.price:.4f}")
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            print(f"xx 订单失败/取消: {order.getstatusname()} xx")
            self.order = None

    def next(self):
        if self.order:
            return

        current_price = self.data.close[0]
        # 实时更新历史最低价
        if current_price < self.historical_low:
            self.historical_low = current_price

        # --- 阶段一：初始建仓和15%止盈 ---
        if self.strategy_phase == 1:
            if not self.position:
                print(f"\n{self.data.datetime.date()}: 策略启动，执行初始全仓买入。")
                self.order = self.buy()
            else:
                buy_price = self.position.price
                profit_target_price = buy_price * (1 + self.p.initial_profit)
                if current_price >= profit_target_price:
                    print(f"\n{self.data.datetime.date()}: 价格达到初始止盈点(>{profit_target_price:.4f})，准备卖出。")
                    self.order = self.close()
        
        # --- 阶段二：锚定低点，循环交易 ---
        elif self.strategy_phase == 2:
            if not self.position:
                # 判断买入条件
                rebuy_trigger_price = self.historical_low * (1 + self.p.rebuy_trigger)
                if current_price <= rebuy_trigger_price:
                    print(f"\n{self.data.datetime.date()}: 价格({current_price:.4f})接近历史低点({self.historical_low:.4f})，触发买入。")
                    self.order = self.buy()
            else:
                # 判断卖出条件
                buy_price = self.position.price
                profit_target_price = buy_price * (1 + self.p.cycle_profit)
                stop_loss_price = buy_price * (1 - self.p.cycle_loss)
                
                if current_price >= profit_target_price:
                    print(f"\n{self.data.datetime.date()}: 价格达到循环止盈点(>{profit_target_price:.4f})，准备卖出。")
                    self.order = self.close()
                elif current_price <= stop_loss_price:
                    print(f"\n{self.data.datetime.date()}: 价格达到循环止损点(<{stop_loss_price:.4f})，准备卖出。")
                    self.order = self.close()

    def stop(self):
        # ... (此函数代码与之前相同，此处省略以保持简洁) ...
        print("\n回测结束，正在生成绩效报告...")
        global benchmark_data
        time_return_analyzer = self.analyzers.getbyname('time_return')
        returns_dict = time_return_analyzer.get_analysis()
        returns = pd.Series(returns_dict)
        if returns.index.tz is not None:
            returns.index = returns.index.tz_localize(None)
        benchmark_rets = benchmark_data.pct_change().dropna()
        report_filename = f'strategy_report_{FUND_SYMBOL}_anchor_low.html'
        try:
            qs.reports.html(returns, benchmark=benchmark_rets, output=report_filename, 
                            title=f'{FUND_SYMBOL} - 锚定低点回归策略 vs. 基准指数')
            print(f"绩效报告已成功生成：{report_filename}")
        except Exception as e:
            print(f"生成 quantstats 报告时出错: {e}")

# ==================================================================================
# 第4步：回测引擎
# ==================================================================================
if __name__ == '__main__':
    fund_data, benchmark_data = get_fund_and_benchmark_data(FUND_SYMBOL, BENCHMARK_SYMBOL, START_DATE, END_DATE)

    if fund_data is not None and not fund_data.empty:
        cerebro = bt.Cerebro()
        data_feed = bt.feeds.PandasData(dataname=fund_data, name=FUND_SYMBOL)
        cerebro.adddata(data_feed)
        cerebro.addstrategy(AnchorLowStrategy)
        cerebro.broker.setcash(INITIAL_CASH)
        cerebro.broker.setcommission(commission=COMMISSION_RATE)
        cerebro.addsizer(bt.sizers.PercentSizer, percents=98)
        cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='time_return')
        
        print("\n开始执行回测...")
        results = cerebro.run()
        
        final_value = cerebro.broker.getvalue()
        print("\n--- 回测完成 ---")
        print(f"初始资产: {INITIAL_CASH:,.2f}")
        print(f"最终资产: {final_value:,.2f}")
        print("详细的绩效分析请打开生成的HTML报告文件查看。")
    else:
        print("未能获取到数据，回测中止。")