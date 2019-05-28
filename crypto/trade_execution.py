import time
from .utils import killable_multiThread


class TradeExecutor:
    '''
    class to execute trades in the arbitrage path when given solution from
    '''
    tasks = None  # a dict to record all the tasks, for the convenience of later parallel execution
    order_waiting_time = 30  # maximum time to wait for an order to be executed

    def __init__(self, PathOptimizer):
        self.exchanges = PathOptimizer.exchanges

    def execute(self, solution):
        '''the function to be used by user to execute the arbitrage solution'''
        self.task_assign(solution)
        input_params = [i for i in self.tasks.keys() if i != 'inter_ex']
        num = len(input_params)
        succeed = killable_multiThread(self.single_task, input_params, num)
        if all(succeed) and 'inter_ex' in self.tasks:
            inter_ex_trades = self.tasks['inter_ex']
            for key, val in inter_ex_trades:
                self.execute_trade(key, val)

    def single_task(self, param, event):
        '''the function to be used in multithread wrapper to execute trades'''
        trade_list = self.tasks[param]
        for key, val in trade_list:
            if not event.isSet():
                succeed = self.execute_trade(key, val)
                if not succeed:
                    event.set()
            else:
                succeed = False
                break

        return succeed

    def task_assign(self, solution):
        '''function to assign trading order and threads'''
        self.tasks = {}
        task_num = 0
        for key, val in solution.items():
            first_exc = key[0].split('_')[0]
            sec_exc = key[1].split('_')[0]
            if first_exc == sec_exc:
                if task_num not in self.tasks:
                    self.tasks[task_num] = [(key, val)]
                else:
                    self.tasks[task_num].append((key, val))
            else:
                if 'inter_ex' not in self.tasks:
                    self.tasks['inter_ex'] = [(key, val)]
                else:
                    self.tasks['inter_ex'].append((key, val))
                task_num += 1

    def execute_trade(self, key, val):
        '''function to execute single trade when given key and val'''
        first_exc = key[0].split('_')[0]
        sec_exc = key[1].split('_')[0]
        if first_exc == sec_exc:
            order_info = self.intra_exc_trade(key, val)
            succeed = self.wait_and_cancel(order_info, first_exc)
        else:
            self.inter_exc_trade(key, val)
            succeed = True

        return succeed

    def intra_exc_trade(self, key, val):
        '''function to execute intra exchange trades'''
        exc_name = key[0].split('_')[0]
        exchange = self.exchanges[exc_name]

        symbol = '/'.join((key[0].split('_')[-1], key[1].split('_')[-1]))
        type = 'limit'
        side = val['direction'].split('_')[-1]
        amount = val['vol']
        price = val['price']

        return exchange.create_order(
            symbol=symbol,
            type=type,
            side=side,
            amount=amount,
            price=price
        )

    def inter_exc_trade(self, key, val):
        '''function to execute inter exchange trades'''
        exc_name, coin = key[0].split('_')
        target_exc_name = key[1].split('_')[0]
        exchange = self.exchanges[exc_name]
        target_exchange = self.exchanges[target_exc_name]

        address_info = target_exchange.fetch_deposit_address(coin)
        address = address_info['address']
        tag = address_info['tag']
        code = coin
        amount = val['vol']

        if exc_name == 'kucoin':
            self.kucoin_transfer_to('main', exchange, amount, code)

        exchange.withdraw(
            code=code,
            amount=amount,
            address=address,
            tag=tag
        )

    def wait_and_cancel(self, order_info, exc_name):
        '''
        function to wait for a certain amount of time when an ordered is placed.
        If the order got executed in the given amount of time, it return True.
        If the order didn't get executed, it will cancel the order and return False
        '''
        closed = False
        id = order_info['info']['orderId']
        symbol = order_info['symbol']
        exchange = self.exchanges[exc_name]
        start = time.clock()

        while time.clock() - start <= self.order_waiting_time:
            if exchange.fetch_order_status(id, symbol) != 'closed':
                time.sleep(0.2)
            else:
                closed = True
                break

        if not closed:
            exchange.cancel_order(id, symbol)
            succeed = False
        else:
            succeed = True

        return succeed

    @staticmethod
    def kucoin_transfer_to(to, exchange, amount, code):
        '''function to transfer amount between main and trading account in kucoin'''
        accounts = exchange.privateGetAccounts()
        data = accounts['data']
        for i in data:
            if i['currency'] == code and i['type'] == 'main':
                main_id = i['id']
            elif i['currency'] == code and i['type'] == 'trade':
                trade_id = i['id']
            else:
                pass

        if to == 'main':
            from_id, to_id = trade_id, main_id
        elif to == 'trade':
            from_id, to_id = main_id, trade_id
        else:
            raise ValueError('to should be main or trade')

        exchange.private_post_accounts_inner_transfer(
            {
                'clientOid': exchange.uuid(),
                'payAccountId': from_id,
                'recAccountId': to_id,
                'amount': amount
            }
        )

    def kucoin_move_to_trade(self):
        '''function to move all the coins to trading account on kucoin'''
        accounts = self.exchanges['kucoin'].privateGetAccounts()
        transfer_list = [(i['balance'], i['currency']) for i in accounts['data'] if
                         i['type'] == 'main' and float(i['balance']) > 0]
        for amount, code in transfer_list:
            self.kucoin_transfer_to('trade', self.exchanges['kucoin'], amount, code)
