//+------------------------------------------------------------------+
//|                                              DWX_Server.mq5       |
//|              Hand Of Midas — DWX Bridge (MT5 ↔ Python)            |
//|                                                                    |
//|  Thin server EA: streams prices, executes commands from Python.    |
//|  All strategy logic lives in Python. This EA just bridges.         |
//+------------------------------------------------------------------+
#property copyright "Hand Of Midas"
#property version   "2.14"
#property description "DWX Bridge: streams market data and executes orders from Python (Filter #27 limit orders + retcode-aware accept + per-cmd response files + history retry pool)"
#property strict

input string InpSymbols = "XAUUSD.ecn,BRENT.ecn";  // Symbols to stream (comma-separated)
input int    InpTimerMs = 25;                        // Timer interval (ms)
input string InpFolder  = "DWX";                    // Folder in MQL5/Files/
input int    InpMagic   = 200000;                   // Magic number base
input bool   InpPartialTPEnabled = true;            // Filter #7: allow CLOSE_PARTIAL action

string g_symbols[];
int    g_numSymbols;
string g_folder;
datetime g_lastBarWrite = 0;

//+------------------------------------------------------------------+
//| Expert initialization                                             |
//+------------------------------------------------------------------+
int OnInit()
{
    g_folder = InpFolder;

    // Create directories
    FolderCreate(g_folder, FILE_COMMON);
    FolderCreate(g_folder + "/commands", FILE_COMMON);

    // Parse symbols
    g_numSymbols = StringSplit(InpSymbols, ',', g_symbols);
    for(int i = 0; i < g_numSymbols; i++)
    {
        StringTrimLeft(g_symbols[i]);
        StringTrimRight(g_symbols[i]);
        SymbolSelect(g_symbols[i], true);
    }

    // Start timer
    EventSetMillisecondTimer(InpTimerMs);

    Print("[DWX] Server started v2.14 (Filter #27 + poll-cancel + retcode-accept + per-cmd-response + history-retry). Symbols: ", InpSymbols,
          " | Folder: ", g_folder, " | Magic: ", InpMagic,
          " | Commands: OPEN, OPEN_PENDING, CANCEL_PENDING, MODIFY, CLOSE, CLOSE_PARTIAL, CLOSE_ALL");
    WriteAccountInfo();
    WriteMarketData();

    return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    EventKillTimer();
    Print("[DWX] Server stopped. Reason: ", reason);
}

//+------------------------------------------------------------------+
//| Timer event — main loop                                           |
//+------------------------------------------------------------------+
void OnTimer()
{
    WriteMarketData();
    WriteOpenOrders();
    WritePendingOrders();
    ReadCommands();

    // Write account info every 2 seconds
    static datetime lastAccount = 0;
    if(TimeCurrent() - lastAccount >= 2)
    {
        WriteAccountInfo();
        lastAccount = TimeCurrent();
    }

    // Write bar data every 3 seconds
    if(TimeCurrent() - g_lastBarWrite >= 3)
    {
        WriteBarData();
        g_lastBarWrite = TimeCurrent();
    }
}

//+------------------------------------------------------------------+
//| Write current prices for all symbols                              |
//+------------------------------------------------------------------+
void WriteMarketData()
{
    string json = "{";
    for(int i = 0; i < g_numSymbols; i++)
    {
        MqlTick tick;
        if(!SymbolInfoTick(g_symbols[i], tick)) continue;

        if(i > 0) json += ",";
        json += StringFormat(
            "\"%s\":{\"bid\":%.5f,\"ask\":%.5f,\"last\":%.5f,\"time\":\"%s\",\"spread\":%.5f}",
            g_symbols[i],
            tick.bid,
            tick.ask,
            tick.last,
            TimeToString(tick.time, TIME_DATE|TIME_SECONDS),
            (tick.ask - tick.bid)
        );
    }
    json += "}";

    WriteFile(g_folder + "/market_data.json", json);
}

//+------------------------------------------------------------------+
//| Write account information                                         |
//+------------------------------------------------------------------+
void WriteAccountInfo()
{
    string json = StringFormat(
        "{\"balance\":%.2f,\"equity\":%.2f,\"margin\":%.2f,\"free_margin\":%.2f,"
        "\"margin_level\":%.2f,\"profit\":%.2f,\"currency\":\"%s\",\"leverage\":%d,"
        "\"name\":\"%s\",\"server\":\"%s\",\"login\":%d}",
        AccountInfoDouble(ACCOUNT_BALANCE),
        AccountInfoDouble(ACCOUNT_EQUITY),
        AccountInfoDouble(ACCOUNT_MARGIN),
        AccountInfoDouble(ACCOUNT_MARGIN_FREE),
        AccountInfoDouble(ACCOUNT_MARGIN_LEVEL),
        AccountInfoDouble(ACCOUNT_PROFIT),
        AccountInfoString(ACCOUNT_CURRENCY),
        (int)AccountInfoInteger(ACCOUNT_LEVERAGE),
        AccountInfoString(ACCOUNT_NAME),
        AccountInfoString(ACCOUNT_SERVER),
        (int)AccountInfoInteger(ACCOUNT_LOGIN)
    );

    WriteFile(g_folder + "/account_info.json", json);
}

//+------------------------------------------------------------------+
//| Write open positions                                              |
//+------------------------------------------------------------------+
void WriteOpenOrders()
{
    string json = "{";
    int total = PositionsTotal();
    bool first = true;

    for(int i = 0; i < total; i++)
    {
        ulong ticket = PositionGetTicket(i);
        if(ticket == 0) continue;

        if(!first) json += ",";
        first = false;

        string symbol = PositionGetString(POSITION_SYMBOL);
        double volume = PositionGetDouble(POSITION_VOLUME);
        double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
        double sl = PositionGetDouble(POSITION_SL);
        double tp = PositionGetDouble(POSITION_TP);
        double profit = PositionGetDouble(POSITION_PROFIT);
        double swap = PositionGetDouble(POSITION_SWAP);
        long posType = PositionGetInteger(POSITION_TYPE);
        long magic = PositionGetInteger(POSITION_MAGIC);
        datetime openTime = (datetime)PositionGetInteger(POSITION_TIME);
        string comment = PositionGetString(POSITION_COMMENT);

        json += StringFormat(
            "\"%d\":{\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.2f,"
            "\"open_price\":%.5f,\"sl\":%.5f,\"tp\":%.5f,\"profit\":%.2f,"
            "\"swap\":%.2f,\"magic\":%d,\"open_time\":\"%s\",\"comment\":\"%s\"}",
            ticket,
            symbol,
            posType == POSITION_TYPE_BUY ? "BUY" : "SELL",
            volume,
            openPrice, sl, tp, profit, swap,
            magic,
            TimeToString(openTime, TIME_DATE|TIME_SECONDS),
            comment
        );
    }
    json += "}";

    WriteFile(g_folder + "/open_orders.json", json);
}

//+------------------------------------------------------------------+
//| Filter #27: write pending limit orders to pending_orders.json    |
//+------------------------------------------------------------------+
//| Iterates OrdersTotal() (NOT PositionsTotal — those are filled    |
//| positions tracked by WriteOpenOrders). Pending limits sit here    |
//| until they fill (move to PositionsTotal) or cancel (disappear).  |
//| Python uses this to detect TTL-expiring pending orders pre-cancel |
//| and to reconcile fills (a ticket that was in pending_orders.json  |
//| then appears in open_orders.json = fill detected).                |
//+------------------------------------------------------------------+
// Track our-magic count between ticks so we can log only on CHANGE,
// not every 25ms timer call. Filter #27.
static int g_lastPendingCount = -1;

// Filter #27 / Fix A — track ticket SET between ticks so we can detect when
// a specific ticket disappears (broker silent-cancel). OnTradeTransaction
// catches client-initiated and broker-notified cancels, but NOT the case
// where the broker auto-expires a TTL'd pending without notifying the
// terminal (confirmed seen on JustMarkets 2026-06-17 with GD-MI-1e53d69b).
// See docs/BUG_FILTER_27_PENDING_RECONCILER_GAP.md
#define FIX_A_MAX_PENDING 64
static ulong  g_prevPendingTickets[FIX_A_MAX_PENDING];
static int    g_prevPendingCount = 0;

// H5 (2026-06-17) — retry pool for tickets where HistoryOrderSelect failed
// on first attempt. Without this, a ticket that vanishes from OrdersTotal()
// before MT5 has populated its history record gets dropped permanently from
// the diff (replaced by the wholesale prev = current swap), and the
// poll-detect cancelled_orders.json entry is silently lost. Python's Fix B
// grace fallback still catches the DB row, but the forensic trail is gone.
// See docs/FILTER_27_AUDIT_BACKLOG.md H5.
//
// Retry semantics:
//   - On first miss: ticket added to retry pool with age=0
//   - Each subsequent tick: try HistoryOrderSelect again, age++
//   - If age >= FIX_A_RETRY_MAX_AGE: drop with Print warn (Python grace handles DB)
//   - On success: remove from retry pool (process normally)
#define FIX_A_RETRY_POOL    16
#define FIX_A_RETRY_MAX_AGE 3   // give MT5 ~3 ticks (~75ms) to populate history
static ulong  g_retryTickets[FIX_A_RETRY_POOL];
static int    g_retryAge[FIX_A_RETRY_POOL];
static int    g_retryCount = 0;

//+------------------------------------------------------------------+
//| H5 (2026-06-17): try to investigate a "lost" pending ticket via   |
//| HistoryOrderSelect. Returns:                                      |
//|    1  → resolved (wrote cancelled_orders.json or skipped non-our)|
//|   -1  → permanently skip (filled-state, double-write, etc.)      |
//|    0  → retry needed (HistoryOrderSelect failed, history not yet |
//|        populated; caller queues for next tick)                   |
//| Extracted from inline Fix A loop so both diff-path and retry-pool |
//| can share the logic. See docs/FILTER_27_AUDIT_BACKLOG.md H5.      |
//+------------------------------------------------------------------+
int TryProcessLostTicket(ulong prevTicket)
{
    if(!HistoryOrderSelect(prevTicket))
    {
        return 0;  // history not populated; caller should retry next tick
    }
    long magic = HistoryOrderGetInteger(prevTicket, ORDER_MAGIC);
    if(magic != InpMagic) return -1;  // not our ticket — done
    long stateRaw = HistoryOrderGetInteger(prevTicket, ORDER_STATE);
    if(stateRaw != ORDER_STATE_CANCELED && stateRaw != ORDER_STATE_EXPIRED)
        return -1;  // filled (became position) — OnTradeTransaction handles it

    // Idempotent guard — if cancelled_orders.json already contains this
    // ticket (OnTradeTransaction already wrote it), don't double-write.
    string existing = ReadFile(g_folder + "/cancelled_orders.json");
    string ticketKey = StringFormat("\"ticket\":\"%d\"", prevTicket);
    if(StringFind(existing, ticketKey) >= 0) return 1;  // already logged — done

    long reasonRaw = HistoryOrderGetInteger(prevTicket, ORDER_REASON);
    string symbol = HistoryOrderGetString(prevTicket, ORDER_SYMBOL);
    double volume = HistoryOrderGetDouble(prevTicket, ORDER_VOLUME_INITIAL);
    double price = HistoryOrderGetDouble(prevTicket, ORDER_PRICE_OPEN);
    long orderType = HistoryOrderGetInteger(prevTicket, ORDER_TYPE);
    datetime setupTime = (datetime)HistoryOrderGetInteger(prevTicket, ORDER_TIME_SETUP);
    datetime doneTime = (datetime)HistoryOrderGetInteger(prevTicket, ORDER_TIME_DONE);
    string comment = HistoryOrderGetString(prevTicket, ORDER_COMMENT);

    string typeStr = "UNKNOWN";
    if(orderType == ORDER_TYPE_BUY_LIMIT)       typeStr = "BUY_LIMIT";
    else if(orderType == ORDER_TYPE_SELL_LIMIT) typeStr = "SELL_LIMIT";
    else if(orderType == ORDER_TYPE_BUY_STOP)   typeStr = "BUY_STOP";
    else if(orderType == ORDER_TYPE_SELL_STOP)  typeStr = "SELL_STOP";

    // Tag state as "EXPIRED_POLLED" / "CANCELED_POLLED" so Python can
    // distinguish poll-detected vs OnTradeTransaction-detected.
    string stateStr = (stateRaw == ORDER_STATE_CANCELED) ? "CANCELED_POLLED" : "EXPIRED_POLLED";

    string entry_json = StringFormat(
        "{\"ticket\":\"%d\",\"symbol\":\"%s\",\"type\":\"%s\","
        "\"volume\":%.2f,\"price\":%.5f,"
        "\"setup_time\":\"%s\",\"done_time\":\"%s\","
        "\"state\":\"%s\",\"reason_code\":%d,"
        "\"magic\":%d,\"comment\":\"%s\",\"detected_via\":\"poll\"}",
        prevTicket,
        symbol,
        typeStr,
        volume,
        price,
        TimeToString(setupTime, TIME_DATE|TIME_SECONDS),
        TimeToString(doneTime, TIME_DATE|TIME_SECONDS),
        stateStr,
        (int)reasonRaw,
        magic,
        comment
    );
    AppendCancelledOrder(entry_json);
    Print("[DWX] PENDING ", stateStr, " (poll-detected): ticket=", prevTicket,
          " ", symbol, " ", typeStr, " @ ", price);
    return 1;  // resolved
}


void WritePendingOrders()
{
    string json = "{";
    int total = OrdersTotal();
    bool first = true;
    int ourCount = 0;

    // Snapshot current tickets for Fix A diff. We size to FIX_A_MAX_PENDING; if
    // we ever have more pending orders than that, the older ones get dropped
    // from the diff (but lost-detection still works for the most-recent slice).
    ulong currentTickets[FIX_A_MAX_PENDING];
    int currentCount = 0;

    for(int i = 0; i < total; i++)
    {
        ulong ticket = OrderGetTicket(i);
        if(ticket == 0) continue;

        long magic = OrderGetInteger(ORDER_MAGIC);
        if(magic != InpMagic) continue;  // Filter to OUR orders only

        ourCount++;
        if(currentCount < FIX_A_MAX_PENDING)
        {
            currentTickets[currentCount] = ticket;
            currentCount++;
        }
        // M5 (2026-06-17): warn on overflow so silent diff-truncation is observable.
        // Bumped on count-change pattern (g_lastPendingCount below) so we don't
        // spam every 25ms tick when count is stable.
        else if(ourCount != g_lastPendingCount)
        {
            Print("[DWX] WARN: M5 pending count ", ourCount,
                  " > FIX_A_MAX_PENDING=", FIX_A_MAX_PENDING,
                  " — diff truncated, lost-ticket detection incomplete for overflow");
        }

        if(!first) json += ",";
        first = false;

        string symbol = OrderGetString(ORDER_SYMBOL);
        double volume = OrderGetDouble(ORDER_VOLUME_CURRENT);
        double price = OrderGetDouble(ORDER_PRICE_OPEN);
        double sl = OrderGetDouble(ORDER_SL);
        double tp = OrderGetDouble(ORDER_TP);
        long orderType = OrderGetInteger(ORDER_TYPE);
        datetime setupTime = (datetime)OrderGetInteger(ORDER_TIME_SETUP);
        datetime expiration = (datetime)OrderGetInteger(ORDER_TIME_EXPIRATION);
        string comment = OrderGetString(ORDER_COMMENT);

        string typeStr = "UNKNOWN";
        if(orderType == ORDER_TYPE_BUY_LIMIT)       typeStr = "BUY_LIMIT";
        else if(orderType == ORDER_TYPE_SELL_LIMIT) typeStr = "SELL_LIMIT";
        else if(orderType == ORDER_TYPE_BUY_STOP)   typeStr = "BUY_STOP";
        else if(orderType == ORDER_TYPE_SELL_STOP)  typeStr = "SELL_STOP";

        json += StringFormat(
            "\"%d\":{\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.2f,"
            "\"price\":%.5f,\"sl\":%.5f,\"tp\":%.5f,"
            "\"setup_time\":\"%s\",\"expiration\":\"%s\","
            "\"magic\":%d,\"comment\":\"%s\"}",
            ticket,
            symbol,
            typeStr,
            volume,
            price, sl, tp,
            TimeToString(setupTime, TIME_DATE|TIME_SECONDS),
            TimeToString(expiration, TIME_DATE|TIME_SECONDS),
            magic,
            comment
        );
    }
    json += "}";

    WriteFile(g_folder + "/pending_orders.json", json);

    // ---- H5 (2026-06-17): retry pool — process tickets where previous tick's
    // HistoryOrderSelect failed. Each gets up to FIX_A_RETRY_MAX_AGE attempts. ----
    int newRetryCount = 0;
    ulong   newRetryTickets[FIX_A_RETRY_POOL];
    int     newRetryAge[FIX_A_RETRY_POOL];
    for(int r = 0; r < g_retryCount; r++)
    {
        ulong retryTicket = g_retryTickets[r];
        int   retryAge    = g_retryAge[r];
        int   result      = TryProcessLostTicket(retryTicket);
        // result: 1 = resolved (wrote cancelled or skipped non-our-magic/non-cancel)
        //        -1 = skip permanently (filled-state, double-write, etc.)
        //         0 = retry (HistoryOrderSelect still failing)
        if(result != 0) continue;  // resolved or permanently skipped — drop from pool
        // Retry: bump age, re-add to pool only if under max
        if(retryAge + 1 >= FIX_A_RETRY_MAX_AGE)
        {
            Print("[DWX] PENDING POLL-DETECT retry exhausted: ticket=", retryTicket,
                  " (age=", retryAge + 1, ", max=", FIX_A_RETRY_MAX_AGE,
                  ") — Python Fix B grace will resolve DB row");
            continue;  // give up on this ticket; Python Fix B will catch DB row
        }
        if(newRetryCount < FIX_A_RETRY_POOL)
        {
            newRetryTickets[newRetryCount] = retryTicket;
            newRetryAge[newRetryCount]     = retryAge + 1;
            newRetryCount++;
        }
        else
        {
            Print("[DWX] WARN: H5 retry pool full (FIX_A_RETRY_POOL=",
                  FIX_A_RETRY_POOL, ") — dropping ticket ", retryTicket,
                  " (age=", retryAge, "). Python Fix B grace will catch DB row.");
        }
    }

    // ---- Fix A — detect tickets in prev set but not in current set ----
    // For each "lost" ticket: try to process it now, queue for retry if history
    // not populated yet. See TryProcessLostTicket for full logic.
    for(int p = 0; p < g_prevPendingCount; p++)
    {
        ulong prevTicket = g_prevPendingTickets[p];
        bool stillPresent = false;
        for(int c = 0; c < currentCount; c++)
        {
            if(currentTickets[c] == prevTicket) { stillPresent = true; break; }
        }
        if(stillPresent) continue;

        int result = TryProcessLostTicket(prevTicket);
        if(result == 0)
        {
            // History not yet populated — queue for retry next tick.
            // Skip if already in newRetry pool (rare race: ticket was already
            // pending retry from a prior tick AND just disappeared from current).
            bool alreadyQueued = false;
            for(int q = 0; q < newRetryCount; q++)
            {
                if(newRetryTickets[q] == prevTicket) { alreadyQueued = true; break; }
            }
            if(!alreadyQueued && newRetryCount < FIX_A_RETRY_POOL)
            {
                newRetryTickets[newRetryCount] = prevTicket;
                newRetryAge[newRetryCount]     = 0;
                newRetryCount++;
            }
            else if(!alreadyQueued)
            {
                Print("[DWX] WARN: H5 retry pool full (FIX_A_RETRY_POOL=",
                      FIX_A_RETRY_POOL, ") — dropping new lost ticket ",
                      prevTicket, ". Python Fix B grace will catch DB row.");
            }
        }
        // result 1 (resolved) or -1 (skip permanently) → done with this ticket
    }
    // Persist new retry pool for next tick
    for(int i = 0; i < newRetryCount; i++)
    {
        g_retryTickets[i] = newRetryTickets[i];
        g_retryAge[i]     = newRetryAge[i];
    }
    g_retryCount = newRetryCount;

    // Replace prev with current for next tick
    for(int i = 0; i < currentCount; i++) g_prevPendingTickets[i] = currentTickets[i];
    g_prevPendingCount = currentCount;
    // ---- end Fix A ----

    // Log on count CHANGE only (avoids 25ms-tick spam). Catches: a new pending
    // appearing (Python sent OPEN_PENDING), or one disappearing (filled OR
    // cancelled — Python's pending_order_monitor will distinguish via
    // open_orders.json vs cancelled_orders.json).
    if(ourCount != g_lastPendingCount)
    {
        Print("[DWX] pending_orders.json count changed: ", g_lastPendingCount,
              " -> ", ourCount, " (our magic ", InpMagic, ")");
        g_lastPendingCount = ourCount;
    }
}

//+------------------------------------------------------------------+
//| Write bar data (M3, H1, D for each symbol)                       |
//+------------------------------------------------------------------+
void WriteBarData()
{
    for(int i = 0; i < g_numSymbols; i++)
    {
        WriteSymbolBars(g_symbols[i], PERIOD_M3, 100, "M3");
        WriteSymbolBars(g_symbols[i], PERIOD_H1, 30, "H1");
        WriteSymbolBars(g_symbols[i], PERIOD_D1, 5, "D1");
    }
}

void WriteSymbolBars(string symbol, ENUM_TIMEFRAMES tf, int count, string tfLabel)
{
    MqlRates rates[];
    int copied = CopyRates(symbol, tf, 0, count, rates);
    if(copied <= 0) return;

    // M3 fix (2026-06-19): warn if CopyRates returned fewer bars than
    // requested. Indicates broker/MT5 history is stale or chart hasn't
    // caught up after reconnect. Python side has its own min-bar check
    // (h1 < 6 → skip cycle) so this is diagnostic only — but without the
    // warn we'd have no signal that the EA is feeding partial data.
    if(copied < count) {
        PrintFormat("[DWX] WARN: CopyRates partial - symbol=%s tf=%s requested=%d got=%d",
                    symbol, tfLabel, count, copied);
    }

    string json = "[";
    for(int i = 0; i < copied; i++)
    {
        if(i > 0) json += ",";
        json += StringFormat(
            "{\"time\":\"%s\",\"open\":%.5f,\"high\":%.5f,\"low\":%.5f,"
            "\"close\":%.5f,\"volume\":%d,\"spread\":%d}",
            TimeToString(rates[i].time, TIME_DATE|TIME_SECONDS),
            rates[i].open, rates[i].high, rates[i].low, rates[i].close,
            (int)rates[i].tick_volume, rates[i].spread
        );
    }
    json += "]";

    // Replace dots in symbol for filename: XAUUSD.ecn → XAUUSD_ecn
    string safeSymbol = symbol;
    StringReplace(safeSymbol, ".", "_");
    WriteFile(g_folder + "/bars_" + safeSymbol + "_" + tfLabel + ".json", json);
}

//+------------------------------------------------------------------+
//| Read and execute commands from Python                             |
//+------------------------------------------------------------------+
void ReadCommands()
{
    string search = g_folder + "/commands/*.txt";
    string filename;
    long handle = FileFindFirst(search, filename, FILE_COMMON);

    if(handle == INVALID_HANDLE) return;

    do
    {
        string fullPath = g_folder + "/commands/" + filename;
        string content = ReadFile(fullPath);
        if(content == "") continue;

        // Parse and execute
        ProcessCommand(content, filename);

        // Delete processed command file
        FileDelete(fullPath, FILE_COMMON);

    } while(FileFindNext(handle, filename));

    FileFindClose(handle);
}

//+------------------------------------------------------------------+
//| H2 (2026-06-17): write response to BOTH last_response.json AND   |
//| responses/<cmdfile>.json (per-cmd response). Python correlates  |
//| command→response by cmd file name (no race possible across the  |
//| 4 services). last_response.json kept for backward compat / EA   |
//| observability via Experts log.                                   |
//| See docs/FILTER_27_AUDIT_BACKLOG.md H2.                          |
//+------------------------------------------------------------------+
void WriteFinalResponse(string content, string filename)
{
    // Per-cmd response file (canonical, race-free path for Python)
    if(StringLen(filename) > 0)
    {
        FolderCreate(g_folder + "/responses", FILE_COMMON);
        WriteFile(g_folder + "/responses/" + filename, content);
    }
    // Shared file (backward compat + observability — each command's response
    // overwrites the previous, so this is best-effort only)
    WriteFile(g_folder + "/last_response.json", content);
}


//+------------------------------------------------------------------+
//| Process a single command                                          |
//+------------------------------------------------------------------+
void ProcessCommand(string cmd, string filename)
{
    string parts[];
    int n = StringSplit(cmd, '|', parts);
    if(n < 2) return;

    string action = parts[0];
    StringTrimLeft(action);
    StringTrimRight(action);

    Print("[DWX] Command: ", cmd);

    if(action == "OPEN" && n >= 7)
    {
        // OPEN|SYMBOL|TYPE|VOLUME|PRICE|SL|TP|COMMENT
        // The COMMENT field may itself contain '|' (e.g., "strategy|trade_ref"),
        // and StringSplit eagerly consumed all separators. Re-join parts[7..n-1]
        // to preserve the full original comment so the broker stores trade_ref.
        string symbol = parts[1];
        string type = parts[2];
        double volume = StringToDouble(parts[3]);
        double price = StringToDouble(parts[4]);
        double sl = StringToDouble(parts[5]);
        double tp = StringToDouble(parts[6]);
        string comment = "";
        if(n >= 8)
        {
            comment = parts[7];
            for(int i = 8; i < n; i++) comment = comment + "|" + parts[i];
        }

        ExecuteOpen(symbol, type, volume, price, sl, tp, comment, filename);
    }
    else if(action == "MODIFY" && n >= 4)
    {
        // MODIFY|TICKET|SL|TP
        ulong ticket = (ulong)StringToInteger(parts[1]);
        double sl = StringToDouble(parts[2]);
        double tp = StringToDouble(parts[3]);

        ExecuteModify(ticket, sl, tp, filename);
    }
    else if(action == "CLOSE" && n >= 2)
    {
        // CLOSE|TICKET
        ulong ticket = (ulong)StringToInteger(parts[1]);
        ExecuteClose(ticket, filename);
    }
    else if(action == "CLOSE_ALL")
    {
        ExecuteCloseAll(filename);
    }
    else if(action == "CLOSE_PARTIAL" && n >= 3)
    {
        // CLOSE_PARTIAL|TICKET|VOLUME_LOTS
        // Filter #7: close partial volume of a position. Remainder stays open
        // with original SL/TP. OnTradeTransaction logs the partial close to
        // closed_orders.json with the same JSON shape as full closes — Python
        // detects "partial" by comparing volume to the original position size.
        if(!InpPartialTPEnabled)
        {
            WriteFinalResponse(
                "{\"success\":false,\"error\":\"PartialTP disabled (InpPartialTPEnabled=false)\"}",
                filename);
            Print("[DWX] CLOSE_PARTIAL rejected: feature flag off");
        }
        else
        {
            ulong ticket = (ulong)StringToInteger(parts[1]);
            double volumeLots = StringToDouble(parts[2]);
            ExecuteClosePartial(ticket, volumeLots, filename);
        }
    }
    else if(action == "OPEN_PENDING" && n >= 9)
    {
        // Filter #27: place a pending limit order.
        // OPEN_PENDING|SYMBOL|BUY_LIMIT|SELL_LIMIT|VOLUME|PRICE|SL|TP|TTL_SECONDS|COMMENT
        // Broker auto-cancels at TimeCurrent() + ttl_seconds via ORDER_TIME_SPECIFIED
        // expiration. Python's APScheduler also fires CANCEL_PENDING at TTL+5s as
        // belt-and-suspenders.
        string symbol = parts[1];
        string type = parts[2];
        double volume = StringToDouble(parts[3]);
        double price = StringToDouble(parts[4]);
        double sl = StringToDouble(parts[5]);
        double tp = StringToDouble(parts[6]);
        int ttl_seconds = (int)StringToInteger(parts[7]);
        // Comment may itself contain '|' (e.g., "strategy|trade_ref"). Re-join
        // parts[8..n-1] like OPEN does to preserve full original comment.
        string comment = "";
        if(n >= 9)
        {
            comment = parts[8];
            for(int i = 9; i < n; i++) comment = comment + "|" + parts[i];
        }
        ExecuteOpenPending(symbol, type, volume, price, sl, tp, ttl_seconds, comment, filename);
    }
    else if(action == "CANCEL_PENDING" && n >= 2)
    {
        // Filter #27: cancel a pending limit order by ticket. Idempotent.
        // CANCEL_PENDING|TICKET
        ulong ticket = (ulong)StringToInteger(parts[1]);
        ExecuteCancelPending(ticket, filename);
    }
    else
    {
        Print("[DWX] Unknown command: ", action);
        WriteFinalResponse("{\"success\":false,\"error\":\"Unknown command: " + action + "\"}", filename);
    }
}

//+------------------------------------------------------------------+
//| Filter #27 / C1 — derive `accepted` from BOTH OrderSend() return  |
//| value AND result.retcode. OrderSend returning true only means the |
//| request reached the trade server; the broker's accept/reject is  |
//| in result.retcode. Without this guard, rejections (10016 invalid |
//| stops, 10018 market closed, etc.) get JSON-serialized as          |
//| success=true with ticket=0 — Python downstream catches malformed |
//| ticket but loses the retcode in the structured response. See     |
//| docs/FILTER_27_AUDIT_BACKLOG.md item C1 + 2026-06-17 RCA.         |
//|                                                                   |
//| Returns true ONLY when:                                           |
//|   sent (delivered to trade server) AND                            |
//|   retcode in {DONE, PLACED, DONE_PARTIAL}                         |
//+------------------------------------------------------------------+
bool IsOrderAccepted(bool sent, uint retcode)
{
    if(!sent) return false;
    return retcode == TRADE_RETCODE_DONE
        || retcode == TRADE_RETCODE_PLACED
        || retcode == TRADE_RETCODE_DONE_PARTIAL;
}

//+------------------------------------------------------------------+
//| Execute market order                                              |
//+------------------------------------------------------------------+
void ExecuteOpen(string symbol, string type, double volume, double price, double sl, double tp, string comment, string filename)
{
    MqlTradeRequest request = {};
    MqlTradeResult result = {};

    request.action = TRADE_ACTION_DEAL;
    request.symbol = symbol;
    request.volume = volume;
    request.sl = sl;
    request.tp = tp;
    request.deviation = 20;
    request.magic = InpMagic;
    request.comment = comment;
    request.type_filling = ORDER_FILLING_FOK;

    if(type == "BUY")
    {
        request.type = ORDER_TYPE_BUY;
        request.price = SymbolInfoDouble(symbol, SYMBOL_ASK);
    }
    else
    {
        request.type = ORDER_TYPE_SELL;
        request.price = SymbolInfoDouble(symbol, SYMBOL_BID);
    }

    bool sent = OrderSend(request, result);
    bool accepted = IsOrderAccepted(sent, result.retcode);

    string response = StringFormat(
        "{\"success\":%s,\"ticket\":%d,\"price\":%.5f,\"volume\":%.2f,"
        "\"retcode\":%d,\"comment\":\"%s\"}",
        accepted ? "true" : "false",
        result.order,
        result.price,
        result.volume,
        result.retcode,
        result.comment
    );

    WriteFinalResponse(response, filename);

    if(accepted)
        Print("[DWX] Order opened: ", symbol, " ", type, " ", volume, " @ ", result.price, " ticket=", result.order);
    else
        Print("[DWX] Order FAILED: ", symbol, " sent=", sent, " retcode=", result.retcode, " ", result.comment);
}

//+------------------------------------------------------------------+
//| Filter #27: place a pending limit order with TTL expiration       |
//+------------------------------------------------------------------+
void ExecuteOpenPending(string symbol, string type, double volume, double price,
                       double sl, double tp, int ttl_seconds, string comment, string filename)
{
    MqlTradeRequest request = {};
    MqlTradeResult result = {};

    request.action = TRADE_ACTION_PENDING;
    request.symbol = symbol;
    request.volume = volume;
    request.price = price;
    request.sl = sl;
    request.tp = tp;
    request.deviation = 20;
    request.magic = InpMagic;
    request.comment = comment;
    request.type_filling = ORDER_FILLING_RETURN;
    // Broker-side TTL: order auto-cancels at this time. Python's APScheduler
    // also fires CANCEL_PENDING at TTL+5s as belt-and-suspenders.
    request.type_time = ORDER_TIME_SPECIFIED;
    request.expiration = (datetime)(TimeCurrent() + ttl_seconds);

    if(type == "BUY_LIMIT")
        request.type = ORDER_TYPE_BUY_LIMIT;
    else if(type == "SELL_LIMIT")
        request.type = ORDER_TYPE_SELL_LIMIT;
    else
    {
        WriteFinalResponse(
            StringFormat("{\"success\":false,\"error\":\"Unknown pending type: %s\"}", type),
            filename);
        Print("[DWX] OPEN_PENDING rejected: unknown type ", type);
        return;
    }

    bool sent = OrderSend(request, result);
    bool accepted = IsOrderAccepted(sent, result.retcode);

    string response = StringFormat(
        "{\"success\":%s,\"ticket\":%d,\"price\":%.5f,\"volume\":%.2f,"
        "\"expiration\":\"%s\",\"retcode\":%d,\"comment\":\"%s\"}",
        accepted ? "true" : "false",
        result.order,
        result.price,
        result.volume,
        TimeToString(request.expiration, TIME_DATE|TIME_SECONDS),
        result.retcode,
        result.comment
    );

    WriteFinalResponse(response, filename);

    if(accepted)
        Print("[DWX] Pending placed: ", symbol, " ", type, " ", volume,
              " @ ", price, " ttl=", ttl_seconds, "s ticket=", result.order);
    else
        Print("[DWX] Pending FAILED: ", symbol, " sent=", sent, " retcode=", result.retcode, " ", result.comment);
}

//+------------------------------------------------------------------+
//| Filter #27: cancel a pending limit order. Idempotent.             |
//+------------------------------------------------------------------+
void ExecuteCancelPending(ulong ticket, string filename)
{
    MqlTradeRequest request = {};
    MqlTradeResult result = {};

    request.action = TRADE_ACTION_REMOVE;
    request.order = ticket;

    bool sent = OrderSend(request, result);
    bool accepted = IsOrderAccepted(sent, result.retcode);

    string response = StringFormat(
        "{\"success\":%s,\"ticket\":%d,\"retcode\":%d,\"comment\":\"%s\"}",
        accepted ? "true" : "false",
        ticket,
        result.retcode,
        result.comment
    );

    WriteFinalResponse(response, filename);

    if(accepted)
        Print("[DWX] Pending cancelled: ticket=", ticket);
    else
        // Common harmless cases: order already filled, already cancelled, already
        // expired by broker. Python caller treats by retcode, not as a hard error.
        Print("[DWX] CANCEL_PENDING failed (often harmless): ticket=", ticket,
              " sent=", sent, " retcode=", result.retcode, " ", result.comment);
}

//+------------------------------------------------------------------+
//| Modify position SL/TP                                            |
//+------------------------------------------------------------------+
void ExecuteModify(ulong ticket, double sl, double tp, string filename)
{
    MqlTradeRequest request = {};
    MqlTradeResult result = {};

    request.action = TRADE_ACTION_SLTP;
    request.position = ticket;

    // Get current position info
    if(!PositionSelectByTicket(ticket))
    {
        WriteFinalResponse(
            StringFormat("{\"success\":false,\"error\":\"Position %d not found\"}", ticket),
            filename);
        return;
    }

    request.symbol = PositionGetString(POSITION_SYMBOL);
    request.sl = sl;
    request.tp = (tp > 0) ? tp : PositionGetDouble(POSITION_TP);

    bool sent = OrderSend(request, result);
    bool accepted = IsOrderAccepted(sent, result.retcode);

    string response = StringFormat(
        "{\"success\":%s,\"ticket\":%d,\"retcode\":%d,\"comment\":\"%s\"}",
        accepted ? "true" : "false",
        ticket,
        result.retcode,
        result.comment
    );

    WriteFinalResponse(response, filename);

    if(accepted)
        Print("[DWX] Modified #", ticket, " SL=", sl, " TP=", tp);
    else
        Print("[DWX] Modify FAILED #", ticket, " sent=", sent, " retcode=", result.retcode, " ", result.comment);
}

//+------------------------------------------------------------------+
//| Close position                                                    |
//+------------------------------------------------------------------+
void ExecuteClose(ulong ticket, string filename)
{
    if(!PositionSelectByTicket(ticket))
    {
        WriteFinalResponse(
            StringFormat("{\"success\":false,\"error\":\"Position %d not found\"}", ticket),
            filename);
        return;
    }

    MqlTradeRequest request = {};
    MqlTradeResult result = {};

    string symbol = PositionGetString(POSITION_SYMBOL);
    double volume = PositionGetDouble(POSITION_VOLUME);
    long posType = PositionGetInteger(POSITION_TYPE);

    request.action = TRADE_ACTION_DEAL;
    request.position = ticket;
    request.symbol = symbol;
    request.volume = volume;
    request.deviation = 20;
    request.magic = InpMagic;
    request.type_filling = ORDER_FILLING_FOK;

    if(posType == POSITION_TYPE_BUY)
    {
        request.type = ORDER_TYPE_SELL;
        request.price = SymbolInfoDouble(symbol, SYMBOL_BID);
    }
    else
    {
        request.type = ORDER_TYPE_BUY;
        request.price = SymbolInfoDouble(symbol, SYMBOL_ASK);
    }

    bool sent = OrderSend(request, result);
    bool accepted = IsOrderAccepted(sent, result.retcode);

    string response = StringFormat(
        "{\"success\":%s,\"ticket\":%d,\"close_price\":%.5f,\"retcode\":%d,\"comment\":\"%s\"}",
        accepted ? "true" : "false",
        ticket,
        result.price,
        result.retcode,
        result.comment
    );

    WriteFinalResponse(response, filename);

    if(accepted)
        Print("[DWX] Closed #", ticket, " @ ", result.price);
    else
        Print("[DWX] Close FAILED #", ticket, " sent=", sent, " retcode=", result.retcode, " ", result.comment);
}

//+------------------------------------------------------------------+
//| Close all positions                                               |
//+------------------------------------------------------------------+
void ExecuteCloseAll(string filename)
{
    int total = PositionsTotal();
    int closed = 0;
    for(int i = total - 1; i >= 0; i--)
    {
        ulong ticket = PositionGetTicket(i);
        if(ticket > 0)
        {
            // Per-position close writes only to last_response.json (passing empty
            // filename) so the loop's intermediate writes don't clobber the final
            // CLOSE_ALL response. Final summary written below.
            ExecuteClose(ticket, "");
            closed++;
        }
    }
    Print("[DWX] CloseAll: closed ", closed, " positions");
    // Single per-cmd response for the CLOSE_ALL command itself.
    string summary = StringFormat("{\"success\":true,\"closed_count\":%d,\"action\":\"CLOSE_ALL\"}", closed);
    WriteFinalResponse(summary, filename);
}

//+------------------------------------------------------------------+
//| Close PARTIAL position volume (Filter #7)                        |
//| Sends an opposite-side market deal with volume < position volume.|
//| MT5 nets it against the existing position: position remains open |
//| with reduced volume, and a partial close shows in deal history   |
//| (which OnTradeTransaction picks up and writes to closed_orders).  |
//+------------------------------------------------------------------+
void ExecuteClosePartial(ulong ticket, double volumeLots, string filename)
{
    if(!PositionSelectByTicket(ticket))
    {
        WriteFinalResponse(
            StringFormat("{\"success\":false,\"error\":\"Position %d not found\"}", ticket),
            filename);
        return;
    }

    string symbol = PositionGetString(POSITION_SYMBOL);
    double posVolume = PositionGetDouble(POSITION_VOLUME);
    long   posType   = PositionGetInteger(POSITION_TYPE);

    // Sanity: requested volume must be > 0 and < full position size
    // (= full close should use CLOSE, not CLOSE_PARTIAL).
    double minLot  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
    double lotStep = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
    if(lotStep > 0)
        volumeLots = MathRound(volumeLots / lotStep) * lotStep;
    if(volumeLots < minLot)
    {
        WriteFinalResponse(
            StringFormat("{\"success\":false,\"error\":\"Requested partial volume %.4f below min %.4f\"}",
                volumeLots, minLot),
            filename);
        return;
    }
    if(volumeLots >= posVolume)
    {
        WriteFinalResponse(
            StringFormat("{\"success\":false,\"error\":\"Requested partial volume %.2f >= position volume %.2f (use CLOSE not CLOSE_PARTIAL)\"}",
                volumeLots, posVolume),
            filename);
        return;
    }
    // Remaining volume must also be >= minLot, else broker rejects (orphan dust).
    double remaining = posVolume - volumeLots;
    if(remaining < minLot)
    {
        WriteFinalResponse(
            StringFormat("{\"success\":false,\"error\":\"Remaining %.4f < min lot %.4f after partial — would orphan dust\"}",
                remaining, minLot),
            filename);
        return;
    }

    MqlTradeRequest request = {};
    MqlTradeResult result = {};

    request.action     = TRADE_ACTION_DEAL;
    request.position   = ticket;
    request.symbol     = symbol;
    request.volume     = volumeLots;
    request.deviation  = 20;
    request.magic      = InpMagic;
    request.type_filling = ORDER_FILLING_FOK;

    if(posType == POSITION_TYPE_BUY)
    {
        request.type  = ORDER_TYPE_SELL;
        request.price = SymbolInfoDouble(symbol, SYMBOL_BID);
    }
    else
    {
        request.type  = ORDER_TYPE_BUY;
        request.price = SymbolInfoDouble(symbol, SYMBOL_ASK);
    }

    bool sent = OrderSend(request, result);
    bool accepted = IsOrderAccepted(sent, result.retcode);

    string response = StringFormat(
        "{\"success\":%s,\"ticket\":%d,\"close_price\":%.5f,\"closed_volume\":%.2f,"
        "\"remaining_volume\":%.2f,\"retcode\":%d,\"comment\":\"%s\",\"partial\":true}",
        accepted ? "true" : "false",
        ticket,
        result.price,
        accepted ? volumeLots : 0.0,
        accepted ? remaining  : posVolume,
        result.retcode,
        result.comment
    );

    WriteFinalResponse(response, filename);

    if(accepted)
        Print("[DWX] PARTIAL #", ticket, " closed ", volumeLots, " lots @ ", result.price,
              " (remaining=", remaining, ")");
    else
        Print("[DWX] PARTIAL FAILED #", ticket, " sent=", sent, " retcode=", result.retcode, " ", result.comment);
}

//+------------------------------------------------------------------+
//| Write response for command feedback                               |
//+------------------------------------------------------------------+
void WriteResponse(string content, string cmdFile)
{
    // Response file named after command file
    string respFile = g_folder + "/responses/" + cmdFile;
    FolderCreate(g_folder + "/responses", FILE_COMMON);
    WriteFile(respFile, content);
}

//+------------------------------------------------------------------+
//| UTILITY: Write string to file (atomic)                           |
//|                                                                  |
//| FILE_SHARE_READ|FILE_SHARE_WRITE: allow other processes (Python  |
//| backends reading market_data.json, open_orders.json, etc.) to    |
//| have the file open while we write. Without these flags MT5 takes |
//| an exclusive lock and reader contention surfaces as              |
//| ERR_FILE_CANNOT_OPEN (5004) every few seconds — burst observed   |
//| post-Filter #7 ship 2026-06-13 when partial-TP poller added a    |
//| 4th concurrent reader path. Fix: 2026-06-15.                     |
//+------------------------------------------------------------------+
void WriteFile(string path, string content)
{
    int handle = FileOpen(path,
        FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE);
    if(handle == INVALID_HANDLE)
    {
        Print("[DWX] Failed to write: ", path, " Error: ", GetLastError());
        return;
    }
    FileWriteString(handle, content);
    FileClose(handle);
}

//+------------------------------------------------------------------+
//| UTILITY: Read string from file                                   |
//|                                                                  |
//| FILE_SHARE flags symmetric with WriteFile so concurrent          |
//| read+write between MT5 and Python backends never blocks.         |
//+------------------------------------------------------------------+
string ReadFile(string path)
{
    int handle = FileOpen(path,
        FILE_READ|FILE_TXT|FILE_COMMON|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE);
    if(handle == INVALID_HANDLE) return "";

    string content = "";
    while(!FileIsEnding(handle))
    {
        content += FileReadString(handle);
    }
    FileClose(handle);
    return content;
}

//+------------------------------------------------------------------+
//| Tick event (not used — we use timer for consistent polling)      |
//+------------------------------------------------------------------+
void OnTick()
{
    // Timer handles everything
}

//+------------------------------------------------------------------+
//| OnTradeTransaction — capture closed positions and append to      |
//| closed_orders.json so Python has the AUTHORITATIVE fill price    |
//| and reason. Replaces the heuristic in check_open_positions()     |
//| that misattributed BE-then-TP exits as SL+\$9 instead of TP+\$910. |
//|                                                                   |
//| File format: JSON array, each entry one closed position:         |
//|   {                                                               |
//|     "ticket":"2032606267",                                        |
//|     "symbol":"XAUUSD.ecn",                                        |
//|     "type":"SELL",                                                |
//|     "volume":0.30,                                                |
//|     "open_price":4204.66, "open_time":"2026.06.10 10:00:01",      |
//|     "close_price":4174.30, "close_time":"2026.06.10 11:04:00",    |
//|     "profit":910.80, "swap":0.00, "commission":-2.40,             |
//|     "magic":200000, "comment":"micro_alpha_sweep|GD-MI-cce2a254", |
//|     "deal_reason":"DEAL_REASON_TP"                                |
//|   }                                                               |
//|                                                                   |
//| Trimmed to last 200 entries to avoid unbounded growth.            |
//+------------------------------------------------------------------+
void OnTradeTransaction(
    const MqlTradeTransaction& trans,
    const MqlTradeRequest& request,
    const MqlTradeResult& result)
{
    // Filter #27: capture pending-order cancellations (TTL expired or manual
    // cancel). Without this Python doesn't know whether a missing pending
    // order filled or expired — it can only see "the ticket is no longer in
    // pending_orders.json". Writing cancelled_orders.json gives us a positive
    // signal to journal LIMIT_TTL_EXPIRED.
    if(trans.type == TRADE_TRANSACTION_ORDER_DELETE && trans.order != 0)
    {
        // Pull from history: HistoryOrderSelect populates the readers
        if(HistoryOrderSelect(trans.order))
        {
            long magic = HistoryOrderGetInteger(trans.order, ORDER_MAGIC);
            if(magic == InpMagic)
            {
                long stateRaw = HistoryOrderGetInteger(trans.order, ORDER_STATE);
                long reasonRaw = HistoryOrderGetInteger(trans.order, ORDER_REASON);
                // Only log if the order was CANCELLED or EXPIRED — not if it was
                // filled (that becomes a position; we don't double-log here).
                // ORDER_STATE_FILLED means the order became a position — skip.
                // ORDER_STATE_CANCELED / ORDER_STATE_EXPIRED are the cases we want.
                if(stateRaw == ORDER_STATE_CANCELED || stateRaw == ORDER_STATE_EXPIRED)
                {
                    // M4 (2026-06-17): dedup against cancelled_orders.json. The
                    // Fix A poll-path may have written this ticket already (race:
                    // poll detects ORDER vanishing from OrdersTotal() before
                    // OnTradeTransaction fires). Same StringFind pattern as
                    // TryProcessLostTicket. See docs/FILTER_27_AUDIT_BACKLOG.md M4.
                    string existing_m4 = ReadFile(g_folder + "/cancelled_orders.json");
                    string ticketKey_m4 = StringFormat("\"ticket\":\"%d\"", trans.order);
                    if(StringFind(existing_m4, ticketKey_m4) >= 0)
                    {
                        Print("[DWX] M4: skipping double-write for ticket ", trans.order,
                              " — already in cancelled_orders.json (poll-path got it first)");
                        return;
                    }
                    string symbol = HistoryOrderGetString(trans.order, ORDER_SYMBOL);
                    double volume = HistoryOrderGetDouble(trans.order, ORDER_VOLUME_INITIAL);
                    double price = HistoryOrderGetDouble(trans.order, ORDER_PRICE_OPEN);
                    long orderType = HistoryOrderGetInteger(trans.order, ORDER_TYPE);
                    datetime setupTime = (datetime)HistoryOrderGetInteger(trans.order, ORDER_TIME_SETUP);
                    datetime doneTime = (datetime)HistoryOrderGetInteger(trans.order, ORDER_TIME_DONE);
                    string comment = HistoryOrderGetString(trans.order, ORDER_COMMENT);

                    string typeStr = "UNKNOWN";
                    if(orderType == ORDER_TYPE_BUY_LIMIT)       typeStr = "BUY_LIMIT";
                    else if(orderType == ORDER_TYPE_SELL_LIMIT) typeStr = "SELL_LIMIT";
                    else if(orderType == ORDER_TYPE_BUY_STOP)   typeStr = "BUY_STOP";
                    else if(orderType == ORDER_TYPE_SELL_STOP)  typeStr = "SELL_STOP";

                    string stateStr = (stateRaw == ORDER_STATE_CANCELED) ? "CANCELED" : "EXPIRED";

                    string entry_json = StringFormat(
                        "{\"ticket\":\"%d\",\"symbol\":\"%s\",\"type\":\"%s\","
                        "\"volume\":%.2f,\"price\":%.5f,"
                        "\"setup_time\":\"%s\",\"done_time\":\"%s\","
                        "\"state\":\"%s\",\"reason_code\":%d,"
                        "\"magic\":%d,\"comment\":\"%s\"}",
                        trans.order,
                        symbol,
                        typeStr,
                        volume,
                        price,
                        TimeToString(setupTime, TIME_DATE|TIME_SECONDS),
                        TimeToString(doneTime, TIME_DATE|TIME_SECONDS),
                        stateStr,
                        (int)reasonRaw,
                        magic,
                        comment
                    );

                    AppendCancelledOrder(entry_json);
                    Print("[DWX] PENDING ", stateStr, ": ticket=", trans.order,
                          " ", symbol, " ", typeStr, " @ ", price);
                }
            }
        }
        return;  // ORDER_DELETE handled — don't fall through to DEAL_ADD logic
    }

    // We only care about completed deals that close a position
    if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
    if(trans.deal == 0) return;

    // Select the deal so we can read its details
    if(!HistoryDealSelect(trans.deal)) return;

    // Only deals that EXIT a position (entry deals don't matter — those are tracked
    // via WriteOpenOrders). Exit deals have entry == DEAL_ENTRY_OUT or DEAL_ENTRY_INOUT.
    long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
    if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT) return;

    // Filter to OUR magic only — don't log other EAs' trades
    long magic = HistoryDealGetInteger(trans.deal, DEAL_MAGIC);
    if(magic != InpMagic) return;

    // Pull all the fields we need
    ulong  positionId  = HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);
    string symbol      = HistoryDealGetString(trans.deal, DEAL_SYMBOL);
    long   dealType    = HistoryDealGetInteger(trans.deal, DEAL_TYPE);
    double volume      = HistoryDealGetDouble(trans.deal, DEAL_VOLUME);
    double closePrice  = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
    datetime closeTime = (datetime)HistoryDealGetInteger(trans.deal, DEAL_TIME);
    double profit      = HistoryDealGetDouble(trans.deal, DEAL_PROFIT);
    double swap        = HistoryDealGetDouble(trans.deal, DEAL_SWAP);
    double commission  = HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
    long   reason      = HistoryDealGetInteger(trans.deal, DEAL_REASON);
    string comment     = HistoryDealGetString(trans.deal, DEAL_COMMENT);

    // Resolve open price/time from the position's entry deal (find by position_id)
    double openPrice = 0;
    datetime openTime = 0;
    string openComment = "";
    if(HistorySelectByPosition(positionId))
    {
        int dealsTotal = HistoryDealsTotal();
        for(int i = 0; i < dealsTotal; i++)
        {
            ulong t = HistoryDealGetTicket(i);
            if(t == 0) continue;
            long e = HistoryDealGetInteger(t, DEAL_ENTRY);
            if(e == DEAL_ENTRY_IN)
            {
                openPrice = HistoryDealGetDouble(t, DEAL_PRICE);
                openTime  = (datetime)HistoryDealGetInteger(t, DEAL_TIME);
                openComment = HistoryDealGetString(t, DEAL_COMMENT);
                break;
            }
        }
    }

    // The DEAL_REASON code maps to our exit_reason
    string reasonStr = "UNKNOWN";
    if(reason == DEAL_REASON_SL)        reasonStr = "SL";
    else if(reason == DEAL_REASON_TP)   reasonStr = "TP";
    else if(reason == DEAL_REASON_SO)   reasonStr = "SO";        // stop-out (margin call)
    else if(reason == DEAL_REASON_CLIENT) reasonStr = "CLIENT";  // manual close
    else if(reason == DEAL_REASON_EXPERT) reasonStr = "EXPERT";  // closed via API (CLOSE cmd from us)

    // Side BEFORE close = opposite of the deal type that's closing it.
    // DEAL_TYPE_SELL closes a BUY position; DEAL_TYPE_BUY closes a SELL position.
    string positionSide = (dealType == DEAL_TYPE_SELL) ? "BUY" : "SELL";

    string entry_json = StringFormat(
        "{\"ticket\":\"%d\",\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.2f,"
        "\"open_price\":%.5f,\"open_time\":\"%s\","
        "\"close_price\":%.5f,\"close_time\":\"%s\","
        "\"profit\":%.2f,\"swap\":%.2f,\"commission\":%.2f,"
        "\"magic\":%d,\"comment\":\"%s\",\"deal_reason\":\"%s\"}",
        positionId,
        symbol,
        positionSide,
        volume,
        openPrice, TimeToString(openTime, TIME_DATE|TIME_SECONDS),
        closePrice, TimeToString(closeTime, TIME_DATE|TIME_SECONDS),
        profit, swap, commission,
        magic,
        openComment,
        reasonStr
    );

    AppendClosedOrder(entry_json);
    Print("[DWX] CLOSED: pos=", positionId, " ", positionSide, " ", symbol,
          " @ ", closePrice, " profit=", profit, " reason=", reasonStr);
}

//+------------------------------------------------------------------+
//| Append a closed-order entry to closed_orders.json                |
//| Reads the existing file, parses minimally to count entries,      |
//| trims to last 200 keep + this new one, writes back.              |
//+------------------------------------------------------------------+
void AppendClosedOrder(string entry_json)
{
    string path = g_folder + "/closed_orders.json";
    string existing = ReadFile(path);

    // Build new array. Keep last 199 + new = 200 max.
    string newJson;
    if(StringLen(existing) < 5)  // empty or barely-existent file
    {
        newJson = "[" + entry_json + "]";
    }
    else
    {
        // Strip leading "[" and trailing "]"
        string trimmed = existing;
        StringTrimLeft(trimmed);
        StringTrimRight(trimmed);
        if(StringGetCharacter(trimmed, 0) == '[')
            trimmed = StringSubstr(trimmed, 1);
        int lastBracket = StringLen(trimmed) - 1;
        if(lastBracket >= 0 && StringGetCharacter(trimmed, lastBracket) == ']')
            trimmed = StringSubstr(trimmed, 0, lastBracket);
        StringTrimLeft(trimmed);
        StringTrimRight(trimmed);

        // Trim to last 199 entries by counting top-level "}{" boundaries.
        // Cheap approach: if the array has > 199 entries, drop oldest.
        // We approximate "entry count" by counting "{\"ticket\"" occurrences.
        int count = 0;
        int searchPos = 0;
        while(true)
        {
            int found = StringFind(trimmed, "{\"ticket\"", searchPos);
            if(found < 0) break;
            count++;
            searchPos = found + 1;
        }
        // Drop oldest entries until count < 200
        while(count >= 200)
        {
            int firstStart = StringFind(trimmed, "{\"ticket\"", 0);
            int secondStart = StringFind(trimmed, "{\"ticket\"", firstStart + 1);
            if(secondStart < 0) break;
            trimmed = StringSubstr(trimmed, secondStart);
            // Strip leading "," if present after the trim
            StringTrimLeft(trimmed);
            if(StringGetCharacter(trimmed, 0) == ',')
                trimmed = StringSubstr(trimmed, 1);
            StringTrimLeft(trimmed);
            count--;
        }

        if(StringLen(trimmed) > 0)
            newJson = "[" + trimmed + "," + entry_json + "]";
        else
            newJson = "[" + entry_json + "]";
    }

    WriteFile(path, newJson);
}

//+------------------------------------------------------------------+
//| Filter #27: Append a cancelled-order entry to cancelled_orders.json |
//| Same shape and trim semantics as AppendClosedOrder. Separate file  |
//| so Python's poller can distinguish FILLED-and-then-closed (closed_  |
//| orders.json) from CANCELLED-without-fill (cancelled_orders.json).   |
//+------------------------------------------------------------------+
void AppendCancelledOrder(string entry_json)
{
    string path = g_folder + "/cancelled_orders.json";
    string existing = ReadFile(path);

    string newJson;
    if(StringLen(existing) < 5)
    {
        newJson = "[" + entry_json + "]";
    }
    else
    {
        string trimmed = existing;
        StringTrimLeft(trimmed);
        StringTrimRight(trimmed);
        if(StringGetCharacter(trimmed, 0) == '[')
            trimmed = StringSubstr(trimmed, 1);
        int lastBracket = StringLen(trimmed) - 1;
        if(lastBracket >= 0 && StringGetCharacter(trimmed, lastBracket) == ']')
            trimmed = StringSubstr(trimmed, 0, lastBracket);
        StringTrimLeft(trimmed);
        StringTrimRight(trimmed);

        int count = 0;
        int searchPos = 0;
        while(true)
        {
            int found = StringFind(trimmed, "{\"ticket\"", searchPos);
            if(found < 0) break;
            count++;
            searchPos = found + 1;
        }
        while(count >= 200)
        {
            int firstStart = StringFind(trimmed, "{\"ticket\"", 0);
            int secondStart = StringFind(trimmed, "{\"ticket\"", firstStart + 1);
            if(secondStart < 0) break;
            trimmed = StringSubstr(trimmed, secondStart);
            StringTrimLeft(trimmed);
            if(StringGetCharacter(trimmed, 0) == ',')
                trimmed = StringSubstr(trimmed, 1);
            StringTrimLeft(trimmed);
            count--;
        }

        if(StringLen(trimmed) > 0)
            newJson = "[" + trimmed + "," + entry_json + "]";
        else
            newJson = "[" + entry_json + "]";
    }

    WriteFile(path, newJson);
}

//+------------------------------------------------------------------+
