# 📊 Dynamic Confidence Scoring for STRAT Patterns

## Overview
STRAT pattern confidence scores are now calculated dynamically based on multiple market factors instead of using static percentages. This provides more accurate and context-aware confidence levels for each signal.

## 🎯 Base Confidence Scores
- **3-2-2 Reversal**: 65% base
- **2-2 Reversal**: 60% base  
- **1-3-1 Miyagi**: 70% base

## 📈 Dynamic Adjustments

### 1. Volume Analysis (±15%)
- **High volume** (>2x average): +15%
- **Above average** (>1.5x average): +10%
- **Normal volume** (>average): +5%
- **Low volume** (<average): -5%

### 2. Trend Alignment (±10%)
For reversal patterns, distance from mean indicates potential:
- **Extended** (>3% from SMA): +10%
- **Moderate** (2-3% from SMA): +5%
- **Near mean** (<2% from SMA): 0%

### 3. Pattern Clarity (±10%)
Specific to pattern type:
- **3-2-2**: Strong outside bar (>1.5x inside bar range): +10%
- **3-2-2**: Normal outside bar: +5%

### 4. Recent Volatility (±5%)
- **High volatility** (>2% average range): +5%
- **Low volatility** (<0.5% average range): -5%
- **Normal volatility**: 0%

### 5. Time of Day (±5%)
- **Opening hour** (9-10 AM EST): +5%
- **Closing hour** (3-4 PM EST): +5%
- **Mid-day** (11 AM-2 PM EST): 0%
- **Off-hours**: -5%

## 📊 Final Confidence Range
- **Minimum**: 40%
- **Maximum**: 95%

## 💡 Examples

### High Confidence Signal (85%+)
- Base: 70% (1-3-1 Miyagi)
- High volume: +15%
- Extended from mean: +10%
- Opening hour: +5%
- **Total**: 100% → Capped at 95%

### Low Confidence Signal (40-50%)
- Base: 60% (2-2 Reversal)
- Low volume: -5%
- Near mean: 0%
- Low volatility: -5%
- Off-hours: -5%
- **Total**: 45%

## 🚀 Benefits
1. **Adaptive**: Adjusts to current market conditions
2. **Transparent**: Each factor's contribution is logged
3. **Realistic**: Reflects actual trading conditions
4. **Professional**: Aligns with institutional analysis

## 📝 Debug Logging
When enabled, the system logs confidence adjustments:
```
AAPL 3-2-2 Reversal confidence adjustments: High volume: +0.15, Extended from mean: +0.10, Strong 3-bar: +0.10, High volatility: +0.05, Opening hour: +0.05
```

This helps understand why each signal received its specific confidence score.
