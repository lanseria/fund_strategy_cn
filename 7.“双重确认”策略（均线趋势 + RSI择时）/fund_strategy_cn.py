# ----------------------------------------------------------------------------------
# 实战项目: “双重确认”策略 (均线趋势 + RSI择时)
# ----------------------------------------------------------------------------------

import backtrader as bt
import akshare as ak
import pandas as pd
import quantstats as qs

# ==================================================================================
# 第1步：参数配置
# ==================================================================================
# --- 基础配置 ---
FUND_SYMBOL = '003096'          # 基金代码
BENCHMARK_SYMBOL = 'sh000300'   # 基准指数代码
START_DATE = '20200812'         # 回测开始日期
END_DATE = '20250127'           # 回测结束日期
INITIAL_CASH = 100000.0         # 初始资金
COMMISSION_RATE = 0.0015        # 手续费率

# --- “双重确认”策略参数 ---
TREND_MA_PERIOD = 120             # 判断长期趋势的均线周期 (半年线)
RSI_PERIOD = 14                   # RSI的计算周期
RSI_LOWER = 30.0                  # RSI超卖阈值 (买入触发点)

# ==================================================================================
# 第2步：数据获取与整合 (代码与之前版本相同)
# ==================================================================================
def get_fund_and_benchmark_data(fund_symbol, benchmark_symbol, start, end):
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
# 第3步：策略定义 - “双重确认”策略
# ==================================================================================
class DualConfirmationStrategy(bt.Strategy):
    params = (
        ('trend_period', TREND_MA_PERIOD),
        ('rsi_period', RSI_PERIOD),
        ('rsi_lower', RSI_LOWER),
    )

    def __init__(self):
        # 第一重确认：长期趋势均线
        self.trend_ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.trend_period)
        
        # 第二重确认：RSI择时指标
        self.rsi = bt.indicators.RelativeStrengthIndex(period=self.p.rsi_period)
        
        # 订单跟踪
        self.order = None

    def notify_order(self, order):
        # (这部分代码与之前相同，用于打印交易日志)
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Completed]:
            if order.isbuy():
                print(
                    f"\n--- 交易执行 ---\n"
                    f"日期: {self.data.datetime.date(0)}\n"
                    f"操作: 牛市回调，买入 (BUY)\n"
                    f"成交份额: {order.executed.size:.2f}, 价格: {order.executed.price:.4f}\n"
                    f"交易金额: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}\n"
                    f"-----------------"
                )
            elif order.issell():
                print(
                    f"\n--- 交易执行 ---\n"
                    f"日期: {self.data.datetime.date(0)}\n"
                    f"操作: 跌破长期均线，卖出 (SELL)\n"
                    f"成交份额: {order.executed.size:.2f}, 价格: {order.executed.price:.4f}\n"
                    f"交易金额: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}\n"
                    f"-----------------"
                )
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            print(f"xx 订单失败/取消: {order.getstatusname()} xx")
            self.order = None

    def next(self):
        # 如果有订单正在处理，则等待
        if self.order:
            return

        # 如果当前没有持仓
        if not self.position:
            # “双重确认”买入逻辑
            is_in_uptrend = self.data.close[0] > self.trend_ma[0]
            is_oversold = self.rsi[0] <= self.p.rsi_lower
            
            if is_in_uptrend and is_oversold:
                print(f"\n{self.data.datetime.date()}: 确认牛市，且RSI回调至({self.rsi[0]:.2f})，准备买入。")
                self.order = self.buy()
        # 如果当前持有仓位
        else:
            # 卖出逻辑：跌破长期趋势线
            if self.data.close[0] <= self.trend_ma[0]:
                print(f"\n{self.data.datetime.date()}: 价格跌破长期均线({self.trend_ma[0]:.2f})，趋势反转，准备卖出。")
                self.order = self.close()

    def stop(self):
        # (这部分代码与之前相同，用于生成报告)
        print("\n回测结束，正在生成绩效报告...")
        global benchmark_data
        time_return_analyzer = self.analyzers.getbyname('time_return')
        returns_dict = time_return_analyzer.get_analysis()
        returns = pd.Series(returns_dict)
        if returns.index.tz is not None:
            returns.index = returns.index.tz_localize(None)
        benchmark_rets = benchmark_data.pct_change().dropna()
        report_filename = f'strategy_report_{FUND_SYMBOL}_dual_confirm.html'
        try:
            qs.reports.html(returns, benchmark=benchmark_rets, output=report_filename, 
                            title=f'{FUND_SYMBOL} - 双重确认策略 vs. 基准指数')
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
        
        # 添加“双重确认”策略
        cerebro.addstrategy(DualConfirmationStrategy)
        
        cerebro.broker.setcash(INITIAL_CASH)
        cerebro.broker.setcommission(commission=COMMISSION_RATE)
        
        # 使用 Sizer 来管理仓位，每次买入都用掉98%的现金
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