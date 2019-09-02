from docplex.mp.model import Model
import numpy as np
from itertools import combinations
from .utils import multiThread
from collections import OrderedDict


class AmtOptimizer(Model):
    '''
    optimization model class for solving the trading amount, price and buy-sell direction in each step of the abitrage path.
    The output is an OrderedDict that records (amount, price , direction) for each step, when given arbitrage path.
    solution will be an empty OrderedDict when no workable solution is found.

    Example Use:
    m = AmtOptimizer(PathOptimizer , 5)
    m.get_solution()
    '''

    path = None  # list, trading arbitrage path same as PathOptimizer model
    path_n = None  # int, the number of steps in the arbitrage path
    orderbook_n = None  # int, determines the number of order info to look at from order book
    x = None  # shape (path_n, orderbook_n) integer decision variable matrix x, to determine the trading amount in each step
    y = None  # shape (path_n, orderbook_n) binary decision variable matrix y, to determine which order_book price to use in each step
    z = None  # shape (path_n, orderbook_n) real trading amount matrix, equals x * precision_matrix
    PathOptimizer = None  # the arbitrage opportunity model
    precision_matrix = None  # shape (path_n,1) array that records the decimal precision of the trading amount in each step
    amt_matrix = None  # shape (path_n, orderbook_n) array that records the max possible trading amount for each step and each price level
    price_matrix = None  # shape (path_n, orderbook_n) array that records the price options for each step
    big_m = None  # int, big M helps to deal with constraints linearization
    order_book = None  # dict, records the top n order-book info of each given pairs in arbitrage path and base-quote relation (reverse).
    trade_solution = None  # OrderedDict, records the final trading solution for the arbitrage path
    profit_unit = None  # str, the unit of the arbitrage final profit
    trade_amt_ptc = None  # float, to determine the feasible trading percentage in terms of given orderbook volume
    print_content = None  # content to be printed when get_solution() is run
    amplifier = None  # a very small float, usually 1e-10 or something, used to amplify the objective function in LP so that the LP gets solved
    default_precision = None  # default precision level when precision is not available

    def __init__(self, PathOptimizer, orderbook_n):
        super().__init__()
        self.PathOptimizer = PathOptimizer
        self.get_pair_info()
        self.get_precision()
        self.orderbook_n = orderbook_n
        self.big_m = 1e+10
        self.trade_amt_ptc = 1
        self.amplifier = 1e-10
        self.default_precision = 3

    def get_solution(self):
        '''the function to be used by user to get trading solution'''
        self._update_path_params()
        self._update_model()
        self._get_solution()

    def _update_path_params(self):
        '''update the parameters for modelling'''
        self.path = self.PathOptimizer.path
        self.path_n = len(self.path)
        self.set_path_commission()
        self.path_order_book()  # requires internet connection
        self.get_reverse_list()
        self.set_precision_matrix()
        self.set_amt_and_price_matrix()
        self.balance_constraint()

    def _update_model(self):
        '''update the decision variables, constraints and objectives of the model'''
        self.clear()
        self._init_decision_vars()
        self._set_constraints()
        self._update_objective()

    def _init_decision_vars(self):
        '''function to initiate all the decision variables'''
        self.int_var = self.integer_var_list(self.path_n * self.orderbook_n, name='x')
        self.x = np.array(self.int_var).reshape(self.path_n, self.orderbook_n)
        self.bi_var = self.binary_var_list(self.path_n * self.orderbook_n, name='y')
        self.y = np.array(self.bi_var).reshape(self.path_n, self.orderbook_n)
        self.z = self.x * self.precision_matrix

    def _set_constraints(self):
        '''function to set linear constraints for the optimization model'''

        # 1. total number of triggered price y should be equal to path length
        self.add_constraint(self.sum(self.y) == self.path_n)
        # 2. you can only choose one price level from each step's order book
        self.add_constraints(self.sum(self.y[i, :]) <= 1 for i in range(self.path_n))
        # only the amount at the chosen price level could be larger than 0
        self.add_constraints(
            self.x[i, j] <= self.big_m * self.y[i, j] for i in range(self.path_n) for j in range(self.orderbook_n))
        # 3. amount for order should be smaller than given order book amount
        self.add_constraints(
            self.z[i, j] <= self.trade_amt_ptc * self.amt_matrix[i, j] for i in range(self.path_n) for j in
            range(self.orderbook_n))
        # 4. first transfer trading amount smaller than balance of first coin
        first_coin_bal = self.balance_vol[self.path[0]][self.path[0][0]]
        if not self.reverse_list[0]:
            self.add_constraint(self.sum(self.z[0, :]) <= first_coin_bal)
        else:
            self.add_constraint(self.dot(self.z[0, :], self.price_matrix[0, :]) <= first_coin_bal)
        # 5. inter exchange transfer amount should be smaller than recipient balance
        for i, trade in enumerate(self.path):
            if trade in self.balance_vol:
                sec_balance = self.balance_vol[trade].get(trade[1])
                withdraw_fee = self.PathOptimizer.withdrawal_fee[trade[0]]['coin_fee']
                if sec_balance is not None:
                    self.add_constraint(self.sum(self.z[i, :]) <= sec_balance + withdraw_fee)
        # 6. later step amount should be bound by prior step amount and price
        for i, trade in enumerate(self.path):
            reverse = self.reverse_list[i]
            inter = trade[0].split('_')[0] != trade[1].split('_')[0]

            if i >= 1:
                if not reverse:
                    self.add_constraint(self.sum(self.z[i, :]) <= prev_amt)
                else:
                    self.add_constraint(self.dot(self.z[i, :], self.price_matrix[i, :]) <= prev_amt)

            if inter:
                withdraw_fee = self.PathOptimizer.withdrawal_fee[trade[0]]['coin_fee']
                prev_amt = self.sum(self.z[i, :]) - withdraw_fee
            else:
                if not reverse:
                    prev_amt = self.dot(self.z[i, :], self.price_matrix[i, :]) * (1 - self.path_commission[i])
                else:
                    prev_amt = self.sum(self.z[i, :]) * (1 - self.path_commission[i])
        # 7. integer variables should all be larger than 0
        self.add_constraints(self.x[i, j] >= 0 for i in range(self.path_n) for j in range(self.orderbook_n))

    def _update_objective(self):
        '''function to update the maximization objectie of the model'''
        end_first_exchange, _ = self.path[-1][0].split('_')
        end_sec_exchange, _ = self.path[-1][1].split('_')
        end_reverse = self.reverse_list[-1]
        start_reverse = self.reverse_list[0]
        end_inter = end_first_exchange != end_sec_exchange

        if end_inter:
            withdraw_fee = self.PathOptimizer.withdrawal_fee[self.path[-1][0]]['coin_fee']
            get = self.sum(self.z[-1, :]) - withdraw_fee
        else:
            if not end_reverse:
                get = self.dot(self.z[-1, :], self.price_matrix[-1, :]) * (1 - self.path_commission[-1])
            else:
                get = self.sum(self.z[-1, :]) * (1 - self.path_commission[-1])

        if not start_reverse:
            pay = self.sum(self.z[0, :])
        else:
            pay = self.dot(self.z[0, :], self.price_matrix[0, :])

        self.maximize((get - pay) / self.amplifier)

    def _get_solution(self):
        '''function to solve the optimization model, save result and print outputs'''
        self.print_content = ''
        self.trade_solution = OrderedDict()
        ms = self.solve()
        xs = np.array(ms.get_values(self.int_var)).reshape(self.path_n, self.orderbook_n)
        zs = xs * self.precision_matrix
        nonzeroZ = list(zip(*np.nonzero(zs)))
        nonzeroZ = sorted(nonzeroZ, key=lambda x: x[0])

        for i, j in nonzeroZ:
            reverse = self.reverse_list[i]
            precision = -int(np.log10(self.precision_matrix[i, 0]))
            trade_vol = round(zs[i, j], precision)
            price = self.price_matrix[i, j]
            trade = self.path[i] if not reverse else self.path[i][::-1]
            direction = 'bid_sell' if not reverse else 'ask_buy'
            self.trade_solution[trade] = {'vol': trade_vol, 'price': price, 'direction': direction}

        if len(self.trade_solution) == 0 or self.objective_value <= 0:
            self.print_content = 'no workable solution'
        else:
            self.profit_unit = self.path[0][0]
            self.print_content = 'Solution: {}, final profit: {} {}'.format(
                self.trade_solution,
                self.objective_value * self.amplifier,
                self.profit_unit
            )
        print(self.print_content)

    def get_pair_info(self):
        '''get all the trading pairs name'''
        self.pair_info = {}
        for exc_name, exchange in self.PathOptimizer.exchanges.items():
            self.pair_info[exc_name] = set(exchange.markets.keys())

    def set_path_commission(self):
        '''get the commission fee for each step in the arbitrage path'''
        self.path_commission = [
            self.PathOptimizer.commission_matrix[
                self.PathOptimizer.currency2index[i[0]], self.PathOptimizer.currency2index[i[1]]
            ] for i in self.path
        ]

    def get_precision(self):
        '''get the amount precision for all the trading pairs'''
        self.precision = {}
        for exc_name, exchange in self.PathOptimizer.exchanges.items():
            for pair, info in exchange.markets.items():
                new_name = '/'.join(['{}_{}'.format(exc_name, i) for i in pair.split('/')])
                precision = info['precision'].get('amount')
                if precision is None:
                    precision = self.default_precision
                self.precision[new_name] = precision

        # withdrawal precision (inter exchange trading)
        if self.PathOptimizer.inter_exchange_trading:
            same_currency_maps = dict()
            for i in self.PathOptimizer.currency_set:
                short_name = i.split('_')[-1]
                if short_name not in same_currency_maps:
                    same_currency_maps[short_name] = [i]
                else:
                    same_currency_maps[short_name].append(i)

            for currencies in same_currency_maps.values():
                if len(currencies) >= 2:
                    for from_cur, to_cur in combinations(currencies, 2):
                        self.precision['{}/{}'.format(from_cur, to_cur)] = 5
                        self.precision['{}/{}'.format(to_cur, from_cur)] = 5

    def set_precision_matrix(self):
        '''set the shape (path_n, 1) precision matrix given the precision info'''
        precision_list = []
        for index, i in enumerate(self.path):
            reverse = self.reverse_list[index]
            trade_pair = '/'.join(i) if not reverse else '/'.join(i[::-1])
            precision = 10 ** -self.precision[trade_pair]
            precision_list.append(precision)

        self.precision_matrix = np.array(precision_list).reshape(self.path_n, 1)

    def set_amt_and_price_matrix(self):
        '''set the amount matrix and price matrix from orderbook info'''
        self.amt_matrix = np.zeros([self.path_n, self.orderbook_n])
        self.price_matrix = np.zeros([self.path_n, self.orderbook_n])

        for index, i in enumerate(self.path):
            orders = self.order_book[i]['orders']
            pad_num = self.orderbook_n - orders.shape[0]
            pad_array = np.zeros([max(pad_num, 0)])

            self.amt_matrix[index, :] = np.concatenate([orders[:, 1], pad_array])
            self.price_matrix[index, :] = np.concatenate([orders[:, 0], pad_array])

    def get_reverse_list(self):
        '''
        get a list of booleans that tells whether each step pair of the arbitrage path is reverse
        when reverse == True, the base currency is the latter in the pair,
        when reverse == False, the base currency is the former in the pair
        '''
        self.reverse_list = [self.order_book[i]['reverse'] for i in self.path]

    def balance_constraint(self):
        '''
        function to save info in the balance_vol variable, which records the balance constraints in each step of the
        arbitrage path, including inter exchange balance and initial balance.
        If no constraint, info will be not be added in the balance_vol dict.
        '''
        self.balance_vol = {}
        balance_dict = self.PathOptimizer.balance_dict

        # init constraint
        init_vol = balance_dict.get(self.path[0][0])
        init_vol = init_vol.get('balance') if init_vol is not None else init_vol
        init_vol = init_vol if init_vol else 0
        self.balance_vol[self.path[0]] = {self.path[0][0]: init_vol}

        if self.PathOptimizer.inter_exchange_trading:
            for i in self.path:
                first_exchange, first_cur = i[0].split('_')
                sec_exchange, sec_cur = i[1].split('_')
                if first_exchange != sec_exchange:
                    balance = balance_dict.get(i[1])
                    balance = balance.get('balance') if balance is not None else balance
                    if i not in self.balance_vol:
                        self.balance_vol[i] = {i[1]: balance if balance else 0}
                    else:
                        self.balance_vol[i][i[1]] = balance if balance else 0

    def parallel_fetch_order_book(self, i):
        '''function to fetch order book information with multithread wrapper'''
        first_exchange, first_cur = i[0].split('_')
        sec_exchange, sec_cur = i[1].split('_')

        if first_exchange == sec_exchange:
            pair = '{}/{}'.format(first_cur, sec_cur)
            if pair not in self.pair_info[first_exchange]:
                pair = '/'.join(pair.split('/')[::-1])

            fetched_order_book = self.PathOptimizer.exchanges[first_exchange].fetch_order_book(pair)
        else:
            fetched_order_book = None

        return fetched_order_book

    def path_order_book(self):
        '''function to transform the orderbook info retrieved from request to a usable format for the model'''
        self.order_book = {}
        if len(self.path) > 0:
            thread_num = len(self.path)
            fetched_order_book_list = multiThread(self.parallel_fetch_order_book, self.path, thread_num)

        for index, i in enumerate(self.path):
            self.order_book[i] = {}
            reverse = False
            first_exchange, first_cur = i[0].split('_')
            sec_exchange, sec_cur = i[1].split('_')

            if first_exchange == sec_exchange:
                pair = '{}/{}'.format(first_cur, sec_cur)
                if pair not in self.pair_info[first_exchange]:
                    reverse = True

                self.order_book[i]['reverse'] = reverse
                fetched_order_book = fetched_order_book_list[index]

                if reverse:
                    asks = np.array(fetched_order_book['asks'])
                    orders = np.concatenate(
                        (asks[:, 0].reshape(-1, 1), np.cumsum(asks[:, 1], axis=0).reshape(-1, 1)),
                        axis=1)
                    self.order_book[i]['orders'] = orders[:self.orderbook_n, :]
                else:
                    bids = np.array(fetched_order_book['bids'])
                    orders = np.concatenate(
                        (bids[:, 0].reshape(-1, 1), np.cumsum(bids[:, 1], axis=0).reshape(-1, 1)),
                        axis=1)
                    self.order_book[i]['orders'] = orders[:self.orderbook_n, :]
            else:
                self.order_book[i]['reverse'] = reverse
                order_book = np.tile(np.array([[1, 0]]), (self.orderbook_n, 1))
                order_book[0][1] = self.big_m  # infinity amount for inter exchange transfer
                self.order_book[i]['orders'] = order_book

    def have_workable_solution(self):
        '''return whether the model has workable solution'''
        return len(self.trade_solution) > 0 and self.objective_value > 0
