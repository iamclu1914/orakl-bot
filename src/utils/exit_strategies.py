"""
Exit Strategy Calculator
Provides stop loss and profit target calculations for options trades
"""
import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class ExitStrategies:
    """Calculate exit points for different trading strategies"""
    
    @staticmethod
    def calculate_exits(signal_type: str, entry_price: float, 
                       underlying_price: float, option_type: str,
                       atr: Optional[float] = None, dte: int = 1) -> Dict:
        """
        Calculate stop loss and profit targets based on signal type
        
        Args:
            signal_type: 'scalp' or 'bullseye'
            entry_price: Option entry price
            underlying_price: Current stock price
            option_type: 'CALL' or 'PUT'
            atr: Average True Range of underlying (optional)
            dte: Days to expiry
            
        Returns:
            Dict with stop_loss, targets, and recommendations
        """
        try:
            # Use default ATR if not provided (2% of underlying)
            if atr is None:
                atr = underlying_price * 0.02
            
            # Calculate based on signal type
            if signal_type.lower() == 'scalp':
                return ExitStrategies._calculate_scalp_exits(
                    entry_price, atr, option_type, dte
                )
            elif signal_type.lower() == 'bullseye':
                return ExitStrategies._calculate_bullseye_exits(
                    entry_price, atr, option_type, dte
                )
            else:
                # Default conservative exits
                return ExitStrategies._calculate_default_exits(entry_price)
                
        except Exception as e:
            logger.error(f"Error calculating exits: {e}")
            return ExitStrategies._calculate_default_exits(entry_price)
    
    @staticmethod
    def _calculate_scalp_exits(entry_price: float, atr: float, 
                              option_type: str, dte: int) -> Dict:
        """Calculate exits for scalp trades (quick in/out)"""
        
        # Tighter stops for scalps
        if dte == 0:  # 0DTE requires tightest stops
            stop_pct = 0.20  # 20% stop
            target1_pct = 0.25  # 25% target
            target2_pct = 0.50  # 50% target
        else:
            stop_pct = 0.25  # 25% stop
            target1_pct = 0.35  # 35% target
            target2_pct = 0.70  # 70% target
        
        stop_loss = entry_price * (1 - stop_pct)
        target_1 = entry_price * (1 + target1_pct)
        target_2 = entry_price * (1 + target2_pct)
        
        # Calculate R:R ratios
        risk = entry_price - stop_loss
        reward1 = target_1 - entry_price
        reward2 = target_2 - entry_price
        
        trail_pct = 0.15  # 15% trailing stop reference

        return {
            'stop_loss': round(stop_loss, 2),
            'target_1': round(target_1, 2),
            'target_2': round(target_2, 2),
            'stop_pct': f"-{stop_pct*100:.0f}%",
            'target1_pct': f"+{target1_pct*100:.0f}%",
            'target2_pct': f"+{target2_pct*100:.0f}%",
            'risk_reward_1': round(reward1 / risk, 2) if risk > 0 else 0,
            'risk_reward_2': round(reward2 / risk, 2) if risk > 0 else 0,
            'trail_stop': round(entry_price * (1 - trail_pct), 2),
            'scale_out': {
                'target_1_size': 0.75,  # Take 75% at T1
                'target_2_size': 0.25,  # Take 25% at T2
                'runner_size': 0.00     # No runners for scalps
            },
            'management': 'Quick exit recommended - Take profits fast',
            'entry_zone': {
                'lower': round(entry_price * 0.98, 2),  # 2% entry zone
                'upper': round(entry_price * 1.02, 2)
            }
        }
    
    @staticmethod
    def _calculate_bullseye_exits(entry_price: float, atr: float,
                                 option_type: str, dte: int) -> Dict:
        """
        Calculate exits for institutional swing trades.
        These aren't scalps - institutions expect MOVES.
        """
        
        # INSTITUTIONAL SWING EXITS - Much wider than scalps
        if dte <= 2:  # 0-2 DTE swings
            # Tighter stops, quicker targets
            stop_pct = 0.30  # 30% stop
            target1_pct = 0.75    # 75% gain
            target2_pct = 1.50    # 150% gain
            target3_pct = 3.00    # 300% runner
        else:  # 3-5 DTE swings  
            # More room to work
            stop_pct = 0.40  # 40% stop
            target1_pct = 1.00    # 100% gain
            target2_pct = 2.00    # 200% gain
            target3_pct = 4.00    # 400% runner
        
        stop_loss = entry_price * (1 - stop_pct)
        target_1 = entry_price * (1 + target1_pct)
        target_2 = entry_price * (1 + target2_pct)
        target_3 = entry_price * (1 + target3_pct)
        
        # Calculate R:R ratios
        risk = entry_price - stop_loss
        reward1 = target_1 - entry_price
        reward2 = target_2 - entry_price
        reward3 = target_3 - entry_price
        
        trail_pct = 0.25  # 25% trailing for swings

        return {
            'stop_loss': round(stop_loss, 2),
            'target_1': round(target_1, 2),
            'target_2': round(target_2, 2),
            'target_3': round(target_3, 2),
            'stop_pct': f"-{stop_pct*100:.0f}%",
            'target1_pct': f"+{target1_pct*100:.0f}%",
            'target2_pct': f"+{target2_pct*100:.0f}%",
            'target3_pct': f"+{target3_pct*100:.0f}%",
            'risk_reward_1': round(reward1 / risk, 2) if risk > 0 else 0,
            'risk_reward_2': round(reward2 / risk, 2) if risk > 0 else 0,
            'risk_reward_3': round(reward3 / risk, 2) if risk > 0 else 0,
            'trail_stop': round(entry_price * (1 - trail_pct), 2),
            'scale_out': {
                'target_1_size': 0.50,  # Take 50% at T1
                'target_2_size': 0.30,  # Take 30% at T2
                'runner_size': 0.20     # Let 20% run to T3
            },
            'management': 'Scale out recommended - Let winners run',
            'entry_zone': {
                'lower': round(entry_price * 0.95, 2),  # 5% entry zone
                'upper': round(entry_price * 1.05, 2)
            }
        }
    
    @staticmethod
    def _calculate_default_exits(entry_price: float) -> Dict:
        """Calculate conservative default exits"""
        
        stop_loss = entry_price * 0.75  # 25% stop
        target_1 = entry_price * 1.30   # 30% target
        target_2 = entry_price * 1.60   # 60% target
        
        trail_pct = 0.15

        return {
            'stop_loss': round(stop_loss, 2),
            'target_1': round(target_1, 2),
            'target_2': round(target_2, 2),
            'stop_pct': "-25%",
            'target1_pct': "+30%",
            'target2_pct': "+60%",
            'risk_reward_1': 1.2,
            'risk_reward_2': 2.4,
            'trail_stop': round(entry_price * (1 - trail_pct), 2),
            'scale_out': {
                'target_1_size': 0.60,
                'target_2_size': 0.40,
                'runner_size': 0.00
            },
            'management': 'Standard exit strategy',
            'entry_zone': {
                'lower': round(entry_price * 0.97, 2),
                'upper': round(entry_price * 1.03, 2)
            }
        }
    
    @staticmethod
    def calculate_position_size(account_size: float, risk_per_trade: float,
                               entry_price: float, stop_loss: float) -> Dict:
        """
        Calculate appropriate position size based on account risk
        
        Args:
            account_size: Total account value
            risk_per_trade: Risk percentage (e.g., 0.02 for 2%)
            entry_price: Option entry price
            stop_loss: Stop loss price
            
        Returns:
            Position sizing recommendations
        """
        try:
            # Calculate dollar risk
            dollar_risk = account_size * risk_per_trade
            
            # Calculate risk per contract
            risk_per_contract = (entry_price - stop_loss) * 100  # Options are 100 shares
            
            if risk_per_contract <= 0:
                return {'contracts': 0, 'error': 'Invalid stop loss'}
            
            # Calculate number of contracts
            num_contracts = int(dollar_risk / risk_per_contract)
            
            # Calculate actual position size
            position_value = num_contracts * entry_price * 100
            position_pct = (position_value / account_size) * 100
            
            return {
                'contracts': num_contracts,
                'position_value': round(position_value, 2),
                'position_pct': round(position_pct, 2),
                'dollar_risk': round(dollar_risk, 2),
                'risk_per_contract': round(risk_per_contract, 2),
                'max_loss': round(num_contracts * risk_per_contract, 2)
            }
            
        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return {'contracts': 0, 'error': str(e)}
    
    @staticmethod
    def format_exit_message(exits: Dict) -> str:
        """Format exit strategy for Discord message"""
        
        message = f"**Entry Zone**: ${exits['entry_zone']['lower']:.2f} - ${exits['entry_zone']['upper']:.2f}\n"
        message += f"**Stop Loss**: ${exits['stop_loss']:.2f} ({exits['stop_pct']})\n"
        message += f"**Target 1**: ${exits['target_1']:.2f} ({exits['target1_pct']}) R:R {exits['risk_reward_1']}\n"
        message += f"**Target 2**: ${exits['target_2']:.2f} ({exits['target2_pct']}) R:R {exits['risk_reward_2']}\n"
        
        if 'target_3' in exits:
            message += f"**Target 3**: ${exits['target_3']:.2f} ({exits['target3_pct']}) R:R {exits['risk_reward_3']}\n"
        
        # Scale out recommendations
        scale_out = exits['scale_out']
        message += f"\n**Scale Out Plan**:\n"
        message += f"• {scale_out['target_1_size']*100:.0f}% at Target 1\n"
        message += f"• {scale_out['target_2_size']*100:.0f}% at Target 2\n"
        
        if scale_out['runner_size'] > 0:
            message += f"• {scale_out['runner_size']*100:.0f}% runner\n"
        
        message += f"\n💡 {exits['management']}"
        
        return message
