from pathlib import Path
path=Path('src/bots/scalps_bot.py')
text=path.read_text()
start=text.index("        for flow in flows:")
end=text.index("                scalp_score =", start)
print(text[start:end])
