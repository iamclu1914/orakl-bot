"""
Custom exceptions for ORAKL Bot
Provides specific error types for better error handling
"""

from typing import Optional, Dict, Any
from datetime import datetime


class ORAKLException(Exception):
    """Base exception for all ORAKL Bot errors"""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for logging"""
        return {
            'error_type': self.__class__.__name__,
            'message': self.message,
            'details': self.details,
            'timestamp': self.timestamp.isoformat()
        }


# API Related Exceptions
class APIException(ORAKLException):
    """Base exception for API-related errors"""
    pass


class RateLimitException(APIException):
    """Raised when API rate limit is exceeded"""
    
    def __init__(self, message: str, retry_after: Optional[int] = None):
        super().__init__(message, {'retry_after': retry_after})
        self.retry_after = retry_after


class AuthenticationException(APIException):
    """Raised when API authentication fails"""
    pass


class APITimeoutException(APIException):
    """Raised when API request times out"""
    
    def __init__(self, message: str, timeout: float):
        super().__init__(message, {'timeout': timeout})
        self.timeout = timeout


class InvalidAPIResponseException(APIException):
    """Raised when API returns invalid response"""
    
    def __init__(self, message: str, response_data: Optional[Any] = None):
        super().__init__(message, {'response_data': response_data})
        self.response_data = response_data


# Data Related Exceptions
class DataException(ORAKLException):
    """Base exception for data-related errors"""
    pass


class DataValidationException(DataException):
    """Raised when data validation fails"""
    
    def __init__(self, message: str, field: str, value: Any):
        super().__init__(message, {'field': field, 'value': value})
        self.field = field
        self.value = value


class InsufficientDataException(DataException):
    """Raised when insufficient data for analysis"""
    
    def __init__(self, message: str, required: int, actual: int):
        super().__init__(message, {'required': required, 'actual': actual})
        self.required = required
        self.actual = actual


class DataIntegrityException(DataException):
    """Raised when data integrity check fails"""
    pass


# Bot Related Exceptions
class BotException(ORAKLException):
    """Base exception for bot-related errors"""
    pass


class BotNotRunningException(BotException):
    """Raised when operation requires bot to be running"""
    pass


class BotAlreadyRunningException(BotException):
    """Raised when trying to start an already running bot"""
    pass


class SignalGenerationException(BotException):
    """Raised when signal generation fails"""
    
    def __init__(self, message: str, bot_name: str, symbol: Optional[str] = None):
        super().__init__(message, {'bot_name': bot_name, 'symbol': symbol})
        self.bot_name = bot_name
        self.symbol = symbol


class WebhookException(BotException):
    """Raised when Discord webhook fails"""
    
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message, {'status_code': status_code})
        self.status_code = status_code


# Analysis Related Exceptions
class AnalysisException(ORAKLException):
    """Base exception for analysis-related errors"""
    pass


class CalculationException(AnalysisException):
    """Raised when calculation fails"""
    
    def __init__(self, message: str, calculation_type: str, params: Optional[Dict] = None):
        super().__init__(message, {'calculation_type': calculation_type, 'params': params})
        self.calculation_type = calculation_type
        self.params = params


class InvalidParameterException(AnalysisException):
    """Raised when invalid parameter is provided"""
    
    def __init__(self, message: str, parameter: str, value: Any, expected_type: str):
        super().__init__(message, {
            'parameter': parameter,
            'value': value,
            'expected_type': expected_type
        })
        self.parameter = parameter
        self.value = value
        self.expected_type = expected_type


# Configuration Related Exceptions
class ConfigurationException(ORAKLException):
    """Base exception for configuration errors"""
    pass


class MissingConfigurationException(ConfigurationException):
    """Raised when required configuration is missing"""
    
    def __init__(self, message: str, config_key: str):
        super().__init__(message, {'config_key': config_key})
        self.config_key = config_key


class InvalidConfigurationException(ConfigurationException):
    """Raised when configuration value is invalid"""
    
    def __init__(self, message: str, config_key: str, value: Any, expected: str):
        super().__init__(message, {
            'config_key': config_key,
            'value': value,
            'expected': expected
        })
        self.config_key = config_key
        self.value = value
        self.expected = expected


# Market Related Exceptions
class MarketException(ORAKLException):
    """Base exception for market-related errors"""
    pass


class MarketClosedException(MarketException):
    """Raised when operation requires market to be open"""
    
    def __init__(self, message: str = "Market is closed"):
        super().__init__(message)


class InvalidSymbolException(MarketException):
    """Raised when invalid symbol is provided"""
    
    def __init__(self, message: str, symbol: str):
        super().__init__(message, {'symbol': symbol})
        self.symbol = symbol


# Utility function for handling exceptions
def handle_exception(exception: Exception, logger=None) -> Dict[str, Any]:
    """
    Handle exception and return formatted error info
    
    Args:
        exception: The exception to handle
        logger: Optional logger instance
        
    Returns:
        Dictionary with error information
    """
    if isinstance(exception, ORAKLException):
        error_info = exception.to_dict()
    else:
        error_info = {
            'error_type': exception.__class__.__name__,
            'message': str(exception),
            'details': {},
            'timestamp': datetime.now().isoformat()
        }
    
    if logger:
        if isinstance(exception, (RateLimitException, MarketClosedException)):
            logger.warning(f"{error_info['error_type']}: {error_info['message']}")
        elif isinstance(exception, (DataValidationException, InvalidParameterException)):
            logger.error(f"{error_info['error_type']}: {error_info['message']}", extra=error_info['details'])
        else:
            logger.exception(f"{error_info['error_type']}: {error_info['message']}", exc_info=exception)
    
    return error_info
