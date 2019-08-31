from docplex.mp.model import Model
import numpy as np
from itertools import combinations
from .info import fiat, trading_fee
from .utils import get_withdrawal_fees, get_crypto_prices, multiThread
import re
from copy import deepcopy


class PathOptimizer(Model):
    '''
    optimization model class for solving multi-lateral arbitrage path that maximizes profit.
    It outputs value zero when no arbitrage opportunity is found. When an opportunity is found,
    the model outputs the profit percentage as well as the arbitrage path.
    Arbitrage output considers the transaction spread as well as commission rates.
    Users can change parameter settings through modifying function set_params or inherit in subclass.

    Example Use:
    m = PathOptimizer()
    m.find_arbitrage()
    '''
    length = None  # number n, the number of currencies included.
    path_length = None  # the upper bound of arbitrage path length
    currency_set = None  # a set of length n, where n is the number of currencies included.
    exchanges = None  # the dict for storing clients towards each exchanges

    # numpy array of shape (n, n), element (i,j) in the array represents the transfer rates from i to j,
    # meaning the number of j that one unit of i is equal to.
    transit_price_matrix = None
    trading_fee = None  # a dict to record each exchange's trading fee percentage\
    interex_trading_size = None  # the amount of money that are expected to be traded in one inter exchange arbitrage in terms of USD
    withdrawal_fee = None  # a dict to record the withdrawal fee of each exchange's currencies
    include_fiat = None  # boolean variable, to decide whether the arbitrage path should include fiat currencies.
    inter_exchange_trading = None  # boolean variable to determine whether considers inter exchange trading
    fiat_set = None  # a set of fiat currencies, that need to be excluded if include_fiat is set to False
    run_times = 0  # an inner counter to see how many times the find_arbitrage function has been run, starts from 0
    refresh_time = None  # the number of times that find_arbitrage function to be run to refresh withdrawal and commission
    var_location = None  # an array that records the location of all the decision variables
    # numpy array of shape (n, n), element (i,j) in the array represents the commission fee rate that a
    # transaction needs to pay when transit from currency i to currency j.
    commission_matrix = None
    vol_matrix = None  # np.array of trading volumes, to check whether path allowed big volume trading
    currency2index = None  # a dict of length n, mapping from currency to its index
    index2currency = None  # a dict of length n, mapping from index to currency
    required_currencies = None  # a list of nodes(coin, currency, commodity etc.) that the arbitrage path have to go by at least one
    crypto_prices = None  # a dict to record all the coins' reference prices in usd
    min_trading_limit = None  # a number in usd that the trading value should be higher than, otherwise not workable
    balance_dict = None  # a dict to record all the currencies' balances in all exchanges
    price = None  # a nested dict that records the ticker information of all trading pairs in all exchanges
    inter_convert_list = None  # a list that records all the feasible inter-exchange pairs
    consider_inter_exc_bal = None  # boolean, determines whether to consider the inter-exchange balance constraint or not (withdraw < balance)
    consider_init_bal = None  # boolean, determines whether to consider the initial balance constraint (trading < initial balance)
    print_content = None  # content to be printed when find_arbitrage() is run
    simulated_bal = None  # dict or None, used for users to run find_arbitrage() under simulated balance.

    obj = None  # profit percentage of the arbitrage path, zero means no arbitrage opportunity.
    var = None  # binary decision variable list, length equal n * n
    x = None  # the matrix version of the binary decision variable list, array of shape (n, n)
    xs = None  # array of shape (n, n), the solved matrix of decision variables, which shows the arbitrage path in matrix.
    path = None  # tuple list of the arbitrage path, e.g. [('USD', 'SGD'), ('SGD', 'GBP'), ('GBP', 'USD')]

    def __init__(self, exchanges, **params):
        super().__init__()
        # initiate exchange clients
        self.exchanges = exchanges
        # initiate all the required params
        self.set_params(params)

    def _run_time_init(self):
        '''function to initialize params and variables only when find_arbitrage() is run'''
        self.init_currency_info()
        self.length = len(self.currency_set)
        self.currency2index = {item: i for i, item in enumerate(self.currency_set)}
        self.index2currency = {val: key for key, val in self.currency2index.items()}
        self.get_inter_convert_list()
        # initiate decision variables and constraints for optimization model
        self.update_withdrawal_fee()
        self.get_var_location()
        var_num = int(np.sum(self.var_location))
        self.var = self.binary_var_list(var_num, name='x')
        self.x = np.zeros([self.length, self.length])
        self.x = self.x.astype('object')
        self.x[self.var_location] = self.var
        self.set_constraints()

    def find_arbitrage(self):
        '''
        solve the optimization model to see whether there is an arbitrage opportunity and save the
        profit rate and arbitrage path. The main function to be used in this object.
        '''
        # update withdrawal fee and commission fee structure every 100 times when the find_arbitrage is run
        self.print_content = ''

        if self.run_times == 0:
            self._run_time_init()

        if self.run_times % self.refresh_time == 0:
            self.update_withdrawal_fee()
            self.update_ref_coin_price()
            self.update_commission_fee()

        self.update_objectives()
        ms = self.solve()
        self.xs = np.zeros([self.length, self.length])
        self.xs[self.var_location] = ms.get_values(self.var)
        path = list(zip(*np.nonzero(self.xs)))
        path = [(self.index2currency[i], self.index2currency[j]) for i, j in path]
        self.path = self._sort_list(path)
        self.obj = np.exp(self.objective_value) - 1

        self.print_content = 'profit rate: {}, arbitrage path: {}'.format(self.obj, self.path)
        print(self.print_content)
        self.run_times += 1

    def set_params(self, params):
        '''modify some params that might affect the initiation of model before init_currency_info()'''

        # default settings
        self.required_currencies = []
        self.path_length = 4
        self.include_fiat = False
        self.trading_fee = trading_fee
        self.fiat_set = fiat
        self.inter_exchange_trading = True
        self.consider_init_bal = True
        self.consider_inter_exc_bal = True
        self.interex_trading_size = 100  # only affects inter-exchange
        self.min_trading_limit = 10
        self.refresh_time = 1000

        for key, val in params.items():
            if hasattr(self, key):
                setattr(self, key, val)
            else:
                raise ValueError('{} is not a valid attribute in model'.format(key))

    def init_currency_info(self):
        '''
        to read in all the available currencies and sort them in order, this function
        needs to initiate the attribute currency_set and required_currencies
        '''
        self.currency_set = set()
        for exc_name, exchange in self.exchanges.items():
            exchange.load_markets()
            currency_names = ['{}_{}'.format(exc_name, cur) for cur in exchange.currencies.keys()]
            self.currency_set |= set(currency_names)
            if not self.include_fiat:
                self.currency_set -= set(['{}_{}'.format(exc_name, fiat) for fiat in self.fiat_set])

        # currency_set should only contain coins that have reference usd price, other wise volume too small and volatile
        coin_set = set([i.split('_')[-1] for i in self.currency_set])
        self.crypto_prices = get_crypto_prices(coin_set)
        self.currency_set = set([i for i in self.currency_set if i.split('_')[-1] in self.crypto_prices.keys()])

    def update_transit_price(self):
        '''to update data of the transit_price_matrix'''
        self.price = {}
        self.transit_price_matrix = np.zeros([self.length, self.length])

        exc_name_list = list(self.exchanges.keys())
        thread_num = len(exc_name_list)
        exc_price_list = multiThread(self.parallel_fetch_tickers, exc_name_list, thread_num)
        for exc_price in exc_price_list:
            self.price.update(exc_price)

        for pair, items in self.price.items():
            from_cur, to_cur = pair.split('/')
            if from_cur in self.currency_set and to_cur in self.currency_set:
                from_index = self.currency2index[from_cur]
                to_index = self.currency2index[to_cur]
                if items['ask'] != 0 and items['bid'] != 0:
                    self.transit_price_matrix[from_index, to_index] = items['bid']
                    self.transit_price_matrix[to_index, from_index] = 1 / items['ask']

        for from_cur, to_cur in self.inter_convert_list:
            from_index = self.currency2index[from_cur]
            to_index = self.currency2index[to_cur]

            if from_cur in self.withdrawal_fee:
                self.transit_price_matrix[from_index, to_index] = 1
            else:
                self.transit_price_matrix[from_index, to_index] = 0

            if to_cur in self.withdrawal_fee:
                self.transit_price_matrix[to_index, from_index] = 1
            else:
                self.transit_price_matrix[to_index, from_index] = 0

    def update_withdrawal_fee(self):
        '''update withdrawal fee for each exchange'''
        self.withdrawal_fee = {}
        for exchange in self.exchanges:
            fee = get_withdrawal_fees(exchange, self.interex_trading_size)
            for currency in list(fee.keys()):
                new_name = '{}_{}'.format(exchange, currency)
                if new_name in self.currency_set:
                    fee[new_name] = fee.pop(currency)
                else:
                    fee.pop(currency)
            self.withdrawal_fee.update(fee)

    def update_balance(self):
        '''function to update the crypto-currency balance in all the exchanges'''
        self.balance_dict = {}
        coin_set = set([i.split('_')[-1] for i in self.currency_set])

        exc_name_list = list(self.exchanges.keys())
        thread_num = len(exc_name_list)
        fetch_free_balance = lambda x: self.exchanges[x].fetch_free_balance()
        if self.simulated_bal is None:
            exc_bal_list = multiThread(fetch_free_balance, exc_name_list, thread_num)
            exc_bal_dict = dict(zip(exc_name_list, exc_bal_list))
        else:
            exc_bal_dict = deepcopy(self.simulated_bal)

        for exc_name, exchange in self.exchanges.items():
            exc_bal = exc_bal_dict[exc_name]
            for i in list(exc_bal.keys()):
                if i in coin_set:
                    balance = exc_bal.pop(i)
                    usd_balance = balance * self.crypto_prices[i]['price']
                    exc_bal['{}_{}'.format(exc_name, i)] = {
                        'balance': balance,
                        'usd_balance': usd_balance
                    }
                else:
                    exc_bal.pop(i)

            self.balance_dict.update(exc_bal)

    def update_commission_fee(self):
        '''function to update the withdrawal fee and trading commission fee into the commission matrix'''

        self.commission_matrix = np.zeros([self.length, self.length])
        # intra exchange commission fee
        for exc_name in self.exchanges.keys():
            indexes = [index for cur_name, index in self.currency2index.items() if exc_name in cur_name]
            self.commission_matrix[np.meshgrid(indexes, indexes, indexing='ij', sparse=True)] = self.trading_fee[
                exc_name]

        # inter exchange commission fee
        for from_cur, to_cur in self.inter_convert_list:
            from_index = self.currency2index[from_cur]
            to_index = self.currency2index[to_cur]

            # currency has withdrawal fee, then it's transferable and commission can be updated
            if from_cur in self.withdrawal_fee:
                self.commission_matrix[from_index, to_index] = self.withdrawal_fee[from_cur]['usd_rate']
            if to_cur in self.withdrawal_fee:
                self.commission_matrix[to_index, from_index] = self.withdrawal_fee[to_cur]['usd_rate']

    def update_ref_coin_price(self):
        '''update all crypto currencies' prices in terms of US dollars'''
        self.crypto_prices = get_crypto_prices(self.crypto_prices.keys())

    def set_constraints(self):
        '''set optimization constraints for the Cplex model'''

        # 1. closed-circle arbitrage requirement, for each currency, transit-in equals transit-out.
        self.add_constraints(
            self.sum(self.x[currency, :]) == self.sum(self.x[:, currency]) for currency in range(self.length))
        # 2. each currency can only be transited-in at most once.
        self.add_constraints(self.sum(self.x[currency, :]) <= 1 for currency in range(self.length))
        # 3. each currency can only be transited-out at most once.
        self.add_constraints(self.sum(self.x[:, currency]) <= 1 for currency in range(self.length))
        # 4. the whole arbitrage path should be less than a given length
        if isinstance(self.path_length, int):
            self.add_constraint(self.sum(self.x) <= self.path_length)
        # 5. the arbitrage path have to go by some certain nodes, in update_changeable_constraint()

    def update_objectives(self):
        '''
        update balance, transition price matrix, volume matrix and changeable constraint, and modify maximization
        objective based on that
        '''
        self.update_balance()
        self.update_transit_price()
        self.update_vol_matrix()
        self.update_changeable_constraint()

        final_transit_matrix = np.log(self.transit_price_matrix * (1 - self.commission_matrix) * (
            (self.vol_matrix >= self.min_trading_limit).astype(int)))
        final_transit = final_transit_matrix[self.var_location]
        x = self.x[self.var_location]
        self.maximize(self.sum(x * final_transit))

    def update_vol_matrix(self, percentile=0.01):
        '''
        function to update the volume matrix which is used to determine whether a path is feasible.
        A path is considered feasible when the trading volume is above a threshold.
        Percentile 0.01 means 1% of the base trading volume of a certain pair should be larger than
        the threshold to be considered as a feasible path. (assume top 50 orders volume is 1% of total volume)
        In this function, balance constraint of inter-exchange path is also integrated into vol_matrix
        '''
        usd_values = {}
        self.vol_matrix = np.zeros([self.length, self.length])

        for key, val in self.price.items():
            base_coin = key.split('/')[0].split('_')[-1]
            if base_coin in self.crypto_prices and val['baseVolume'] is not None \
                    and self.crypto_prices[base_coin]['price'] is not None:
                usd_values[key] = val['baseVolume'] * self.crypto_prices[base_coin]['price'] * percentile

        for key, val in usd_values.items():
            from_cur, to_cur = key.split('/')
            if from_cur in self.currency_set and to_cur in self.currency_set:
                self.vol_matrix[self.currency2index[from_cur], self.currency2index[to_cur]] = val
                self.vol_matrix[self.currency2index[to_cur], self.currency2index[from_cur]] = val

        for from_cur, to_cur in self.inter_convert_list:
            # constraint on inter exchange balance
            if self.consider_inter_exc_bal:
                from_cur_bal = self.balance_dict[from_cur]['usd_balance'] if from_cur in self.balance_dict else 0
                to_cur_bal = self.balance_dict[to_cur]['usd_balance'] if to_cur in self.balance_dict else 0
            else:
                from_cur_bal = np.nan_to_num(np.inf)
                to_cur_bal = np.nan_to_num(np.inf)

            if from_cur in self.withdrawal_fee:
                from_cur_withdraw = self.withdrawal_fee[from_cur]['usd_fee']
                self.vol_matrix[
                    self.currency2index[from_cur], self.currency2index[to_cur]] = to_cur_bal + from_cur_withdraw
            if to_cur in self.withdrawal_fee:
                to_cur_withdraw = self.withdrawal_fee[to_cur]['usd_fee']
                self.vol_matrix[
                    self.currency2index[to_cur], self.currency2index[from_cur]] = from_cur_bal + to_cur_withdraw

    def get_inter_convert_list(self):
        '''store all the possible inter-exchange trading path'''
        self.inter_convert_list = []
        if self.inter_exchange_trading:
            same_currency_maps = dict()
            for i in self.currency_set:
                short_name = i.split('_')[-1]
                if short_name not in same_currency_maps:
                    same_currency_maps[short_name] = [i]
                else:
                    same_currency_maps[short_name].append(i)

            for currencies in same_currency_maps.values():
                if len(currencies) >= 2:
                    for from_cur, to_cur in combinations(currencies, 2):
                        self.inter_convert_list.append((from_cur, to_cur))

    def _sort_list(self, tuple_list):
        '''
        sort the list by having each tuple in the list to be connected one by one, head to tail,
        the first item of the list would be a top-rank coin if the path includes one.
        '''
        if len(tuple_list) > 0:
            first_num = {i[0]: i for i in tuple_list}

            found_first = False
            for currency in self.required_currencies:
                if currency in first_num:
                    item = first_num[currency]
                    found_first = True
                    break

            if not found_first:
                item = tuple_list[0]
            output = [item]

            while True:
                next_item = first_num[item[1]]
                if next_item in output:
                    break
                else:
                    output.append(next_item)
                item = next_item
        else:
            output = []
        return output

    def parallel_fetch_tickers(self, exc_name):
        '''function to be used to fetch ticker info in multi-thread wrapper'''
        exc_price = self.exchanges[exc_name].fetch_tickers()
        for pair in list(exc_price.keys()):
            match = re.findall(r'[A-Z]+/[A-Z]+', pair)
            if len(match) == 1 and match[0] == pair and pair in self.exchanges[exc_name].markets:
                new_name = '/'.join(['{}_{}'.format(exc_name, i) for i in pair.split('/')])
                exc_price[new_name] = exc_price.pop(pair)
            else:
                exc_price.pop(pair)

        return exc_price

    def update_changeable_constraint(self):
        '''
        constraint about required currencies
        the arbitrage path have to go by some certain nodes.
        '''
        if self.consider_init_bal:

            coin_balance_list = [(key, val['usd_balance']) for key, val in self.balance_dict.items() if
                                 val['usd_balance'] >= self.min_trading_limit]
            coin_balance_list = sorted(coin_balance_list, key=lambda x: x[-1], reverse=True)
            required_currencies = [i[0] for i in coin_balance_list]
            same = required_currencies == self.required_currencies
            self.required_currencies = required_currencies

            if self.required_currencies == []:
                pass
            elif same:
                pass
            else:
                required_cur_index = [self.currency2index[i] for i in self.required_currencies]
                constraint = self.get_constraint_by_name('changeable')
                left = self.sum(self.x[required_cur_index, :])
                right = 0.0000001 * self.sum(self.x)
                if constraint is None:
                    self.add_constraint(left >= right, ctname='changeable')  # small m
                else:
                    self.remove_constraint('changeable')
                    self.add_constraint(left >= right, ctname='changeable')  # small m

    def get_var_location(self):
        '''
        a function to locate all the trading-feasible pairs so that decision variables can be located,
        used to reduced the number of decision variables, to accelerate the modelling speed.
        '''
        self.var_location = np.zeros([self.length, self.length])
        # intra exchange
        for exc_name, exchange in self.exchanges.items():
            pairs = exchange.markets.keys()
            for i in pairs:
                try:
                    former, latter = i.split('/')
                except:
                    print(i)
                from_cur = '{}_{}'.format(exc_name, former)
                to_cur = '{}_{}'.format(exc_name, latter)
                if from_cur in self.currency2index and to_cur in self.currency2index:
                    from_index = self.currency2index[from_cur]
                    to_index = self.currency2index[to_cur]
                    self.var_location[from_index, to_index] = 1
                    self.var_location[to_index, from_index] = 1

        # inter exchange
        for from_cur, to_cur in self.inter_convert_list:
            if from_cur in self.currency2index and to_cur in self.currency2index:
                from_index = self.currency2index[from_cur]
                to_index = self.currency2index[to_cur]
                self.var_location[from_index, to_index] = 1
                self.var_location[to_index, from_index] = 1

        self.var_location = self.var_location == 1

    def have_opportunity(self):
        '''return whether the optimizer finds a possible arbitrage path'''
        return len(self.path) > 0
