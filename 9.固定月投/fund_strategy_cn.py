# ----------------------------------------------------------------------------------
# 实战项目: 纯固定定投策略 (无脑定投)
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
INITIAL_CASH = 200000.0         # 初始资金 (定投策略需要较多现金)
COMMISSION_RATE = 0.0015        # 手续费率

# --- 纯固定定投策略参数 ---
INVESTMENT_DAY = 1                # 每月定投日 (例如: 1号)
FIXED_INVESTMENT_AMOUNT = 2000.0  # 每月固定投资金额

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
# 第3步：策略定义 - 纯固定定投策略
# ==================================================================================
class FixedAutoInvestStrategy(bt.Strategy):
    params = (
        ('investment_day', INVESTMENT_DAY),
        ('investment_amount', FIXED_INVESTMENT_AMOUNT),
    )

    def __init__(self):
        self.order = None
        # 记录上一个定投的月份，防止一个月内重复投资
        self.last_investment_month = -1

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Completed]:
            if order.isbuy():
                print(
                    f"\n--- 交易执行 ---\n"
                    f"日期: {self.data.datetime.date(0)}\n"
                    f"操作: 固定定投买入 (BUY)\n"
                    f"成交份额: {order.executed.size:.2f}, 价格: {order.executed.price:.4f}\n"
                    f"交易金额: {order.executed.value:.2f}, 手续费: {order.executed.comm:.2f}\n"
                    f"-----------------"
                )
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            print(f"xx 订单失败/取消: {order.getstatusname()} xx")
            self.order = None

    def next(self):
        if self.order:
            return

        # 核心逻辑：只在每月固定日期无条件买入
        current_date = self.data.datetime.date()
        current_month = current_date.month
        
        # 判断是否是新的月份的定投时点
        if current_month != self.last_investment_month and current_date.day >= self.p.investment_day:
            
            # 更新投资月份，确保本月只投一次
            self.last_investment_month = current_month
            
            print(f"\n{current_date}: 到达定投日，准备无条件买入。")
            
            # 检查现金是否足够
            if self.broker.get_cash() > self.p.investment_amount:
                size_to_buy = self.p.investment_amount / self.data.close[0]
                self.order = self.buy(size=size_to_buy)
            else:
                print(f"{current_date}: 现金不足，无法定投。")

    def stop(self):
        print("\n回测结束，正在生成绩效报告...")
        global benchmark_data
        time_return_analyzer = self.analyzers.getbyname('time_return')
        returns_dict = time_return_analyzer.get_analysis()
        returns = pd.Series(returns_dict)
        if returns.index.tz is not None:
            returns.index = returns.index.tz_localize(None)
        benchmark_rets = benchmark_data.pct_change().dropna()
        report_filename = f'strategy_report_{FUND_SYMBOL}_fixed_invest.html'
        try:
            qs.reports.html(returns, benchmark=benchmark_rets, output=report_filename, 
                            title=f'{FUND_SYMBOL} - 纯固定定投策略 vs. 基准指数')
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
        
        # 添加纯固定定投策略
        cerebro.addstrategy(FixedAutoInvestStrategy)
        
        cerebro.broker.setcash(INITIAL_CASH)
        cerebro.broker.setcommission(commission=COMMISSION_RATE)
        
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