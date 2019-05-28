# crypto-arbitrage-framework
A cryptocurrency arbitrage framework implemented with ccxt and cplex. It can be used to monitor multiple exchanges, find a multi-lateral arbitrage path which maximizes rate of return, calculate the optimal trading amount for each pair in the path given flexible constraints, execute trades, and execute trades according to the calculated amount with multi-threading techniques.

## Components
The framework contains 3 main components, **`PathOptimizer`**, **`AmtOptimizer`** and **`TradeExecutor`**. **`PathOptimizer`** and **`AmtOptimizer`** runs a two-step optimization to find out a feasible and workable solution (optimal path and optimal trading amount). 
**`TradeExecutor`** executes the solution generated from the previous two components.

### PathOptimizer
```python
from crypto.path_optimizer import PathOptimizer
from crypto.exchanges import exchanges

# initiation
path_optimizer = PathOptimizer(exchanges=exchanges)
path_optimizer.init_currency_info()

#usage
path_optimizer.find_arbitrage()
```
**`PathOptimizer`** calculates the optimal arbitrage path (maximizing rate of return) with cplex algorithm given bid-ask prices of each crypto trading pair fetched from ccxt. It takes in **exchanges** as a required parameter and some other optional parameters that affects the path constraint. It can be used to monitor multiple exchanges as long as it's supported by ccxt and you put it in [`exhcanges.py`](https://github.com/hzjken/crypto-arbitrage-framework/blob/master/crypto/exchanges.py).

Before usage, **`path_optimizer.init_currency_info()`** is required to load market information. And then, the usage will be very simple by just a call of **`path_optimizer.find_arbitrage()`**, where the latest price info will be fetched and used to calculate the arbitrage path. If a feasible arbitrage path is found, it will be saved in the class's **`path`** attribute.

There are some optional parameters which could change the modelling constraints of **`PathOptimizer`**.

**Params: `path_length`**<br> 
**Type: `Int`**<br>
To set the max feasible length of the arbitrage path, or in other words, the maximum number of trading pairs the path is allowed to go through. Default is set to be 4.

**Params: `include_fiat`**<br>
**Type: `Boolean`**<br>
Some exchanges allow users to trade fiat-to-crypto pairs. This param sets whether to include fiat-to-crypto trading pairs in the model. Default is set to be False, as fiat trading and money transfer includes some more complex form of commision calculation.

**Params: `inter_exchange_trading`**<br>
**Type: `Boolean`**<br>
Whether to allow the model to consider inter-exchange arbitrage opportunity. Default is set to be True. Cross-exchange trading will need to consider withdrawal fee but usually contains more arbitrage opportunity.

**Params: `interex_trading_size`**<br>
**Type: `Float`**<br>
The amount of money that are expected to be traded in inter-exchange arbitrage in terms of USD, which is used to approximate the withdrawal commission rate. Default is set to be 100.

**Params: `consider_init_bal`**<br>
**Type: `Boolean`**<br>
Whether to consider initial balance. If set to True, the arbitrage path is required to start from one of the cryptocurrencies whose balance is greater than 0. If set to False, the arbitrage path can check all the arbitrage opportunities without considering your balance. Default is set to be True.

**Params: `consider_inter_exc_bal`**<br>
**Type: `Boolean`**<br>
Whether to consider the balance constraint of inter-exchange arbitrage. In cross-platform cryptocurrency trading, withdrawal and deposit are not like intra-platform trading that the trade is done instantly. Cross-platform withdrawal and deposit usually require several confirmation on the blockchain, which could take up to hours. To avoid rapid price changes which might happen during the withdrawal and deposit. In real arbitrage, we require the deposited wallet to have enough money to do the rest of the arbitrage without waiting for the inter-exchange transfer to complete. If set to be True, the above constraint is considered, else not considered. Default is set to be True. 

**Params: `min_trading_limit`**<br>
**Type: `Float`**<br>
The minimum trading amount in terms of USD for each trading pair that needs to be satisfied. As most of the crypto exchanges will set a minimum trading amount, the default is set to be 10 (US dollars) so that all these constraints can be satisfied.
        
**Params: `simulated_bal`**<br>
**Type: `Dict` or `None`**<br>
```python
simulated_bal = {
    'kucoin': {'BTC': 10, 'ETH': 200, 'NEO': 1000, 'XRP': 30000, 'XLM': 80000},
    'binance': {'BTC': 10, 'ETH': 200, 'NEO': 1000, 'XRP': 30000, 'XLM': 80000},
    'bittrex': {'BTC': 10, 'ETH': 200, 'NEO': 1000, 'XRP': 30000, 'XLM': 80000},
}
```
The simulated balance in each exchange, format is like above. If it's given, the optimizer will calculate optimal path given your simulated balance, if not, it will fetch your real balances on all the exchanges you specify and calulate path based on real balances. (only if you provide api keys in [`exhcanges.py`](https://github.com/hzjken/crypto-arbitrage-framework/blob/master/crypto/exchanges.py)). Default is set to be None.
