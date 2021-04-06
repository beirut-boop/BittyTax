# -*- coding: utf-8 -*-
# (c) Nano Nano Ltd 2020

import sys
import copy

from decimal import Decimal, Context

from ..out_record import TransactionOutRecord
# from ..datarow import DataRow
from ..dataparser import DataParser
from ..exceptions import UnexpectedTypeError, UnexpectedTradingPairError

from colorama import Fore, Back

WALLET = "Kraken"

QUOTE_ASSETS = ['AUD', 'CAD', 'CHF', 'DAI', 'ETH', 'EUR', 'GBP', 'JPY', 'USD', 'USDC',
                'USDT', 'XBT', 'XETH', 'XXBT', 'ZCAD', 'ZEUR', 'ZGBP', 'ZJPY', 'ZUSD']

ALT_ASSETS = {"KFEE": "FEE", "XETC": "ETC", "XETH": "ETH", "XLTC": "LTC", "XMLN": "MLN",
              "XREP": "REP", "XXBT": "XBT", "XXDG": "XDG", "XXLM": "XLM", "XXMR": "XMR",
              "XXRP": "XRP", "XZEC": "ZEC", "ZAUD": "AUD", "ZCAD": "CAD", "ZEUR": "EUR",
              "ZGBP": "GBP", "ZJPY": "JPY", "ZUSD": "USD"}


def parse_kraken_deposits_withdrawals(data_row, _parser, _filename, _data_files, _data_rows):
    if data_row.parsed:
        return

    # https://support.kraken.com/hc/en-us/articles/360001169383-How-to-interpret-Ledger-history-fields
    in_row = data_row.in_row
    data_row.timestamp = DataParser.parse_timestamp(in_row[2])

    if in_row[3] == "deposit" and in_row[0] != "":
        # Check for txid to filter failed transactions
        data_row.t_record = TransactionOutRecord(TransactionOutRecord.TYPE_DEPOSIT,
                                                 data_row.timestamp,
                                                 buy_quantity=in_row[7],
                                                 buy_asset=normalise_asset(in_row[6]),
                                                 fee_quantity=in_row[8],
                                                 fee_asset=normalise_asset(in_row[6]),
                                                 wallet=WALLET)
    elif in_row[3] == "withdrawal" and in_row[0] != "":
        data_row.t_record = TransactionOutRecord(TransactionOutRecord.TYPE_WITHDRAWAL,
                                                 data_row.timestamp,
                                                 sell_quantity=abs(Decimal(in_row[7])),
                                                 sell_asset=normalise_asset(in_row[6]),
                                                 fee_quantity=in_row[8],
                                                 fee_asset=normalise_asset(in_row[6]),
                                                 wallet=WALLET)
    elif in_row[3] == "transfer" and in_row[0] != "":
        if float(in_row[7]) >= 0:
            # Positive transfers are forks and airdrops
            data_row.t_record = TransactionOutRecord(TransactionOutRecord.TYPE_GIFT_RECEIVED,
                                                     data_row.timestamp,
                                                     buy_quantity=in_row[7],
                                                     buy_asset=normalise_asset(in_row[6]),
                                                     fee_quantity=in_row[8],
                                                     fee_asset=normalise_asset(in_row[6]),
                                                     wallet=WALLET)
        else:
            # Negative transfers are delisted assets
            data_row.t_record = TransactionOutRecord(TransactionOutRecord.TYPE_SPEND,
                                                     data_row.timestamp,
                                                     sell_quantity=abs(Decimal(in_row[7])),
                                                     sell_asset=normalise_asset(in_row[6]),
                                                     fee_quantity=in_row[8],
                                                     fee_asset=normalise_asset(in_row[6]),
                                                     wallet=WALLET)
    elif in_row[3] == "rollover" and in_row[0] != "":
        # Margin positions eat a lot of fees. We need to apply them for a correct balance.
        # Type: rollover - interest on open margin positions.
        # Fee only transactions result in "Missing data for Buy Quantity" errors, but we need to discard of it somehow
        # so let's fake a sell of 10% the fee's value
        data_row.t_record = TransactionOutRecord(TransactionOutRecord.TYPE_TRADE, # TYPE_SELL
                                                 data_row.timestamp,
                                                 buy_quantity='0.00',
                                                 buy_asset=normalise_asset(in_row[6]),
                                                 sell_quantity='0.00',
                                                 sell_asset=normalise_asset(in_row[6]),
                                                 fee_quantity=in_row[8],
                                                 fee_asset=normalise_asset(in_row[6]),
                                                 wallet=WALLET)
        # awert= 234



def parse_kraken_trades(data_row, parser, _filename, _data_files, _data_rows):
    if data_row.parsed:
        return

    # https://support.kraken.com/hc/en-us/articles/360001184886-How-to-interpret-Trades-history-fields
    # We need a ledger for fee calculation
    if not hasattr(parser, 'kraken_ledger'):
        parser.kraken_ledger = ledger = {}
        for (key, data_file) in _data_files.items():
            if data_file.parser.worksheet_name == 'Kraken D,W':
                ## order the files
                refid_idx = data_file.parser.header.index('refid')
                txid_idx = data_file.parser.header.index('txid')
                type_idx = data_file.parser.header.index('type')
                for row in data_file.data_rows:
                    if row.in_row[txid_idx] != '' and row.in_row[type_idx] in ['trade', 'margin']:
                        ledger.setdefault(row.in_row[refid_idx], []).append(row)
    else:
        ledger = parser.kraken_ledger

    if not len(parser.kraken_ledger):
        sys.stderr.write(
            "%sWARNING%s Kraken ledgers (Kraken D,W) need to be imported BEFORE trades (Kraken T) for proper fee calculation.%s\n" % (
                Back.YELLOW + Fore.BLACK, Back.RESET + Fore.YELLOW, Fore.RESET))

    in_row = data_row.in_row
    data_row.timestamp = DataParser.parse_timestamp(in_row[3])

    base_asset, quote_asset = split_trading_pair(in_row[2])
    if base_asset is None or quote_asset is None:
        raise UnexpectedTradingPairError(2, parser.in_header[2], in_row[2])

    if data_row.in_row[3].startswith('2016-10-23 05:44:12'):
        debuggertoo = True

    ctx = Context()
    ctx.prec = 13

    # Get fees from Ledger
    txid = in_row[0]
    fee_asset = normalise_asset(quote_asset)
    fee_quantity = in_row[8]
    fees = {}
    if txid in ledger:
        for row in ledger[txid]:
            ledger_fee_asset = normalise_asset(row.in_row[6])
            ledger_fee_quantity = float(row.in_row[8])
            if ledger_fee_quantity:
                fees[ledger_fee_asset] = fees.get(ledger_fee_asset, 0) + ledger_fee_quantity
        for asset in fees:
            # Use the first fee in this trade, additional fees will be added below
            fee_asset = asset
            fee_quantity = format(ctx.create_decimal(repr(fees[asset])), 'f')
            break
        if len(fees) >= 1:
            del fees[fee_asset]

    if in_row[4] == "buy":
        data_row.t_record = TransactionOutRecord(TransactionOutRecord.TYPE_TRADE,
                                                 data_row.timestamp,
                                                 buy_quantity=in_row[9],
                                                 buy_asset=normalise_asset(base_asset),
                                                 sell_quantity=in_row[7],
                                                 sell_asset=normalise_asset(quote_asset),
                                                 fee_quantity=fee_quantity,
                                                 fee_asset=fee_asset,
                                                 wallet=WALLET)
    elif in_row[4] == "sell":
        data_row.t_record = TransactionOutRecord(TransactionOutRecord.TYPE_TRADE,
                                                 data_row.timestamp,
                                                 buy_quantity=in_row[7],
                                                 buy_asset=normalise_asset(quote_asset),
                                                 sell_quantity=in_row[9],
                                                 sell_asset=normalise_asset(base_asset),
                                                 fee_quantity=fee_quantity,
                                                 fee_asset=fee_asset,
                                                 wallet=WALLET)
    else:
        raise UnexpectedTypeError(4, parser.in_header[4], in_row[4])

    # If fees were taken from multiple assets, we need to update those assets by adding an emtpy trade with fee.
    # Fee only transactions are not possible, so let's fake a sell of 10% the fee's value.
    if len(fees):
        for asset in fees:
            fee_asset = asset
            fee_quantity = format(ctx.create_decimal(repr(fees[asset])), 'f')
            ## fee_data_row = DataRow(data_row.line_num, data_row.in_row)
            ##fee_data_row = copy.copy(data_row)
            ##fee_data_row.parsed = True
            ## fee_data_row.t_record = TransactionOutRecord(TransactionOutRecord.TYPE_TRADE,
            #data_row.t_record = TransactionOutRecord(TransactionOutRecord.TYPE_TRADE,
            #                                             data_row.timestamp,
            #                                             buy_quantity='0.00',
            #                                             buy_asset=fee_asset,
            #                                             sell_quantity='0.00',
            #                                             sell_asset=fee_asset,
            #                                             fee_quantity=fee_quantity,
            #                                             fee_asset=fee_asset,
            #                                             wallet=WALLET)
            # _data_rows.append(fee_data_row)
            # This is not working. Final audit is still broken.


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
           row_handler=parse_kraken_deposits_withdrawals)

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
