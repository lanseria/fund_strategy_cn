# ----------------------------------------------------------------------------------
# 实战项目: 基于双均线交叉的基金交易策略 (全中文注释版)
# ----------------------------------------------------------------------------------

import backtrader as bt
import akshare as ak
import pandas as pd
import quantstats as qs

# ==================================================================================
# 第1步：参数配置
# ==================================================================================
# --- 策略与回测配置 ---
FUND_SYMBOL = '001632'          # 需要回测的基金代码 (例如：天弘沪深300指数增强A)
BENCHMARK_SYMBOL = 'sh000300'   # 业绩比较基准的指数代码 (例如：沪深300指数)
START_DATE = '20200812'         # 回测开始日期
END_DATE = '20250127'           # 回测结束日期
INITIAL_CASH = 100000.0         # 初始资金
COMMISSION_RATE = 0.0015        # 买卖手续费率 (例如: 0.15%)

# --- 策略参数 ---
FAST_MA_PERIOD = 20             # 快速移动平均线的周期
SLOW_MA_PERIOD = 60             # 慢速移动平均线的周期

# ==================================================================================
# 第2步：数据获取与整合
# ==================================================================================
def get_fund_and_benchmark_data(fund_symbol, benchmark_symbol, start, end):
    print("开始下载基金和基准数据...")
    try:
        # 获取基金净值数据
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
        # 获取基准指数数据
        benchmark_df = ak.stock_zh_index_daily(symbol=benchmark_symbol)
        benchmark_df['date'] = pd.to_datetime(benchmark_df['date'])
        benchmark_df = benchmark_df.set_index('date')
        benchmark_df = benchmark_df[['close']]
    except Exception as e:
        print(f"获取基准 {benchmark_symbol} 数据失败: {e}")
        return None, None
    
    # 为backtrader准备数据格式
    data = fund_nav_df.copy().sort_index()
    data['open'] = data['high'] = data['low'] = data['close']
    data['volume'] = 1000  # 设置一个虚拟成交量
    data['openinterest'] = 0
    
    # 根据指定日期范围筛选数据
    data = data[start:end]
    benchmark_df = benchmark_df[start:end]
    
    print("数据下载和整合完成。")
    return data, benchmark_df['close']

# ==================================================================================
# 第3步：策略定义
# ==================================================================================
class DualMACrossoverStrategy(bt.Strategy):
    # 策略参数
    params = (
        ('fast_ma_period', FAST_MA_PERIOD),
        ('slow_ma_period', SLOW_MA_PERIOD),
    )

    def __init__(self):
        # 计算快线和慢线
        self.sma_fast = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.fast_ma_period)
        self.sma_slow = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.slow_ma_period)
        
        # 计算交叉信号
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        
        # 订单跟踪
        self.order = None

    def notify_order(self, order):
        # 如果订单已提交或被接受，则不执行任何操作
        if order.status in [order.Submitted, order.Accepted]:
            return

        # 如果订单已完成
        if order.status in [order.Completed]:
            if order.isbuy():
                print(
                    f"\n--- 交易执行 ---\n"
                    f"日期: {self.data.datetime.date(0)}\n"
                    f"操作: 买入 (BUY)\n"
                    f"基金: {self.data._name}\n"
                    f"成交份额: {order.executed.size:.2f}\n"
                    f"成交价格: {order.executed.price:.4f}\n"
                    f"交易金额: {order.executed.value:.2f}\n"
                    f"手续费: {order.executed.comm:.2f}\n"
                    f"-----------------"
                )
            elif order.issell():
                print(
                    f"\n--- 交易执行 ---\n"
                    f"日期: {self.data.datetime.date(0)}\n"
                    f"操作: 卖出 (SELL)\n"
                    f"基金: {self.data._name}\n"
                    f"成交份额: {order.executed.size:.2f}\n"
                    f"成交价格: {order.executed.price:.4f}\n"
                    f"交易金额: {order.executed.value:.2f}\n"
                    f"手续费: {order.executed.comm:.2f}\n"
                    f"-----------------"
                )
            self.order = None # 重置订单跟踪
        
        # 如果订单被取消、保证金不足或被拒绝
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            print(f"xx 订单失败/取消: {order.getstatusname()} xx")
            self.order = None

    def next(self):
        # 如果有正在处理的订单，则不产生新订单
        if self.order:
            return

        # 如果持有仓位
        if self.position:
            # 如果出现死叉信号
            if self.crossover < 0:
                print(f"\n{self.data.datetime.date()}: 死叉信号，准备卖出全部 {self.data._name}")
                self.order = self.close() # 发出卖出指令
        # 如果没有仓位
        else:
            # 如果出现金叉信号
            if self.crossover > 0:
                print(f"\n{self.data.datetime.date()}: 金叉信号，准备买入基金 {self.data._name}")
                self.order = self.buy() # 发出买入指令

    def stop(self):
        print("\n回测结束，正在生成绩效报告...")
        
        # 声明全局变量以便在此处使用
        global benchmark_data
        
        time_return_analyzer = self.analyzers.getbyname('time_return')
        returns_dict = time_return_analyzer.get_analysis()
        
        returns = pd.Series(returns_dict)
        # 移除时区信息以兼容 quantstats
        if returns.index.tz is not None:
            returns.index = returns.index.tz_localize(None)
            
        benchmark_rets = benchmark_data.pct_change().dropna()
        report_filename = f'strategy_report_{FUND_SYMBOL}.html'
        
        try:
            # 使用 quantstats 生成HTML报告
            qs.reports.html(returns, 
                            benchmark=benchmark_rets, 
                            output=report_filename, 
                            title=f'{FUND_SYMBOL} - 双均线交叉策略 vs. 基准指数'
                          )
            print(f"绩效报告已成功生成：{report_filename}")
        except Exception as e:
            print(f"生成 quantstats 报告时出错: {e}")

# ==================================================================================
# 第4步：回测引擎
# ==================================================================================
if __name__ == '__main__':
    # 获取数据
    fund_data, benchmark_data = get_fund_and_benchmark_data(FUND_SYMBOL, BENCHMARK_SYMBOL, START_DATE, END_DATE)

    if fund_data is not None and not fund_data.empty:
        # 创建Cerebro回测引擎实例
        cerebro = bt.Cerebro()
        
        # 添加数据源
        data_feed = bt.feeds.PandasData(dataname=fund_data, name=FUND_SYMBOL)
        cerebro.adddata(data_feed)
        
        # 添加策略
        cerebro.addstrategy(DualMACrossoverStrategy)
        
        # 设置初始资金和手续费
        cerebro.broker.setcash(INITIAL_CASH)
        cerebro.broker.setcommission(commission=COMMISSION_RATE)
        
        # 添加资金管理策略 (Sizer)，按现金的百分比买入，避免保证金不足的错误
        cerebro.addsizer(bt.sizers.PercentSizer, percents=98)
        
        # 添加分析器
        cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='time_return')
        
        print("\n开始执行回测...")
        results = cerebro.run()
        
        # 打印最终资产
        final_value = cerebro.broker.getvalue()
        print("\n--- 回测完成 ---")
        print(f"初始资产: {INITIAL_CASH:,.2f}")
        print(f"最终资产: {final_value:,.2f}")
        print("详细的绩效分析请打开生成的HTML报告文件查看。")
    else:
        print("未能获取到数据，回测中止。")