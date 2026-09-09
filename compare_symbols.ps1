param(
    [string[]]$Symbols = @("BTCUSDT", "ETHUSDT", "BNBUSDT"),
    [string]$Interval = "15m",
    [int]$Limit = 1000,
    [string]$Capital = "1000"
)

$ErrorActionPreference = "Stop"

python compare_symbols.py --symbols $Symbols --interval $Interval --limit $Limit --capital $Capital
