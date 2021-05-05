from tda.auth import easy_client
from tda.client import Client
from tda.streaming import StreamClient
from tda import orders
import asyncio
import pprint
from datetime import date
from datetime import timedelta
from datetime import datetime
from datetime import time
from time import sleep
import json
import atexit
import logging
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates




class BackTesting:
    """
    We use a class to enforce good code organization practices
    """

    def __init__(self, api_key_filename, account_id_filename, queue_size=1,
                 credentials_path='token.json'):
        """
        We're storing the configuration variables within the class for easy
        access later in the code!
        """
        self.api_key = self.read_APIKEY(api_key_filename)
        self.account_id = self.read_AccountID(account_id_filename)
        self.credentials_path = credentials_path
        self.tda_client = None
        self.Account = {'PL_LOCKED':0, 'CURRENT_PL':0, 'LIQUID_VALUE':0, 'CASH_AVAIL_FOR_TRADING':0, 'DAY_TRADES':0}
        self.symbols = ['AAPL']
        self.date = datetime(2021, 2, 22) # datetime(year, month, day)
        self.currentPosition = {'SYMBOL':'', 'PRICE':0, 'TYPE':0, 'QUANTITY':0}

        # Create a queue so we can queue up work gathered from the client
        self.queue = asyncio.Queue(queue_size)

    def initialize(self):
        """
        Create the clients and log in. Using easy_client, we can get new creds
        from the user via the web browser if necessary
        """
        self.tda_client = easy_client(
            api_key=self.api_key,
            redirect_uri='https://localhost',
            token_path=self.credentials_path)
        self.stream_client = StreamClient(
            self.tda_client, account_id=self.account_id)


        #Initialize the App with 
        accinfohttp = self.tda_client.get_account(self.account_id, fields=None)
        acc_info = json.loads(accinfohttp.content.decode('utf-8'))
        self.Account['LIQUID_VALUE'] = acc_info['securitiesAccount']['currentBalances']['liquidationValue']
        self.Account['CASH_AVAIL_FOR_TRADING'] = acc_info['securitiesAccount']['currentBalances']['availableFundsNonMarginableTrade']


        logging.basicConfig(filename="example.log",level=logging.DEBUG)
       

    def read_APIKEY(self, filename):
        """
        Takes the text file name and reads the API key.
        It assumes that only first line is the API Key. More checks could be added later.
        """
        with open(filename,'r') as fd:
            APIKey = fd.readline() + "@AMER.OAUTHAP"
        return APIKey
    
    def read_AccountID(self,filename):
        """
        Takes the filename and reads the account id.
        """
        with open(filename,'r') as fd:
            ACCOUNT_ID = int(fd.readline())

        return ACCOUNT_ID

        
    async def handle_minute_equity(self, msg):
        """
        This is where we take msgs from the streaming client and put them on a
        queue for later consumption. We use a queue to prevent us from wasting
        resources processing old data, and falling behind.
        """
        # if the queue is full, make room
        if self.queue.full():
            await self.queue.get()
        await self.queue.put(msg)

    


    def getPriceHistory(self, symbol):
        start_date = datetime(self.date.year, self.date.month, self.date.day, 9, 30, 0)
        end_date = datetime(self.date.year, self.date.month, self.date.day, 16, 0, 0)
        r = self.tda_client.get_price_history(symbol,
        period_type=Client.PriceHistory.PeriodType.DAY,
        frequency_type=Client.PriceHistory.FrequencyType.MINUTE,
        frequency=Client.PriceHistory.Frequency.EVERY_MINUTE,
        start_datetime=start_date,
        end_datetime=end_date)
        hist = json.loads(r.content.decode('utf-8'))
        candles = hist['candles']
        return candles

    def backTest(self):
        prev_set = False
        candles = self.getPriceHistory(self.symbols[0])
        start_date = datetime(self.date.year, self.date.month, self.date.day, 9, 30, 0)
        end_date = datetime(self.date.year, self.date.month, self.date.day, 16, 0, 0)
        pl = {'PROFIT/LOSS': [0 for x in range(len(candles))], 'TIME': [datetime.fromtimestamp(candle['datetime'] / 1e3) for candle in candles]}
        i = 0
        for candle in candles:
            new_candle = {'OPEN': candle['open'], 'CLOSE': candle['close'], 'LOW': candle['low'], 'HIGH': candle['high'], 'TIME': candle['datetime']/1e3}
            if prev_set == True:
                HA_candle = self.heikin_ashi(new_candle,prev_candle)
                signal = self.bs_signal(HA_candle) #This is where our different analysis will go to tell whether to buy call or puts
                quantity = self.getQuantity(new_candle)
                self.handle_trade(signal, quantity, new_candle)
                prev_candle = HA_candle
            else:
                prev_set = True
                prev_candle = new_candle
           
            pl['PROFIT/LOSS'][i] = self.Account['CURRENT_PL']
            i = i+1
        return pl
    
    def plot(self, pl):
        fmt = mdates.DateFormatter('%H:%M')

        fig, ax = plt.subplots()
        ax.plot(pl['TIME'],pl['PROFIT/LOSS'])
        ax.xaxis.set_major_formatter(fmt)
        plt.show()

    def getQuantity(self,candle):
        start = time(9, 30, 00)
        end = time(16, 0, 0)
        marketOpen = datetime(self.date.year, self.date.month, self.date.day, start.hour, start.minute).timestamp()
        marketClose = datetime(self.date.year, self.date.month, self.date.day, end.hour, end.minute).timestamp()
        if candle['TIME'] >= marketOpen and candle['TIME'] < marketClose:
            return 1
        else:
            return 0



    def handle_trade(self, signal, quantity, candle):
        start = time(9, 30, 00)
        end = time(16, 0, 0)
        marketOpen = datetime(self.date.year, self.date.month, self.date.day, start.hour, start.minute).timestamp()
        marketClose = datetime(self.date.year, self.date.month, self.date.day, end.hour, end.minute).timestamp()
        if signal !=0 and candle['TIME'] >= marketOpen and candle['TIME'] < marketClose:
            if self.currentPosition['TYPE'] == 0: #Begining of the trading day.
                #Buy option and set the current position

                self.currentPosition['TYPE'] = signal
                self.currentPosition['SYMBOL'] = self.symbols[0]
                self.currentPosition['PRICE'] = candle['CLOSE']
                self.currentPosition['QUANTITY'] = quantity
            else:
                #Get the current ASK and BID from self.Account['SYMBOL']
                #self.Account['DAYS_PL'] = previous ask - current bid of the exiting position
                if self.currentPosition['TYPE'] == -1:
                    #ask = OC['putExpDateMap'][self.currentPosition['DATE']][self.currentPosition['STRIKE_PRICE']][0]['ask']
                    self.Account['PL_LOCKED'] = self.Account['PL_LOCKED'] + (self.currentPosition['PRICE'] - candle['CLOSE']) * quantity 

                else:
                    #ask = OC['callExpDateMap'][self.currentPosition['DATE']][self.currentPosition['STRIKE_PRICE']][0]['ask']
                    self.Account['PL_LOCKED'] = self.Account['PL_LOCKED'] + (candle['CLOSE'] - self.currentPosition['PRICE']) * quantity 

                
                self.Account['DAY_TRADES'] = self.Account['DAY_TRADES'] + 1 


                
                #Update the current position with the new opened trade
                self.currentPosition['TYPE'] = signal
                self.currentPosition['SYMBOL'] = self.symbols[0]
                self.currentPosition['PRICE'] = candle['CLOSE']
                self.currentPosition['QUANTITY'] = quantity
        
            #trade  = self.placeTrade(Option['SYMBOL'])
            #print('Trade Sent')
        if self.currentPosition['TYPE'] == -1:
            #ask = OC['putExpDateMap'][self.currentPosition['DATE']][self.currentPosition['STRIKE_PRICE']][0]['ask']
            self.Account['CURRENT_PL'] = self.Account['PL_LOCKED'] + (self.currentPosition['PRICE'] - candle['CLOSE']) * quantity 

        else:
            #ask = OC['callExpDateMap'][self.currentPosition['DATE']][self.currentPosition['STRIKE_PRICE']][0]['ask']
            self.Account['CURRENT_PL'] = self.Account['PL_LOCKED'] + (candle['CLOSE'] - self.currentPosition['PRICE']) * quantity 
        print('Current PL is ${}'.format(self.Account['CURRENT_PL'])) 
        return

    """
        Keep track of current order id
        Based on BS signal (-1,0,1) - based on signal value it gets the option to place
        if(-1 or 1):
            exits the current order
            places the new order
    """
            
    """                    
    async def check_balance(self):
        accinfohttp = self.tda_client.get_account(self.account_id, fields=None)
        acc_info = json.loads(accinfohttp.content.decode('utf-8'))
        #Update PL = (New liquid - Old liquid)
        self.Account['PL_LOCKED'] = self.Account['PL_LOCKED'] + (acc_info['securitiesAccount']['currentBalances']['liquidationValue'] - self.Account['LIQUID_VALUE']) 
        self.Account['LIQUID_VALUE'] = acc_info['securitiesAccount']['currentBalances']['liquidationValue']
        self.Account['CASH_AVAIL_FOR_TRADING'] = acc_info['securitiesAccount']['currentBalances']['cashAvailableForTrading']
        #print('Your liquidation balance is ${}'.format(balance))
            
    async def update_account(self,time_in_seconds):
        while True:
            await asyncio.sleep(time_in_seconds)
            #self.check_balance()
            #logging.debug('Liquid Value is %d' %(self.Account['LIQUID_VALUE']))
            #print('Liquid Balance is ${}'.format(self.Account['LIQUID_VALUE']))
            #print('Cash Avail For Trading is ${}'.format(self.Account['CASH_AVAIL_FOR_TRADING']))
            print('Days PL is ${}'.format(self.Account['PL_LOCKED']))
    """


    def bs_signal(self, candle):
        """
            Here we analyze the HA Candle to see to buy Put or Call
        """
        if candle['CLOSE'] > candle['OPEN'] and self.currentPosition['TYPE'] != 1 :
            print("Buy Call")
            return 1
        elif candle['CLOSE'] > candle['OPEN'] and self.currentPosition['TYPE'] == 1 :
            print("Already in Call Position")
            return 0
        elif candle['CLOSE'] < candle['OPEN'] and self.currentPosition['TYPE'] != -1 :
            print("Buy Put")
            return -1
        else:
            print("Already in Put Position or same Open/Close candle")
            return 0

    def heikin_ashi(self,new_candle, prev_candle):
        HA_candle = {'HIGH':0 , 'LOW':0 , 'OPEN':0 , 'CLOSE':0 }
        HA_candle['CLOSE'] = (new_candle['OPEN'] + new_candle['HIGH'] + new_candle['LOW'] + new_candle['CLOSE'])/4
        HA_candle['OPEN'] = (prev_candle['OPEN'] + prev_candle['CLOSE'])/2
        HA_candle['HIGH'] = max(new_candle['OPEN'],new_candle['HIGH'],new_candle['CLOSE'])
        HA_candle['LOW'] = min(new_candle['OPEN'],new_candle['LOW'],new_candle['CLOSE'])
        HA_candle['TIME'] = new_candle['TIME']
        return HA_candle
    
        

async def main():
    """
    Create and instantiate the consumer, and start the stream
    """
    consumer = BackTesting("API_KEY.txt", "ACCOUNT_ID.txt")
    consumer.initialize()
    pl = consumer.backTest()
    consumer.plot(pl)


if __name__ == '__main__':
    asyncio.run(main())
