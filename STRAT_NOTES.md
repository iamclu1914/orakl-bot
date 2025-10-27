# STRAT Pattern Detection Notes

## Issue Found: Bar Composition

### Problem
When composing 12-hour bars from 60-minute data, some stocks (like COST) only show bars at **20:00 ET** and are missing **08:00 ET** bars.

### Expected Pattern Structure
For a 1-3-1 completing at Thursday 20:00:
- Bar 1: **Wednesday 20:00** (Type 1 - Inside)
- Bar 2: **Thursday 08:00** (Type 3 - Outside)
- Bar 3: **Thursday 20:00** (Type 1 - Inside)

### What We're Getting
COST example - only 20:00 bars:
- 10/20 20:00
- 10/21 20:00  
- 10/22 20:00
- 10/23 20:00

Missing: 10/23 08:00 morning bar

### Successful Scan Results
The last scan found and posted 15 patterns:
- AXP, DPZ, ETN, FAST, GNRC, IPG, JCI, K, KEY, NRG, OMC, PLD, RCL, SNPS, SPGI

These stocks successfully had proper 1-3-1 patterns detected.

### Next Steps
1. Investigate why some stocks don't have 08:00 bars
2. Ensure 60m data includes all trading hours
3. May need to fetch data with extended hours flag
4. Consider if sparse trading during morning session causes missing buckets

