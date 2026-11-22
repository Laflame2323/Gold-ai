// Gold AI — read-only MT5 tick collector (research archive only)
// This EA sends bid/ask/last tick updates to the research service.
// It never opens, modifies, or closes trades.

#property strict
#property version   "1.00"
#property description "Gold AI read-only tick collector"

input string TickIngestURL = "https://gold-ai-mtf-research.onrender.com/broker/mt5/ticks";
input string IngestToken = "";
input int InitialLookbackHours = 24;
input int MaxTicksPerBatch = 500;
input int TimerSeconds = 5;
input int RequestTimeoutMs = 30000;

long LastTickTimeMsc = 0;

string JsonPrice(const double value, const int digits)
{
   if(value <= 0.0)
      return "null";
   return DoubleToString(value, digits);
}

bool SendNewTicks()
{
   if(StringLen(IngestToken) < 24)
   {
      Print("Gold AI ticks: enter the private ingestion token in EA inputs; no data sent.");
      return false;
   }

   MqlTick ticks[];
   ulong fromMsc;
   if(LastTickTimeMsc <= 0)
   {
      long lookback = (long)MathMax(1, InitialLookbackHours) * 3600 * 1000;
      fromMsc = (ulong)MathMax(1, (long)TimeTradeServer() * 1000 - lookback);
   }
   else
   {
      // Re-read the last millisecond to avoid losing ticks sharing a timestamp.
      fromMsc = (ulong)MathMax(1, LastTickTimeMsc);
   }

   ResetLastError();
   int copied = CopyTicks(_Symbol, ticks, COPY_TICKS_ALL, fromMsc,
                           (uint)MathMax(50, MathMin(MaxTicksPerBatch, 500)));
   if(copied < 0)
   {
      Print("Gold AI ticks: CopyTicks failed. MT5 error=", GetLastError());
      return false;
   }
   if(copied == 0)
      return true;

   long offsetSeconds = (long)(TimeTradeServer() - TimeGMT());
   string broker = AccountInfoString(ACCOUNT_SERVER);
   string body = "{";
   body += "\"broker_server\":\"" + broker + "\",";
   body += "\"symbol\":\"" + _Symbol + "\",";
   body += "\"server_utc_offset_seconds\":" + IntegerToString((int)offsetSeconds) + ",";
   body += "\"ticks\":[";

   long newestMsc = LastTickTimeMsc;
   for(int i = 0; i < copied; i++)
   {
      if(i > 0)
         body += ",";
      body += "{";
      body += "\"time_msc\":" + IntegerToString((long)ticks[i].time_msc) + ",";
      body += "\"bid\":" + JsonPrice(ticks[i].bid, _Digits) + ",";
      body += "\"ask\":" + JsonPrice(ticks[i].ask, _Digits) + ",";
      body += "\"last\":" + JsonPrice(ticks[i].last, _Digits) + ",";
      body += "\"volume\":" + DoubleToString(ticks[i].volume, 2) + ",";
      body += "\"volume_real\":" + DoubleToString(ticks[i].volume_real, 4) + ",";
      body += "\"flags\":" + IntegerToString((int)ticks[i].flags);
      body += "}";
      if((long)ticks[i].time_msc > newestMsc)
         newestMsc = (long)ticks[i].time_msc;
   }
   body += "]}";

   char requestData[];
   int bytes = StringToCharArray(body, requestData, 0, WHOLE_ARRAY, CP_UTF8);
   if(bytes <= 1)
   {
      Print("Gold AI ticks: JSON encoding failed.");
      return false;
   }
   ArrayResize(requestData, bytes - 1);

   char responseData[];
   string responseHeaders;
   string headers = "Content-Type: application/json\r\nX-MT5-Token: " + IngestToken + "\r\n";
   ResetLastError();
   int httpStatus = WebRequest("POST", TickIngestURL, headers, RequestTimeoutMs,
                               requestData, responseData, responseHeaders);
   if(httpStatus != 200)
   {
      int mt5Error = GetLastError();
      Print("Gold AI ticks: upload failed. HTTP=", httpStatus,
            " MT5 error=", mt5Error, " Response=",
            CharArrayToString(responseData, 0, -1, CP_UTF8));
      return false;
   }

   LastTickTimeMsc = newestMsc;
   Print("Gold AI ticks: uploaded ", copied, " ticks for ", _Symbol,
         ". Latest broker timestamp(ms)=", LastTickTimeMsc);
   return true;
}

int OnInit()
{
   if(StringLen(IngestToken) < 24)
      Print("Gold AI ticks: configure the private ingestion token in EA inputs.");
   EventSetTimer(MathMax(2, TimerSeconds));
   Print("Gold AI read-only tick collector started for ", _Symbol,
         ". Initial lookback hours=", InitialLookbackHours,
         ". Research archive only; no trading functions.");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("Gold AI read-only tick collector stopped.");
}

void OnTimer()
{
   SendNewTicks();
}
