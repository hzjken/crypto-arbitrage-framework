# Crypto Arbitrage Framework
A cryptocurrency arbitrage framework implemented with ccxt and cplex. It can be used to monitor multiple exchanges, find a multi-lateral arbitrage path which maximizes rate of return, calculate the optimal trading amount for each pair in the path given flexible constraints, execute trades, and execute trades according to the calculated amount with multi-threading techniques.

## Why This Framework?
There are quite a few cryptocurrency arbitrage bots open-sourced out there as well, but here are some features that could potentially distinguish this framework from the others.

#### 1. Speed
A majority of the arbitrage bots monitor the market with **brute-force** solution to calculate the rates of return for all the possible trading path, which requires much computing power and time. This framework leverages **linear programming** solution with **cplex solver** to find out the arbitrage path with the max rate of return, which is much faster. In the future, I might continue to develop the framework to support top n arbitrage paths.   
#### 2. Flexibility
Most of the brute-force solutions can only check arbitrage path of length 3 (only contains 3 crypto-currencies, known as **triangular arbitrage** in forex market). With this framework, things become much more **flexible**. It allows the optimizer to give an arbitrage path with no length limit (**multi-lateral arbitrage**). But of course, you can limit the path length or set any other constraints very easily in the **linear programming** optimizer to meet your preference.
#### 3. Trading Amount Optimization
Some arbitrage bots tell you there is an profitable arbitrage path, but do not tell you how much you should buy or sell in each trading pair in the path. It's **meaningless**! This framework utilizes a **two-step optimization** to tell you what's the **optimal path** and what's the **optimal amount** to sell or trade in the path. The trading amount optimization also considers a bunch of **practical constraints** (trading limit, digit precision, orderbook price level and volume etc.) that traders will meet in real trading environment. It gives a correct solution in a fast and clear way.
#### 4. Multi-threading Order Submission
In the part of order execution, the framework utilizes **multi-threading** to parallelize order submission of different exchanges when cross-exchange arbitrage is set to be allowed. It helps to accelerate the order execution process and increase success rate. The framework also has a mechanism that if the time an order waits to be executed exceed a threshold, the order and following orders will be cancelled to **stop loss** from market turbulance.
#### 5. Scalability
Integrated with **`ccxt`**, it's pretty easy for users to scale up their arbitrage scope to multiple exchanges by adding new exchanges to the [`exchanges.py`](https://github.com/hzjken/crypto-arbitrage-framework/blob/master/crypto/exchanges.py). With such, users can explore a **larger trading network** and **more arbitrage opportunities** but not limited to one or two exchanges only. 

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

# initiation with extra params
path_optimizer = PathOptimizer(
    exchanges=exchanges,
    path_length=10,
    simulated_bal=simulated_bal,
    interex_trading_size=2000,
    min_trading_limit=100
)
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
The simulated balance in each exchange, format is like above (the amount for each coin is the number of coins, not in terms of USD value). If it's given, the optimizer will calculate optimal path given your simulated balance, if not, it will fetch your real balances on all the exchanges you specify and calulate path based on real balances. (only if you provide api keys in [`exhcanges.py`](https://github.com/hzjken/crypto-arbitrage-framework/blob/master/crypto/exchanges.py)). Default is set to be None.

### AmtOptimizer
```python
from crypto.amount_optimizer import AmtOptimizer

# initiation
amt_optimizer = AmtOptimizer(
    PathOptimizer=path_optimizer, 
    orderbook_n=100
)

# usage
if path_optimizer.have_opportunity():
    amt_optimizer.get_solution()
```
**`AmtOptimizer`** calculates the optimal trading amount for each trading pair in the arbitrage path. It can only work when a feasible arbitrage path is found. Therefore, we need to use **`path_optimizer.have_opportunity()`** to check whether a path is found before using the **`amt_optimizer.get_solution()`** function. It takes in two required parameters, the **`PathOptimizer`** and **`orderbook_n`**. **`PathOptimizer`** is the class initiated from last step and **`orderbook_n`** specifies the number of existing orders that the optimization will find solution from.

The **`AmtOptimizer`** calculates optimal trading amount with consideration of **available balances**, **orderbook prices and volumes**, **minimum trading limit** and **trading amount digit precision** etc (details can be checked in the function **`_set_constraints()`** in [`amount_optimizer.py`](https://github.com/hzjken/crypto-arbitrage-framework/blob/master/crypto/amount_optimizer.py)), which is able to satisfy a real trading environment. It also accelerates the optimal amount calculation process greatly with the help of **cplex linear programming** in comparison to brute-force enumeration, and allows scalable extension to longer path length and larger orderbook. 

### TradeExecutor
```python
from crypto.trade_execution import TradeExecutor

# initiation
trade_executor = TradeExecutor(path_optimizer)

# usage
if amt_optimizer.have_workable_solution():
    solution = amt_optimizer.trade_solution
    trade_executor.execute(solution)
```
**`TradeExecutor`** executes the trading solution given from **`AmtOptimizer`** with multi-threading implementation to parallelize the order submission of different exchanges to accelerate the process and increase success rate. In the mechanism of **`TradeExecutor`**, if an order is submitted but doesn't get executed within 30 seconds, this and all the later orders will be cancelled so as to stop loss from the market turbulance, while the executed orders are kept remained.

The **`TradeExecutor`** can only work if a workable solution can be provided from the **`AmtOptimizer`** (In many cases, you can find a feasible path but no workable solution can be found due to **digit precision** or **amount limit** constraints). Therefore, we need to check if there's workable solution with **`amt_optimizer.have_workable_solution()`** before we use **`trade_executor.execute(solution)`** to execute.

## Before Usage
There are some preparation works you need to do before you can use this arbitrage framework.
1. **`pip install ccxt`**, ccxt is a great open-source library that provides api to more than 100 crypto exchanges.
2. **`pip install docplex`**, docplex is the python api for using cplex solver.
3. install and setup cplex studio (I use the academic version, because community version has limitation on model size)
4. add all the exchanges (supported by ccxt) you want to monitor and do arbitrage on in [`exchanges.py`](https://github.com/hzjken/crypto-arbitrage-framework/blob/master/crypto/exchanges.py) with the same format. If you only want to check whether there's arbitrage opporunity, you don't need to specify keys. But if you want to execute trades with this framework, add keys like this.
```python
exchanges = {
    'binance': ccxt.binance({
        'apiKey': 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
        'secret': 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
    }),
    'bittrex': ccxt.bittrex({
        'apiKey': 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
        'secret': 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
    }),
}
```
5. check the trading commission rates for the exchanges you specify and put them in the variable `trading_fee` in [`info.py`](https://github.com/hzjken/crypto-arbitrage-framework/blob/master/crypto/info.py)
6.  get an api key from coinmarketcap in order to fetch cryptocurrencies usd prices, and add it to function `get_crypto_prices` in [`utils.py`](https://github.com/hzjken/crypto-arbitrage-framework/blob/master/crypto/utils.py)
```python
'X-CMC_PRO_API_KEY': 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
```

## Usage Example
Check [`main.py`](https://github.com/hzjken/crypto-arbitrage-framework/blob/master/crypto/main.py)

## Something Else To Know
1. This project is done on my personal interest, without rigorous test on the code, so check the code first and use it **at your own risk**.
2. I did successfully find arbitrage opportunities with this framework recently (when the bitfinex btc is 300$ higher than other exchanges), but you should check the **validity of the arbitrage opportunity** on your own (whether an exchange is scam? whether a coin can be withdrawed or deposited? etc.).
3. There are cases when some minor coins' orderbook information is out of date when fetched from ccxt, maybe because the trading of the minor pair is paused for a while, which leads to a fake opportunity. You should verify this as well.
4. I myself think this project idea and the solution quite cool and valuable, but it will require some more time to verify the validity of arbitrage opportunities and resource (money) to really utilize it, both of which I don't have currently... So I decided to share it here to people who can utilize it! If you think it's good or successfully earn money with this framework, feel free to donate me some money through the following wallet addresses. **:p**

**BTC: 1DQvcRAST4VgPMYKKs9HFJLQVT3i3h8XCg**<br>
**ETH: 0x04f6874c50b5b4a31e663b8840d233c666aec0c9**
