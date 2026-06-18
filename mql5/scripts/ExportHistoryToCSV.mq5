//+------------------------------------------------------------------+
//| ExportHistoryToCSV.mq5                                            |
//| Export JM/MT5 broker history to CSV for backtesting              |
//|                                                                   |
//| Usage:                                                            |
//|   1. Drop this script onto a BRENT.ecn or XAUUSD.ecn chart        |
//|   2. Set inputs: SYMBOL_EXPORT, FROM_YEAR, TO_YEAR, EXPORT_M3     |
//|   3. F5 to compile, drag onto chart to run                        |
//|   4. CSVs written to MQL5\Files\ folder                           |
//|                                                                   |
//| Output format matches the local data/raw/*.csv schema:            |
//|   timestamp,bid_open,bid_high,bid_low,bid_close,                  |
//|     ask_open,ask_high,ask_low,ask_close,volume                    |
//|                                                                   |
//| Notes:                                                            |
//| - MT5 only stores LAST-trade OHLC by default. To get bid/ask      |
//|   we use SymbolInfoTick history, but for OHLC we use the chart's  |
//|   stored prices and approximate bid=ask=close (no real spread).   |
//| - For real bid/ask history use M1 + tick replay. M3/H1/D from     |
//|   CopyRates is mid/last-trade prices.                             |
//| - To match existing CSV format, we write same value for bid_*     |
//|   and ask_* fields.                                               |
//+------------------------------------------------------------------+

#property script_show_inputs
#property strict

input string  SYMBOL_EXPORT  = "BRENT.ecn";    // Symbol to export (BRENT.ecn / XAUUSD.ecn)
input int     FROM_YEAR      = 2016;           // Start year (inclusive)
input int     TO_YEAR        = 2016;           // End year (inclusive)
input bool    EXPORT_M3      = true;           // Export M3 (huge file, slow)
input bool    EXPORT_H1      = true;           // Export H1
input bool    EXPORT_D       = true;           // Export D1

//+------------------------------------------------------------------+
//| Convert ENUM_TIMEFRAMES to readable label                         |
//+------------------------------------------------------------------+
string TfLabel(ENUM_TIMEFRAMES tf)
{
   switch(tf)
   {
      case PERIOD_M1:  return "M1";
      case PERIOD_M3:  return "M3";
      case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_M30: return "M30";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
      case PERIOD_D1:  return "D";
      default:         return "??";
   }
}

//+------------------------------------------------------------------+
//| Build CSV filename: <SYMBOL>_<TF>_<YEAR>.csv                     |
//| Strip .ecn suffix and dots from symbol for cleaner filename      |
//+------------------------------------------------------------------+
string CleanSymbol(string sym)
{
   string s = sym;
   StringReplace(s, ".ecn", "");
   StringReplace(s, ".", "");
   return s;
}

//+------------------------------------------------------------------+
//| Export one timeframe for one year range to CSV                   |
//+------------------------------------------------------------------+
void ExportTimeframe(string symbol, ENUM_TIMEFRAMES tf, int from_year, int to_year)
{
   string tfLabel = TfLabel(tf);
   string clean = CleanSymbol(symbol);
   string fname;
   if(from_year == to_year)
      fname = StringFormat("%s_%s_%d.csv", clean, tfLabel, from_year);
   else
      fname = StringFormat("%s_%s_%d-%d.csv", clean, tfLabel, from_year, to_year);

   datetime from_dt = StringToTime(StringFormat("%d.01.01 00:00", from_year));
   datetime to_dt   = StringToTime(StringFormat("%d.12.31 23:59", to_year));

   PrintFormat("[%s] Fetching %s from %s to %s...",
               symbol, tfLabel,
               TimeToString(from_dt, TIME_DATE),
               TimeToString(to_dt, TIME_DATE));

   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int copied = CopyRates(symbol, tf, from_dt, to_dt, rates);
   if(copied <= 0)
   {
      PrintFormat("[%s] ERROR: CopyRates returned %d for %s. err=%d",
                  symbol, copied, tfLabel, GetLastError());
      return;
   }
   PrintFormat("[%s] %s: got %d bars", symbol, tfLabel, copied);

   // Open file in MQL5\Files\
   int fh = FileOpen(fname, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(fh == INVALID_HANDLE)
   {
      PrintFormat("[%s] ERROR: FileOpen failed for %s. err=%d",
                  symbol, fname, GetLastError());
      return;
   }

   // Header — matches existing CSV schema
   if(tf == PERIOD_D1)
      FileWrite(fh, "timestamp", "open", "high", "low", "close", "volume");
   else
      FileWrite(fh, "timestamp",
                "bid_open", "bid_high", "bid_low", "bid_close",
                "ask_open", "ask_high", "ask_low", "ask_close",
                "volume");

   // Rows — MT5 OHLC is last-trade. We can't reconstruct true bid/ask
   // history, so we write the same value for bid_* and ask_* fields.
   // This mirrors what the existing CSV builder does when only mid is available.
   for(int i = 0; i < copied; i++)
   {
      // ISO format with +00:00 to match existing rows: "2016-01-15 13:00:00+00:00"
      MqlDateTime mdt;
      TimeToStruct(rates[i].time, mdt);
      string ts = StringFormat("%04d-%02d-%02d %02d:%02d:%02d+00:00",
                               mdt.year, mdt.mon, mdt.day,
                               mdt.hour, mdt.min, mdt.sec);

      double o = rates[i].open;
      double h = rates[i].high;
      double l = rates[i].low;
      double c = rates[i].close;
      long   v = rates[i].tick_volume;

      if(tf == PERIOD_D1)
         FileWrite(fh, ts,
                   DoubleToString(o, 4),
                   DoubleToString(h, 4),
                   DoubleToString(l, 4),
                   DoubleToString(c, 4),
                   v);
      else
         FileWrite(fh, ts,
                   DoubleToString(o, 4),  // bid_open
                   DoubleToString(h, 4),  // bid_high
                   DoubleToString(l, 4),  // bid_low
                   DoubleToString(c, 4),  // bid_close
                   DoubleToString(o, 4),  // ask_open  (no real spread history)
                   DoubleToString(h, 4),  // ask_high
                   DoubleToString(l, 4),  // ask_low
                   DoubleToString(c, 4),  // ask_close
                   v);
   }

   FileClose(fh);
   PrintFormat("[%s] Wrote %d rows to MQL5\\Files\\%s", symbol, copied, fname);
}

//+------------------------------------------------------------------+
//| Script entry point                                               |
//+------------------------------------------------------------------+
void OnStart()
{
   PrintFormat("=== ExportHistoryToCSV ===");
   PrintFormat("Symbol: %s, Years: %d to %d", SYMBOL_EXPORT, FROM_YEAR, TO_YEAR);
   PrintFormat("Export D=%s, H1=%s, M3=%s",
               (string)EXPORT_D, (string)EXPORT_H1, (string)EXPORT_M3);

   // Verify symbol is selected (if not, MT5 hasn't downloaded its history)
   if(!SymbolInfoInteger(SYMBOL_EXPORT, SYMBOL_SELECT))
   {
      PrintFormat("WARN: %s is not in Market Watch. Adding...", SYMBOL_EXPORT);
      if(!SymbolSelect(SYMBOL_EXPORT, true))
      {
         PrintFormat("ERROR: Cannot select %s. err=%d",
                     SYMBOL_EXPORT, GetLastError());
         return;
      }
   }

   if(EXPORT_D)
      ExportTimeframe(SYMBOL_EXPORT, PERIOD_D1, FROM_YEAR, TO_YEAR);
   if(EXPORT_H1)
      ExportTimeframe(SYMBOL_EXPORT, PERIOD_H1, FROM_YEAR, TO_YEAR);
   if(EXPORT_M3)
      ExportTimeframe(SYMBOL_EXPORT, PERIOD_M3, FROM_YEAR, TO_YEAR);

   PrintFormat("=== Done. CSVs written to <data folder>\\MQL5\\Files\\ ===");
   PrintFormat("Find that folder via MT5 menu: File → Open Data Folder");
}
//+------------------------------------------------------------------+
