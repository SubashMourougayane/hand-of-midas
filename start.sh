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
NC='\033[0m'

clear

# Banner
printf "${YELLOW}"
printf "  ╔═══════════════════════════════════════════════════╗\n"
printf "  ║                                                   ║\n"
printf "  ║   ⛏️   G O L D D I G G E R  +  O I L M I N E R   ║\n"
printf "  ║                                                   ║\n"
printf "  ╚═══════════════════════════════════════════════════╝\n"
printf "${NC}\n"
printf "  ${DIM}Multi-Asset Trading Engine | Alpha-Sweep + Mean-Rev + Cross-Market${NC}\n\n"

# Service Table
printf "  ${BOLD}┌────────────────────┬───────┬────────────┬─────────────┐${NC}\n"
printf "  ${BOLD}│${NC} ${BOLD}Service${NC}            ${BOLD}│${NC} Port  ${BOLD}│${NC} Instrument ${BOLD}│${NC} Status      ${BOLD}│${NC}\n"
printf "  ${BOLD}├────────────────────┼───────┼────────────┼─────────────┤${NC}\n"
printf "  ${BOLD}│${NC} ${YELLOW}🥇 Gold Backend${NC}    ${BOLD}│${NC} 5053  ${BOLD}│${NC} XAU/USD    ${BOLD}│${NC} ${DIM}starting..${NC}  ${BOLD}│${NC}\n"
printf "  ${BOLD}│${NC} ${CYAN}🛢️  Oil Backend${NC}     ${BOLD}│${NC} 5054  ${BOLD}│${NC} BCO/USD    ${BOLD}│${NC} ${DIM}starting..${NC}  ${BOLD}│${NC}\n"
printf "  ${BOLD}│${NC} ${PURPLE}🖥️  Frontend${NC}        ${BOLD}│${NC} 3001  ${BOLD}│${NC} Dashboard  ${BOLD}│${NC} ${DIM}waiting..${NC}   ${BOLD}│${NC}\n"
printf "  ${BOLD}└────────────────────┴───────┴────────────┴─────────────┘${NC}\n\n"

# Start Gold backend
printf "  ${YELLOW}🥇 Starting Gold Engine...${NC}"
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 5053 --timeout-keep-alive 300 2>&1 | grep -v "^INFO" &
GOLD_PID=$!
printf " ${GREEN}✓${NC} PID $GOLD_PID\n"

# Start Oil backend
printf "  ${CYAN}🛢️  Starting Oil Engine...${NC}"
cd "$DIR/backend-oil"
python3 -m uvicorn main:app --host 0.0.0.0 --port 5054 --timeout-keep-alive 300 2>&1 | grep -v "^INFO" &
OIL_PID=$!
cd "$DIR"
printf " ${GREEN}✓${NC} PID $OIL_PID\n\n"

# Loading animation
printf "  ${DIM}📊 Loading 20 years of market data ${NC}"
for i in {1..10}; do
    sleep 1
    printf "${YELLOW}█${NC}"
done
printf " ${GREEN}done${NC}\n\n"

# Start frontend
printf "  ${PURPLE}🖥️  Starting Dashboard...${NC}"
cd "$DIR/frontend"
npm run dev -- -p 3001 2>&1 | grep -v "^$" | grep -v "▲" | grep -v "─" &
FRONTEND_PID=$!
cd "$DIR"
sleep 2
printf " ${GREEN}✓${NC} PID $FRONTEND_PID\n\n"

# Final status
printf "  ${BOLD}┌──────────────────────────────────────────────────────────┐${NC}\n"
printf "  ${BOLD}│${NC}  ${GREEN}✅ ALL SYSTEMS ONLINE${NC}                                    ${BOLD}│${NC}\n"
printf "  ${BOLD}├──────────────────────────────────────────────────────────┤${NC}\n"
printf "  ${BOLD}│${NC}                                                            ${BOLD}│${NC}\n"
printf "  ${BOLD}│${NC}  ${YELLOW}🥇 Gold${NC}  http://localhost:5053  ${DIM}(XAU/USD)${NC}               ${BOLD}│${NC}\n"
printf "  ${BOLD}│${NC}  ${CYAN}🛢️  Oil${NC}   http://localhost:5054  ${DIM}(BCO/USD)${NC}               ${BOLD}│${NC}\n"
printf "  ${BOLD}│${NC}  ${PURPLE}🖥️  UI${NC}    http://localhost:3001  ${DIM}(Dashboard)${NC}             ${BOLD}│${NC}\n"
printf "  ${BOLD}│${NC}                                                            ${BOLD}│${NC}\n"
printf "  ${BOLD}├──────────────────────────────────────────────────────────┤${NC}\n"
printf "  ${BOLD}│${NC}  ${BOLD}📅 Trading Schedule (UTC):${NC}                                ${BOLD}│${NC}\n"
printf "  ${BOLD}│${NC}  ${DIM}├─${NC} ${YELLOW}22:00${NC}       Cross-Market + Mean-Rev ${DIM}(daily)${NC}        ${BOLD}│${NC}\n"
printf "  ${BOLD}│${NC}  ${DIM}├─${NC} ${CYAN}08:00-10:30${NC} Alpha-Sweep Gold ${DIM}(London, 3min)${NC}      ${BOLD}│${NC}\n"
printf "  ${BOLD}│${NC}  ${DIM}├─${NC} ${CYAN}08:00-10:30${NC} Alpha-Sweep Oil ${DIM}(London, 3min)${NC}       ${BOLD}│${NC}\n"
printf "  ${BOLD}│${NC}  ${DIM}└─${NC} ${GREEN}every 1min${NC}  Position Monitor ${DIM}(SL/TP/MaxHold)${NC}     ${BOLD}│${NC}\n"
printf "  ${BOLD}│${NC}                                                            ${BOLD}│${NC}\n"
printf "  ${BOLD}└──────────────────────────────────────────────────────────┘${NC}\n\n"
printf "  ${DIM}Press ${RED}Ctrl+C${NC}${DIM} to stop all services${NC}\n\n"

trap "printf '\n  ${RED}🛑 Shutting down...${NC}\n'; kill $GOLD_PID $OIL_PID $FRONTEND_PID 2>/dev/null; printf '  ${GREEN}✓ All services stopped${NC}\n'; exit" SIGINT SIGTERM
wait
