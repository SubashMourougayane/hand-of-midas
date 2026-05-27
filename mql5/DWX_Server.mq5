//+------------------------------------------------------------------+
//|                                              DWX_Server.mq5       |
//|              Hand Of Midas — DWX Bridge (MT5 ↔ Python)            |
//|                                                                    |
//|  Thin server EA: streams prices, executes commands from Python.    |
//|  All strategy logic lives in Python. This EA just bridges.         |
//+------------------------------------------------------------------+
#property copyright "Hand Of Midas"
#property version   "2.00"
#property description "DWX Bridge: streams market data and executes orders from Python"
#property strict

input string InpSymbols = "XAUUSD.ecn,BRENT.ecn";  // Symbols to stream (comma-separated)
input int    InpTimerMs = 25;                        // Timer interval (ms)
input string InpFolder  = "DWX";                    // Folder in MQL5/Files/
input int    InpMagic   = 200000;                   // Magic number base

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

    Print("[DWX] Server started. Symbols: ", InpSymbols, " | Folder: ", g_folder);
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
        string symbol = parts[1];
        string type = parts[2];
        double volume = StringToDouble(parts[3]);
        double price = StringToDouble(parts[4]);
        double sl = StringToDouble(parts[5]);
        double tp = StringToDouble(parts[6]);
        string comment = (n >= 8) ? parts[7] : "";

        ExecuteOpen(symbol, type, volume, price, sl, tp, comment);
    }
    else if(action == "MODIFY" && n >= 4)
    {
        // MODIFY|TICKET|SL|TP
        ulong ticket = (ulong)StringToInteger(parts[1]);
        double sl = StringToDouble(parts[2]);
        double tp = StringToDouble(parts[3]);

        ExecuteModify(ticket, sl, tp);
    }
    else if(action == "CLOSE" && n >= 2)
    {
        // CLOSE|TICKET
        ulong ticket = (ulong)StringToInteger(parts[1]);
        ExecuteClose(ticket);
    }
    else if(action == "CLOSE_ALL")
    {
        ExecuteCloseAll();
    }
    else
    {
        Print("[DWX] Unknown command: ", action);
        WriteResponse("ERROR|Unknown command: " + action, filename);
    }
}

//+------------------------------------------------------------------+
//| Execute market order                                              |
//+------------------------------------------------------------------+
void ExecuteOpen(string symbol, string type, double volume, double price, double sl, double tp, string comment)
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

    bool success = OrderSend(request, result);

    string response = StringFormat(
        "{\"success\":%s,\"ticket\":%d,\"price\":%.5f,\"volume\":%.2f,"
        "\"retcode\":%d,\"comment\":\"%s\"}",
        success ? "true" : "false",
        result.order,
        result.price,
        result.volume,
        result.retcode,
        result.comment
    );

    WriteFile(g_folder + "/last_response.json", response);

    if(success)
        Print("[DWX] Order opened: ", symbol, " ", type, " ", volume, " @ ", result.price, " ticket=", result.order);
    else
        Print("[DWX] Order FAILED: ", symbol, " retcode=", result.retcode, " ", result.comment);
}

//+------------------------------------------------------------------+
//| Modify position SL/TP                                            |
//+------------------------------------------------------------------+
void ExecuteModify(ulong ticket, double sl, double tp)
{
    MqlTradeRequest request = {};
    MqlTradeResult result = {};

    request.action = TRADE_ACTION_SLTP;
    request.position = ticket;

    // Get current position info
    if(!PositionSelectByTicket(ticket))
    {
        WriteFile(g_folder + "/last_response.json",
            StringFormat("{\"success\":false,\"error\":\"Position %d not found\"}", ticket));
        return;
    }

    request.symbol = PositionGetString(POSITION_SYMBOL);
    request.sl = sl;
    request.tp = (tp > 0) ? tp : PositionGetDouble(POSITION_TP);

    bool success = OrderSend(request, result);

    string response = StringFormat(
        "{\"success\":%s,\"ticket\":%d,\"retcode\":%d,\"comment\":\"%s\"}",
        success ? "true" : "false",
        ticket,
        result.retcode,
        result.comment
    );

    WriteFile(g_folder + "/last_response.json", response);

    if(success)
        Print("[DWX] Modified #", ticket, " SL=", sl, " TP=", tp);
    else
        Print("[DWX] Modify FAILED #", ticket, " retcode=", result.retcode);
}

//+------------------------------------------------------------------+
//| Close position                                                    |
//+------------------------------------------------------------------+
void ExecuteClose(ulong ticket)
{
    if(!PositionSelectByTicket(ticket))
    {
        WriteFile(g_folder + "/last_response.json",
            StringFormat("{\"success\":false,\"error\":\"Position %d not found\"}", ticket));
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

    bool success = OrderSend(request, result);

    string response = StringFormat(
        "{\"success\":%s,\"ticket\":%d,\"close_price\":%.5f,\"retcode\":%d,\"comment\":\"%s\"}",
        success ? "true" : "false",
        ticket,
        result.price,
        result.retcode,
        result.comment
    );

    WriteFile(g_folder + "/last_response.json", response);

    if(success)
        Print("[DWX] Closed #", ticket, " @ ", result.price);
    else
        Print("[DWX] Close FAILED #", ticket, " retcode=", result.retcode);
}

//+------------------------------------------------------------------+
//| Close all positions                                               |
//+------------------------------------------------------------------+
void ExecuteCloseAll()
{
    int total = PositionsTotal();
    int closed = 0;
    for(int i = total - 1; i >= 0; i--)
    {
        ulong ticket = PositionGetTicket(i);
        if(ticket > 0)
        {
            ExecuteClose(ticket);
            closed++;
        }
    }
    Print("[DWX] CloseAll: closed ", closed, " positions");
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
//+------------------------------------------------------------------+
void WriteFile(string path, string content)
{
    int handle = FileOpen(path, FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_ANSI);
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
//+------------------------------------------------------------------+
string ReadFile(string path)
{
    int handle = FileOpen(path, FILE_READ|FILE_TXT|FILE_COMMON|FILE_ANSI);
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
