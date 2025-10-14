"""
Data validation utilities for ORAKL Bot
Ensures data integrity and correctness
"""

import pandas as pd
import numpy as np
from typing import Any, Dict, List, Optional, Union, Callable
from datetime import datetime, timedelta
import logging
from decimal import Decimal, InvalidOperation

from .exceptions import DataValidationException, InvalidParameterException

logger = logging.getLogger(__name__)


class DataValidator:
    """Comprehensive data validation for API responses and calculations"""
    
    @staticmethod
    def validate_api_response(response: Any, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate API response against schema
        
        Args:
            response: API response data
            schema: Expected schema definition
            
        Returns:
            Validated data
            
        Raises:
            DataValidationException: If validation fails
        """
        if response is None:
            raise DataValidationException("API response is None", "response", None)
        
        validated = {}
        
        for field, rules in schema.items():
            # Check required fields
            if rules.get('required', False) and field not in response:
                raise DataValidationException(
                    f"Required field '{field}' missing from response",
                    field,
                    None
                )
            
            if field in response:
                value = response[field]
                
                # Type validation
                expected_type = rules.get('type')
                if expected_type and not isinstance(value, expected_type):
                    raise DataValidationException(
                        f"Field '{field}' has invalid type. Expected {expected_type.__name__}, got {type(value).__name__}",
                        field,
                        value
                    )
                
                # Range validation
                if 'min' in rules and value < rules['min']:
                    raise DataValidationException(
                        f"Field '{field}' value {value} is below minimum {rules['min']}",
                        field,
                        value
                    )
                
                if 'max' in rules and value > rules['max']:
                    raise DataValidationException(
                        f"Field '{field}' value {value} is above maximum {rules['max']}",
                        field,
                        value
                    )
                
                # Custom validation
                if 'validator' in rules:
                    validator_func = rules['validator']
                    if not validator_func(value):
                        raise DataValidationException(
                            f"Field '{field}' failed custom validation",
                            field,
                            value
                        )
                
                validated[field] = value
            elif 'default' in rules:
                validated[field] = rules['default']
        
        return validated
    
    @staticmethod
    def validate_price(price: Any, field_name: str = "price") -> float:
        """
        Validate and convert price to float
        
        Args:
            price: Price value
            field_name: Field name for error messages
            
        Returns:
            Validated price as float
            
        Raises:
            DataValidationException: If price is invalid
        """
        if price is None:
            raise DataValidationException(f"{field_name} is None", field_name, price)
        
        try:
            price_float = float(price)
            if price_float <= 0:
                raise DataValidationException(
                    f"{field_name} must be positive",
                    field_name,
                    price
                )
            if np.isnan(price_float) or np.isinf(price_float):
                raise DataValidationException(
                    f"{field_name} is NaN or infinite",
                    field_name,
                    price
                )
            return price_float
        except (ValueError, TypeError) as e:
            raise DataValidationException(
                f"Invalid {field_name}: {e}",
                field_name,
                price
            )
    
    @staticmethod
    def validate_volume(volume: Any, field_name: str = "volume") -> int:
        """
        Validate and convert volume to int
        
        Args:
            volume: Volume value
            field_name: Field name for error messages
            
        Returns:
            Validated volume as int
            
        Raises:
            DataValidationException: If volume is invalid
        """
        if volume is None:
            raise DataValidationException(f"{field_name} is None", field_name, volume)
        
        try:
            volume_int = int(volume)
            if volume_int < 0:
                raise DataValidationException(
                    f"{field_name} cannot be negative",
                    field_name,
                    volume
                )
            return volume_int
        except (ValueError, TypeError) as e:
            raise DataValidationException(
                f"Invalid {field_name}: {e}",
                field_name,
                volume
            )
    
    @staticmethod
    def validate_dataframe(
        df: pd.DataFrame,
        required_columns: List[str],
        min_rows: int = 1
    ) -> pd.DataFrame:
        """
        Validate DataFrame structure and content
        
        Args:
            df: DataFrame to validate
            required_columns: Required column names
            min_rows: Minimum number of rows required
            
        Returns:
            Validated DataFrame
            
        Raises:
            DataValidationException: If validation fails
        """
        if df is None:
            raise DataValidationException("DataFrame is None", "dataframe", None)
        
        if df.empty and min_rows > 0:
            raise DataValidationException(
                f"DataFrame is empty, requires at least {min_rows} rows",
                "dataframe",
                len(df)
            )
        
        if len(df) < min_rows:
            raise DataValidationException(
                f"DataFrame has {len(df)} rows, requires at least {min_rows}",
                "dataframe",
                len(df)
            )
        
        # Check required columns
        missing_columns = set(required_columns) - set(df.columns)
        if missing_columns:
            raise DataValidationException(
                f"Missing required columns: {missing_columns}",
                "columns",
                list(df.columns)
            )
        
        # Remove rows with all NaN values
        df_clean = df.dropna(how='all')
        
        # Check for infinite values in numeric columns
        numeric_columns = df_clean.select_dtypes(include=[np.number]).columns
        for col in numeric_columns:
            if df_clean[col].isin([np.inf, -np.inf]).any():
                raise DataValidationException(
                    f"Column '{col}' contains infinite values",
                    col,
                    "inf"
                )
        
        return df_clean
    
    @staticmethod
    def validate_options_contract(contract_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate options contract data
        
        Args:
            contract_data: Contract data dictionary
            
        Returns:
            Validated contract data
            
        Raises:
            DataValidationException: If validation fails
        """
        schema = {
            'ticker': {'required': True, 'type': str},
            'type': {
                'required': True,
                'type': str,
                'validator': lambda x: x in ['CALL', 'PUT']
            },
            'strike': {
                'required': True,
                'type': (int, float),
                'min': 0
            },
            'expiration': {
                'required': True,
                'type': str,
                'validator': lambda x: DataValidator._is_valid_date(x)
            },
            'volume': {
                'required': False,
                'type': (int, float),
                'min': 0,
                'default': 0
            },
            'premium': {
                'required': False,
                'type': (int, float),
                'min': 0,
                'default': 0
            }
        }
        
        return DataValidator.validate_api_response(contract_data, schema)
    
    @staticmethod
    def validate_trade_data(trade_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate trade data
        
        Args:
            trade_data: Trade data dictionary
            
        Returns:
            Validated trade data
            
        Raises:
            DataValidationException: If validation fails
        """
        # Validate required fields
        validated = {}
        
        # Symbol
        if 'symbol' not in trade_data or not trade_data['symbol']:
            raise DataValidationException("Missing symbol", "symbol", None)
        validated['symbol'] = str(trade_data['symbol']).upper()
        
        # Price
        validated['price'] = DataValidator.validate_price(
            trade_data.get('price'), 'price'
        )
        
        # Size/Volume
        validated['size'] = DataValidator.validate_volume(
            trade_data.get('size', trade_data.get('volume')), 'size'
        )
        
        # Timestamp
        if 'timestamp' in trade_data:
            validated['timestamp'] = DataValidator._validate_timestamp(
                trade_data['timestamp']
            )
        
        # Optional fields
        if 'conditions' in trade_data:
            validated['conditions'] = trade_data['conditions']
        
        if 'exchange' in trade_data:
            validated['exchange'] = str(trade_data['exchange'])
        
        return validated
    
    @staticmethod
    def validate_calculation_inputs(**kwargs) -> Dict[str, Any]:
        """
        Validate inputs for calculations
        
        Args:
            **kwargs: Calculation parameters
            
        Returns:
            Validated parameters
            
        Raises:
            InvalidParameterException: If parameter is invalid
        """
        validated = {}
        
        # Common calculation parameters
        param_validators = {
            'current_price': lambda x: DataValidator.validate_price(x, 'current_price'),
            'strike_price': lambda x: DataValidator.validate_price(x, 'strike_price'),
            'days_to_expiry': lambda x: DataValidator._validate_days_to_expiry(x),
            'volatility': lambda x: DataValidator._validate_volatility(x),
            'interest_rate': lambda x: DataValidator._validate_interest_rate(x),
            'dividend_yield': lambda x: DataValidator._validate_dividend_yield(x)
        }
        
        for param, value in kwargs.items():
            if param in param_validators:
                try:
                    validated[param] = param_validators[param](value)
                except Exception as e:
                    raise InvalidParameterException(
                        f"Invalid {param}: {e}",
                        param,
                        value,
                        "numeric"
                    )
            else:
                validated[param] = value
        
        return validated
    
    @staticmethod
    def _is_valid_date(date_str: str) -> bool:
        """Check if string is valid date"""
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
            return True
        except ValueError:
            return False
    
    @staticmethod
    def _validate_timestamp(timestamp: Any) -> datetime:
        """Validate and convert timestamp"""
        if isinstance(timestamp, datetime):
            return timestamp
        
        if isinstance(timestamp, (int, float)):
            # Assume milliseconds if large number
            if timestamp > 1e10:
                timestamp = timestamp / 1000
            return datetime.fromtimestamp(timestamp)
        
        if isinstance(timestamp, str):
            # Try common formats
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']:
                try:
                    return datetime.strptime(timestamp, fmt)
                except ValueError:
                    continue
        
        raise DataValidationException(
            "Invalid timestamp format",
            "timestamp",
            timestamp
        )
    
    @staticmethod
    def _validate_days_to_expiry(days: Any) -> int:
        """Validate days to expiry"""
        try:
            days_int = int(days)
            if days_int < 0:
                raise ValueError("Days to expiry cannot be negative")
            return days_int
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid days to expiry: {e}")
    
    @staticmethod
    def _validate_volatility(vol: Any) -> float:
        """Validate volatility (0-5 range, typically 0-1)"""
        try:
            vol_float = float(vol)
            if not 0 <= vol_float <= 5:
                raise ValueError("Volatility must be between 0 and 5")
            return vol_float
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid volatility: {e}")
    
    @staticmethod
    def _validate_interest_rate(rate: Any) -> float:
        """Validate interest rate (-0.1 to 0.5 range)"""
        try:
            rate_float = float(rate)
            if not -0.1 <= rate_float <= 0.5:
                raise ValueError("Interest rate must be between -0.1 and 0.5")
            return rate_float
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid interest rate: {e}")
    
    @staticmethod
    def _validate_dividend_yield(div: Any) -> float:
        """Validate dividend yield (0-0.2 range)"""
        try:
            div_float = float(div)
            if not 0 <= div_float <= 0.2:
                raise ValueError("Dividend yield must be between 0 and 0.2")
            return div_float
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid dividend yield: {e}")


class SafeCalculations:
    """Safe mathematical calculations with error handling"""
    
    @staticmethod
    def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
        """
        Safe division with zero check
        
        Args:
            numerator: Numerator
            denominator: Denominator
            default: Default value if division by zero
            
        Returns:
            Result of division or default
        """
        if denominator == 0 or np.isnan(denominator) or np.isnan(numerator):
            logger.debug(f"Safe divide returning default: {numerator}/{denominator}")
            return default
        
        result = numerator / denominator
        if np.isnan(result) or np.isinf(result):
            return default
        
        return result
    
    @staticmethod
    def safe_percentage(value: float, total: float, default: float = 0.0) -> float:
        """
        Calculate percentage safely
        
        Args:
            value: Value to calculate percentage of
            total: Total value
            default: Default percentage if calculation fails
            
        Returns:
            Percentage or default
        """
        return SafeCalculations.safe_divide(value * 100, total, default)
    
    @staticmethod
    def safe_log(value: float, default: float = 0.0) -> float:
        """
        Safe logarithm calculation
        
        Args:
            value: Value to calculate log of
            default: Default if calculation fails
            
        Returns:
            Log value or default
        """
        if value <= 0 or np.isnan(value):
            return default
        
        try:
            result = np.log(value)
            if np.isnan(result) or np.isinf(result):
                return default
            return result
        except Exception:
            return default
    
    @staticmethod
    def safe_sqrt(value: float, default: float = 0.0) -> float:
        """
        Safe square root calculation
        
        Args:
            value: Value to calculate sqrt of
            default: Default if calculation fails
            
        Returns:
            Square root or default
        """
        if value < 0 or np.isnan(value):
            return default
        
        try:
            result = np.sqrt(value)
            if np.isnan(result):
                return default
            return result
        except Exception:
            return default
