Output media/hytech-eth.gif
Set Shell zsh
Set FontSize 16
Set Width 1400
Set Height 520
Set Padding 18
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set Framerate 5
Set PlaybackSpeed 8
Env PS1 "$ "
Hide
Type 'cd "$(git rev-parse --show-toplevel)" && export PATH="$HOME/.local/bin:$PATH" && clear' Enter
Sleep 1s
Show
Type "./demo eth" Enter
Wait+Screen@900s /done: \d+ Ethernet frames/
Sleep 4s
