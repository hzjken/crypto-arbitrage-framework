from crypto.exchanges import exchanges
from crypto.path_optimizer import PathOptimizer
from crypto.amount_optimizer import AmtOptimizer
from crypto.trade_execution import TradeExecutor
from crypto.utils import save_record
import time

if __name__ == '__main__':

    simulated_bal = {
        'kucoin': {'BTC': 10, 'ETH': 200, 'NEO': 1000, 'XRP': 30000, 'XLM': 80000},
        'binance': {'BTC': 10, 'ETH': 200, 'NEO': 1000, 'XRP': 30000, 'XLM': 80000},
        'bittrex': {'BTC': 10, 'ETH': 200, 'NEO': 1000, 'XRP': 30000, 'XLM': 80000},

    }

    path_optimizer = PathOptimizer(
        exchanges,
        path_length=10,
        simulated_bal=simulated_bal,
        interex_trading_size=2000,
        min_trading_limit=100
    )
    path_optimizer.init_currency_info()
    amt_optimizer = AmtOptimizer(path_optimizer, orderbook_n=100)
    trade_executor = TradeExecutor(path_optimizer)

    for i in range(10):

        if i % 1500 == 0:
            trade_executor.kucoin_move_to_trade()

        path_optimizer.find_arbitrage()
        if path_optimizer.have_opportunity():
            amt_optimizer.get_solution()
            save_record(path_optimizer, amt_optimizer)
            if amt_optimizer.have_workable_solution():
                solution = amt_optimizer.trade_solution
                trade_executor.execute(solution)

        time.sleep(20)
