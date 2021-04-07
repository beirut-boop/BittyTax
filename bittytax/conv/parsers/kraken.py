# -*- coding: utf-8 -*-
# (c) Nano Nano Ltd 2020

import sys

from decimal import Decimal

from ..out_record import TransactionOutRecord
from ..dataparser import DataParser
from ..exceptions import UnexpectedTypeError, UnexpectedTradingPairError

from colorama import Fore, Back

WALLET = "Kraken"

QUOTE_ASSETS =  ['AUD', 'CAD', 'CHF', 'DAI', 'ETH', 'EUR', 'GBP', 'JPY', 'USD', 'USDC',
                 'USDT', 'XBT', 'XETH', 'XXBT', 'ZCAD', 'ZEUR', 'ZGBP', 'ZJPY', 'ZUSD']

ALT_ASSETS = {"KFEE": "FEE", "XETC": "ETC", "XETH": "ETH", "XLTC": "LTC", "XMLN": "MLN",
              "XREP": "REP", "XXBT": "XBT", "XXDG": "XDG", "XXLM": "XLM", "XXMR": "XMR",
              "XXRP": "XRP", "XZEC": "ZEC", "ZAUD": "AUD", "ZCAD": "CAD", "ZEUR": "EUR",
              "ZGBP": "GBP", "ZJPY": "JPY", "ZUSD": "USD"}


# https://support.kraken.com/hc/en-us/articles/360001169383-How-to-interpret-Ledger-history-fields
def parse_kraken_deposits_withdrawals(data_rows, parser, _filename, data_files):
    data_groups = {}
    refid_idx = parser.header.index('refid')
    txid_idx = parser.header.index('txid')
    type_idx = parser.header.index('type')
    time_idx = parser.header.index('time')
    asset_idx = parser.header.index('asset')
    amount_idx = parser.header.index('amount')
    fee_idx = parser.header.index('fee')

    # We need trade data
    if not hasattr(parser, 'kraken_trades'):
        parser.kraken_trades = trades = {}
        for (key, data_file) in data_files.items():
            if data_file.parser.worksheet_name == 'Kraken T':
                trades_header = data_file.parser.header
                for row in data_file.data_rows:
                    if row.in_row[trades_header.index('txid')] != '' and row.in_row[trades_header.index('type')] in ['buy', 'sell']:
                        trades[row.in_row[trades_header.index('txid')]] = row
    else:
        trades = parser.kraken_trades

    if not len(trades):
        sys.stderr.write(
            "%sWARNING%s Kraken Trades (Kraken T) need to be imported BEFORE ledgers (Kraken D,W) for margin trades.%s\n" % (
                Back.YELLOW + Fore.BLACK, Back.RESET + Fore.YELLOW, Fore.RESET))

    for row in data_rows:
        if row.in_row[txid_idx] != '':
            data_groups.setdefault(row.in_row[refid_idx], []).append(row)

    for row in data_rows:
        if row.in_row[txid_idx] == '':
            continue
        type = row.in_row[type_idx]
        amount = row.in_row[amount_idx]
        fee = row.in_row[fee_idx]
        row.timestamp = timestamp = DataParser.parse_timestamp(row.in_row[time_idx])
        transaction_type = TransactionOutRecord.TYPE_TRADE
        buy_quantity = sell_quantity = None
        fee_quantity = fee
        buy_asset = sell_asset = fee_asset = normalise_asset(row.in_row[asset_idx])

        if type == 'deposit':
            transaction_type = TransactionOutRecord.TYPE_DEPOSIT
            sell_asset = None
            buy_quantity = amount
        elif type == 'withdrawal':
            transaction_type = TransactionOutRecord.TYPE_WITHDRAWAL
            buy_asset = None
            sell_quantity = abs(Decimal(amount))
        elif type in ['trade', 'margin', 'rollover', 'transfer']:
            buy_quantity = sell_quantity = '0'
            fee_quantity = fee
            if float(amount) > 0:
                buy_quantity = amount
                if type == 'transfer':
                    sell_asset = None
                    sell_quantity = None
                    transaction_type = TransactionOutRecord.TYPE_GIFT_RECEIVED
            else:
                sell_quantity = abs(Decimal(amount))
                if type == 'transfer':
                    transaction_type = TransactionOutRecord.TYPE_TRADE
        else:
            sys.stderr.write(
                "%sWARNING%s Unsupported type: 'Kraken:%s'. Audit will not match.%s\n" % (
                    Back.YELLOW + Fore.BLACK, Back.RESET + Fore.YELLOW, type, Fore.RESET))

        row.t_record = TransactionOutRecord(transaction_type, timestamp,
                                            buy_quantity=buy_quantity,
                                            buy_asset=buy_asset,
                                            sell_quantity=sell_quantity,
                                            sell_asset=sell_asset,
                                            fee_quantity=fee_quantity,
                                            fee_asset=fee_asset,
                                            wallet=WALLET)


# https://support.kraken.com/hc/en-us/articles/360001184886-How-to-interpret-Trades-history-fields
def parse_kraken_trades(data_row, parser, _filename):
    # Do nothing. Just load trades for reference.
    data_row.timestamp = DataParser.parse_timestamp(data_row.in_row[parser.header.index('time')])
    data_row.parsed = True


def split_trading_pair(trading_pair):
    for quote_asset in sorted(QUOTE_ASSETS, reverse=True):
        if trading_pair.endswith(quote_asset):
            return trading_pair[:-len(quote_asset)], quote_asset

    return None, None


def normalise_asset(asset):
    if asset in ALT_ASSETS:
        asset = ALT_ASSETS.get(asset)

    if asset == "XBT":
        return "BTC"
    return asset


DataParser(DataParser.TYPE_EXCHANGE,
           "Kraken Deposits/Withdrawals",
           ['txid', 'refid', 'time', 'type', 'subtype', 'aclass', 'asset', 'amount', 'fee',
            'balance'],
           worksheet_name="Kraken D,W",
           all_handler=parse_kraken_deposits_withdrawals)

DataParser(DataParser.TYPE_EXCHANGE,
           "Kraken Trades",
           ['txid', 'ordertxid', 'pair', 'time', 'type', 'ordertype', 'price', 'cost', 'fee', 'vol',
            'margin', 'misc', 'ledgers', 'postxid', 'posstatus', 'cprice', 'ccost', 'cfee', 'cvol',
            'cmargin', 'net', 'trades'],
           worksheet_name="Kraken T",
           row_handler=parse_kraken_trades)

DataParser(DataParser.TYPE_EXCHANGE,
           "Kraken Trades",
           ['txid', 'ordertxid', 'pair', 'time', 'type', 'ordertype', 'price', 'cost', 'fee', 'vol',
            'margin', 'misc', 'ledgers'],
           worksheet_name="Kraken T",
           row_handler=parse_kraken_trades)
