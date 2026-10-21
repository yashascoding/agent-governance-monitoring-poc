# Chapter 1/6 - title card.
#
# Recorded by docs/record-demo.sh, then concatenated into docs/assets/demo.mp4.
# Requires vhs, ttyd and ffmpeg on PATH. Run from the repository root.

Output docs/assets/parts/01-title.mp4

Set Shell "bash"
Set FontSize 18
Set Width 1400
Set Height 900
Set TypingSpeed 20ms
Set Theme {
  "name": "Dracula",
  "background": "#1e1f26",
  "foreground": "#f8f8f2",
  "selection": "#44475a",
  "black": "#21222c",
  "red": "#ff5555",
  "green": "#50fa7b",
  "yellow": "#f1fa8c",
  "blue": "#bd93f9",
  "magenta": "#ff79c6",
  "cyan": "#8be9fd",
  "white": "#f8f8f2"
}

Type "clear"
Enter
Type "printf '\\n\\n'"
Enter
Type "printf '  \\033[1;36mAGENT GOVERNANCE & MONITORING\\033[0m\\n'"
Enter
Type "printf '  \\033[1;36mPROOF OF CONCEPT\\033[0m\\n\\n'"
Enter
Type "printf '  \\033[1mTwo halves:\\033[0m\\n'"
Enter
Type "printf '    1. agents that enforce policy at their own boundaries\\n'"
Enter
Type "printf '    2. a monitor that re-derives everything from the event log\\n'"
Enter
Type "printf '\\n'"
Enter
Sleep 7s
