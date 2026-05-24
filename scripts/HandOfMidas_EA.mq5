//+------------------------------------------------------------------+
//|                                            HandOfMidas_EA.mq5     |
//|                          Hand Of Midas — Multi-Strategy EA        |
//|                     Alpha-Sweep + Mean-Rev + Cross-Market          |
//+------------------------------------------------------------------+
#property copyright "Hand Of Midas"
#property version   "1.00"
#property description "Gold trading: Alpha-Sweep (08-20 UTC, 3/day) + Mean-Rev + Cross-Market"
#property strict

//+------------------------------------------------------------------+
//| INPUTS                                                            |
//+------------------------------------------------------------------+

// --- Symbol config (JustMarkets ECN) ---
input string   InpGoldSymbol     = "XAUUSD.ecn";   // Gold symbol name
input string   InpOilSymbol      = "BRENT.ecn";     // Brent Crude Oil
input bool     InpTradeGold      = true;            // Trade Gold
input bool     InpTradeOil       = false;           // Trade Oil

// --- Alpha-Sweep params ---
input double   InpAsiaMinRange   = 5.0;            // Min Asia range ($)
input double   InpSweepThreshold = 2.0;            // Sweep extension ($)
input double   InpSLBuffer       = 0.30;           // SL buffer beyond sweep wick ($)
input double   InpMinSL          = 5.0;            // Minimum SL distance ($)
input double   InpTPMultiplier   = 2.0;            // TP = Asia range × this
input int      InpMaxBars        = 48;             // Max hold (M5 bars, ~4hrs)
input double   InpBETriggerPct   = 0.50;           // Break-even at X% to TP
input double   InpBEOffset       = 0.30;           // BE SL offset above/below entry
input int      InpScanStartHour  = 8;              // Scan start (UTC hour)
input int      InpScanEndHour    = 20;             // Scan end (UTC hour)
input int      InpMaxTradesPerDay = 3;             // Max Alpha-Sweep trades/day
input int      InpEngulfingWindow = 40;            // Engulfing window (M3 bars after sweep)

// --- Mean-Rev params ---
input double   InpMR_C1Threshold = -0.4;           // Mean-Rev condition 1 threshold
input double   InpMR_C2Threshold = -0.8;           // Mean-Rev condition 2 threshold
input int      InpMR_MaxHoldDays = 5;              // Mean-Rev max hold (days)
input double   InpMR_SLMultiplier = 1.0;           // Mean-Rev SL = avg range × this

// --- Cross-Market params ---
input double   InpCM_ConsensusMin = 0.3;           // Cross-Market min consensus score
input double   InpCM_SLATRMult   = 2.0;            // Cross-Market SL = ATR × this
input double   InpCM_TPATRMult   = 4.0;            // Cross-Market TP = ATR × this
input int      InpCM_MaxHoldDays = 20;             // Cross-Market max hold (days)
input int      InpCM_MinGapDays  = 2;              // Min days between CM signals

// --- Risk management ---
input double   InpRiskAlpha      = 4.0;            // Alpha-Sweep risk %
input double   InpRiskMeanRev    = 3.0;            // Mean-Rev risk %
input double   InpRiskCross      = 2.0;            // Cross-Market risk %
input double   InpMaxLots        = 1.0;            // Max lot size

// --- DD Protection ---
input int      InpDD_HalveAt     = 3;              // Halve size after N consecutive losses
input int      InpDD_PauseAt     = 5;              // Pause after N consecutive losses
input int      InpDD_PauseSignals = 2;             // Skip N signals when paused

// --- Cross-Market symbols (JustMarkets ECN) ---
input string   InpSymEURUSD      = "EURUSD.ecn";    // EUR/USD
input string   InpSymUS10Y       = "";              // Not available
input string   InpSymSPX500      = "US500.ecn";     // S&P 500
input string   InpSymSilver      = "XAGUSD.ecn";   // Silver
input string   InpSymOil         = "BRENT.ecn";     // Brent Crude
input string   InpSymUS2Y        = "";              // Not available

// --- Magic number ---
input int      InpMagicAlpha     = 100001;
input int      InpMagicMeanRev   = 100002;
input int      InpMagicCross     = 100003;

//+------------------------------------------------------------------+
//| GLOBAL VARIABLES                                                  |
//+------------------------------------------------------------------+
int g_consecutiveLosses = 0;
int g_pauseCounter = 0;
int g_alphaTradestoday = 0;
datetime g_lastAlphaDate = 0;
datetime g_lastCrossSignalDate = 0;

double g_asiaHigh = 0;
double g_asiaLow = 0;
double g_asiaRange = 0;
bool g_asiaCalculated = false;
datetime g_asiaDate = 0;

//+------------------------------------------------------------------+
//| Expert initialization                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("Hand Of Midas EA initialized");
   Print("Gold: ", InpGoldSymbol, " | Oil: ", InpOilSymbol);
   Print("Alpha-Sweep: ", InpScanStartHour, "-", InpScanEndHour, " UTC, max ", InpMaxTradesPerDay, "/day");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert tick function                                              |
//+------------------------------------------------------------------+
void OnTick()
{
   if(!InpTradeGold) return;

   // Use TimeCurrent() (works in both live and tester) + broker GMT offset
   MqlDateTime tm;
   datetime serverTime = TimeCurrent();
   int gmtOffset = (int)((TimeGMT() - serverTime));  // Will be 0 if broker is GMT
   datetime utcTime = serverTime + gmtOffset;
   TimeToStruct(utcTime, tm);
   int utcHour = tm.hour;
   int utcMin = tm.min;

   // Reset daily counter
   datetime today = iTime(InpGoldSymbol, PERIOD_D1, 0);
   if(today != g_lastAlphaDate)
   {
      g_alphaTradestoday = 0;
      g_lastAlphaDate = today;
      g_asiaCalculated = false;
   }

   // Calculate Asia range once per day (after 08:00 UTC)
   if(!g_asiaCalculated && utcHour >= 8)
   {
      CalculateAsiaRange();
      g_asiaCalculated = true;
   }

   // Alpha-Sweep scan (08:00-20:00 UTC)
   if(utcHour >= InpScanStartHour && utcHour < InpScanEndHour)
   {
      CheckAlphaSweep(tm);
   }

   // Daily scan at 22:00 UTC — Mean-Rev + Cross-Market
   static datetime lastDailyScan = 0;
   if(utcHour == 22 && utcMin == 0 && today != lastDailyScan)
   {
      lastDailyScan = today;
      CheckMeanRev();
      CheckCrossMarket();
   }

   // Position management — every tick
   ManageOpenPositions();
}

//+------------------------------------------------------------------+
//| Timer for daily scan (22:00 UTC)                                  |
//+------------------------------------------------------------------+
void OnTimer()
{
   // Not used — daily scan triggered by OnTick at 22:00
}

//+------------------------------------------------------------------+
//| ASIA RANGE CALCULATION                                            |
//+------------------------------------------------------------------+
void CalculateAsiaRange()
{
   // Get H1 bars, find Asia session (00:00-08:00 UTC today)
   double high = 0, low = 999999;
   int bars = iBars(InpGoldSymbol, PERIOD_H1);

   for(int i = 0; i < 24 && i < bars; i++)
   {
      datetime barTime = iTime(InpGoldSymbol, PERIOD_H1, i);
      MqlDateTime bt;
      TimeToStruct(barTime, bt);

      // Only today's Asia bars (00:00-08:00 UTC)
      MqlDateTime nowStruct;
      TimeToStruct(TimeGMT(), nowStruct);
      if(bt.day_of_year != nowStruct.day_of_year) continue;
      if(bt.hour >= 8) continue;

      double h = iHigh(InpGoldSymbol, PERIOD_H1, i);
      double l = iLow(InpGoldSymbol, PERIOD_H1, i);
      if(h > high) high = h;
      if(l < low) low = l;
   }

   if(high > 0 && low < 999999)
   {
      g_asiaHigh = high;
      g_asiaLow = low;
      g_asiaRange = high - low;
   }
}

//+------------------------------------------------------------------+
//| DAILY BIAS                                                        |
//+------------------------------------------------------------------+
string GetDailyBias()
{
   double prevClose = iClose(InpGoldSymbol, PERIOD_D1, 1);
   double prevOpen = iOpen(InpGoldSymbol, PERIOD_D1, 1);
   if(prevClose > prevOpen) return "bullish";
   return "bearish";
}

//+------------------------------------------------------------------+
//| ALPHA-SWEEP — Main signal detection                               |
//+------------------------------------------------------------------+
void CheckAlphaSweep(MqlDateTime &tm)
{
   if(g_alphaTradestoday >= InpMaxTradesPerDay) return;
   if(g_asiaRange < InpAsiaMinRange) return;
   if(g_pauseCounter > 0) { g_pauseCounter--; return; }

   string bias = GetDailyBias();

   // Check current H1 bar for sweep
   double h1High = iHigh(InpGoldSymbol, PERIOD_H1, 0);
   double h1Low = iLow(InpGoldSymbol, PERIOD_H1, 0);
   double h1Close = iClose(InpGoldSymbol, PERIOD_H1, 0);

   string sweepDir = "";
   double sweepWick = 0;

   // Bearish sweep: high > Asia high + threshold, close < Asia high
   if(h1High > g_asiaHigh + InpSweepThreshold && h1Close < g_asiaHigh)
   {
      sweepDir = "bearish";
      sweepWick = h1High;
   }
   // Bullish sweep: low < Asia low - threshold, close > Asia low
   else if(h1Low < g_asiaLow - InpSweepThreshold && h1Close > g_asiaLow)
   {
      sweepDir = "bullish";
      sweepWick = h1Low;
   }

   if(sweepDir == "") return;

   // Bias filter
   if(sweepDir == "bullish" && bias != "bullish") return;
   if(sweepDir == "bearish" && bias != "bearish") return;

   // Check M3 for engulfing
   if(CheckEngulfing(sweepDir, sweepWick))
   {
      ExecuteAlphaSweep(sweepDir, sweepWick);
   }
}

//+------------------------------------------------------------------+
//| ENGULFING DETECTION on M3                                         |
//+------------------------------------------------------------------+
bool CheckEngulfing(string sweepDir, double sweepWick)
{
   // Check last N M3 bars for engulfing pattern
   for(int i = 2; i < InpEngulfingWindow; i++)
   {
      double co = iOpen(InpGoldSymbol, PERIOD_M5, i);
      double cc = iClose(InpGoldSymbol, PERIOD_M5, i);
      double po = iOpen(InpGoldSymbol, PERIOD_M5, i + 1);
      double pc = iClose(InpGoldSymbol, PERIOD_M5, i + 1);

      double ct = MathMax(co, cc);
      double cb = MathMin(co, cc);
      double pt = MathMax(po, pc);
      double pb = MathMin(po, pc);

      if(sweepDir == "bullish")
      {
         if(cc > co && cb <= pb && ct >= pt) return true;
      }
      else
      {
         if(cc < co && cb <= pb && ct >= pt) return true;
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| EXECUTE ALPHA-SWEEP TRADE                                         |
//+------------------------------------------------------------------+
void ExecuteAlphaSweep(string sweepDir, double sweepWick)
{
   double entry, sl, tp, risk;
   double ask = SymbolInfoDouble(InpGoldSymbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(InpGoldSymbol, SYMBOL_BID);
   double point = SymbolInfoDouble(InpGoldSymbol, SYMBOL_POINT);

   if(sweepDir == "bullish")
   {
      entry = ask;
      sl = sweepWick - InpSLBuffer;
      risk = entry - sl;
      if(risk < InpMinSL) { sl = entry - InpMinSL; risk = InpMinSL; }
      if(risk < 0.3 || risk > g_asiaRange * 0.8) return;
      tp = entry + g_asiaRange * InpTPMultiplier;
      if(tp - entry < risk * 0.8) return;

      double lots = CalculateLots(risk, InpRiskAlpha);
      if(lots <= 0) return;

      MqlTradeRequest request = {};
      MqlTradeResult result = {};
      request.action = TRADE_ACTION_DEAL;
      request.symbol = InpGoldSymbol;
      request.volume = lots;
      request.type = ORDER_TYPE_BUY;
      request.price = ask;
      request.sl = sl;
      request.tp = tp;
      request.magic = InpMagicAlpha;
      request.type_filling = ORDER_FILLING_FOK;
      request.comment = "HOM_Alpha_Long";

      if(OrderSend(request, result))
      {
         g_alphaTradestoday++;
         Print("Alpha-Sweep LONG: entry=", ask, " SL=", sl, " TP=", tp, " lots=", lots);
      }
   }
   else // bearish
   {
      entry = bid;
      sl = sweepWick + InpSLBuffer;
      risk = sl - entry;
      if(risk < InpMinSL) { sl = entry + InpMinSL; risk = InpMinSL; }
      if(risk < 0.3 || risk > g_asiaRange * 0.8) return;
      tp = entry - g_asiaRange * InpTPMultiplier;
      if(entry - tp < risk * 0.8) return;

      double lots = CalculateLots(risk, InpRiskAlpha);
      if(lots <= 0) return;

      MqlTradeRequest request = {};
      MqlTradeResult result = {};
      request.action = TRADE_ACTION_DEAL;
      request.symbol = InpGoldSymbol;
      request.volume = lots;
      request.type = ORDER_TYPE_SELL;
      request.price = bid;
      request.sl = sl;
      request.tp = tp;
      request.magic = InpMagicAlpha;
      request.type_filling = ORDER_FILLING_FOK;
      request.comment = "HOM_Alpha_Short";

      if(OrderSend(request, result))
      {
         g_alphaTradestoday++;
         Print("Alpha-Sweep SHORT: entry=", bid, " SL=", sl, " TP=", tp, " lots=", lots);
      }
   }
}

//+------------------------------------------------------------------+
//| POSITION MANAGEMENT — Break-even + Max hold                       |
//+------------------------------------------------------------------+
void ManageOpenPositions()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(!PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL) != InpGoldSymbol) continue;

      long magic = PositionGetInteger(POSITION_MAGIC);
      if(magic != InpMagicAlpha && magic != InpMagicMeanRev && magic != InpMagicCross) continue;

      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      ENUM_POSITION_TYPE posType = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      datetime openTime = (datetime)PositionGetInteger(POSITION_TIME);

      // --- Break-even for Alpha-Sweep ---
      if(magic == InpMagicAlpha)
      {
         double currentPrice = (posType == POSITION_TYPE_BUY) ?
            SymbolInfoDouble(InpGoldSymbol, SYMBOL_BID) :
            SymbolInfoDouble(InpGoldSymbol, SYMBOL_ASK);

         if(posType == POSITION_TYPE_BUY)
         {
            if(sl < entry) // BE not yet applied
            {
               double target50 = entry + (tp - entry) * InpBETriggerPct;
               if(currentPrice >= target50)
               {
                  double newSL = entry + InpBEOffset;
                  ModifySL(ticket, newSL);
               }
            }
         }
         else // SELL
         {
            if(sl > entry) // BE not yet applied
            {
               double target50 = entry - (entry - tp) * InpBETriggerPct;
               if(currentPrice <= target50)
               {
                  double newSL = entry - InpBEOffset;
                  ModifySL(ticket, newSL);
               }
            }
         }

         // Max hold (80 M3 bars = 240 minutes)
         int minutesHeld = (int)((TimeGMT() - openTime) / 60);
         if(minutesHeld >= InpMaxBars * 5)
         {
            ClosePosition(ticket, "MaxHold_Alpha");
         }
      }

      // --- Max hold for Mean-Rev (5 days) ---
      if(magic == InpMagicMeanRev)
      {
         int daysHeld = (int)((TimeGMT() - openTime) / 86400);
         if(daysHeld >= InpMR_MaxHoldDays)
         {
            ClosePosition(ticket, "MaxHold_MeanRev");
         }
      }

      // --- Max hold for Cross-Market (20 days) ---
      if(magic == InpMagicCross)
      {
         int daysHeld = (int)((TimeGMT() - openTime) / 86400);
         if(daysHeld >= InpCM_MaxHoldDays)
         {
            ClosePosition(ticket, "MaxHold_Cross");
         }
      }
   }
}

//+------------------------------------------------------------------+
//| LOT SIZE CALCULATOR                                               |
//+------------------------------------------------------------------+
double CalculateLots(double slDistance, double riskPercent)
{
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMult = 1.0;

   // DD protection
   if(g_consecutiveLosses >= InpDD_HalveAt) riskMult = 0.5;

   double riskAmount = balance * (riskPercent / 100.0) * riskMult;
   double tickValue = SymbolInfoDouble(InpGoldSymbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(InpGoldSymbol, SYMBOL_TRADE_TICK_SIZE);

   if(tickValue <= 0 || tickSize <= 0 || slDistance <= 0) return 0;

   double lots = riskAmount / (slDistance / tickSize * tickValue);

   // Normalize
   double minLot = SymbolInfoDouble(InpGoldSymbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(InpGoldSymbol, SYMBOL_VOLUME_MAX);
   double stepLot = SymbolInfoDouble(InpGoldSymbol, SYMBOL_VOLUME_STEP);

   lots = MathMin(lots, InpMaxLots);
   lots = MathMin(lots, maxLot);
   lots = MathMax(lots, minLot);
   lots = NormalizeDouble(MathFloor(lots / stepLot) * stepLot, 2);

   return lots;
}

//+------------------------------------------------------------------+
//| MODIFY SL                                                         |
//+------------------------------------------------------------------+
void ModifySL(ulong ticket, double newSL)
{
   MqlTradeRequest request = {};
   MqlTradeResult result = {};
   request.action = TRADE_ACTION_SLTP;
   request.position = ticket;
   request.sl = NormalizeDouble(newSL, (int)SymbolInfoInteger(InpGoldSymbol, SYMBOL_DIGITS));
   request.tp = PositionGetDouble(POSITION_TP);

   if(!OrderSend(request, result))
      Print("ModifySL failed: ", result.comment);
}

//+------------------------------------------------------------------+
//| CLOSE POSITION                                                    |
//+------------------------------------------------------------------+
void ClosePosition(ulong ticket, string reason)
{
   MqlTradeRequest request = {};
   MqlTradeResult result = {};

   ENUM_POSITION_TYPE posType = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   double volume = PositionGetDouble(POSITION_VOLUME);

   request.action = TRADE_ACTION_DEAL;
   request.position = ticket;
   request.symbol = InpGoldSymbol;
   request.volume = volume;
   request.type = (posType == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   request.price = (posType == POSITION_TYPE_BUY) ?
      SymbolInfoDouble(InpGoldSymbol, SYMBOL_BID) :
      SymbolInfoDouble(InpGoldSymbol, SYMBOL_ASK);

   if(OrderSend(request, result))
   {
      double profit = PositionGetDouble(POSITION_PROFIT);
      Print("Closed: ", reason, " P&L=", profit);

      // Update DD state
      if(profit > 0)
         g_consecutiveLosses = 0;
      else
      {
         g_consecutiveLosses++;
         if(g_consecutiveLosses >= InpDD_PauseAt)
            g_pauseCounter = InpDD_PauseSignals;
      }
   }
}

//+------------------------------------------------------------------+
//| MEAN-REV SIGNAL (called at 22:00 UTC via OnTick check)           |
//+------------------------------------------------------------------+
void CheckMeanRev()
{
   // Check if already has open Mean-Rev position
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(PositionGetTicket(i) == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) == InpMagicMeanRev) return; // Already open
   }

   // Get daily data
   double closes[], highs[], lows[];
   ArraySetAsSeries(closes, true);
   ArraySetAsSeries(highs, true);
   ArraySetAsSeries(lows, true);
   CopyClose(InpGoldSymbol, PERIOD_D1, 0, 15, closes);
   CopyHigh(InpGoldSymbol, PERIOD_D1, 0, 15, highs);
   CopyLow(InpGoldSymbol, PERIOD_D1, 0, 15, lows);

   if(ArraySize(closes) < 12) return;

   // Compute conditions
   double ma10Low = 0, ma10High = 0;
   for(int i = 1; i <= 10; i++) ma10Low += lows[i];
   ma10Low /= 10.0;
   for(int i = 2; i <= 11; i++) ma10High += highs[i];
   ma10High /= 10.0;

   double closeYesterday = closes[1];
   double close2dAgo = closes[2];
   double rangeYesterday = highs[1] - lows[1];
   if(rangeYesterday <= 0) return;

   double c1 = (ma10Low - close2dAgo) / rangeYesterday;
   double c2 = (closeYesterday - ma10High) / rangeYesterday;

   // Signal: c1 < -0.4 AND c2 < -0.8
   if(c1 >= InpMR_C1Threshold || c2 >= InpMR_C2Threshold) return;

   // 50-MA gate
   double ma50[];
   ArraySetAsSeries(ma50, true);
   CopyClose(InpGoldSymbol, PERIOD_D1, 0, 55, ma50);
   if(ArraySize(ma50) < 50) return;
   double sum50 = 0;
   for(int i = 0; i < 50; i++) sum50 += ma50[i];
   double goldMA50 = sum50 / 50.0;
   if(closes[0] < goldMA50) return; // Below 50MA, skip longs

   // Entry
   double ask = SymbolInfoDouble(InpGoldSymbol, SYMBOL_ASK);
   double avgRange = 0;
   for(int i = 1; i <= 10; i++) avgRange += (highs[i] - lows[i]);
   avgRange /= 10.0;

   double sl = ask - avgRange * InpMR_SLMultiplier;
   double risk = ask - sl;
   double tp = ask + risk * 2.0;
   double lots = CalculateLots(risk, InpRiskMeanRev);
   if(lots <= 0) return;

   MqlTradeRequest request = {};
   MqlTradeResult result = {};
   request.action = TRADE_ACTION_DEAL;
   request.symbol = InpGoldSymbol;
   request.volume = lots;
   request.type = ORDER_TYPE_BUY;
   request.price = ask;
   request.sl = sl;
   request.tp = tp;
   request.magic = InpMagicMeanRev;
   request.type_filling = ORDER_FILLING_FOK;
      request.comment = "HOM_MeanRev_Long";

   if(OrderSend(request, result))
      Print("Mean-Rev LONG: entry=", ask, " SL=", sl, " TP=", tp);
}

//+------------------------------------------------------------------+
//| CROSS-MARKET SIGNAL (called at 22:00 UTC)                        |
//+------------------------------------------------------------------+
void CheckCrossMarket()
{
   // Check if already has open Cross-Market position
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(PositionGetTicket(i) == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) == InpMagicCross) return;
   }

   // Min gap between signals
   if(TimeGMT() - g_lastCrossSignalDate < InpCM_MinGapDays * 86400) return;

   // Compute consensus from 6 instruments
   double consensus = 0;
   int totalWeight = 0;

   // EUR/USD (weight 2, bullish on negative = USD weakness)
   double eurClose1 = iClose(InpSymEURUSD, PERIOD_D1, 1);
   double eurClose2 = iClose(InpSymEURUSD, PERIOD_D1, 2);
   if(eurClose1 > 0 && eurClose2 > 0)
   {
      double ret = (eurClose1 - eurClose2) / eurClose2;
      if(ret > 0.001) consensus += 2;
      totalWeight += 2;
   }

   // SPX500 (weight 1, bullish on positive return, extra on big negative)
   double spxClose1 = iClose(InpSymSPX500, PERIOD_D1, 1);
   double spxClose2 = iClose(InpSymSPX500, PERIOD_D1, 2);
   if(spxClose1 > 0 && spxClose2 > 0)
   {
      double ret = (spxClose1 - spxClose2) / spxClose2;
      if(ret > 0.001) consensus += 1;
      else if(ret < -0.005) consensus += 1; // Flight to safety
      totalWeight += 1;
   }

   // Silver (weight 2, bullish on positive return)
   double xagClose1 = iClose(InpSymSilver, PERIOD_D1, 1);
   double xagClose2 = iClose(InpSymSilver, PERIOD_D1, 2);
   if(xagClose1 > 0 && xagClose2 > 0)
   {
      double ret = (xagClose1 - xagClose2) / xagClose2;
      if(ret > 0.001) consensus += 2;
      totalWeight += 2;
   }

   // Oil (weight 1, bullish on positive return)
   double oilClose1 = iClose(InpSymOil, PERIOD_D1, 1);
   double oilClose2 = iClose(InpSymOil, PERIOD_D1, 2);
   if(oilClose1 > 0 && oilClose2 > 0)
   {
      double ret = (oilClose1 - oilClose2) / oilClose2;
      if(ret > 0.001) consensus += 1;
      totalWeight += 1;
   }

   // Normalize consensus
   if(totalWeight == 0) return;
   double normalizedConsensus = consensus / (double)totalWeight;

   if(normalizedConsensus < InpCM_ConsensusMin) return;

   // Entry
   double ask = SymbolInfoDouble(InpGoldSymbol, SYMBOL_ASK);

   // ATR for SL/TP
   double atr = 0;
   double h[], l[];
   ArraySetAsSeries(h, true); ArraySetAsSeries(l, true);
   CopyHigh(InpGoldSymbol, PERIOD_D1, 1, 14, h);
   CopyLow(InpGoldSymbol, PERIOD_D1, 1, 14, l);
   for(int i = 0; i < 14 && i < ArraySize(h); i++) atr += (h[i] - l[i]);
   atr /= 14.0;

   double sl = ask - atr * InpCM_SLATRMult;
   double tp = ask + atr * InpCM_TPATRMult;
   double risk = ask - sl;
   double lots = CalculateLots(risk, InpRiskCross);
   if(lots <= 0) return;

   MqlTradeRequest request = {};
   MqlTradeResult result = {};
   request.action = TRADE_ACTION_DEAL;
   request.symbol = InpGoldSymbol;
   request.volume = lots;
   request.type = ORDER_TYPE_BUY;
   request.price = ask;
   request.sl = sl;
   request.tp = tp;
   request.magic = InpMagicCross;
   request.type_filling = ORDER_FILLING_FOK;
      request.comment = "HOM_Cross_Long";

   if(OrderSend(request, result))
   {
      g_lastCrossSignalDate = TimeGMT();
      Print("Cross-Market LONG: entry=", ask, " SL=", sl, " TP=", tp, " consensus=", normalizedConsensus);
   }
}

//+------------------------------------------------------------------+
//| TRADE RESULT HANDLER — Update DD state on close                  |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
{
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD)
   {
      if(trans.deal_type == DEAL_TYPE_BUY || trans.deal_type == DEAL_TYPE_SELL)
      {
         // Check if this is a closing deal
         if(trans.position != 0)
         {
            double profit = trans.price; // Simplified — use HistoryDealGetDouble for exact
            // DD tracking handled in ClosePosition()
         }
      }
   }
}

//+------------------------------------------------------------------+
//| DEINITIALIZATION                                                  |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print("Hand Of Midas EA removed. Reason: ", reason);
}
//+------------------------------------------------------------------+
