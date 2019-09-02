from crypto.exchanges import exchanges
from crypto.path_optimizer import PathOptimizer
from crypto.amount_optimizer import AmtOptimizer
from crypto.trade_execution import TradeExecutor
from crypto.utils import save_record
import time

if __name__ == '__main__':

    # simulate the balance of coins in each exchange so that arbitrage opportunities in such asset allocation can be tested
    simulated_bal = {
        'kucoin': {'BTC': 10, 'ETH': 200, 'NEO': 1000, 'XRP': 30000, 'XLM': 80000},
        'binance': {'BTC': 10, 'ETH': 200, 'NEO': 1000, 'XRP': 30000, 'XLM': 80000},
        'bittrex': {'BTC': 10, 'ETH': 200, 'NEO': 1000, 'XRP': 30000, 'XLM': 80000},
    }
    
    # inititate the path_optimizer with extra parameters
    path_optimizer = PathOptimizer(
        exchanges,
        path_length=6, # to allow arbitrage path of max length 10
        simulated_bal=simulated_bal, # check opportunities with simulated balance
        interex_trading_size=2000, # approximate the inter exchange trading size to be 2000 USD
        inter_exchange_trading=True,
        min_trading_limit=10 # minimum trading limit is 10 USD
    )
    path_optimizer.init_currency_info()
    # inititate the amt_optimizer, considers top 100 orders from the order book when doing amount optimization.
    amt_optimizer = AmtOptimizer(path_optimizer, orderbook_n=20)
    # inititate the trade executor
    trade_executor = TradeExecutor(path_optimizer)

    # loop over the process of find opportunity, optimize amount and do trading for 10 times.
    for i in range(10):

        # move all the kucoin money to trade wallet, kucoin is special for having two wallets main and trade wallet, details can be checked on kucoin.com
        if i % 1500 == 0:
            trade_executor.kucoin_move_to_trade()
        
        # find arbitrage
        path_optimizer.find_arbitrage()
        # if there is arbitrage path, optimize the solution
        if path_optimizer.have_opportunity():
            amt_optimizer.get_solution()
            # save the arbitrage path info and amount optimization info to record.txt, to provide historical action check later
            save_record(path_optimizer, amt_optimizer)
            # if a workable trading solution is found, do the trade
            if amt_optimizer.have_workable_solution():
                solution = amt_optimizer.trade_solution
                trade_executor.execute(solution)
        # rest for 20 seconds as some of the apis do not allow too frequent requests
        time.sleep(20)
