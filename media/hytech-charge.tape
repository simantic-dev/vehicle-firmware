Output media/hytech-charge.gif
Set Shell zsh
Set FontSize 16
Set Width 1280
Set Height 740
Set Padding 18
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set Framerate 5
Set PlaybackSpeed 18
Env PS1 "$ "
Hide
Type 'cd "$(git rev-parse --show-toplevel)" && export PATH="$HOME/.local/bin:$PATH" && clear' Enter
Sleep 1s
Show
Type "./demo" Enter
Wait+Screen@1500s /done: CCU state/
Sleep 4s
