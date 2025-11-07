from pathlib import Path
path = Path('src/bots/scalps_bot.py')
lines = path.read_text(encoding='utf-8').splitlines()
for idx,line in enumerate(lines):
    if line.strip().startswith("ask = flow.get('ask', 0)"):
        insert_idx = idx + 1
        lines.insert(insert_idx, "                if bid > 0 and ask > 0 and (ask - bid) > self.MAX_SPREAD:")
        lines.insert(insert_idx + 1, "                    self._log_skip(symbol, f'scalps spread {(ask - bid):.2f} exceeds {self.MAX_SPREAD}')")
        lines.insert(insert_idx + 2, "                    continue")
        break
else:
    raise SystemExit('bid/ask block not found')
path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
