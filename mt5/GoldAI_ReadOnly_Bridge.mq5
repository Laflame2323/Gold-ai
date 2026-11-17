// Gold AI — read-only MetaTrader 5 market-data bridge
// Sends completed candles only. This EA never opens, modifies, or closes trades.
// Add https://gold-ai-backend-p9el.onrender.com to MT5 WebRequest allowed URLs.

#property strict
#property version   "1.00"
#property description "Gold AI read-only candle uploader"

input string IngestURL = "https://gold-ai-backend-p9el.onrender.com/broker/mt5/candles";
input string IngestToken = "";
input int    BarsToSend = 100;
input int    TimerSeconds = 10;
input int    RequestTimeoutMs = 15000;

ENUM_TIMEFRAMES Frames[6] = { PERIOD_M1, PERIOD_M5, PERIOD_M15, PERIOD_M30, PERIOD_H1, PERIOD_H4 };
string FrameNames[6] = { "M1", "M5", "M15", "M30", "H1", "H4" };
datetime LastSentBar[6];

string JsonEscape(const string value)
{
   string result = value;
   StringReplace(result, "\\", "\\\\");
   StringReplace(result, "\"", "\\\"");
   return result;
}

bool SendFrame(const int index)
{
   if(StringLen(IngestToken) < 24)
   {
      Print("Gold AI: enter the ingestion token in EA inputs; no data sent.");
      return false;
   }

   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int requested = MathMax(60, MathMin(BarsToSend, 300));
   int copied = CopyRates(_Symbol, Frames[index], 1, requested, rates);
   if(copied < 60)
   {
      Print("Gold AI: waiting for at least 60 completed ", FrameNames[index], " candles. Found ", copied);
      return false;
   }

   datetime newestClosed = rates[copied - 1].time;
   if(LastSentBar[index] == newestClosed)
      return true;

   long offsetSeconds = (long)(TimeTradeServer() - TimeGMT());
   string broker = JsonEscape(AccountInfoString(ACCOUNT_SERVER));
   string symbol = JsonEscape(_Symbol);

   string body = "{";
   body += "\"broker_server\":\"" + broker + "\",";
   body += "\"symbol\":\"" + symbol + "\",";
   body += "\"timeframe\":\"" + FrameNames[index] + "\",";
   body += "\"server_utc_offset_seconds\":" + IntegerToString((int)offsetSeconds) + ",";
   body += "\"candles\":[";

   for(int i = 0; i < copied; i++)
   {
      if(i > 0) body += ",";
      body += "{";
      body += "\"time\":" + IntegerToString((long)rates[i].time) + ",";
      body += "\"open\":" + DoubleToString(rates[i].open, _Digits) + ",";
      body += "\"high\":" + DoubleToString(rates[i].high, _Digits) + ",";
      body += "\"low\":" + DoubleToString(rates[i].low, _Digits) + ",";
      body += "\"close\":" + DoubleToString(rates[i].close, _Digits) + ",";
      body += "\"tick_volume\":" + IntegerToString((long)rates[i].tick_volume) + ",";
      body += "\"real_volume\":" + IntegerToString((long)rates[i].real_volume) + ",";
      body += "\"spread_points\":" + IntegerToString((int)rates[i].spread);
      body += "}";
   }
   body += "]}";

   char requestData[];
   int bytes = StringToCharArray(body, requestData, 0, WHOLE_ARRAY, CP_UTF8);
   if(bytes <= 1)
   {
      Print("Gold AI: could not encode ", FrameNames[index], " payload.");
      return false;
   }
   ArrayResize(requestData, bytes - 1);

   char responseData[];
   string responseHeaders;
   string headers = "Content-Type: application/json\r\nX-MT5-Token: " + IngestToken + "\r\n";
   ResetLastError();
   int httpStatus = WebRequest("POST", IngestURL, headers, RequestTimeoutMs,
                              requestData, responseData, responseHeaders);
   if(httpStatus != 200)
   {
      Print("Gold AI: ", FrameNames[index], " upload failed. HTTP=", httpStatus,
            " MT5 error=", GetLastError(), " Response=",
            CharArrayToString(responseData, 0, -1, CP_UTF8));
      return false;
   }

   LastSentBar[index] = newestClosed;
   Print("Gold AI: uploaded ", copied, " completed ", FrameNames[index],
         " candles for ", symbol, " from ", broker, ".");
   return true;
}

int OnInit()
{
   if(StringLen(IngestToken) < 24)
      Print("Gold AI: configure the private ingestion token in EA inputs before use.");
   EventSetTimer(MathMax(5, TimerSeconds));
   Print("Gold AI read-only bridge started for ", _Symbol,
         ". It sends completed candles only and does not trade.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("Gold AI read-only bridge stopped.");
}

void OnTimer()
{
   for(int i = 0; i < ArraySize(Frames); i++)
      SendFrame(i);
}
