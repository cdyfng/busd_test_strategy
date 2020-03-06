# -*- coding:utf-8 -*-

"""
OKEx Swap 模块使用演示

> 策略执行的几个步骤:
    1. 在当前盘口价差10美金的位置，挂一个买入buy_open_quantity的委托单，即开仓大小为buy_open_quantity；
    2. 委托单成功成交之后，即持多仓大小buy_open_quantity；
    3. 程序判断何时平仓，亏损千分之一或者在下单后高点的千分之一止盈；
    4. 平仓成功之后，程序退出；
"""

import sys
import os

from quant import const
from quant.utils import tools
from quant.utils import logger
from quant.config import config
from quant.market import Market
from quant.trade import Trade
from quant.order import Order
from quant.market import Orderbook
from quant.position import Position
from quant.tasks import LoopRunTask
from quant.order import ORDER_ACTION_BUY, ORDER_ACTION_SELL, ORDER_STATUS_FILLED
from quant.order import TRADE_TYPE_OPEN_LONG, TRADE_TYPE_OPEN_SHORT, TRADE_TYPE_CLOSE_LONG, TRADE_TYPE_CLOSE_SHORT
#Swap order type
# TRADE_TYPE_OPEN_LONG = 1 
# TRADE_TYPE_OPEN_SHORT = 2 
# TRADE_TYPE_CLOSE_LONG = 3 
# TRADE_TYPE_CLOSE_SHORT = 4  


class MyStrategy:

    def __init__(self):
        """ 初始化
        """
        self.strategy = config.strategy
        self.platform = const.BINANCE
        self.account = config.accounts[0]["account"]
        self.access_key = config.accounts[0]["access_key"]
        self.secret_key = config.accounts[0]["secret_key"]
        self.symbol = config.symbol

        self.buy_open_order_no = None  # 开仓做多订单号
        self.buy_open_price = 0
        self.buy_open_quantity = "0.003"  # 开仓数量(USD)
        self.sell_close_order_no = None  # 多仓平仓订单号
        self.sell_close_time_down = 0  # 平仓倒计时
        self.bsud_usdt_price = 0
        self.btc_busd_relative = {}
        self.highest_price = 0
        self.lowest_price = 999999
        self.threshold = 0.001

        #self.current_price = None  # 当前盘口价格，为了方便，这里假设盘口价格为 卖一 和 买一 的平均值

        # 交易模块
        cc = {
            "strategy": self.strategy,
            "platform": self.platform,
            "symbol": self.symbol,
            "account": self.account,
            "access_key": self.access_key,
            "secret_key": self.secret_key,
            "order_update_callback": self.on_event_order_update,
            "position_update_callback": self.on_event_position_update
        }
        self.trader = Trade(**cc)

        # 订阅行情
        Market(const.MARKET_TYPE_ORDERBOOK, 'binance', 'BTC/USDT', self.on_event_orderbook_btcusdt_update)
        Market(const.MARKET_TYPE_ORDERBOOK, 'binance', 'BUSD/USDT', self.on_event_orderbook_busdusdt_update)
        Market(const.MARKET_TYPE_ORDERBOOK, 'binance', 'BTC/BUSD', self.on_event_orderbook_update)

        # 注册系统循环回调
        LoopRunTask.register(self.on_ticker, 1)  # 每隔1秒执行一次回调

    async def on_event_orderbook_btcusdt_update(self, orderbook: Orderbook):
        """ 订单薄更新
        """
        if self.bsud_usdt_price == 0:
            logger.debug("busd/usdt not get now")
            return        
        #logger.debug("orderbook:", orderbook, caller=self)
        ask1_price = float(orderbook.asks[0][0])/self.bsud_usdt_price  # 卖一价格
        bid1_price = float(orderbook.bids[0][0])/self.bsud_usdt_price  # 买一价格
        self.btc_busd_relative['ask0_relative'] = ask1_price
        self.btc_busd_relative['bid0_relative'] = bid1_price
        logger.debug("btc/busd relative:", self.btc_busd_relative, aller=self) 


    async def on_event_orderbook_busdusdt_update(self, orderbook: Orderbook):
        """ 订单薄更新
        """

        #logger.debug("orderbook:", orderbook, caller=self)
        ask1_price = float(orderbook.asks[0][0])  # 卖一价格
        bid1_price = float(orderbook.bids[0][0])  # 买一价格
        self.bsud_usdt_price = (ask1_price + bid1_price) / 2 #
        logger.debug("busd/usdt :", ask1_price, bid1_price, self.bsud_usdt_price, caller=self)


    async def on_event_orderbook_update(self, orderbook: Orderbook):
        """ 订单薄更新
        """
        #logger.debug("orderbook:", orderbook, caller=self)
        ask1_price = float(orderbook.asks[0][0])  # 卖一价格
        bid1_price = float(orderbook.bids[0][0])  # 买一价格
        logger.debug("btc/busd :", ask1_price, bid1_price, self.bsud_usdt_price, caller=self)


        if self.bsud_usdt_price == 0:
            logger.debug("on_event_orderbook_update busd/usdt not get now")
            return        

        self.highest_price = max(self.highest_price, ask1_price)
        self.lowest_price = min(self.lowest_price, bid1_price)

        if ask1_price < self.btc_busd_relative['bid0_relative'] and not self.buy_open_order_no:
            logger.info("on_event_orderbook_update: Buy signal", bid1_price, orderbook.bids[0][1])
            self.buy_open_price = float(orderbook.asks[0][0])
            quantity = self.buy_open_quantity
            action = ORDER_ACTION_BUY
            new_price = tools.float_to_str(self.buy_open_price)
            logger.info('check :', action)
            order_no, error = await self.trader.create_order(action, new_price, quantity)
            s = "buy bitcoin" + new_price
            os.system('say '+ s)           
            if error:
                logger.error("create order error! error:", error, caller=self)
                return
            self.buy_open_order_no = order_no
            logger.info("create buy open order:", order_no, caller=self)
        elif self.buy_open_order_no and not self.sell_close_order_no:
            #止损 
            if ask1_price < self.buy_open_price * (1 - self.threshold) or \
                (ask1_price < self.highest_price *  (1 - self.threshold) and ask1_price > self.buy_open_price * (1 + self.threshold)):
                price = bid1_price # 当前盘口价格，
                new_price = tools.float_to_str(price)  # 将价格转换为字符串，保持精度
                order_no, error = await self.trader.create_order(ORDER_ACTION_SELL, new_price, self.buy_open_quantity)
                if error:
                    logger.error("create order error! error:", error, caller=self)
                    return
                self.sell_close_order_no = order_no
                logger.info("create sell close order:", order_no, caller=self)

        elif self.sell_close_order_no:
            logger.info("wait for sell close")
        else:
            logger.info("wait for better price")


    async def on_event_order_update(self, order: Order):
        """ 订单状态更新
        """
        logger.info("order update:", order, caller=self)

        if order.status == ORDER_STATUS_FILLED:
            if order.order_no == self.buy_open_order_no:  # 开仓委托单已经完全成交
                logger.info("buy open completed.", caller=self)
                #self.sell_close_time_down = 30 #60 * 5  # 设置平仓倒计时 5分钟

            if order.order_no == self.sell_close_order_no:  # 平仓委托单已经完全成交
                logger.info("sell close completed.", caller=self)
                exit(0)

    async def on_event_position_update(self, position: Position):
        """ 持仓更新
        """
        logger.info("position:", position, caller=self)

    async def on_ticker(self, *args, **kwargs):
        """ 系统循环回调，每秒钟执行一次
        """
        logger.info("do ticker ...", caller=self)
        # if self.sell_close_time_down > 0:
        #     self.sell_close_time_down -= 1
        #     if self.sell_close_time_down <= 0:
        #         price = self.current_price # 当前盘口价格，
        #         new_price = tools.float_to_str(price)  # 将价格转换为字符串，保持精度
        #         order_no, error = await self.trader.create_order(TRADE_TYPE_OPEN_SHORT, new_price, self.buy_open_quantity)
        #         if error:
        #             logger.error("create order error! error:", error, caller=self)
        #             return
        #         logger.info("create sell close order:", order_no, caller=self)


def main():
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    else:
        config_file = None

    from quant.quant import quant
    quant.initialize(config_file)
    MyStrategy()
    quant.start()


if __name__ == '__main__':
    main()
