// Gold AI MT5 Read-Only Bridge
// Sends completed XAUUSD candles only. This EA contains no order/trading functions.
#property strict
#property version   "1.00"
#property description "Read-only closed-candle bridge for Gold AI"

input string IngestUrl = "https://gold-ai-backend-p9el.onrender.com/broker/mt5/candles";
input string IngestToken = "PASTE_MT5_INGEST_TOKEN_HERE";
input string GoldSymbol = "XAUUSD";
input int InitialHistoryBars = 500;
input int PollSeconds = 15;
input int RequestTimeoutMs = 15000;

ENUM_TIMEFRAMES Frames[6] = {PERIOD_M1, PERIOD_M5, PERIOD_M15, PERIOD_M30, PERIOD_H1, PERIOD_H4};
string FrameNames[6] = {"M1", "M5", "M15", "M30", "H1", "H4"};
datetime LastSentBar[6];
int TimerSeconds = 15;

string SafeLabel(const string value)
{
   string result = "";
   for(int i = 0; i < StringLen(value); i++)
   {
      ushort ch = StringGetCharacter(value, i);
      bool allowed = ((ch >= 48 && ch <= 57) || (ch >= 65 && ch <= 90) ||
                      (ch >= 97 && ch <= 122) || ch == 45 || ch == 46 || ch == 95);
      if(allowed) result += ShortToString(ch);
   }
   return result;
}

string CandleJson(const MqlRates &bar, const int digits, const int serverOffsetSeconds)
{
   return StringFormat(
      "{\"time\":%I64d,\"open\":%s,\"high\":%s,\"low\":%s,\"close\":%s,\"tick_volume\":%I64u,\"real_volume\":%I64u,\"spread_points\":%d}",
      (long)bar.time - serverOffsetSeconds,
      DoubleToString(bar.open, digits),
      DoubleToString(bar.high, digits),
      DoubleToString(bar.low, digits),
      DoubleToString(bar.close, digits),
      bar.tick_volume, bar.real_volume, (int)bar.spread
   );
}

bool SendBatch(const int index, MqlRates &rates[])
{
   int count = ArraySize(rates);
   if(count <= 0) return false;

   string server = SafeLabel(AccountInfoString(ACCOUNT_SERVER));
   string symbol = SafeLabel(GoldSymbol);
   if(server == "" || symbol == "") return false;

   int digits = (int)SymbolInfoInteger(GoldSymbol, SYMBOL_DIGITS);
   datetime serverNow = TimeTradeServer();
   datetime utcNow = TimeGMT();
   if(serverNow <= 0 || utcNow <= 0) return false;
   int serverOffsetSeconds = (int)(serverNow - utcNow);
   if(MathAbs(serverOffsetSeconds) > 14 * 3600) return false;
   string body = "{\"broker_server\":\"" + server +
                 "\",\"server_utc_offset_seconds\":" + IntegerToString(serverOffsetSeconds) +
                 ",\"symbol\":\"" + symbol +
                 "\",\"timeframe\":\"" + FrameNames[index] +
                 "\",\"candles\":[";
   for(int i = 0; i < count; i++)
   {
      if(i > 0) body += ",";
      body += CandleJson(rates[i], digits, serverOffsetSeconds);
   }
   body += "]}";

   char requestData[];
   int copied = StringToCharArray(body, requestData, 0, WHOLE_ARRAY, CP_UTF8);
   if(copied <= 1) return false;
   ArrayResize(requestData, copied - 1);

   char responseData[];
   string responseHeaders;
   string headers = "Content-Type: application/json\r\nX-MT5-Token: " + IngestToken + "\r\n";
   ResetLastError();
   int status = WebRequest("POST", IngestUrl, headers, RequestTimeoutMs,
                           requestData, responseData, responseHeaders);
   if(status == 200 || status == 201)
   {
      LastSentBar[index] = rates[count - 1].time;
      Print("Gold AI: archived ", count, " closed ", FrameNames[index],
            " candles. Latest bar: ", TimeToString(LastSentBar[index]));
      return true;
   }

   int error = GetLastError();
   Print("Gold AI bridge request failed. HTTP=", status, " terminal_error=", error,
         ". Check URL allow-list, network, and token configuration.");
   return false;
}

void PollTimeframe(const int index)
{
   MqlRates latest[];
   ArraySetAsSeries(latest, false);
   if(CopyRates(GoldSymbol, Frames[index], 1, 1, latest) != 1) return;
   datetime latestClosed = latest[0].time;
   if(latestClosed <= LastSentBar[index]) return;

   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int copied = 0;
   if(LastSentBar[index] == 0)
      copied = CopyRates(GoldSymbol, Frames[index], 1, InitialHistoryBars, rates);
   else
      copied = CopyRates(GoldSymbol, Frames[index],
                         (datetime)(LastSentBar[index] + 1), latestClosed, rates);

   if(copied <= 0) return;
   ArraySetAsSeries(rates, false);
   SendBatch(index, rates);
}

int OnInit()
{
   if(IngestToken == "" || IngestToken == "PASTE_MT5_INGEST_TOKEN_HERE")
   {
      Print("Gold AI: set the private MT5 ingest token in EA inputs before starting.");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(!SymbolSelect(GoldSymbol, true))
   {
      Print("Gold AI: could not select broker symbol ", GoldSymbol);
      return INIT_FAILED;
   }
   TimerSeconds = (PollSeconds < 5 ? 5 : PollSeconds);
   EventSetTimer(TimerSeconds);
   Print("Gold AI read-only bridge started for ", GoldSymbol,
         ". No trades or orders will be placed.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   for(int i = 0; i < ArraySize(Frames); i++)
      PollTimeframe(i);
}
