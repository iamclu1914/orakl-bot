from pathlib import Path
path = Path('src/bots/golden_sweeps_bot.py')
lines = path.read_text(encoding='utf-8').splitlines()
idx = None
for i, line in enumerate(lines):
    if line.strip() == "if dedup_result['should_alert']:":
        idx = i
        break
if idx is None:
    raise SystemExit('if block not found')
block = [
    "                if dedup_result['should_alert']:",
    "                    if self._cooldown_active(signal_key):",
    "                        self._log_skip(symbol, f'golden sweep cooldown {signal_key}')",
    "                        continue",
    "                    sweep['alert_type'] = dedup_result['type']  # NEW, ACCUMULATION, REFRESH",
    "                    sweep['alert_reason'] = dedup_result['reason']",
    "                    sweeps.append(sweep)",
    "                    self._mark_cooldown(signal_key)",
    "",
    "                    logger.info(f'? Golden Sweep detected: {symbol} {opt_type} ${strike} - '",
    "                              f'Premium:${premium:,.0f}, Score:{golden_score}/100')"
]
# existing block spans 6 lines plus blank+logger (8 lines). We'll replace 8 lines starting at idx
lines[idx:idx+8] = block
path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
