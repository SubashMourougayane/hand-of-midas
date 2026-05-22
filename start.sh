#!/bin/bash
# GoldDigger + OilMiner — Start all services
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

# Clear screen
clear

# ASCII Art Banner
echo -e "${YELLOW}"
echo "  ╔═══════════════════════════════════════════════════╗"
echo "  ║                                                   ║"
echo "  ║   ⛏️   G O L D D I G G E R  +  O I L M I N E R   ║"
echo "  ║                                                   ║"
echo "  ╚═══════════════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "${DIM}  Multi-Asset Trading Engine | Alpha-Sweep + Mean-Rev + Cross-Market${NC}"
echo ""

# Service Table
echo -e "${BOLD}  ┌──────────────────────────────────────────────────────────┐${NC}"
echo -e "${BOLD}  │${NC}  ${YELLOW}⚡${NC} Service          ${DIM}│${NC} Port  ${DIM}│${NC} Instrument ${DIM}│${NC} Status       ${BOLD}│${NC}"
echo -e "${BOLD}  ├──────────────────────────────────────────────────────────┤${NC}"
echo -e "${BOLD}  │${NC}  ${YELLOW}🥇${NC} Gold Backend     ${DIM}│${NC} 5053  ${DIM}│${NC} XAU/USD    ${DIM}│${NC} ${DIM}starting...${NC}  ${BOLD}│${NC}"
echo -e "${BOLD}  │${NC}  ${CYAN}🛢️ ${NC} Oil Backend      ${DIM}│${NC} 5054  ${DIM}│${NC} BCO/USD    ${DIM}│${NC} ${DIM}starting...${NC}  ${BOLD}│${NC}"
echo -e "${BOLD}  │${NC}  ${PURPLE}🖥️ ${NC} Frontend         ${DIM}│${NC} 3001  ${DIM}│${NC} Dashboard  ${DIM}│${NC} ${DIM}waiting...${NC}   ${BOLD}│${NC}"
echo -e "${BOLD}  └──────────────────────────────────────────────────────────┘${NC}"
echo ""

# Start Gold backend
echo -ne "  ${YELLOW}🥇 Starting Gold Engine...${NC}"
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 5053 --timeout-keep-alive 300 2>&1 | grep -v "^INFO" &
GOLD_PID=$!
echo -e " ${GREEN}✓${NC} PID $GOLD_PID"

# Start Oil backend
echo -ne "  ${CYAN}🛢️  Starting Oil Engine...${NC}"
cd "$DIR/backend-oil"
python3 -m uvicorn main:app --host 0.0.0.0 --port 5054 --timeout-keep-alive 300 2>&1 | grep -v "^INFO" &
OIL_PID=$!
cd "$DIR"
echo -e " ${GREEN}✓${NC} PID $OIL_PID"

# Loading animation
echo ""
echo -ne "  ${DIM}📊 Loading 20 years of market data "
for i in {1..10}; do
    sleep 1
    echo -ne "${YELLOW}█${NC}"
done
echo -e " ${GREEN}done${NC}"

# Start frontend
echo -ne "  ${PURPLE}🖥️  Starting Dashboard...${NC}"
cd "$DIR/frontend"
npm run dev -- -p 3001 2>&1 | grep -v "^$" | grep -v "▲" | grep -v "─" &
FRONTEND_PID=$!
cd "$DIR"
sleep 2
echo -e " ${GREEN}✓${NC} PID $FRONTEND_PID"

echo ""
echo -e "${BOLD}  ┌──────────────────────────────────────────────────────────┐${NC}"
echo -e "${BOLD}  │${NC}  ${GREEN}✅ ALL SYSTEMS ONLINE${NC}                                    ${BOLD}│${NC}"
echo -e "${BOLD}  ├──────────────────────────────────────────────────────────┤${NC}"
echo -e "${BOLD}  │${NC}                                                            ${BOLD}│${NC}"
echo -e "${BOLD}  │${NC}  ${YELLOW}🥇 Gold${NC}  http://localhost:5053  ${DIM}(XAU/USD)${NC}               ${BOLD}│${NC}"
echo -e "${BOLD}  │${NC}  ${CYAN}🛢️  Oil${NC}   http://localhost:5054  ${DIM}(BCO/USD)${NC}               ${BOLD}│${NC}"
echo -e "${BOLD}  │${NC}  ${PURPLE}🖥️  UI${NC}    http://localhost:3001  ${DIM}(Dashboard)${NC}             ${BOLD}│${NC}"
echo -e "${BOLD}  │${NC}                                                            ${BOLD}│${NC}"
echo -e "${BOLD}  ├──────────────────────────────────────────────────────────┤${NC}"
echo -e "${BOLD}  │${NC}  ${BOLD}📅 Trading Schedule (UTC):${NC}                                ${BOLD}│${NC}"
echo -e "${BOLD}  │${NC}  ${DIM}├─${NC} ${YELLOW}22:00${NC}       Cross-Market + Mean-Rev ${DIM}(daily)${NC}        ${BOLD}│${NC}"
echo -e "${BOLD}  │${NC}  ${DIM}├─${NC} ${CYAN}08:00-10:30${NC} Alpha-Sweep Gold ${DIM}(London, 3min)${NC}      ${BOLD}│${NC}"
echo -e "${BOLD}  │${NC}  ${DIM}├─${NC} ${CYAN}08:00-10:30${NC} Alpha-Sweep Oil ${DIM}(London, 3min)${NC}       ${BOLD}│${NC}"
echo -e "${BOLD}  │${NC}  ${DIM}└─${NC} ${GREEN}every 1min${NC}  Position Monitor ${DIM}(SL/TP/MaxHold)${NC}     ${BOLD}│${NC}"
echo -e "${BOLD}  │${NC}                                                            ${BOLD}│${NC}"
echo -e "${BOLD}  └──────────────────────────────────────────────────────────┘${NC}"
echo ""
echo -e "  ${DIM}Press ${RED}Ctrl+C${NC}${DIM} to stop all services${NC}"
echo ""

trap "echo -e '\n  ${RED}🛑 Shutting down...${NC}'; kill $GOLD_PID $OIL_PID $FRONTEND_PID 2>/dev/null; echo -e '  ${GREEN}✓ All services stopped${NC}'; exit" SIGINT SIGTERM
wait
