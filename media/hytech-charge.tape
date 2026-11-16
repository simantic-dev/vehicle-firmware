Output media/hytech-charge.gif
Set Shell zsh
Set FontSize 15
Set Width 1280
Set Height 740
Set Padding 18
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Env PS1 "$ "
Hide
Type 'cd "$(git rev-parse --show-toplevel)" && clear' Enter
Show
Type "sh sim/run.sh charge demo 7 --ascii > /dev/null && grep --line-buffered -h -E 'CHARGER_CONTROL|Charging State|Charger Current' sim/build/out/demo/stderr.txt sim/build/out/demo/uart.txt" Enter
Wait+Screen@420s /Charger Current +:/
Sleep 3s
