# Chapter 3/6 - the live monitor: compliant agents stay silent, violations
# are detected and alerted on as they happen.
#
# Recorded by docs/record-demo.sh, then concatenated into docs/assets/demo.mp4.

Output docs/assets/parts/03-watch.mp4

Set Shell "bash"
Set FontSize 16
Set Width 1400
Set Height 900
Set TypingSpeed 25ms
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
Type "printf '\\n\\033[1;36m━━━ 2 / LIVE MONITOR: AGENTS vs INDEPENDENT CHECK ━━━\\033[0m\\n'"
Enter
Type "python main.py watch --pace 1.2"
Enter
Sleep 30s
