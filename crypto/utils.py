import requests
from lxml import html
import re
from requests import Session
import json
import threading
import datetime
import pytz


def get_withdrawal_fees(exchange, trading_size=1000):
    '''
    function to get the withdrawal fees of each exchanges on website https://withdrawalfees.com/
    will also calculate the withdrawal fee percentage based on an approximate trading size
    '''

    withdrawal_fee = {}
    response = requests.get('https://withdrawalfees.com/exchanges/{}'.format(exchange))
    if response.ok:
        tree = html.fromstring(response.content)

        for ele in tree.xpath('//tbody//tr'):
            coin_name = ele.xpath('.//div[@class="symbol"]/text()')[0]
            usd_fee = ele.xpath('.//td[@class="withdrawalFee"]//div[@class="usd"]/text()')[0]
            coin_fee = ele.xpath('.//td[@class="withdrawalFee"]//div[@class="fee"]/text()')[
                0] if usd_fee != 'FREE' else 'FREE'

            usd_fee = 0 if usd_fee == 'FREE' else float(re.findall(r'[0-9\.]+', usd_fee)[0])
            coin_fee = 0 if coin_fee == 'FREE' else float(re.findall(r'[0-9\.]+', coin_fee)[0])

            withdrawal_fee[coin_name] = {
                'usd_fee': usd_fee,
                'usd_rate': usd_fee / trading_size,
                'coin_fee': coin_fee
            }
        return withdrawal_fee

    else:
        raise ValueError('{} is not an exchange supported by withdrawalfees.com'.format(exchange))


def get_crypto_prices(coin_set, convert='USD'):
    '''fetch crypto currencies price from coin market cap api'''
    coin_set = set([i for i in coin_set if i.isalnum()])
    output = {}
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest'
    parameters = {
        'symbol': ','.join(coin_set),
        'convert': convert
    }
    headers = {
        'Accepts': 'application/json',
        'X-CMC_PRO_API_KEY': 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
    }

    session = Session()
    session.headers.update(headers)
    response = session.get(url, params=parameters)
    data = json.loads(response.text)

    if response.ok:
        for key, val in data['data'].items():
            output[key] = {
                'price': val['quote']['USD']['price'],
                'cmc_rank': val['cmc_rank']
            }
    else:
        if response.status_code == 400:
            msg = data['status']['error_message']
            not_avail_coins = re.findall(r'[0-9A-Z]+', msg.split(':')[-1])
            new_coin_set = coin_set - set(not_avail_coins)
            output = get_crypto_prices(new_coin_set, convert)
        else:
            raise ConnectionError

    return output


def eachThread(func, num, partList, localVar, outputList):
    '''A helper function for each thread.'''
    output = ''
    localVar.num = num
    localVar.partList = partList
    localVar.output = output
    for i in range(len(num)):
        try:
            output = func(partList[i])
            outputList.append((num[i], output))
        except:
            outputList.append((num[i], None))


def multiThread(func, List, threadNum):
    '''A multi threading decorator.
       func: the function to be implemented in multi-threaded way.
       List: the input list.
       threadNum: the number of threads used, can be adjusted for different tasks.
    '''
    List = list(List)
    localVar = threading.local()
    outputList = []
    line = []
    for i in range(threadNum):
        num = range(i, len(List), threadNum)
        partList = [List[j] for j in num]
        t = threading.Thread(target=eachThread, args=(func, num, partList, localVar, outputList))
        line.append(t)
        t.start()
    for t in line:
        t.join()
    outputList = sorted(outputList, key=lambda x: x[0])
    outputList = [x[1] for x in outputList]

    return outputList


def killable_eachThread(func, num, partList, localVar, outputList, event):
    '''A helper function for each thread'''
    output = ''
    localVar.num = num
    localVar.partList = partList
    localVar.output = output
    for i in range(len(num)):
        try:
            output = func(partList[i], event)
            outputList.append((num[i], output))
        except:
            outputList.append((num[i], None))


def killable_multiThread(func, List, threadNum):
    '''A multi threading decorator that provides the function when one thread stops, it kills all the other threads
       func: the function to be implemented in multi-threaded way.
       List: the input list.
       threadNum: the number of threads used, can be adjusted for different tasks.
    '''
    event = threading.Event()
    List = list(List)
    localVar = threading.local()
    outputList = []
    line = []
    for i in range(threadNum):
        num = range(i, len(List), threadNum)
        partList = [List[j] for j in num]
        t = threading.Thread(target=killable_eachThread, args=(func, num, partList, localVar, outputList, event))
        line.append(t)
        t.start()
    for t in line:
        t.join()
    outputList = sorted(outputList, key=lambda x: x[0])
    outputList = [x[1] for x in outputList]

    return outputList


def opp_and_solution_txt(path_optimizer, amt_optimizer):
    '''output the print content from path_optimizer and amt_optimizer'''
    tz = pytz.timezone('Asia/Singapore')
    time = str(datetime.datetime.now().astimezone(tz))
    print1 = path_optimizer.print_content
    print2 = amt_optimizer.print_content if path_optimizer.have_opportunity() else ''
    output = '-------------------------------\n{}\n{}\n{}\n\n'.format(time, print1, print2)

    return output


def save_to_file(output):
    '''save the print content to be in record.txt file'''
    with open('record.txt', 'r') as f:
        original = f.read()
    with open('record.txt', 'w') as f:
        to_save = original + output
        f.write(to_save)


def save_record(path_optimizer, amt_optimizer):
    output = opp_and_solution_txt(path_optimizer, amt_optimizer)
    save_to_file(output)
