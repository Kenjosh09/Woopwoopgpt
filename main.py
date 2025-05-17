# ---------------------------- Ganja Paraiso Telegram Bot ----------------------------
"""
All-in-one Telegram bot for Ganja Paraiso cannabis store.
Handles product ordering, order tracking, payment processing, and admin management.
"""
import asyncio
import json
import logging
import os
import pickle
import random
import re
import shutil
import sys
import time
import string
from collections import deque, defaultdict
from datetime import datetime, timedelta
from io import BytesIO
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional, Tuple, Any, Union, Callable, cast

# Handle optional dependencies
PSUTIL_AVAILABLE = False
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    # psutil module not installed - system stats will be limited
    pass

# Import Telegram components
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Message
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes,
    filters, Application, PicklePersistence, TypeHandler
)
from telegram.error import NetworkError, TelegramError, TimedOut

# Import specific errors or define fallbacks
try:
    from telegram.error import NetworkError, TelegramError
except ImportError:
    # Define fallback error classes if telegram errors not available
    class NetworkError(Exception):
        """Fallback for telegram.error.NetworkError"""
        pass
    
    class TelegramError(Exception):
        """Fallback for telegram.error.TelegramError"""
        pass

# Import Google API components
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Import .env support
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add after load_dotenv()
print(f"Debug - TOKEN env var exists: {'Yes' if os.getenv('TELEGRAM_BOT_TOKEN') else 'No'}")

# ---------------------------- Constants & Configuration ----------------------------
# States for the ConversationHandler
CATEGORY, STRAIN_TYPE, BROWSE_BY, PRODUCT_SELECTION, QUANTITY, CONFIRM, DETAILS, CONFIRM_DETAILS, PAYMENT, TRACKING = range(10)
ADMIN_SEARCH, ADMIN_TRACKING = 10, 11

# Define conversation states
TRACK_ORDER = 1

# Support admin user ID (the Telegram user ID that will receive support requests)
SUPPORT_ADMIN_ID = os.getenv("SUPPORT_ADMIN_ID", "123456789")
SUPPORT_ADMIN_USERNAME = os.getenv("SUPPORT_ADMIN_USERNAME", "your_support_username")

# Get configuration from environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN environment variable not set")
    logging.error("TELEGRAM_BOT_TOKEN environment variable not set")
    sys.exit(1)
    
ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "5167750837"))
GCASH_NUMBER = os.getenv("GCASH_NUMBER", "09171234567")
GCASH_QR_CODE_URL = os.getenv("GCASH_QR_CODE_URL", "https://example.com/gcash_qr.jpg")

# Google API configuration
GOOGLE_SHEET_NAME = "Telegram Orders"
GOOGLE_CREDENTIALS_FILE = "woop-woop-project-2ba60593fd8d.json"
PAYMENT_SCREENSHOTS_FOLDER_ID = "1hIanVMnTFSnKvHESoK7mgexn_QwlmF69"

# ----- Credentials File Configuration -----
# Default location (for backward compatibility)
DEFAULT_CREDENTIALS_FILE = "woop-woop-project-2ba60593fd8d.json"

# Known locations to try in order if default isn't found
CREDENTIALS_LOCATIONS = [
    # Exact path you provided
    r"C:\Users\Kenneth\OneDrive\Documents\Telegram Bot\woop-woop-project-2ba60593fd8d.json",
    
    # Current directory
    DEFAULT_CREDENTIALS_FILE,
    
    # Environment variable (if set)
    os.environ.get("GOOGLE_CREDENTIALS_FILE", "")
]

# Function to find the first valid credentials file
def find_credentials_file():
    """Find the first valid Google credentials file from known locations"""
    for location in CREDENTIALS_LOCATIONS:
        if location and os.path.isfile(location):
            print(f"✅ Found credentials file: {location}")
            return location
            
    # If no valid file found, use the default and warn
    print(f"⚠️ WARNING: Could not locate credentials file in known locations")
    print(f"  Will try with default: {DEFAULT_CREDENTIALS_FILE}")
    return DEFAULT_CREDENTIALS_FILE

# Set the credentials file path
GOOGLE_CREDENTIALS_FILE = find_credentials_file()

# Log the selected path
print(f"Using Google credentials from: {GOOGLE_CREDENTIALS_FILE}")
# ---------------------------- Emoji Dictionary ----------------------------
EMOJI = {
    # Status emojis
    "success": "✅",
    "error": "❌",
    "warning": "⚠️",
    "info": "ℹ️",
    
    # Product emojis
    "buds": "🌿",
    "carts": "🔋",
    "edibles": "🍬",
    "local": "🍃",
    
    # Order process emojis
    "cart": "🛒",
    "money": "💰",
    "shipping": "📦",
    "payment": "💸",
    "order": "📝",
    "deliver": "🚚",
    "tracking": "🔍",
    "qrcode": "📱",
    
    # User interaction emojis
    "welcome": "👋",
    "thanks": "🙏",
    "question": "❓",
    "time": "⏰",
    "new": "🆕",
    "attention": "📢",
    
    # Admin panel emojis
    "admin": "🔐",
    "list": "📋",
    "search": "🔎",
    "inventory": "📊",
    "review": "💯",
    "id": "🆔",
    "customer": "👤",
    "date": "📅",
    "status": "📊",
    "back": "◀️",
    "phone": "📞",
    "address": "🏠",
    "link": "🔗",
    "screenshot": "🖼️",
    "update": "💫",
    
    # Additional emojis
    "restart": "🔄",
    "help": "❓",
    "home": "🏠",
    "browse": "🛒",
    "clock": "⏰", 
    "package": "📦",
    "truck": "🚚",
    "party": "🎉",
    "support": "🧑‍💼",
    "alert": "🚨",
    'home': '🏠',
}

# ---------------------------- Product Dictionary ----------------------------
PRODUCTS = {
    "buds": {
        "name": "Premium Buds",
        "emoji": EMOJI["buds"],
        "description": "High-quality cannabis flowers",
        "min_order": 1,
        "unit": "grams",
        "tag": "buds",
        "requires_strain_selection": True
    },
    "local": {
        "name": "Local (BG)",
        "emoji": EMOJI["local"],
        "description": "Local budget-friendly option",
        "min_order": 10,
        "unit": "grams",
        "tag": "local",
        "price_per_unit": 1000
    },
    "carts": {
        "name": "Carts/Disposables",
        "emoji": EMOJI["carts"],
        "description": "Pre-filled vape cartridges",
        "min_order": 1,
        "unit": "units",
        "tag": "carts",
        "browse_options": ["brand", "weight"]
    },
    "edibles": {
        "name": "Edibles",
        "emoji": EMOJI["edibles"],
        "description": "Cannabis-infused food products",
        "min_order": 1,
        "unit": "packs",
        "tag": "edibs",
        "requires_strain_selection": True
    }
}

# ---------------------------- Status Dictionary ----------------------------
STATUS = {
    "pending_payment": {
        "label": "Pending Payment Review",
        "description": "We're currently reviewing your payment. This usually takes 1-2 hours during business hours.",
        "emoji": EMOJI["warning"]
    },
    "payment_confirmed": {
        "label": "Payment Confirmed and Preparing Order",
        "description": "Great news! Your payment has been confirmed and we're now preparing your order. We'll update you again when it's ready for delivery.",
        "emoji": EMOJI["success"]
    },
    "booking": {
        "label": "Booking",
        "description": "We're currently booking a delivery partner for your order. This process typically takes 1-3 hours depending on availability.",
        "emoji": EMOJI["info"]
    },
    "booked": {
        "label": "Booked",
        "description": "Good news! Your order has been booked with a delivery partner and is on its way.",
        "emoji": EMOJI["deliver"],
        "with_tracking": "Good news! Your order has been booked with Lalamove and is on its way. You can track your delivery in real-time using the link below:"
    },
    "delivered": {
        "label": "Delivered",
        "description": "Your order has been delivered! We hope you enjoy your products. Thank you for choosing Ganja Paraiso!",
        "emoji": EMOJI["success"]
    },
    "payment_rejected": {
        "label": "Payment Rejected",
        "description": "Unfortunately, there was an issue with your payment. Please contact customer support for assistance.",
        "emoji": EMOJI["error"]
    }
}

# ---------------------------- Message Templates ----------------------------
MESSAGES = {
    "welcome": f"{EMOJI['welcome']} Mabuhigh! Welcome to Ganja Paraiso! What would you like to order today?",
    
    "order_added": f"{EMOJI['success']} Item added to your cart. What would you like to do next?",
    
    "checkout_prompt": (
        f"{EMOJI['cart']} Please enter your shipping details (Name / Address / Contact Number).\n\n"
        f"{EMOJI['info']} Example: Juan Dela Cruz / 123 Main St, City / 09171234567\n\n"
        "Please provide the correct information to proceed."
    ),
    
    "payment_instructions": (
    f"{EMOJI['payment']} Please send a screenshot of your payment to complete the order.\n\n"
    f"{EMOJI['money']} Send payment to GCash: {{}}\n\n"
    f"{EMOJI['qrcode']} Scan this QR code for faster payment:\n"
    f"[QR Code will appear here]\n\n"
    f"{EMOJI['info']} <b>Note: If you're using the desktop app of Telegram, please select "
    "the option to compress the image when uploading or pasting your payment screenshot.</b>\n\n"
    f"{EMOJI['success']} We will review your payment and proceed with processing your order."
    ),
    
    "order_confirmation": (
        f"{EMOJI['success']} Payment screenshot received! Your order ID is: {{}}\n\n"
        "We will review it shortly and process your order. You can check the status "
        "of your order anytime using the /track command."
    ),
    
    "invalid_format": f"{EMOJI['error']} Invalid format. Please try again using the correct format.",
    
    "cancel_order": f"{EMOJI['warning']} Order cancelled. You can start over anytime by typing /start.",
    
    "empty_cart": f"{EMOJI['cart']} Your cart is empty. Please add items before continuing.",
    
    "invalid_details": (
        f"{EMOJI['error']} Invalid shipping details. Please use the format:\n\n"
        "Name / Address / Contact Number\n\n"
        f"{EMOJI['success']} Example: Juan Dela Cruz / 123 Main St, City / 09171234567\n\n"
        "Please provide the correct information to proceed."
    ),
    
    "invalid_payment": f"{EMOJI['error']} Please send a valid payment screenshot.",
    
    "admin_welcome": (
        f"{EMOJI['admin']} Welcome to the Admin Panel\n\n"
        "From here, you can manage orders, update statuses, handle inventory, and process payments."
    ),
    
    "not_authorized": f"{EMOJI['error']} You are not authorized to access this feature.",
    
    "order_not_found": f"{EMOJI['error']} Order {{}} not found.",
    
    "status_updated": f"{EMOJI['success']} Status updated to '{{}}' for Order {{}}.",
    
    "tracking_updated": f"{EMOJI['success']} Tracking link has been updated for Order {{}}.",
    
    "error": f"{EMOJI['error']} An unexpected error occurred. Please try again later.",
    
    "tracking_prompt": (
        f"{EMOJI['tracking']} Please enter your Order ID to track your order:\n\n"
        "Example: WW-1234-ABC"
    ),
    
    "order_status_heading": f"{EMOJI['shipping']} Order Status Update"
}

# ---------------------------- Error Messages ----------------------------
ERRORS = {
    "payment_processing": f"{EMOJI['error']} We had trouble processing your payment. Please try again.",
    
    "invalid_quantity": f"{EMOJI['warning']} Please enter a valid quantity.",
    
    "minimum_order": f"{EMOJI['info']} Minimum order for {{}} is {{}} {{}}.",
    
    "invalid_category": f"{EMOJI['error']} Invalid category or suboption. Please try again.",
    
    "network_error": f"{EMOJI['error']} Network connection issue. Please try again later.",
    
    "timeout": f"{EMOJI['time']} Your session has timed out for security reasons. Please start again with /start.",
    
    "not_authorized": f"{EMOJI['error']} You are not authorized to use this feature.",
    
    "update_failed": f"{EMOJI['error']} Failed to update status for Order {{}}.",
    
    "no_screenshot": f"{EMOJI['error']} Payment screenshot not found for this order.",
    
    "tracking_not_found": (
        f"{EMOJI['error']} Order ID not found. Please check your Order ID and try again.\n\n"
        "If you continue having issues, please contact customer support."
    )
}

# ---------------------------- Google Sheets Column Mappings ----------------------------
SHEET_COLUMNS = {
    "order_id": "Order ID",
    "telegram_id": "Telegram ID",
    "name": "Customer Name",
    "address": "Address",
    "contact": "Contact",
    "product": "Product",
    "quantity": "Quantity",
    "price": "Price",
    "status": "Status",
    "payment_url": "Payment URL",
    "order_date": "Order Date",
    "notes": "Notes",
    "tracking_link": "Tracking Link"
}

# Default headers for orders sheet
SHEET_HEADERS = [
    SHEET_COLUMNS["order_id"],
    SHEET_COLUMNS["telegram_id"],
    SHEET_COLUMNS["name"],
    SHEET_COLUMNS["address"],
    SHEET_COLUMNS["contact"],
    SHEET_COLUMNS["product"],
    SHEET_COLUMNS["quantity"],
    SHEET_COLUMNS["price"],
    SHEET_COLUMNS["status"],
    SHEET_COLUMNS["payment_url"],
    SHEET_COLUMNS["order_date"],
    SHEET_COLUMNS["notes"],
    SHEET_COLUMNS["tracking_link"]
]

# Mapping of sheet column names to their index (1-based for gspread API)
SHEET_COLUMN_INDICES = {name: idx+1 for idx, name in enumerate(SHEET_HEADERS)}

# ---------------------------- Regular Expressions ----------------------------
REGEX = {
    "shipping_details": r"^(.+?)\s*\/\s*(.+?)\s*\/\s*(\+?[\d\s\-]{10,15})$",
    "quantity": r"(\d+)"
}

# ---------------------------- Rate Limiting ----------------------------
RATE_LIMITS = {
    "order": 10,    # Max 10 orders per hour
    "payment": 15,  # Max 15 payment uploads per hour
    "track": 30,    # Max 30 tracking requests per hour
    "admin": 50,     # Max 50 admin actions per hour
    "checkout": {"limit": 10, "window": 3600},  # 10 checkouts per hour
    "verify": {"limit": 20, "window": 3600},  # 20 verifications per hour
    "global": {"limit": 100, "window": 3600},  # 100 actions per hour
}

# ---------------------------- Cache Configuration ----------------------------
CACHE_EXPIRY = {
    "inventory": 300,     # 5 minutes
    "orders": 60,   # 1 minute
    "customer_info": 600,  # 10 minutes
    "sheets": 120,     # 2 minutes
    "drive": 600,      # 10 minutes
}

# ---------------------------- Default Values ----------------------------
DEFAULT_INVENTORY = [
    {"Name": "Unknown Indica", "Type": "indica", "Tag": "buds", "Price": 2000, "Stock": 5},
    {"Name": "Unknown Sativa", "Type": "sativa", "Tag": "buds", "Price": 2000, "Stock": 5},
    {"Name": "Unknown Hybrid", "Type": "hybrid", "Tag": "buds", "Price": 2000, "Stock": 5},
    {"Name": "Local BG", "Type": "", "Tag": "local", "Price": 1000, "Stock": 10},
    {"Name": "Basic Cart", "Type": "", "Tag": "carts", "Brand": "Generic", "Weight": "1g", "Price": 1500, "Stock": 3},
    {"Name": "Basic Edible", "Type": "hybrid", "Tag": "edibs", "Price": 500, "Stock": 5}
]

# ---------------------------- Logging Setup ----------------------------
def setup_logging():
    """
    Set up a robust logging system with rotation and separate log files.
    
    Returns:
        dict: Dictionary containing configured loggers for different components
    """
    # Create logs directory if it doesn't exist
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    
    # Define all required loggers
    logger_names = [
        "main", "orders", "payments", "errors", "admin", 
        "performance", "status", "users", "security"
    ]
    
    loggers = {}
    
    # Configure each logger
    for name in logger_names:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        
        # Create rotating file handler (10 files, 5MB each)
        handler = RotatingFileHandler(
            f"{log_dir}/{name}.log",
            maxBytes=5*1024*1024,
            backupCount=10
        )
        
        # Create formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        
        # Add handler to logger
        logger.addHandler(handler)
        
        # Also add a console handler for development
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(formatter)
        logger.addHandler(console)
        
        loggers[name] = logger
    
    # Log startup message
    loggers["main"].info("Bot logging system initialized")
    
    return loggers

def log_order(logger, order_data, action="created"):
    """
    Log order information with consistent formatting.
    Sensitive data is masked for security.
    
    Args:
        logger: The logger instance to use
        order_data (dict): Order information
        action (str): Action being performed on the order
    """
    order_id = order_data.get("order_id", "Unknown")
    customer = mask_sensitive_data(order_data.get("name", "Unknown"), 'name')
    total = order_data.get("total", 0)
    
    logger.info(
        f"Order {order_id} {action} | Customer: {customer} | "
        f"Total: ₱{total:,.2f} | Items: {order_data.get('items_count', 0)}"
    )

def mask_sensitive_data(data, mask_type='default'):
    """
    Mask sensitive data for logging purposes.
    
    Args:
        data (str): Data to mask
        mask_type (str): Type of data being masked ('phone', 'address', 'name', etc.)
        
    Returns:
        str: Masked data
    """
    if not data:
        return ''
    
    data = str(data)
    
    if mask_type == 'phone':
        # Mask phone number - keep first 3 and last 2 digits
        if len(data) > 5:
            visible_part = data[:3] + '*' * (len(data) - 5) + data[-2:]
            return visible_part
        return '*' * len(data)
    
    elif mask_type == 'address':
        # For address, show only the first part and city
        parts = data.split(',')
        if len(parts) > 1:
            # Take first part of street address
            street = parts[0].strip()
            city_part = parts[-1].strip()
            
            # Get house/building number if available
            address_parts = street.split(' ', 1)
            
            if len(address_parts) > 1 and address_parts[0].isdigit():
                # Show house number and first letter of street name
                masked_street = address_parts[0] + ' ' + address_parts[1][0] + '*' * (len(address_parts[1]) - 1)
            else:
                # Just show first 3 chars of address
                masked_street = street[:3] + '*' * (len(street) - 3) if len(street) > 3 else street
                
            return f"{masked_street}, {city_part}"
        
        # If simple address, show first 4 chars
        if len(data) > 4:
            return data[:4] + '*' * (len(data) - 4)
        return data
        
    elif mask_type == 'name':
        # Show first letter of each name part (with Unicode support)
        import unicodedata
        name_parts = data.split()
        masked_parts = []
    
        for part in name_parts:
            if len(part) > 1:
                # Get first character correctly even with multi-byte chars
                first_char = part[0]
                masked_parts.append(f"{first_char}{'*' * (len(part) - 1)}")
            else:
                masked_parts.append(part)
            
        return ' '.join(masked_parts)
        
    else:
        # Default masking - show first 3 chars and last char
        if len(data) > 4:
            return data[:3] + '*' * (len(data) - 4) + data[-1]
        return '*' * len(data)

def log_payment(logger, order_id, status, amount=None):
    """
    Log payment information with consistent formatting.
    
    Args:
        logger: The logger instance to use
        order_id (str): The order ID
        status (str): Payment status (received, confirmed, rejected)
        amount (float, optional): Payment amount
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    amount_str = f" | Amount: ₱{amount:,.2f}" if amount else ""
    
    logger.info(
        f"Payment for order {order_id} {status} at {timestamp}{amount_str}"
    )

def log_error(logger, function_name, error, user_id=None):
    """
    Log error information with consistent formatting.
    
    Args:
        logger: The logger instance to use
        function_name (str): Name of the function where the error occurred
        error (Exception): The error object
        user_id (int, optional): Telegram user ID if applicable
    """
    user_info = f" | User: {user_id}" if user_id else ""
    
    logger.error(
        f"Error in {function_name}{user_info} | {type(error).__name__}: {str(error)}"
    )

def log_security_event(logger, event_type, user_id=None, ip=None, details=None):
    """
    Log security-related events for monitoring and auditing.
    
    Args:
        logger: The logger instance to use
        event_type (str): Type of security event
        user_id (int, optional): Telegram user ID if applicable
        ip (str, optional): IP address if available
        details (str, optional): Additional event details
    """
    # Create a secure log with consistent format and UTC time
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    user_info = f"User: {user_id}" if user_id else "No user"
    ip_info = f"IP: {ip}" if ip else "No IP"
    details_info = f"Details: {details}" if details else ""
    
    logger["security"].warning(
        f"SECURITY EVENT [{event_type}] | {timestamp} | {user_info} | {ip_info} | {details_info}"
    )

async def send_typing_action(context, chat_id, seconds=1):
    """
    Send a typing indicator to the user to show the bot is processing.
    
    Args:
        context: Conversation context containing the bot
        chat_id (int): Chat ID to send typing indicator to
        seconds (float): How long to show typing for
    """
    try:
        # Send typing action
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        # If more than minimal typing time is requested, sleep
        if seconds > 0.5:
            await asyncio.sleep(seconds)
    except Exception:
        # Silently ignore errors with typing indicator
        pass

class BotResponse:
    """
    Class to create consistent, well-formatted bot responses.
    
    This helps maintain a consistent style and structure across all bot messages.
    """
    
    def __init__(self, emoji_key=None, header=None):
        """
        Initialize a bot response.
    
        Args:
            emoji_key (str, optional): Key to lookup in EMOJI dictionary
            header (str, optional): Header text for the message
        """
        self.parts = []
    
        # Get emoji dict safely
        emoji_dict = {}
        if 'EMOJI' in globals():
            emoji_dict = globals().get('EMOJI', {})
    
        if emoji_key and emoji_key in emoji_dict:
            self.header = f"{emoji_dict[emoji_key]} {header}" if header else emoji_dict[emoji_key]
        else:
            self.header = header
    
    def add_header(self, text, emoji_key=None):
        """
        Add a header to the message.
        
        Args:
            text (str): Header text
            emoji_key (str, optional): Key to lookup in EMOJI dictionary
            
        Returns:
            BotResponse: self for method chaining
        """
        if emoji_key and emoji_key in EMOJI:
            self.header = f"{EMOJI[emoji_key]} {text}"
        else:
            self.header = text
        return self
    
    def add_paragraph(self, text):
        """
        Add a paragraph to the message.
        
        Args:
            text (str): Paragraph text
            
        Returns:
            BotResponse: self for method chaining
        """
        self.parts.append(text)
        return self
    
    def add_bullet_list(self, items, emoji_key=None):
        """
        Add a bullet list to the message.
        
        Args:
            items (list): List items
            emoji_key (str, optional): Key to lookup in EMOJI dictionary for bullets
            
        Returns:
            BotResponse: self for method chaining
        """
        bullet = EMOJI[emoji_key] if emoji_key and emoji_key in EMOJI else "•"
        bullet_list = []
        
        for item in items:
            bullet_list.append(f"{bullet} {item}")
        
        self.parts.append("\n".join(bullet_list))
        return self
    
    def add_data_table(self, data, headers=None):
        """
        Add a formatted data table.
        
        Args:
            data (list): List of data rows
            headers (list, optional): Column headers
            
        Returns:
            BotResponse: self for method chaining
        """
        if not data:
            return self
        
        table_str = ""
        
        # Add headers if provided
        if headers:
            table_str += " | ".join(headers) + "\n"
            table_str += "-" * (sum(len(h) for h in headers) + 3 * (len(headers) - 1)) + "\n"
        
        # Add data rows
        for row in data:
            table_str += " | ".join(str(cell) for cell in row)
            table_str += "\n"
        
        self.parts.append(table_str)
        return self
    
    def add_divider(self):
        """
        Add a divider line.
        
        Returns:
            BotResponse: self for method chaining
        """
        self.parts.append("------------------------")
        return self
    
    def get_message(self):
        """
        Get the complete formatted message.
        
        Returns:
            str: The formatted message text
        """
        message = ""
        
        # Add header if present
        if self.header:
            message += f"{self.header}\n\n"
        
        # Add all parts with spacing
        for i, part in enumerate(self.parts):
            message += part
            # Add spacing after all parts except the last
            if i < len(self.parts) - 1:
                message += "\n\n"
        
        return message

def log_admin_action(logger, admin_id, action, order_id=None):
    """
    Log admin actions with consistent formatting.
    
    Args:
        logger: The logger instance to use
        admin_id (int): Telegram ID of the admin
        action (str): Action performed
        order_id (str, optional): Order ID if applicable
    """
    order_info = f" | Order: {order_id}" if order_id else ""
    
    logger.info(
        f"Admin {admin_id} performed: {action}{order_info}"
    )

# ---------------------------- Google API Services ----------------------------
class GoogleAPIsManager:
    """Manage Google API connections with rate limiting, backoff, and enhanced caching."""
    
    def __init__(self, loggers: Dict[str, logging.Logger]) -> None:
        """
        Initialize the Google APIs Manager.
        
        Args:
            loggers: Dictionary of logger instances
        """
        self.loggers = loggers
        self.last_request_time: Dict[str, float] = {}
        self.min_request_interval: float = 1.0  # Minimum seconds between requests
        self._sheet_client = None
        self._drive_service = None
        self._sheet = None
        self._inventory_sheet = None
        self._sheet_initialized: bool = False
        
        # Create enhanced caches with appropriate sizes
        self.caches = {
            "inventory": EnhancedCache(max_items=20),
            "orders": EnhancedCache(max_items=100),
            "sheets": EnhancedCache(max_items=50),
            "drive": EnhancedCache(max_items=30)
        }
        
        # Set appropriate TTLs for different cache types
        self.caches["inventory"].default_ttl = 300  # 5 minutes for inventory
        self.caches["orders"].default_ttl = 60      # 1 minute for orders 
        self.caches["sheets"].default_ttl = 120     # 2 minutes for sheets
        self.caches["drive"].default_ttl = 600      # 10 minutes for drive
        
    async def get_sheet_client(self):
        """
        Get or create a gspread client with authorization.
        
        Returns:
            gspread.Client: Authorized gspread client
        """
        # Use existing client if available
        if self._sheet_client:
            return self._sheet_client
                
        try:
            # Verify the file exists before proceeding
            if not os.path.isfile(GOOGLE_CREDENTIALS_FILE):
                error_msg = (
                    f"Credentials file not found: {GOOGLE_CREDENTIALS_FILE}\n"
                    f"Please ensure the file exists at this location."
                )
                self.loggers["errors"].error(error_msg)
                print(f"❌ {error_msg}")
                raise FileNotFoundError(error_msg)
            
            # Log successful file access
            file_size = os.path.getsize(GOOGLE_CREDENTIALS_FILE)
            self.loggers["main"].info(
                f"Using credentials file ({file_size} bytes): {GOOGLE_CREDENTIALS_FILE}"
            )
            
            # Set up authentication for Google Sheets using google-auth
            scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/drive']
            
            try:
                creds = service_account.Credentials.from_service_account_file(
                    GOOGLE_CREDENTIALS_FILE,
                    scopes=scope
                )
            except json.JSONDecodeError:
                error_msg = f"Credentials file is not valid JSON: {GOOGLE_CREDENTIALS_FILE}"
                self.loggers["errors"].error(error_msg)
                raise ValueError(error_msg)
            except Exception as cred_error:
                self.loggers["errors"].error(f"Error loading credentials: {str(cred_error)}")
                raise
            
            self._sheet_client = gspread.authorize(creds)
            self.loggers["main"].info("Successfully authenticated with Google Sheets")
            return self._sheet_client
        except Exception as e:
            self.loggers["errors"].error(f"Failed to authenticate with Google Sheets: {e}")
            raise
    
    async def get_drive_service(self):
        """
        Get or create a Google Drive service client.
        
        Returns:
            Resource: Google Drive API service instance
        """
        # Use existing drive service if available
        if self._drive_service:
            return self._drive_service
            
        try:
            # Set up Google Drive API client
            credentials = service_account.Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_FILE, 
                scopes=['https://www.googleapis.com/auth/drive']
            )
            self._drive_service = build('drive', 'v3', credentials=credentials)
            return self._drive_service
        except Exception as e:
            self.loggers["errors"].error(f"Failed to authenticate with Google Drive: {e}")
            raise
    
    async def initialize_sheets(self):
        """
        Initialize the order sheet and inventory sheet.
        Sets up headers if needed.
        
        Returns:
            tuple: (orders_sheet, inventory_sheet)
        """
        if self._sheet_initialized and self._sheet and self._inventory_sheet:
            return self._sheet, self._inventory_sheet
            
        try:
            # Make a rate-limited request
            await self._rate_limit_request('sheets')
            
            # Get the spreadsheet with enhanced error handling
            client = await self.get_sheet_client()
            if not client:
                self.loggers["errors"].error("Failed to get sheet client")
                return None, None
                
            print("DEBUG SHEETS: Got sheet client, opening spreadsheet")
            
            try:
                spreadsheet = client.open(GOOGLE_SHEET_NAME)
            except Exception as sheet_err:
                self.loggers["errors"].error(f"Failed to open spreadsheet: {str(sheet_err)}")
                print(f"DEBUG SHEETS: Error opening spreadsheet: {str(sheet_err)}")
                return None, None
            
            # Get or create the main orders sheet
            try:
                self._sheet = spreadsheet.sheet1
                print("DEBUG SHEETS: Successfully accessed orders sheet")
            except Exception as orders_err:
                self.loggers["errors"].error(f"Error accessing orders sheet: {str(orders_err)}")
                try:
                    print("DEBUG SHEETS: Creating orders sheet")
                    self._sheet = spreadsheet.add_worksheet("Orders", 1000, 20)
                except Exception as create_err:
                    self.loggers["errors"].error(f"Error creating orders sheet: {str(create_err)}")
                    return None, None
            
            # Get or create the inventory sheet
            try:
                self._inventory_sheet = spreadsheet.worksheet("Inventory")
                print("DEBUG SHEETS: Successfully accessed inventory sheet")
            except Exception as inv_err:
                self.loggers["errors"].error(f"Error accessing inventory sheet: {str(inv_err)}")
                try:
                    print("DEBUG SHEETS: Creating inventory sheet")
                    self._inventory_sheet = spreadsheet.add_worksheet("Inventory", 100, 10)
                    # Initialize inventory headers with new columns
                    self._inventory_sheet.append_row([
                        "Name", "Strain", "Type", "Tag", "Price", "Stock", 
                        "Weight", "Brand", "Description", "Image_URL"
                    ])
                except Exception as create_err:
                    self.loggers["errors"].error(f"Error creating inventory sheet: {str(create_err)}")
                    # We can continue with just the orders sheet if needed
            
            # Ensure the orders sheet has the correct headers
            try:
                current_headers = self._sheet.row_values(1)
                if not current_headers or len(current_headers) < len(SHEET_HEADERS):
                    print("DEBUG SHEETS: Setting up sheet headers")
                    self._sheet.update("A1", [SHEET_HEADERS])
            except Exception as header_err:
                self.loggers["errors"].error(f"Error setting sheet headers: {str(header_err)}")
                # We can still try to continue if headers exist
            
            self._sheet_initialized = True
            print("DEBUG SHEETS: Sheets successfully initialized")
            return self._sheet, self._inventory_sheet
            
        except Exception as e:
            self.loggers["errors"].error(f"Failed to initialize sheets: {e}")
            # Return None or provide fallback behavior
            print(f"DEBUG SHEETS: Fatal error initializing sheets: {str(e)}")
            return None, None
                
    def _check_cache(self, cache_key, cache_type="inventory", max_age=None):
        """
        Check if cached data exists and is still valid.
        
        Args:
            cache_key (str): The specific key for the cached data
            cache_type (str): The type of cache to use
            max_age (int, optional): Override the default TTL
            
        Returns:
            tuple: (is_valid, cached_data)
        """
        if cache_type not in self.caches:
            cache_type = "inventory"  # Default to inventory cache
            
        cache = self.caches[cache_type]
        ttl = max_age if max_age is not None else None  # Use cache default if not specified
        
        return cache.get(cache_key, ttl)
    
    def _update_cache(self, cache_key, data, cache_type="inventory", ttl=None):
        """
        Update the cache with new data.
        
        Args:
            cache_key (str): The key for the cached data
            data: The data to cache
            cache_type (str): The type of cache to use
            ttl (int, optional): Override the default TTL
            
        Returns:
            The cached data
        """
        if cache_type not in self.caches:
            cache_type = "inventory"  # Default to inventory cache
            
        cache = self.caches[cache_type]
        return cache.set(cache_key, data, ttl)
    
    async def fetch_inventory(self):
        """
        Fetch inventory data from Google Sheets including tags and stock.
        Uses enhanced caching to reduce API calls.
        
        Returns:
            tuple: (products_by_tag, products_by_strain, all_products)
        """
        # Check cache first
        is_valid, cached_data = self._check_cache("inventory_data", "inventory")
        if is_valid:
            return cached_data
        
        products_by_tag = {'buds': [], 'local': [], 'carts': [], 'edibs': []}
        products_by_strain = {'indica': [], 'sativa': [], 'hybrid': []}
        all_products = []
        
        try:
            # Initialize sheets
            _, inventory_sheet = await self.initialize_sheets()
            
            if not inventory_sheet:
                default_inventory = self._create_default_inventory()
                return self._update_cache("inventory_data", default_inventory, "inventory")
            
            # Make a rate-limited request
            await self._rate_limit_request('inventory')
            
            # Get inventory data
            inventory_data = inventory_sheet.get_all_records()
            
            for item in inventory_data:
                # Skip items with no stock
                if 'Stock' not in item or item['Stock'] <= 0:
                    continue
                    
                product_name = item.get('Name', item.get('Strain', 'Unknown'))
                product_key = product_name.lower().replace(' ', '_')
                product_tag = item.get('Tag', '').lower()
                strain_type = item.get('Type', '').lower()
                price = item.get('Price', 0)
                stock = item.get('Stock', 0)
                
                product = {
                    'name': product_name,
                    'key': product_key,
                    'price': price,
                    'stock': stock,
                    'tag': product_tag,
                    'strain': strain_type,
                    'weight': item.get('Weight', ''),  # For carts
                    'brand': item.get('Brand', '')     # For carts
                }
                
                # Add to all products list
                all_products.append(product)
                
                # Categorize by tag
                if product_tag in products_by_tag:
                    products_by_tag[product_tag].append(product)
                    
                # Categorize by strain
                if strain_type in products_by_strain:
                    products_by_strain[strain_type].append(product)
            
            result = (products_by_tag, products_by_strain, all_products)
            return self._update_cache("inventory_data", result, "inventory")
            
        except Exception as e:
            self.loggers["errors"].error(f"Error fetching inventory: {e}")
            # Fallback to default inventory
            default_inventory = self._create_default_inventory()
            return self._update_cache("inventory_data", default_inventory, "inventory")
            
    def _create_default_inventory(self):
        """
        Create a default inventory when API access fails.
        
        Returns:
            tuple: (products_by_tag, products_by_strain, all_products)
        """
        products_by_tag = {'buds': [], 'local': [], 'carts': [], 'edibs': []}
        products_by_strain = {'indica': [], 'sativa': [], 'hybrid': []}
        all_products = []
        
        for item in DEFAULT_INVENTORY:
            product_name = item.get('Name', item.get('Strain', 'Unknown'))
            product_key = product_name.lower().replace(' ', '_')
            product_tag = item.get('Tag', '').lower()
            strain_type = item.get('Type', '').lower()
            price = item.get('Price', 0)
            stock = item.get('Stock', 0)
            
            product = {
                'name': product_name,
                'key': product_key,
                'price': price,
                'stock': stock,
                'tag': product_tag,
                'strain': strain_type,
                'weight': item.get('Weight', ''),
                'brand': item.get('Brand', '')
            }
            
            all_products.append(product)
            
            if product_tag and product_tag in products_by_tag:
                products_by_tag[product_tag].append(product)
                
            if strain_type and strain_type in products_by_strain:
                products_by_strain[strain_type].append(product)
        
        self.loggers["errors"].warning("Using default inventory due to API failure")
        return products_by_tag, products_by_strain, all_products
    
    async def upload_payment_screenshot(self, file_bytes, filename):
        """
        Upload a payment screenshot to Google Drive with enhanced retry logic.
        
        Args:
            file_bytes (BytesIO): File bytes to upload
            filename (str): Name to give the file
            
        Returns:
            str: Web view link to the uploaded file
            
        Raises:
            ConnectionError: When network connectivity issues occur
            ValueError: When file data is invalid
            RuntimeError: For Google API issues
            Exception: For other unexpected errors
        """
        try:
            # Make a rate-limited request
            await self._rate_limit_request('drive')
            
            # Get the drive service
            drive_service = await self.get_drive_service()
            
            # Validate input
            if not file_bytes:
                raise ValueError("Empty file bytes provided")
            
            if not filename or not isinstance(filename, str):
                filename = f"payment_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
            
            # Prepare file metadata
            file_metadata = {
                'name': filename,
                'mimeType': 'image/jpeg',
                'parents': [PAYMENT_SCREENSHOTS_FOLDER_ID]
            }
            
            # Create media upload object
            try:
                media = MediaIoBaseUpload(BytesIO(file_bytes), mimetype='image/jpeg')
            except Exception as media_error:
                raise ValueError(f"Invalid file bytes: {media_error}") from media_error
            
            # Create a retryable operation for the upload
            async def perform_upload():
                try:
                    return drive_service.files().create(
                        body=file_metadata, 
                        media_body=media, 
                        fields='id, webViewLink'
                    ).execute()
                except TimeoutError as timeout_err:
                    raise TimeoutError(f"Upload timed out: {timeout_err}") from timeout_err
                except ConnectionError as conn_err:
                    raise ConnectionError(f"Connection error during upload: {conn_err}") from conn_err
                except Exception as api_err:
                    raise RuntimeError(f"Google Drive API error: {api_err}") from api_err
            
            # Use the retryable operation with specific error types
            retry_handler = RetryableOperation(
                self.loggers, 
                max_retries=3,
                retry_on=(ConnectionError, TimeoutError, BrokenPipeError)
            )
            
            drive_file = await retry_handler.run(
                perform_upload, 
                operation_name="upload_payment_screenshot"
            )
            
            # Validate and return the web link
            web_link = drive_file.get('webViewLink')
            if not web_link:
                raise RuntimeError("Drive API returned no webViewLink")
                
            return web_link
            
        except ConnectionError as e:
            self.loggers["errors"].error(f"Connection error uploading payment screenshot: {e}")
            raise
        except TimeoutError as e:
            self.loggers["errors"].error(f"Timeout uploading payment screenshot: {e}")
            raise
        except ValueError as e:
            self.loggers["errors"].error(f"Invalid data for payment screenshot: {e}")
            raise
        except RuntimeError as e:
            self.loggers["errors"].error(f"API error uploading payment screenshot: {e}")
            raise
        except Exception as e:
            self.loggers["errors"].error(f"Unexpected error uploading payment screenshot: {str(e)}")
            raise RuntimeError(f"Failed to upload payment screenshot: {e}") from e
    
    async def add_order_to_sheet(self, order_data):
        """
        Add a new order to the Google Sheet.
        
        Args:
            order_data: List of order values to add to sheet
            
        Returns:
            bool: Success status
        """
        try:
            # Initialize the sheets if not already done
            sheet, _ = await self.initialize_sheets()
            if not sheet:
                self.loggers["errors"].error("Failed to initialize sheet for adding order")
                return False
                
            # Make a rate-limited request
            await self._rate_limit_request('sheets_write')
            
            # Debug print the order data length
            print(f"DEBUG SHEET: Adding order with {len(order_data)} columns to sheet")
            
            # Check if row has correct number of columns
            expected_columns = len(SHEET_HEADERS)
            if len(order_data) != expected_columns:
                # Adjust the order data to match expected columns
                if len(order_data) < expected_columns:
                    # Add empty strings to fill missing columns
                    order_data.extend([""] * (expected_columns - len(order_data)))
                else:
                    # Truncate extra columns
                    order_data = order_data[:expected_columns]
                
                print(f"DEBUG SHEET: Adjusted order data to {len(order_data)} columns")
            
            # Find the next empty row
            try:
                # Get all values in first column
                col_a = sheet.col_values(1)
                # Next row is one more than the length
                next_row = len(col_a) + 1
            except Exception as row_err:
                self.loggers["errors"].error(f"Error finding next row: {str(row_err)}")
                # Default to append as fallback
                next_row = None
            
            # Use RetryableOperation for robust error handling
            retry_handler = RetryableOperation(
                self.loggers, 
                max_retries=3,
                retry_on=(ConnectionError, TimeoutError, BrokenPipeError)
            )
            
            # Define the add operation
            async def add_to_sheet():
                if next_row:
                    # If we know the next row, insert there
                    sheet.insert_row(order_data, next_row)
                else:
                    # Otherwise just append
                    sheet.append_row(order_data)
                return True
            
            # Try adding with retries
            success = await retry_handler.run(
                add_to_sheet,
                operation_name="add_order_to_sheet"
            )
            
            # Update cache
            if success:
                # Invalidate orders cache
                if 'orders' in self.caches:
                    self.caches['orders'].clear()
            
            return success
            
        except Exception as e:
            self.loggers["errors"].error(f"Failed to add order to sheet: {str(e)}")
            return False

    async def update_order_status(self, order_id, new_status, tracking_link=None):
        """
        Update the status and optional tracking link for an existing order.
        
        Args:
            order_id (str): Order ID to update
            new_status (str): New status to set for the order
            tracking_link (str, optional): Tracking link to add to the order
            
        Returns:
            tuple: (success, customer_id) - Success status and customer Telegram ID for notifications
        """
        try:
            # Initialize the sheets if needed
            sheet, _ = await self.initialize_sheets()
            if not sheet:
                self.loggers["errors"].error(f"Failed to initialize sheets for updating order {order_id}")
                return False, None
                
            # Make a rate-limited request
            await self._rate_limit_request('sheets_write')
            
            # Find the order by ID
            all_orders = sheet.get_all_records()
            
            # Debug logging
            print(f"DEBUG STATUS: Updating order {order_id} to status: {new_status}")
            
            # Track if we found and updated the order
            found_order = False
            customer_id = None
            
            # Process the orders
            for idx, order in enumerate(all_orders):
                # Look for the main order entry with matching ID
                if 'Order ID' in order and order['Order ID'] == order_id:
                    if 'Product' in order and order['Product'] == "COMPLETE ORDER":
                        # This is our main order row
                        found_order = True
                        
                        # Extract customer ID for notifications
                        if 'Telegram ID' in order:
                            try:
                                customer_id = int(order['Telegram ID'])
                            except (ValueError, TypeError):
                                customer_id = None
                        
                        # Calculate the row number (add 2: 1 for header, 1 for 0-indexing)
                        row_number = idx + 2
                        
                        # Define what to update
                        updates = {
                            'Status': new_status  # Always update status
                        }
                        
                        # Add tracking link if provided
                        if tracking_link:
                            updates['Tracking Link'] = tracking_link
                        
                        # Perform updates with retry logic
                        retry_handler = RetryableOperation(
                            self.loggers, 
                            max_retries=3,
                            retry_on=(ConnectionError, TimeoutError, BrokenPipeError)
                        )
                        
                        # Define the update operation
                        async def update_sheet_cells():
                            for field, value in updates.items():
                                # Find the column index for this field
                                if field in SHEET_COLUMN_INDICES:
                                    col_idx = SHEET_COLUMN_INDICES[field]
                                    # Update the cell
                                    sheet.update_cell(row_number, col_idx, value)
                                    # Small delay to avoid rate limits
                                    await asyncio.sleep(0.5)
                            return True
                        
                        # Execute with retries
                        success = await retry_handler.run(
                            update_sheet_cells,
                            operation_name=f"update_order_status_{order_id}"
                        )
                        
                        # Clear cache for this order
                        cache_key = f"order_{order_id}"
                        if 'orders' in self.caches:
                            self.caches["orders"].clear(cache_key)
                        
                        # Log the result
                        if success:
                            self.loggers["main"].info(
                                f"Updated order {order_id} status to '{new_status}'"
                                f"{' with tracking' if tracking_link else ''}"
                            )
                        else:
                            self.loggers["errors"].error(
                                f"Failed to update sheet cells for order {order_id}"
                            )
                        
                        # Return the result with customer ID for notifications
                        return success, customer_id
            
            # If we reach here, we didn't find the order
            if not found_order:
                self.loggers["errors"].error(f"Order {order_id} not found for status update")
                return False, None
                
        except Exception as e:
            self.loggers["errors"].error(f"Error updating order status: {str(e)}")
            return False, None
        
    async def get_order_details(self, order_id):
        """
        Get details for a specific order with enhanced caching for frequent requests.
        
        Args:
            order_id (str): Order ID to look up
            
        Returns:
            dict: Order details or None if not found
        """
        # For active orders, use a shorter cache expiry
        cache_key = f"order_{order_id}"
        is_valid, cached_data = self._check_cache(cache_key, "orders", max_age=30)  # Short cache time for orders
        if is_valid:
            return cached_data

        try:
            # Initialize sheets
            sheet, _ = await self.initialize_sheets()
            
            if not sheet:
                self.loggers["errors"].error("Failed to get sheet for order details")
                return None
            
            # Make a rate-limited request
            await self._rate_limit_request('sheets_read')
            
            # Get all orders
            orders = sheet.get_all_records()
            
            # Find the main order
            for order in orders:
                if (order.get('Order ID') == order_id and 
                    order.get('Product') == 'COMPLETE ORDER'):
                    # Cache this order's details
                    return self._update_cache(cache_key, order, "orders")
            
            # If not found, cache a None value briefly to prevent repeated lookups
            return self._update_cache(cache_key, None, "orders", ttl=30)
            
        except Exception as e:
            self.loggers["errors"].error(f"Failed to get order details: {e}")
            return None
    
    async def _rate_limit_request(self, api_name):
        """
        Rate limit requests to Google APIs to prevent quota issues.
        
        This method implements an adaptive rate limiting strategy that tracks
        request timing and enforces appropriate delays between requests.
        
        Args:
            api_name (str): Name of the API being accessed for tracking purposes
        """
        now = time.time()
        
        # Define minimum wait times for different API operations (in seconds)
        min_wait_times = {
            'sheets': 1.0,           # General sheets access
            'sheets_read': 0.5,      # Read operations (less intensive)
            'sheets_write': 1.2,     # Write operations (more intensive)
            'drive': 1.5,            # Drive operations
            'inventory': 0.8,        # Inventory fetches
            'default': 1.0           # Default for any other operation
        }
        
        # Get the appropriate wait time
        min_wait = min_wait_times.get(api_name, min_wait_times['default'])
        
        # Check if we need to wait
        last_request = self.last_request_time.get(api_name, 0)
        time_since_last = now - last_request
        
        if time_since_last < min_wait:
            # Calculate wait time with a small buffer
            wait_time = min_wait - time_since_last + 0.1  # Add 0.1s buffer
            
            # Add jitter to prevent synchronized requests (±10%)
            jitter = random.uniform(-0.1, 0.1) * wait_time
            adjusted_wait = max(0.1, wait_time + jitter)  # Ensure at least a minimal wait
            
            # Wait the calculated time
            await asyncio.sleep(adjusted_wait)
        
        # Update the last request time
        self.last_request_time[api_name] = time.time()
        
        # If there are too many entries in last_request_time, clean it up
        if len(self.last_request_time) > 20:
            # Keep only the most recent APIs used
            recent_apis = sorted(
                self.last_request_time.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]
            self.last_request_time = dict(recent_apis)

    def get_cache_stats(self):
        """
        Get statistics on cache performance.
        
        Returns:
            dict: Cache statistics
        """
        stats = {}
        total_hits = 0
        total_misses = 0
        
        for cache_type, cache in self.caches.items():
            cache_stats = cache.get_stats()
            stats[cache_type] = cache_stats
            total_hits += cache_stats["hits"]
            total_misses += cache_stats["misses"]
        
        total_requests = total_hits + total_misses
        hit_ratio = 0 if total_requests == 0 else (total_hits / total_requests)
        
        # Add aggregated statistics
        stats["total"] = {
            "hits": total_hits,
            "misses": total_misses,
            "hit_ratio": hit_ratio,
            "total_requests": total_requests,
            "cache_types": len(self.caches)
        }
        
        return stats
# ---------------------------- Utility Functions ----------------------------
def is_valid_order_id(order_id: str) -> bool:
    """
    Validate the format of an order ID with enhanced security checks.
    
    This function ensures that order IDs follow the expected format (WW-XXXX-YYY)
    and helps prevent injection attacks or invalid queries. Uses the validate_sensitive_data
    function with specific order ID validation rules.
    
    Args:
        order_id: Order ID to validate
        
    Returns:
        bool: True if the order ID is valid, False otherwise
        
    Example:
        >>> is_valid_order_id("WW-1234-ABC")
        True
        >>> is_valid_order_id("INVALID")
        False
    """
    valid, _ = validate_sensitive_data('order_id', order_id)
    return valid

def get_user_orders(user_id):
    """Get a list of orders for a specific user."""
    # Implement your logic to retrieve orders from database
    # Return a list of order dictionaries sorted by date (newest first)
    # Each order should have 'order_id', 'date', 'total', etc.
    return []  # Replace with actual implementation

def get_support_deep_link(user_id, order_id):
    """Create a deep link for support chat with prepared message."""
    import urllib.parse
    
    message = f"Hi Support, I need help with my order. My user ID is {user_id} and my order ID is {order_id}."
    encoded_message = urllib.parse.quote(message)
    
    deep_link = f"https://t.me/{SUPPORT_ADMIN_USERNAME}?start&text={encoded_message}"
    
    return deep_link

def build_category_buttons(available_categories):
    """
    Build inline keyboard with available product category buttons.
    
    Args:
        available_categories (list): List of available category IDs
        
    Returns:
        InlineKeyboardMarkup: Keyboard with product category buttons
    """
    buttons = []
    
    # Debug print to verify available categories
    print(f"DEBUG: Building category buttons for: {available_categories}")
    
    for product_id in available_categories:
        if product_id in PRODUCTS:
            product = PRODUCTS[product_id]
            button_text = f"{product['emoji']} {product['name']}"
            
            buttons.append([InlineKeyboardButton(button_text, callback_data=product_id)])
    
    # Add cancel button
    buttons.append([create_button("cancel", "cancel", "Cancel")])
    
    return InlineKeyboardMarkup(buttons)

def build_admin_buttons():
    """
    Build inline keyboard with admin panel options.
    
    Returns:
        InlineKeyboardMarkup: Keyboard with admin options
    """
    buttons = [
        [create_button("action", "view_orders", f"{EMOJI['list']} View All Orders")],
        [create_button("action", "search_order", f"{EMOJI['search']} Search Order by ID")],
        [create_button("action", "manage_inventory", f"{EMOJI['inventory']} Manage Inventory")],
        [create_button("action", "approve_payments", f"{EMOJI['review']} Review Payments")]
    ]
    
    return InlineKeyboardMarkup(buttons)

def build_cart_summary(cart):
    """
    Build a formatted summary of the cart contents.
    
    Args:
        cart (list): List of cart items
        
    Returns:
        tuple: (summary_text, total_cost)
    """
    # If the cart is empty, return a message indicating so
    if not cart:
        return f"{EMOJI['cart']} Your cart is empty.\n", 0

    # Initialize the summary string and total cost
    summary = f"{EMOJI['cart']} Your Cart:\n\n"
    total_cost = 0

    # Loop through each item in the cart to generate a detailed summary
    for item in cart:
        category = item.get("category", "Unknown")
        suboption = item.get("suboption", "Unknown")
        quantity = item.get("quantity", 0)
        total_price = item.get("total_price", 0)
        unit = PRODUCTS.get(category.lower(), {}).get("unit", "units")
        total_cost += total_price  # Accumulate the total cost
        
        # Check if there's discount information available
        regular_price = item.get("regular_price")
        discount_info = item.get("discount_info", "")
        
        # Add the item details to the summary, with discount if applicable
        if category.lower() == "local" and regular_price:
            summary += (
                f"- {category} ({suboption}): {quantity} {unit}\n"
                f"  Regular Price: ₱{regular_price:,.0f}\n"
                f"  Discounted Price: ₱{total_price:,.0f} {discount_info}\n"
            )
        else:
            summary += f"- {category} ({suboption}): {quantity} {unit} - ₱{total_price:,.0f}\n"

    # Add the total cost to the summary
    summary += f"\n{EMOJI['money']} Total Cost: ₱{total_cost:,.0f}\n"

    return summary, total_cost

def manage_cart(context, action, item=None):
    """
    Manage the user's shopping cart.
    
    Args:
        context: The conversation context
        action (str): Action to perform ('add', 'get', 'clear')
        item (dict, optional): Item to add to cart
        
    Returns:
        list: The current cart after the operation
    """
    if "cart" not in context.user_data:
        context.user_data["cart"] = []
        
    if action == "add" and item:
        context.user_data["cart"].append(item)
    elif action == "clear":
        context.user_data["cart"] = []
        
    return context.user_data["cart"]

def sanitize_input(text, max_length=100):
    """
    Sanitize user input to prevent injection attacks and ensure data quality.
    
    Args:
        text (str): Text to sanitize
        max_length (int): Maximum length to allow
        
    Returns:
        str: Sanitized text
    """
    if not text:
        return ""
        
    # Remove any HTML or unwanted characters - use a more comprehensive pattern
    sanitized = re.sub(r'<[^>]*>|[^\w\s,.!?@:;()\-_\/]', '', text)
    
    # Trim whitespace
    sanitized = sanitized.strip()
    
    # Limit length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
        
    return sanitized

def validate_sensitive_data(data_type, value):
    """
    Validate sensitive user data against specific patterns.
    
    Args:
        data_type (str): Type of data being validated ('name', 'address', 'phone', etc.)
        value (str): Value to validate
        
    Returns:
        tuple: (is_valid, error_message or sanitized_value)
    """
    # First sanitize the input
    value = sanitize_input(value, max_length=200)
    
    if data_type == 'name':
        # Name should only contain letters, spaces, and basic punctuation
        if not re.match(r'^[\w\s.,\'-]{2,50}$', value):
            return False, "Name contains invalid characters or is too short/long."
        return True, value
        
    elif data_type == 'address':
        # Address should have minimum length and contain some numbers and letters
        if len(value) < 10:
            return False, "Address is too short. Please provide a complete address."
        if not (re.search(r'\d', value) and re.search(r'[a-zA-Z]', value)):
            return False, "Address should contain both numbers and letters."
        return True, value
        
    elif data_type == 'phone':
        # Phone number validation - allow different formats but ensure it has enough digits
        # Remove all non-digit characters first
        digits = re.sub(r'\D', '', value)
        if len(digits) < 10 or len(digits) > 15:
            return False, "Phone number should have 10-15 digits."
        # Format the phone number consistently
        formatted = digits
        return True, formatted
        
    elif data_type == 'order_id':
        # Validate order ID format (WW-XXXX-YYY)
        if not re.match(r'^WW-\d{4}-[A-Z]{3}$', value):
            return False, "Invalid order ID format. Should be like WW-1234-ABC."
        return True, value
    
    # Default case
    return True, value

def create_button(button_type, callback_data=None, custom_text=None, url=None):
    """
    Factory function to create common button types with consistent styling.
    
    Args:
        button_type (str): Type of button ('back', 'action', 'status', etc.)
        callback_data (str, optional): Callback data for the button
        custom_text (str, optional): Custom button text
        url (str, optional): URL for link buttons
    
    Returns:
        InlineKeyboardButton: Configured button with appropriate text and callback
    """
    if button_type == "back":
        destination = callback_data.replace("back_to_", "") if callback_data else "previous"
        destination_text = destination.replace("_", " ").title()
        text = f"{EMOJI['back']} Back to {destination_text}" if not custom_text else f"{EMOJI['back']} {custom_text}"
        return InlineKeyboardButton(text, callback_data=callback_data or "back")
        
    elif button_type == "action":
        # Extract emoji key from callback data if possible
        emoji_key = callback_data.split("_")[0] if callback_data and "_" in callback_data else callback_data
        emoji = EMOJI.get(emoji_key, EMOJI.get("info", "ℹ️"))
        text = f"{emoji} {custom_text}" if custom_text else f"{emoji} {callback_data.replace('_', ' ').title()}"
        return InlineKeyboardButton(text, callback_data=callback_data)
        
    elif button_type == "link":
        if not url:
            raise ValueError("URL is required for link buttons")
        emoji = EMOJI.get("link", "🔗")
        text = f"{emoji} {custom_text}" if custom_text else f"{emoji} Link"
        return InlineKeyboardButton(text, url=url)
        
    elif button_type == "cancel":
        text = f"{EMOJI['error']} {custom_text}" if custom_text else f"{EMOJI['error']} Cancel"
        return InlineKeyboardButton(text, callback_data=callback_data or "cancel")
    
    # Default case - generic button
    return InlineKeyboardButton(custom_text or "Button", callback_data=callback_data or "generic")

def create_button_layout(buttons, columns=1):
    """
    Create a standardized button layout with specified number of columns.
    
    Args:
        buttons (list): List of InlineKeyboardButton objects or lists of buttons
        columns (int): Number of buttons per row
    
    Returns:
        InlineKeyboardMarkup: Formatted keyboard markup
    """
    keyboard = []
    
    # If buttons already contains rows (nested lists), use them directly
    if buttons and isinstance(buttons[0], list):
        keyboard = buttons
    else:
        # Create rows based on columns specification
        row = []
        for idx, button in enumerate(buttons):
            row.append(button)
            if (idx + 1) % columns == 0:
                keyboard.append(row)
                row = []
        
        # Add any remaining buttons
        if row:
            keyboard.append(row)
    
    return InlineKeyboardMarkup(keyboard)

def get_navigation_buttons(current_location=None, include_home=True, include_help=True, custom_back=None):
    """
    Get appropriate navigation buttons based on current location.
    
    Args:
        current_location (str, optional): Current conversation location
        include_home (bool): Whether to include main menu button
        include_help (bool): Whether to include help button
        custom_back (tuple, optional): Custom back button (text, callback_data)
    
    Returns:
        list: List of InlineKeyboardButton objects
    """
    buttons = []
    
    # Add context-specific back button
    if custom_back:
        buttons.append(InlineKeyboardButton(
            f"{EMOJI['back']} {custom_back[0]}", 
            callback_data=custom_back[1]
        ))
    elif current_location:
        # Standard back buttons based on location
        if "product_" in current_location:
            buttons.append(create_button("back", "back_to_browse", "Back to Browse"))
        elif current_location == "strain_selection":
            buttons.append(create_button("back", "back_to_categories", "Back to Categories"))
        elif current_location == "browse_carts_by":
            buttons.append(create_button("back", "back_to_categories", "Back to Categories"))
        elif current_location == "admin_orders":
            buttons.append(create_button("back", "back_to_admin", "Back to Admin Panel"))
    
    # Add home button if requested
    if include_home:
        buttons.append(InlineKeyboardButton(f"{EMOJI['home']} Main Menu", callback_data="start"))
    
    # Add help button if requested
    if include_help:
        buttons.append(InlineKeyboardButton(f"{EMOJI['help']} Help", callback_data="get_help"))
    
    return buttons

def get_common_buttons(button_type, context_data=None):
    """
    Get common button groups used throughout the application.
    
    Args:
        button_type (str): Type of button group ('order_actions', 'confirm_cancel', etc.)
        context_data (dict, optional): Additional context data for customizing buttons
    
    Returns:
        list: List of InlineKeyboardButton objects or rows
    """
    if button_type == "confirm_cancel":
        # Confirm and cancel buttons
        return [
            [create_button("action", "confirm", "Confirm")],
            [create_button("cancel", "cancel", "Cancel")]
        ]
    
    elif button_type == "order_actions":
        # Order action buttons
        return [
            [create_button("action", "add_more", "Add More", f"{EMOJI['cart']} Add More")],
            [create_button("action", "proceed", "Proceed to Checkout", f"{EMOJI['shipping']} Proceed to Checkout")],
            [create_button("cancel", "cancel", "Cancel Order")]
        ]
    
    elif button_type == "restart_home":
        # Restart and home buttons
        return [
            [create_button("action", "restart_conversation", "Reset Session", f"{EMOJI['restart']} Reset Session")],
            [create_button("action", "start", "Main Menu", f"{EMOJI['home']} Main Menu")]
        ]
    
    elif button_type == "strain_buttons":
        # Strain selection buttons
        return [
            [InlineKeyboardButton("🌿 Indica", callback_data="indica")],
            [InlineKeyboardButton("🌱 Sativa", callback_data="sativa")],
            [InlineKeyboardButton("🍃 Hybrid", callback_data="hybrid")],
            [create_button("back", "back_to_categories", "Back to Categories")]
        ]
    
    # Default empty button list
    return []

def convert_gdrive_url_to_direct_link(url):
    """
    Convert a Google Drive sharing URL to a direct download link suitable for images.
    
    Args:
        url (str): Google Drive URL (e.g., https://drive.google.com/file/d/FILE_ID/view?usp=sharing)
        
    Returns:
        str: Direct download URL or the original URL if conversion fails
    """
    try:
        # Check if it's a Google Drive URL
        if "drive.google.com" in url and "/file/d/" in url:
            # Extract the file ID
            file_id = url.split("/file/d/")[1].split("/")[0]
            # Create direct download link
            return f"https://drive.google.com/uc?export=download&id={file_id}"
        return url
    except Exception:
        # Return original URL if any error occurs
        return url

def validate_quantity(text, category=None):
    """
    Validate quantity input from user.
    
    Args:
        text (str): Quantity text input
        category (str, optional): Product category
        
    Returns:
        tuple: (is_valid, result_or_error_message)
    """
    # Check if input is a number
    match = re.search(REGEX["quantity"], text)
    if not match:
        return False, "Please enter a number."
    
    quantity = int(match.group(1))
    
    # Basic validation
    if quantity <= 0:
        return False, "Please enter a positive number."
        
    # Category-specific validation
    if category == "local":
        # Only allow specific quantities
        valid_quantities = [10, 50, 100, 300]
        if quantity not in valid_quantities:
            return False, "For Local (BG), please select one of the available options: 10g, 50g, 100g, or 300g."
    
    # Product-specific validation
    if category and category in PRODUCTS:
        min_order = PRODUCTS[category].get("min_order", 1)
        unit = PRODUCTS[category].get("unit", "units")
        
        if quantity < min_order:
            return False, f"Minimum order for {PRODUCTS[category]['name']} is {min_order} {unit}."
    
    return True, quantity

def validate_shipping_details(text):
    """
    Validate shipping details format with enhanced flexibility and security.
    
    Args:
        text (str): Shipping details text in format "Name / Address / Contact"
        
    Returns:
        tuple: (is_valid, result_dict_or_error_message)
    """
    # Log the input for debugging without exposing full details
    logging.debug(f"Validating shipping details (length: {len(text)})")
    
    # Basic format check - need two slashes to have three parts
    if text.count('/') != 2:
        return False, "Invalid format. Need exactly two '/' separators. Format: Name / Address / Contact"
    
    # Split the text by slashes and trim whitespace
    parts = [part.strip() for part in text.split('/')]
    
    # Ensure we have three parts
    if len(parts) != 3:
        return False, "Invalid format. Use: Name / Address / Contact"
        
    name, address, contact = parts
    
    # Validate each part using our enhanced validators
    name_valid, name_result = validate_sensitive_data('name', name)
    if not name_valid:
        return False, f"Name validation failed: {name_result}"
    
    address_valid, address_result = validate_sensitive_data('address', address)
    if not address_valid:
        return False, f"Address validation failed: {address_result}"
    
    phone_valid, phone_result = validate_sensitive_data('phone', contact)
    if not phone_valid:
        return False, f"Contact number validation failed: {phone_result}"
    
    # Success - return the validated details
    return True, {
        "name": name_result,
        "address": address_result,
        "contact": phone_result
    }

class EnhancedCache:
    """
    Enhanced caching system with dynamic TTL and LRU eviction.
    """
    
    def __init__(self, max_items=100):
        """
        Initialize the enhanced cache.
        
        Args:
            max_items (int): Maximum number of items to cache
        """
        self.cache = {}
        self.access_order = deque(maxlen=max_items)
        self.hits = 0
        self.misses = 0
        self.max_items = max_items
        self.default_ttl = 60  # Default TTL is 60 seconds
    
    def get(self, key, default_ttl=None):
        """
        Get a value from cache with freshness check.
        
        Args:
            key (str): Cache key
            default_ttl (int, optional): TTL to use if not specified in item
            
        Returns:
            tuple: (is_hit, cached_value)
        """
        if key not in self.cache:
            self.misses += 1
            return False, None
        
        # Get the cache entry
        entry = self.cache[key]
        now = time.time()
        ttl = entry.get("ttl", default_ttl or self.default_ttl)
        
        # Check if expired
        if now - entry.get("timestamp", 0) > ttl:
            # Remove the expired entry
            self._remove_entry(key)
            self.misses += 1
            return False, None
        
        # Update access order (LRU behavior)
        self._update_access_order(key)
        
        # Record the hit
        self.hits += 1
        return True, entry.get("data")
    
    def set(self, key, value, ttl=None):
        """
        Set a value in cache with specified TTL.
        
        Args:
            key (str): Cache key
            value: Value to cache
            ttl (int, optional): Time-to-live in seconds
            
        Returns:
            value: The cached value
        """
        # If cache is full, evict least recently used item
        if len(self.cache) >= self.max_items and key not in self.cache:
            self._evict_lru()
        
        # Store the value
        self.cache[key] = {
            "data": value,
            "timestamp": time.time(),
            "ttl": ttl or self.default_ttl
        }
        
        # Update access order
        self._update_access_order(key)
        
        return value
    
    def _update_access_order(self, key):
        """Update the access order for LRU tracking."""
        # Remove key if it exists and add it to the end (most recently used)
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)
    
    def _remove_entry(self, key):
        """Remove a cache entry."""
        if key in self.cache:
            del self.cache[key]
        if key in self.access_order:
            self.access_order.remove(key)
    
    def _evict_lru(self):
        """Evict the least recently used cache entry."""
        if self.access_order:
            lru_key = self.access_order[0]
            self._remove_entry(lru_key)
    
    def clear(self):
        """Clear the entire cache."""
        self.cache.clear()
        self.access_order.clear()
    
    def get_stats(self):
        """Get cache statistics."""
        total_requests = self.hits + self.misses
        hit_ratio = 0 if total_requests == 0 else (self.hits / total_requests)
        
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_ratio": hit_ratio,
            "total_requests": total_requests,
            "items": len(self.cache),
            "max_items": self.max_items
        }
    
    def clear(self, key=None):
        """
        Clear a specific key or the entire cache.
        
        Args:
            key (str, optional): Specific key to clear, or None to clear all
        """
        if key:
            if key in self.cache:
                del self.cache[key]
                if key in self.access_order:
                    self.access_order.remove(key)
        else:
            self.cache.clear()
            self.access_order.clear()

class RetryableOperation:
    """
    A class to encapsulate retryable async operations with advanced error handling.
    """
    
    def __init__(self, loggers, max_retries=3, base_delay=1.0, 
                 retry_on=(ConnectionError, TimeoutError), jitter=True):
        """
        Initialize a retryable operation.
        
        Args:
            loggers (dict): Dictionary of logger instances
            max_retries (int): Maximum number of retry attempts
            base_delay (float): Base delay between retries in seconds
            retry_on (tuple): Exceptions that should trigger a retry
            jitter (bool): Whether to add randomness to retry delays
        """
        self.loggers = loggers
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.retry_on = retry_on
        self.use_jitter = jitter
    
    async def run(self, operation_func, operation_name=None, *args, **kwargs):
        """
        Execute an async operation with retry logic.
        
        Args:
            operation_func (callable): Async function to execute
            operation_name (str, optional): Name for logging purposes
            *args: Arguments to pass to operation_func
            **kwargs: Keyword arguments to pass to operation_func
            
        Returns:
            Any: Result from the successful operation
            
        Raises:
            Exception: The last exception if all retries fail
        """
        if not operation_name:
            operation_name = getattr(operation_func, "__name__", "unknown_operation")
        
        retry_count = 0
        last_exception = None
        
        while retry_count <= self.max_retries:
            try:
                # Attempt the operation
                result = await operation_func(*args, **kwargs)
                return result
                
            except self.retry_on as e:
                # This is a retryable error
                retry_count += 1
                last_exception = e
                
                if retry_count > self.max_retries:
                    self.loggers["errors"].error(
                        f"Operation '{operation_name}' failed after {retry_count} attempts: {e}"
                    )
                    break
                
                # Calculate delay with exponential backoff
                delay = min(self.base_delay * (2 ** (retry_count - 1)), 60)  # Cap at 60 seconds
                
                # Add jitter if enabled (helps prevent thundering herd problem)
                if self.use_jitter:
                    jitter_amount = random.uniform(0, 0.5 * delay)
                    delay += jitter_amount
                
                self.loggers["main"].warning(
                    f"Operation '{operation_name}' attempt {retry_count}/{self.max_retries} "
                    f"failed: {e}. Retrying in {delay:.2f} seconds."
                )
                await asyncio.sleep(delay)
                
            except Exception as e:
                # Non-retryable error
                self.loggers["errors"].error(
                    f"Non-retryable error in operation '{operation_name}': {type(e).__name__}: {e}"
                )
                raise
        
        # If we get here, all retries failed
        raise last_exception or RuntimeError(f"Operation '{operation_name}' failed for unknown reasons")
    

def check_rate_limit(context, user_id, action_type):
    """
    Check if user has exceeded rate limits.
    
    Args:
        context: The conversation context
        user_id (int): User's Telegram ID
        action_type (str): Type of action being rate limited
        
    Returns:
        bool: True if within limits, False if exceeded
    """
    if "rate_limits" not in context.bot_data:
        context.bot_data["rate_limits"] = {}
        
    key = f"{user_id}:{action_type}"
    now = time.time()
    
    if key not in context.bot_data["rate_limits"]:
        context.bot_data["rate_limits"][key] = {"count": 1, "first_action": now}
        return True
        
    data = context.bot_data["rate_limits"][key]
    
    # Reset counter if more than 1 hour has passed
    if now - data["first_action"] > 3600:
        data["count"] = 1
        data["first_action"] = now
        return True
        
    # Get limit for this action type
    max_actions = RATE_LIMITS.get(action_type, 20)  # Default limit
    
    # Increment and check
    data["count"] += 1
    return data["count"] <= max_actions

def get_user_session(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> Dict[str, Any]:
    """
    Get or create a user session.
    
    Args:
        context: The conversation context
        user_id: User's Telegram ID
        
    Returns:
        Dict[str, Any]: User session data
    """
    if "sessions" not in context.bot_data:
        context.bot_data["sessions"] = {}
        
    if user_id not in context.bot_data["sessions"]:
        context.bot_data["sessions"][user_id] = {
            "last_activity": time.time(),
            "order_count": 0,
            "total_spent": 0,
            "preferences": {}
        }
        
    # Update last activity time
    context.bot_data["sessions"][user_id]["last_activity"] = time.time()
    
    # Check user data size and trim if necessary
    if hasattr(context, "user_data") and user_id in context.user_data:
        trim_large_data_structures(context.user_data[user_id], loggers)
    
    return context.bot_data["sessions"][user_id]

def cleanup_old_sessions(context):
    """
    Clean up old or inactive user sessions to prevent memory leaks.
    
    Args:
        context: The conversation context
        
    Returns:
        int: Number of sessions cleaned up
    """
    if "sessions" not in context.bot_data:
        return 0
    
    now = time.time()
    cleanup_count = 0
    sessions_to_remove = []
    
    # Find old sessions
    for user_id, session in context.bot_data["sessions"].items():
        # Check if session is older than 7 days
        if now - session.get("last_activity", now) > 604800:  # 7 days in seconds
            sessions_to_remove.append(user_id)
    
    # Remove old sessions
    for user_id in sessions_to_remove:
        del context.bot_data["sessions"][user_id]
        cleanup_count += 1
    
    return cleanup_count

async def cleanup_abandoned_carts(context, order_manager, loggers):
    """
    Find and clean up abandoned carts (incomplete orders).
    """
    if not hasattr(context, "user_data") or not context.user_data:
        return 0
    
    now = time.time()
    cleanup_count = 0
    user_ids_with_abandoned_carts = []
    
    # Find users with abandoned carts (active over 3 hours)
    for user_id in context.user_data:
        user_data = context.user_data[user_id]
        # Skip users that don't have cart data
        if "cart" not in user_data:
            continue
        
        # Skip empty carts
        if not user_data["cart"]:
            continue
        
        # Get the last activity time
        last_activity = user_data.get("last_activity_time", now)
        
        # If inactive for more than 3 hours, consider it abandoned
        if now - last_activity > 10800:  # 3 hours in seconds
            user_ids_with_abandoned_carts.append(user_id)
    
    # Process abandoned carts
    for user_id in user_ids_with_abandoned_carts:
        try:
            # Get cart content for logging
            cart = context.user_data[user_id].get("cart", [])
            cart_size = len(cart)
            
            # Clear the cart
            context.user_data[user_id]["cart"] = []
            
            # Log the cleanup
            loggers["main"].info(f"Cleaned up abandoned cart for user {user_id}: {cart_size} items")
            
            cleanup_count += 1
        except Exception as e:
            loggers["errors"].error(f"Error cleaning up cart for user {user_id}: {e}")
    
    return cleanup_count

def get_persistence_file_size():
    """
    Get the size of the persistence file in megabytes.
    
    Returns:
        float: Size of the persistence file in MB, or 0 if file doesn't exist
    """
    try:
        # Check if the file exists
        if not os.path.exists("bot_persistence"):
            return 0
            
        # Get file size in bytes and convert to MB
        size_in_bytes = os.path.getsize("bot_persistence")
        size_in_mb = size_in_bytes / (1024 * 1024)
        
        return size_in_mb
    except Exception:
        # If there's an error, return 0
        return 0

def check_context_data_size(user_data, key, max_size_kb=512):
    """
    Check if a data structure in user_data is getting too large and should be trimmed.
    
    Args:
        user_data (dict): User data dictionary
        key (str): Key of the data structure to check
        max_size_kb (int): Maximum size in kilobytes
        
    Returns:
        bool: True if data is too large, False otherwise
    """
    if key not in user_data:
        return False
    
    try:
        # Estimate size by pickling
        data_size = len(pickle.dumps(user_data[key])) / 1024  # size in KB
        
        return data_size > max_size_kb
    except Exception:
        # If there's an error in size calculation, assume it's not too large
        return False

def trim_large_data_structures(user_data, loggers):
    """
    Monitor and trim large data structures in user_data to prevent memory issues.
    
    Args:
        user_data (dict): User data dictionary
        loggers (dict): Dictionary of logger instances
        
    Returns:
        int: Number of items trimmed
    """
    trim_count = 0
    
    # Check and trim oversized message history
    if check_context_data_size(user_data, "message_history", max_size_kb=256):
        # If present and too large, keep only the 20 most recent messages
        if isinstance(user_data["message_history"], list):
            user_data["message_history"] = user_data["message_history"][-20:]
            trim_count += 1
            loggers["main"].info("Trimmed large message history to last 20 messages")
    
    # Check and clean up any large cached data
    for key in list(user_data.keys()):
        if key.startswith("cached_") and check_context_data_size(user_data, key, max_size_kb=128):
            # Remove oversized cache entries
            del user_data[key]
            trim_count += 1
            loggers["main"].info(f"Removed oversized cached data: {key}")
    
    return trim_count

def cleanup_persistence_file(context, loggers):
    """
    Create a backup of the persistence file and rebuild it with only essential data.
    This helps prevent the pickle file from growing too large over time.
    
    Args:
        context: The conversation context
        loggers: Dictionary of logger instances
        
    Returns:
        tuple: (success, old_size, new_size)
    """
    try:
        # Check current file size
        current_size = get_persistence_file_size()
        
        # If file is smaller than 10MB, no need to clean up
        if current_size < 10:
            return True, current_size, current_size
        
        # Create a backup with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"bot_persistence_backup_{timestamp}"
        
        # Copy the file
        if os.path.exists("bot_persistence"):
            shutil.copy2("bot_persistence", backup_filename)
            loggers["main"].info(f"Created persistence backup: {backup_filename}")
        
        # Clean up the context data before saving
        # Note: We don't modify context directly, as that would change the running state
        
        # We need to manually write a new persistence file with cleaned data
        # This approach keeps the running context intact but creates a cleaner file
        
        # First, create a clean copy of essential data
        essential_data = {
            "user_data": {},
            "chat_data": {},
            "bot_data": {
                "start_time": context.bot_data.get("start_time", time.time()),
                "sessions": context.bot_data.get("sessions", {})
            },
            "callback_data": context.bot_data.get("callback_data", {})
        }
        
        # Copy only active user data (last 30 days)
        now = time.time()
        for user_id, user_data in context.user_data.items():
            last_activity = user_data.get("last_activity_time", 0)
            
            # If active in the last 30 days, keep their data
            if now - last_activity < 2592000:  # 30 days in seconds
                # Scrub sensitive data before persistence
                scrubbed_data = scrub_sensitive_data(user_data)
                essential_data["user_data"][user_id] = scrubbed_data
        
        # Use pickle to save the essential data
        with open("bot_persistence_clean", "wb") as f:
            pickle.dump(essential_data, f)
        
        # Get the new file size
        new_size = os.path.getsize("bot_persistence_clean") / (1024 * 1024)
        
        # Rename the clean file to replace the original
        try:
            if os.path.exists("bot_persistence_clean"):
                # On Windows, we need to make sure the target doesn't exist
                if os.path.exists("bot_persistence"):
                    os.remove("bot_persistence")
                os.rename("bot_persistence_clean", "bot_persistence")
        except Exception as e:
            loggers["errors"].error(f"Error replacing persistence file: {e}")
            return False, current_size, current_size
        
    except Exception as e:
        loggers["errors"].error(f"Error cleaning up persistence file: {e}")
        return False, current_size, current_size
    
def scrub_sensitive_data(data_dict):
    """
    Recursively remove sensitive data from dictionaries before persistence.
    
    Args:
        data_dict (dict): Dictionary to scrub
        
    Returns:
        dict: Scrubbed dictionary
    """
    if not isinstance(data_dict, dict):
        return data_dict
    
    scrubbed_dict = {}
    
    for key, value in data_dict.items():
        # Skip sensitive keys entirely
        if key in ['password', 'credit_card', 'token', 'secret']:
            continue
        
        # Recursively scrub nested dictionaries
        if isinstance(value, dict):
            scrubbed_dict[key] = scrub_sensitive_data(value)
        # Scrub sensitive data in lists
        elif isinstance(value, list):
            scrubbed_dict[key] = [
                scrub_sensitive_data(item) if isinstance(item, dict) else item
                for item in value
            ]
        # Special handling for potentially sensitive fields
        elif isinstance(value, str) and key in ['address', 'contact', 'phone', 'email']:
            # Don't actually store the sensitive data in persistence
            scrubbed_dict[key] = f"{value[:3]}***(masked for security)"
        else:
            scrubbed_dict[key] = value
    
    return scrubbed_dict

def generate_order_id():
    """
    Generate a short, unique order ID.
    Format: WW-[last 4 digits of timestamp]-[3 random letters]
    
    Returns:
        str: Unique order ID
    """
    timestamp = int(time.time())
    last_4_digits = str(timestamp)[-4:]
    # Excluding confusing letters I, O
    random_letters = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ', k=3))
    return f"WW-{last_4_digits}-{random_letters}"

def get_status_message(status_key, tracking_link=None):
    """
    Get a formatted status message based on status key.
    
    Args:
        status_key (str): Status key
        tracking_link (str, optional): Tracking link if available
        
    Returns:
        tuple: (emoji, formatted_message)
    """
    # Convert from Google Sheet format to status dictionary key if needed
    status_key = status_key.lower().replace(' ', '_')
    
    # Handle special case for payment confirmed (different format in sheet vs dict)
    if "payment_confirmed" in status_key:
        status_key = "payment_confirmed"
    
    # Get status info from dictionary, or use fallback
    status_info = STATUS.get(status_key, {
        "label": status_key.replace('_', ' ').title(),
        "description": f"Your order is currently marked as: {status_key.replace('_', ' ').title()}",
        "emoji": EMOJI.get("info")
    })
    
    emoji = status_info.get("emoji", EMOJI.get("info"))
    description = status_info.get("description", "")
    
    # Handle tracking link for booked status
    if status_key == "booked" and tracking_link:
        description = status_info.get("with_tracking", description)
        
    return emoji, description

async def retry_operation(operation, operation_name=None, max_retries=3):
    """
    Retry an async operation with exponential backoff.
    
    This function is a simpler wrapper around RetryableOperation for backward
    compatibility with existing code.
    
    Args:
        operation (callable): Async function to retry
        operation_name (str, optional): Name of operation for logging
        max_retries (int): Maximum number of retry attempts
        
    Returns:
        Any: Result from the operation
        
    Raises:
        Exception: The last exception encountered after all retries
    """
    retry_handler = RetryableOperation(
        loggers, 
        max_retries=max_retries,
        retry_on=(ConnectionError, TimeoutError, BrokenPipeError, NetworkError)
    )
    
    return await retry_handler.run(operation, operation_name)

# ---------------------------- Inventory Management ----------------------------
class InventoryManager:
    """
    Manage product inventory with caching and efficient access patterns.
    """
    
    def __init__(self, google_apis: Any, loggers: Dict[str, logging.Logger]) -> None:
        """
        Initialize the inventory manager.
        
        Args:
            google_apis: Google APIs manager instance
            loggers: Dictionary of logger instances
        """
        self.google_apis = google_apis
        self.loggers = loggers
        self._inventory_cache: Dict[str, Any] = {}
        self._last_refresh: float = 0
        self._cache_ttl: int = 300  # 5 minutes
        
    async def get_inventory(self, force_refresh: bool = False) -> Tuple[Dict[str, List[Dict]], Dict[str, List[Dict]], List[Dict]]:
        """
        Get product inventory data with caching.
        
        Args:
            force_refresh: Force refresh the cache regardless of age
            
        Returns:
            tuple: (products_by_tag, products_by_strain, all_products)
        """
        now = time.time()
        
        # Check if we need to refresh the cache
        if force_refresh or not self._inventory_cache or now - self._last_refresh > self._cache_ttl:
            # Fetch fresh inventory data
            products_by_tag, products_by_strain, all_products = await self.google_apis.fetch_inventory()
            
            # Update cache
            self._inventory_cache = {
                "products_by_tag": products_by_tag,
                "products_by_strain": products_by_strain,
                "all_products": all_products
            }
            self._last_refresh = now
            
        # Return cached data
        return (
            self._inventory_cache.get("products_by_tag", {}),
            self._inventory_cache.get("products_by_strain", {}),
            self._inventory_cache.get("all_products", [])
        )
        
    async def get_inventory_safe(self, force_refresh=False):
        """
        Get inventory data with graceful degradation if API fails.
    
        Args:
            force_refresh (bool): Force refresh the cache regardless of age
        
        Returns:
            tuple: (products_by_tag, products_by_strain, all_products)
        """
        try:
            # First attempt - normal get_inventory with caching
            return await self.get_inventory(force_refresh)
        
        except Exception as primary_error:
            # Log the primary error
            self.loggers["errors"].error(f"Primary inventory fetch failed: {primary_error}")
        
            try:
                # Second attempt - try with default settings and no force refresh
                if force_refresh:
                    self.loggers["main"].warning("Retrying inventory fetch without force refresh")
                    # Call get_inventory directly, not get_inventory_safe to avoid recursion
                    return await self.get_inventory(False)
            
                # If we're already using cached data or defaults, raise the original error
                raise primary_error
            
            except Exception as secondary_error:
                # Log the secondary error
                self.loggers["errors"].error(f"Secondary inventory fetch failed: {secondary_error}")
                
                # Final fallback - create a minimal default inventory that won't crash the app
                self.loggers["main"].warning("Using emergency minimal inventory")
                
                # Create minimal defaults for critical categories
                products_by_tag = {'buds': [], 'local': [], 'carts': [], 'edibs': []}
                products_by_strain = {'indica': [], 'sativa': [], 'hybrid': []}
                
                # Include at least one product per category to keep the app functional
                default_product = {
                    'name': 'Default Product',
                    'key': 'default_product',
                    'price': 1000,
                    'stock': 1,
                    'tag': 'buds',
                    'strain': 'hybrid',
                }
                
                # Add the default product to each category
                for tag in products_by_tag:
                    product_copy = default_product.copy()
                    product_copy['tag'] = tag
                    products_by_tag[tag].append(product_copy)
                
                for strain in products_by_strain:
                    product_copy = default_product.copy()
                    product_copy['strain'] = strain
                    products_by_strain[strain].append(product_copy)
                
                all_products = [default_product]
                
                return products_by_tag, products_by_strain, all_products
    
    async def category_has_products(self, category):
        """
        Check if a category has any products in stock.
        Enhanced with better error handling and graceful degradation.

        Args:
            category (str): Product category key
        
        Returns:
            bool: True if category has products in stock, False otherwise
        """
        try:
            if category not in PRODUCTS:
                return False
            
            tag = PRODUCTS[category].get("tag")
            if not tag:
                return False
            
            # Use the safe inventory method
            products_by_tag, _, _ = await self.get_inventory_safe()
        
            # Get products for this category
            category_products = products_by_tag.get(tag, [])
            has_products = len(category_products) > 0
            
            # Log what we found
            print(f"DEBUG: Category '{category}' (tag: {tag}) has {len(category_products)} products available")
            
            return has_products
        
        except Exception as e:
            # Log the error
            self.loggers["errors"].error(f"Error checking products for {category}: {str(e)}")
            print(f"DEBUG ERROR in category_has_products: {str(e)}")
        
            # Return True as a fallback to avoid breaking the flow
            return True
    
    async def calculate_price(self, category, product_key, quantity):
        """
        Calculate price for a product based on category and quantity.
        Handles special pricing for local products with discounts.
        
        Args:
            category (str): Product category
            product_key (str): Product key 
            quantity (int): Quantity
            
        Returns:
            tuple: (total_price, unit_price) or (total_price, unit_price, regular_price, discount_info)
        """
        # Get category info
        if category not in PRODUCTS:
            return 0, 0
            
        product = PRODUCTS[category]
        
        # Handle Local (BG)
        if category == "local":
            # Ensure minimum order
            adjusted_quantity = max(quantity, product["min_order"])
            # Find product by key
            _, _, all_products = await self.get_inventory()
            selected_product = None
            for p in all_products:
                if p.get("key") == product_key:
                    selected_product = p
                    break
                    
            if not selected_product:
                return 0, 0
                
            unit_price = selected_product.get("price", 0)
            
            # Calculate based on multiples of 10
            price_factor = adjusted_quantity / product["min_order"]
            regular_price = unit_price * price_factor
            
            # Apply discounts for specific quantities with fixed prices
            if adjusted_quantity == 50:
                # No discount for 50g
                total_price = 5000
                return total_price, unit_price
            elif adjusted_quantity == 100:
                # 20% discount for 100g
                total_price = 8000
                discount_info = f"(Save ₱{regular_price - total_price:,.0f})"
                return total_price, unit_price, regular_price, discount_info
            elif adjusted_quantity == 300:
                # 20% discount for 300g
                total_price = 24000
                discount_info = f"(Save ₱{regular_price - total_price:,.0f} + Free Shipping)"
                return total_price, unit_price, regular_price, discount_info
            else:
                # No discount for other quantities
                total_price = regular_price
                return total_price, unit_price
        
        # For other products, get price directly from inventory
        _, _, all_products = await self.get_inventory()
        selected_product = None
        for p in all_products:
            if p.get("key") == product_key:
                selected_product = p
                break
                
        if not selected_product:
            return 0, 0
            
        unit_price = selected_product.get("price", 0)
        total_price = unit_price * quantity
        return total_price, unit_price

# ---------------------------- Order Management ----------------------------
class OrderManager:
    """Manages order operations and persistence."""
    
    def __init__(self, google_apis, loggers):
        """
        Initialize the order manager.
        
        Args:
            google_apis: GoogleAPIsManager instance
            loggers: Dictionary of logger instances
        """
        self.google_apis = google_apis
        self.loggers = loggers
        
    async def create_order(self, context, user_data, payment_url=None):
        """
        Create a new order in the system.
        
        Args:
            context: The conversation context
            user_data: Dictionary containing user and order information
            payment_url: URL to payment screenshot
            
        Returns:
            tuple: (order_id, success_status)
        """
        # Send a message indicating the order is being processed
        status_message = None
        try:
            status_message = await context.bot.send_message(
                chat_id=user_data.get("telegram_id"),
                text=f"{EMOJI['info']} Processing your order... Please wait a moment."
            )
        except Exception as msg_err:
            # Continue even if we can't send this message
            self.loggers["errors"].error(f"Failed to send processing message: {str(msg_err)}")
            pass
            
        try:
            # Generate order ID
            order_id = generate_order_id()
            
            # Get current timestamp
            current_date = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            
            # Get user details
            name = user_data.get("name", "Unknown")
            address = user_data.get("address", "Unknown")
            contact = user_data.get("contact", "Unknown")
            telegram_id = user_data.get("telegram_id", 0)
            
            # Get cart items
            cart = user_data.get("cart", [])
            total_price = sum(item.get("total_price", 0) for item in cart)
            
            # Verify we have required data
            if not cart:
                self.loggers["errors"].error(f"Attempted to create order with empty cart for user {telegram_id}")
                
                # Update status message if it was sent
                if status_message:
                    try:
                        await status_message.edit_text(f"{EMOJI['error']} Error: Your cart is empty. Please add items before ordering.")
                    except Exception:
                        pass
                        
                return None, False
            
            if not telegram_id or telegram_id == 0:
                self.loggers["errors"].error(f"Missing telegram_id for order with name: {name}")
                
                # Update status message if it was sent
                if status_message:
                    try:
                        await status_message.edit_text(f"{EMOJI['error']} Error: Missing user identification. Please restart the ordering process.")
                    except Exception:
                        pass
                        
                return None, False
            
            # Format cart items in a single cell with bullet points
            cart_summary = ""
            for idx, item in enumerate(cart, 1):
                product = item.get("suboption", "Unknown")
                category = item.get("category", "Unknown")
                quantity = item.get("quantity", 0)
                unit = item.get("unit", "gram/s")
                item_price = item.get("total_price", 0)
                
                # Add each item with bullet points
                cart_summary += f"• {quantity}x {category} ({product}): {unit} ₱{item_price:,.2f}\n"
            
            # Debug logging
            self.loggers["main"].info(f"Creating order with ID {order_id} for user {telegram_id}")
            print(f"DEBUG ORDER: Creating order {order_id} for user {telegram_id} with {len(cart)} items")
            
            # Create order data row
            order_data = [
                order_id,                    # Order ID
                telegram_id,                 # Telegram ID
                name,                        # Name
                address,                     # Address
                contact,                     # Contact
                "COMPLETE ORDER",            # Product (marks this as main order)
                len(cart),                   # Quantity (number of items)
                f"₱{total_price:,.2f}",      # Price
                STATUS["pending_payment"]["label"], # Initial status
                payment_url or "",           # Payment URL
                current_date,                # Order date
                cart_summary.strip()         # Notes (cart summary)
            ]
            
            # Check data validity
            if not all([order_id, name, address, contact, cart_summary]):
                self.loggers["errors"].error(f"Invalid order data for user {telegram_id}")
                return None, False
            
            # Update status message with progress
            if status_message:
                try:
                    await status_message.edit_text(f"{EMOJI['info']} Saving your order... Almost done!")
                except Exception:
                    pass
            
            # Add to Google Sheet with enhanced error handling
            try:
                # First ensure the sheets are initialized
                sheet, _ = await self.google_apis.initialize_sheets()
                if not sheet:
                    self.loggers["errors"].error(f"Sheets not initialized for order {order_id}")
                    return None, False
                    
                # Add the order with retries
                success = await self.google_apis.add_order_to_sheet(order_data)
                
                if not success:
                    self.loggers["errors"].error(f"Failed to add order {order_id} to sheet")
                    return None, False
                    
            except Exception as sheet_error:
                self.loggers["errors"].error(f"Error adding order to sheet: {str(sheet_error)}")
                return None, False
            
            # Update user session data - if this is causing errors, handle it robustly
            try:
                user_session = get_user_session(context, telegram_id)
                user_session["order_count"] = user_session.get("order_count", 0) + 1
                user_session["total_spent"] = user_session.get("total_spent", 0) + total_price
                user_session["last_order_id"] = order_id
            except Exception as session_err:
                # Just log it but continue with the order
                self.loggers["errors"].error(f"Failed to update user session: {str(session_err)}")
            
            # Log the successful order creation
            self.loggers["orders"].info(
                f"Order {order_id} created for {name} ({telegram_id}) | "
                f"Items: {len(cart)} | Total: ₱{total_price:,.2f}"
            )
            
            # Delete the status message now that we're done
            if status_message:
                try:
                    await status_message.delete()
                except Exception:
                    pass
                    
            return order_id, True
            
        except Exception as e:
            # Detailed error logging
            self.loggers["errors"].error(f"Exception creating order for user {user_data.get('telegram_id', 'Unknown')}: {str(e)}")
            self.loggers["errors"].error(f"Exception type: {type(e).__name__}")
            
            # Update status message with error
            if status_message:
                try:
                    await status_message.edit_text(f"{EMOJI['error']} Failed to process your order. Please try again later.")
                except Exception:
                    pass
                    
            return None, False


    async def update_order_status(self, context, order_id, new_status, tracking_link=None):
        """
        Update an order's status and notify the customer.
        
        Args:
            context: The conversation context
            order_id (str): Order ID to update
            new_status (str): New status to set
            tracking_link (str, optional): Tracking link to add
            
        Returns:
            bool: Success status
        """
        # Update in Google Sheet
        success, customer_id = await self.google_apis.update_order_status(
            order_id, new_status, tracking_link
        )
        
        if success and customer_id:
            try:
                # Get status message components based on status key
                status_key = new_status.lower().replace(' ', '_')
                
                # Special case for payment confirmed
                if "payment_confirmed" in status_key:
                    status_key = "payment_confirmed"
                
                # Get status info from status dictionary
                status_info = STATUS.get(status_key, {})
                emoji = status_info.get("emoji", EMOJI["info"])
                message = status_info.get("description", f"Your order status has been updated to: {new_status}")
                
                # For booked status with tracking
                if status_key == "booked" and tracking_link:
                    message = status_info.get("with_tracking", message)
                    
                # Construct notification message
                notification = (
                    f"{EMOJI['attention']} Order Update for {order_id}\n\n"
                    f"{emoji} {new_status}\n\n"
                    f"{message}"
                )
                
                # Add tracking link if available
                if tracking_link and status_key == "booked":
                    notification += f"\n\n{EMOJI['tracking']} Track your delivery: {tracking_link}"
                
                # Send notification to customer
                await context.bot.send_message(
                    chat_id=customer_id,
                    text=notification
                )
                
                # Log the successful status update
                self.loggers["orders"].info(
                    f"Order {order_id} status updated to '{new_status}' | "
                    f"Customer {customer_id} notified"
                )
                
                return True
                
            except Exception as e:
                self.loggers["errors"].error(f"Failed to notify customer for order {order_id}: {e}")
                # Still consider it success as the sheet was updated
                return True
        
        # Log failed update
        if not success:
            self.loggers["errors"].error(f"Failed to update status for order {order_id}")
        
        return success
    
    async def get_order_details(self, order_id):
        """
        Get details for a specific order.
        
        Args:
            order_id (str): Order ID to look up
            
        Returns:
            dict: Order details or None if not found
        """
        return await self.google_apis.get_order_details(order_id)
        
    async def get_order_status(self, order_id):
        """
        Get the current status of an order.
        
        Args:
            order_id (str): Order ID to check
            
        Returns:
            tuple: (status, tracking_link, order_details) or (None, None, None) if not found
        """
        order_details = await self.get_order_details(order_id)
        
        if not order_details:
            return None, None, None
            
        status = order_details.get(SHEET_COLUMNS["status"], "Unknown")
        tracking_link = order_details.get(SHEET_COLUMNS["tracking_link"], "")
        
        return status, tracking_link, order_details
    
# ---------------------------- Order Handlers ----------------------------

# ==========================================================================
# CONVERSATION HANDLERS
# ==========================================================================
# The following functions handle the conversation flow for the bot.
# Each function corresponds to a state in the conversation FSM.
# 
# General handler pattern:
# 1. Extract information from user input
# 2. Validate input and handle errors
# 3. Update user data/state
# 4. Respond to user
# 5. Return next conversation state
# ==========================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                inventory_manager: InventoryManager, 
                loggers: Dict[str, logging.Logger]) -> int:
    """
    Start the ordering conversation with available categories.
    Enhanced with better UX and user guidance.
    
    This function initializes a new order conversation, checks inventory
    for available categories, and presents them to the user in a
    formatted message with emoji-enhanced buttons.
    
    Flow:
    1. Initialize user cart
    2. Check rate limits
    3. Log conversation start
    4. Create welcome message
    5. Check available categories from inventory
    6. Display category selection buttons
    
    Args:
        update: Telegram update
        context: Conversation context
        inventory_manager: Inventory manager instance
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state (CATEGORY)
    """
    user = update.message.from_user
    first_name = user.first_name if user.first_name else "there"
    
    # Initialize user cart if needed
    if "cart" not in context.user_data:
        context.user_data["cart"] = []
        
    # Check rate limits
    if not check_rate_limit(context, user.id, "order"):
        await update.message.reply_text(
            f"{EMOJI['warning']} You've reached the maximum number of orders allowed per hour. "
            "Please try again later."
        )
        return ConversationHandler.END
        
    # Log the conversation start
    loggers["main"].info(f"User {user.id} ({user.full_name}) started order conversation")
    
    # Create welcome response with BotResponse
    welcome = BotResponse("welcome") \
        .add_header(f"Hi {first_name}! Welcome to Ganja Paraiso!", "welcome") \
        .add_paragraph("We're excited to help you find the perfect products to enhance your experience.") \
        .add_paragraph("Please select a category below to start browsing:")

    # Send the welcome message with typing indicator
    await send_typing_action(context, update.effective_chat.id, 1)
    
    # Fixed category list approach - ensure we have categories
    available_categories = ['buds', 'local', 'carts', 'edibles']  # Include all main categories
    
    # Verify which categories have available products (for logging only)
    for category_id in PRODUCTS:
        try:
            has_products = await inventory_manager.category_has_products(category_id)
            product_count = "has products" if has_products else "no products"
            print(f"DEBUG: Category {category_id} {product_count}")
        except Exception as e:
            # Just log errors but continue
            print(f"DEBUG ERROR: Problem checking category {category_id}: {str(e)}")
    
    if not available_categories:
        no_products = BotResponse("warning") \
            .add_header("No Products Available", "warning") \
            .add_paragraph("Sorry, we don't have any products in stock at the moment.") \
            .add_paragraph("Please check back later or contact support for assistance.")
            
        await update.message.reply_text(no_products.get_message())
        return ConversationHandler.END
    
    # Build the keyboard markup
    category_markup = build_category_buttons(available_categories)
    
    # Add explicit debug for callback data in buttons
    try:
        # Send welcome message with available category buttons
        sent_message = await update.message.reply_text(
            welcome.get_message(),
            reply_markup=category_markup
        )
        
        # Debug log to verify sent message and keyboard
        print(f"DEBUG: Sent welcome message with ID: {sent_message.message_id}")
        
        # Set current location in context
        context.user_data["current_location"] = "categories"
        
        return CATEGORY
    except Exception as e:
        # Log any errors during message sending
        print(f"DEBUG ERROR: Failed to send welcome message: {str(e)}")
        loggers["errors"].error(f"Error sending welcome message: {str(e)}")
        
        # Try a simpler message as fallback
        try:
            await update.message.reply_text(
                "Welcome! Please select a category:",
                reply_markup=create_button_layout([
                    [InlineKeyboardButton("Premium Buds", callback_data="buds")],
                    [InlineKeyboardButton("Local (BG)", callback_data="local")],
                    [InlineKeyboardButton("Carts", callback_data="carts")],
                    [create_button("cancel", "cancel", "Cancel")]
                ])
            )
            return CATEGORY
        except Exception:
            # Ultimate fallback
            await update.message.reply_text("Sorry, there was an error displaying the menu. Please try again later.")
            return ConversationHandler.END

async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE, inventory_manager, loggers):
    """
    Handle category selection and determine next steps based on category.
    Enhanced with additional debugging and error handling.
    
    Args:
        update: Telegram update
        context: Conversation context
        inventory_manager: Inventory manager instance
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state
    """
    query = update.callback_query
    # Print detailed debug info about the callback query
    print(f"DEBUG: choose_category received callback query: {query.data}")
    
    # Always answer the callback query first to prevent the loading spinner
    await query.answer()
    
    # Handle cancellation
    if query.data == "cancel":
        await query.edit_message_text(MESSAGES["cancel_order"])
        return ConversationHandler.END
    
    # Get the selected category
    category = query.data
    context.user_data["category"] = category
    
    # Log the selection
    loggers["main"].info(f"User {query.from_user.id} selected category: {category}")
    print(f"DEBUG: User selected category: {category}")
    
    # Get product details
    product = PRODUCTS.get(category)
    if not product:
        # Invalid category, go back to selection
        print(f"DEBUG: Invalid category: {category}")
        await query.edit_message_text("Invalid selection. Please try again.")
        return CATEGORY
    
    # Handle different category flows
    try:
        if category == "local":
            # For Local (BG), go directly to product selection
            print(f"DEBUG: Selected local category, proceeding to show_local_products")
            return await show_local_products(update, context, inventory_manager, loggers)
        
        elif category == "carts":
            # For Carts, choose browsing option first
            print(f"DEBUG: Selected carts category, showing browse options")
            browse_options = product.get("browse_options", [])
            buttons = []
                        
            for option in browse_options:
                option_text = f"Browse by {option.capitalize()}"
                buttons.append([InlineKeyboardButton(option_text, callback_data=option)])
                
            # Add back button
            buttons.append([create_button("back", "back_to_categories", "Back")])
                        
            keyboard = buttons

        elif product.get("requires_strain_selection", False):
            # For products requiring strain selection (buds, edibles)
            print(f"DEBUG: Selected {category} category, requires strain selection")
            
            # Define the keyboard clearly
            keyboard = get_common_buttons("strain_buttons")

            # Debug keyboard structure
            print(f"DEBUG: Creating strain keyboard with {len(keyboard)} buttons")
            for row in keyboard:
                for btn in row:
                    print(f"DEBUG: Button: {btn.text} -> {btn.callback_data}")
            
            # Send with error handling
            try:
                await query.edit_message_text(
                    f"{product['emoji']} Please select the strain type for {product['name']}:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                print(f"DEBUG: Successfully sent strain selection message")
                return STRAIN_TYPE
            except Exception as btn_err:
                print(f"DEBUG ERROR: Failed to send strain selection: {str(btn_err)}")
                raise btn_err
        
        else:
            # Unknown category type
            print(f"DEBUG: Category {category} has no specific handling")
            await query.edit_message_text("This category is currently unavailable.")
            return CATEGORY
            
    except Exception as e:
        # Comprehensive error handling
        error_msg = f"Error in category selection for {category}: {str(e)}"
        loggers["errors"].error(error_msg)
        print(f"DEBUG ERROR: {error_msg}")
        
        # Try to recover with a simple message
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"Sorry, there was an error with your selection. Please try again.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔄 Try Again", callback_data="start")
                ]])
            )
        except Exception:
            pass
            
        return ConversationHandler.END

async def handle_back_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE, inventory_manager, loggers):
    """
    Universal handler for back navigation throughout the application.
    This handles 'back_to_browse' and other back navigation callback data.
    
    Args:
        update: Telegram update
        context: Conversation context
        inventory_manager: Inventory manager instance
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state
    """
    query = update.callback_query
    await query.answer()
    
    # Extract the callback data
    callback_data = query.data
    
    # Get current location from context
    current_location = context.user_data.get("current_location", "")
    category = context.user_data.get("category")
    strain_type = context.user_data.get("strain_type")
    
    # Log the navigation action
    loggers["main"].info(f"User {query.from_user.id} navigating back with action: {callback_data}")
    
    try:
        # Handle different types of back navigation
        if callback_data == "back_to_browse":
            # Clear product-specific data
            for key in ["product_key", "parsed_quantity"]:
                if key in context.user_data:
                    del context.user_data[key]
            
            # Determine the right place to go back to
            if category == "carts":
                # Return to cart browse options
                context.user_data["current_location"] = "browse_carts"
                
                keyboard = [
                    [InlineKeyboardButton("Browse by Brand", callback_data="brand")],
                    [InlineKeyboardButton("Browse by Weight", callback_data="weight")],
                    [create_button("back", "back_to_categories", "Back to Categories")]
                ]
                
                await query.edit_message_text(
                    f"{EMOJI['carts']} How would you like to browse our carts?",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return BROWSE_BY
                
            elif category == "buds" and strain_type:
                # Return to strain type selection for buds
                context.user_data["current_location"] = "strain_selection"
                
                keyboard = get_common_buttons("strain_buttons")
                
                await query.edit_message_text(
                    f"{EMOJI['buds']} Select Strain Type:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return STRAIN_TYPE
                
            else:
                # Default back to categories for other cases
                return await back_to_categories(update, context, inventory_manager, loggers)
                
        elif callback_data == "back_to_categories":
            # Always go back to categories selection
            return await back_to_categories(update, context, inventory_manager, loggers)
            
        elif callback_data == "back_to_strain":
            # Go back to strain selection
            if "strain_type" in context.user_data:
                del context.user_data["strain_type"]
            
            # Build the strain selection keyboard
            keyboard = keyboard = get_common_buttons("strain_buttons")
            
            await query.edit_message_text(
                f"{EMOJI['buds']} Select Strain Type:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return STRAIN_TYPE
            
        else:
            # For any unrecognized back navigation, go to categories as a safe default
            return await back_to_categories(update, context, inventory_manager, loggers)
            
    except Exception as e:
        # Log the error with specific navigation details
        loggers["errors"].error(f"Error during back navigation ({callback_data}): {e}")
        
        # Provide user feedback and safe fallback
        try:
            await query.edit_message_text(
                f"{EMOJI['error']} Sorry, something went wrong during navigation. Let's start again.",
                reply_markup=create_button_layout([
                    [create_button("action", "restart_conversation", "Start Over", f"{EMOJI['restart']} Start Over")]
                ])
            )
        except Exception:
            pass  # Ignore any error sending the message
            
        return CATEGORY

async def back_to_categories(update: Update, context: ContextTypes.DEFAULT_TYPE, inventory_manager, loggers):
    """
    Navigate back to the categories selection screen.
    Works from both callback queries and direct commands.
    
    Args:
        update: Telegram update
        context: Conversation context
        inventory_manager: Inventory manager instance
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state (CATEGORY)
    """
    # Determine if this is from a callback query or direct message
    if update.callback_query:
        user = update.callback_query.from_user
        is_callback = True
    else:
        user = update.message.from_user
        is_callback = False
    
    # Log the navigation action
    loggers["main"].info(f"User {user.id} navigating back to categories")
    
    # Clear navigation-related context variables
    context.user_data.pop("category", None)
    context.user_data.pop("strain_type", None)
    context.user_data.pop("browse_by", None)
    context.user_data.pop("product_key", None)
    context.user_data.pop("parsed_quantity", None)
    
    # Set current location
    context.user_data["current_location"] = "categories"
    
    # Check available categories
    available_categories = []
    for category_id in PRODUCTS:
        try:
            has_products = await inventory_manager.category_has_products(category_id)
            if has_products:
                available_categories.append(category_id)
        except Exception as e:
            loggers["errors"].error(f"Error checking products for {category_id}: {str(e)}")
            # If there's an error, include the category anyway to avoid blocking the flow
            available_categories.append(category_id)
    
    # Build the welcome message with category buttons
    welcome_message = MESSAGES["welcome"]
    categories_markup = build_category_buttons(available_categories)
    
    # Send response based on update type
    if is_callback:
        await update.callback_query.edit_message_text(
            welcome_message,
            reply_markup=categories_markup
        )
    else:
        await update.message.reply_text(
            welcome_message,
            reply_markup=categories_markup
        )
    
    return CATEGORY

async def choose_strain_type(update: Update, context: ContextTypes.DEFAULT_TYPE, inventory_manager, loggers):
    """
    Handle strain type selection for products that require it.
    Enhanced with state tracking and robust error handling.
    """
    # Track state for debugging
    await debug_state_tracking(update, context)
    
    query = update.callback_query
    await query.answer()
    
    # Log for debugging
    loggers["main"].info(f"Strain type selection callback received with data: {query.data}")
    print(f"DEBUG: Strain type selection with data: {query.data}")
    
    # Check if this callback was already processed (prevent duplicate processing)
    callback_id = query.id
    processed_callbacks = context.user_data.get("processed_callbacks", set())
    
    if callback_id in processed_callbacks:
        print(f"DEBUG: Skipping already processed callback: {callback_id}")
        return STRAIN_TYPE
        
    # Mark this callback as processed
    processed_callbacks.add(callback_id)
    context.user_data["processed_callbacks"] = processed_callbacks
    
    # Keep the size of processed_callbacks manageable
    if len(processed_callbacks) > 100:
        # Keep only the 50 most recent items
        processed_callbacks = set(list(processed_callbacks)[-50:])
        context.user_data["processed_callbacks"] = processed_callbacks
    
    if query.data == "back_to_categories":
        # Go back to category selection
        return await back_to_categories(update, context, inventory_manager, loggers)
    
    # Store the selected strain type
    strain_type = query.data
    context.user_data["strain_type"] = strain_type
    
    # Get the category
    category = context.user_data.get("category")
    if not category:
        # Something went wrong, go back to category selection
        loggers["errors"].error("Missing category in user data during strain selection")
        return await back_to_categories(update, context, inventory_manager, loggers)
    
    # Log the selection
    loggers["main"].info(
        f"User {query.from_user.id} selected strain type: {strain_type} for {category}"
    )
    
    # Set current location for state tracking
    context.user_data["current_location"] = "strain_selection"
    
    # Fetch the inventory data
    try:
        products_by_tag, products_by_strain, all_products = await inventory_manager.get_inventory_safe()
        
        # Get the tag for this category
        tag = PRODUCTS[category].get("tag", "")
        print(f"DEBUG: Category {category} has tag {tag}")
        
        # Debug info about available products
        print(f"DEBUG: Available strain types: {list(products_by_strain.keys())}")
        print(f"DEBUG: Products for {strain_type}: {len(products_by_strain.get(strain_type, []))}")
        
        # Filter products by tag and strain
        filtered_products = []
        
        # This is a critical section - make very robust
        for product in products_by_strain.get(strain_type, []):
            if product.get("tag") == tag:
                filtered_products.append(product)
        
        print(f"DEBUG: Filtered products count: {len(filtered_products)}")
        
        # If no products found, use a fallback
        if not filtered_products:
            print(f"DEBUG: No products found for {strain_type} {category}. Using fallback.")
            
            # Add a fallback product to prevent empty selection
            fallback_product = {
                'name': f"Default {strain_type.capitalize()} Strain",
                'key': f"default_{strain_type}_product",
                'price': 2000,  # Default price
                'stock': 3,     # Default stock
                'tag': tag,
                'strain': strain_type
            }
            filtered_products = [fallback_product]
    except Exception as e:
        error_msg = f"Error fetching inventory in strain selection: {str(e)}"
        loggers["errors"].error(error_msg)
        print(f"DEBUG ERROR: {error_msg}")
        
        # Create fallback product to keep flow working
        fallback_product = {
            'name': f"Default {strain_type.capitalize()} Strain",
            'key': f"default_{strain_type}_product",
            'price': 2000,
            'stock': 3,
            'tag': tag if 'tag' in locals() else PRODUCTS[category].get("tag", ""),
            'strain': strain_type
        }
        filtered_products = [fallback_product]

    # Build product selection keyboard
    keyboard = []
    for product in filtered_products:
        product_name = product.get("name")
        product_price = product.get("price", 0)
        product_key = product.get("key")
        
        button_text = f"{product_name} - ₱{product_price:,}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=product_key)])
    
    # Add back button
    keyboard.append([create_button("back", "back_to_strain", "Back")])
    
    # Create message based on category
    if category == "edibles":
        message = f"{EMOJI['edibles']} Select an edible ({strain_type.capitalize()}):"
    else:
        message = f"{EMOJI['buds']} Select a {strain_type.capitalize()} strain:"
        
    # Send the message with retries
    MAX_RETRIES = 3
    for attempt in range(MAX_RETRIES):
        try:
            await query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            # Log success and break if successful
            print(f"DEBUG: Successfully sent product selection keyboard on attempt {attempt+1}")
            break
        except TelegramError as e:
            # Check if this is a "message not modified" error
            if "message is not modified" in str(e).lower():
                # Message is identical, consider it successful
                print(f"DEBUG: Message not modified (identical content)")
                break
            elif attempt == MAX_RETRIES - 1:
                # This is our last attempt, log the failure and provide fallback
                loggers["errors"].error(f"Failed to show strain products after {MAX_RETRIES} attempts: {e}")
                
                # Try sending a new message instead of editing
                try:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=f"{EMOJI['warning']} Had trouble displaying products. Please try again.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton(f"{EMOJI['back']} Back to Categories", callback_data="back_to_categories")]
                        ])
                    )
                except Exception:
                    pass  # Last resort, just give up silently
            else:
                print(f"DEBUG: Failed to send message on attempt {attempt+1}, retrying...")
                await asyncio.sleep(0.5)  # Small delay before retry
    
    return PRODUCT_SELECTION
async def browse_carts_by(update: Update, context: ContextTypes.DEFAULT_TYPE, inventory_manager, loggers):
    """
    Handle the browse carts by selection.
    
    Args:
        update: Telegram update
        context: Conversation context
        inventory_manager: Inventory manager instance
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state
    """
    query = update.callback_query
    await query.answer()
    
    browse_by = query.data
    
    # If user is going back
    if browse_by == "back_to_categories":
        return await back_to_categories(update, context, inventory_manager, loggers)
    
    # Store the browse by selection
    context.user_data["browse_by"] = browse_by
    context.user_data["current_location"] = "browse_carts_by"
    
    # Fetch cart products
    products_by_tag, products_by_strain, _ = await inventory_manager.get_inventory()
    cart_products = products_by_tag.get("carts", [])
    
    if not cart_products:
        await query.edit_message_text(
            "Sorry, no cart products are available. Please try another category.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Categories", callback_data="back_to_categories")]
            ])
        )
        return CATEGORY
    
    # Group products by brand or strain
    if browse_by == "browse_by_brand":
        # Group by brand
        products_by_group = {}
        for product in cart_products:
            brand = product.get("brand", "Unknown")
            if brand not in products_by_group:
                products_by_group[brand] = []
            products_by_group[brand].append(product)
            
        # Build the brand buttons
        keyboard = []
        for brand in sorted(products_by_group.keys()):
            keyboard.append([InlineKeyboardButton(brand, callback_data=f"brand_{brand}")])
            
        # Add back buttons
        keyboard.append([InlineKeyboardButton(f"{EMOJI['back']} Back to Browse Options", callback_data="back_to_browse")])
        keyboard.append([InlineKeyboardButton(f"{EMOJI['back']} Back to Categories", callback_data="back_to_categories")])
        
        await query.edit_message_text(
            f"{EMOJI['carts']} Select Brand:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    elif browse_by == "browse_by_strain":
        # Group by strain
        products_by_group = {}
        for product in cart_products:
            strain = product.get("strain", "Unknown")
            if strain not in products_by_group:
                products_by_group[strain] = []
            products_by_group[strain].append(product)
            
        # Build the strain buttons
        keyboard = []
        for strain in sorted(products_by_group.keys()):
            keyboard.append([InlineKeyboardButton(strain.capitalize(), callback_data=f"strain_{strain}")])
            
        # Add back buttons
        keyboard.append([InlineKeyboardButton(f"{EMOJI['back']} Back to Browse Options", callback_data="back_to_browse")])
        keyboard.append([InlineKeyboardButton(f"{EMOJI['back']} Back to Categories", callback_data="back_to_categories")])
        
        await query.edit_message_text(
            f"{EMOJI['carts']} Select Strain Type:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return PRODUCT_SELECTION

async def show_local_products(update: Update, context: ContextTypes.DEFAULT_TYPE, inventory_manager, loggers):
    """
    Show local products directly after category selection with specific quantity buttons.
    
    Args:
        update: Telegram update
        context: Conversation context
        inventory_manager: Inventory manager instance
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state
    """
    query = update.callback_query
    
    # Fetch local products
    products_by_tag, _, _ = await inventory_manager.get_inventory()
    local_products = products_by_tag.get("local", [])
    
    if not local_products:
        # No local products available, inform the user
        await query.edit_message_text(
            "Sorry, no local products are currently in stock. Please try another category.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Categories", callback_data="back_to_categories")]
            ])
        )
        return CATEGORY
    
    # Get the first local product (usually only one type)
    product = local_products[0]
    product_name = product.get("name")
    product_key = product.get("key")
    
    # Store the product details in context
    context.user_data["product_key"] = product_key
    context.user_data["product_name"] = product_name
    context.user_data["product_price"] = product.get("price", 1000)  # Default 1000 per 10g
    context.user_data["product_stock"] = product.get("stock", 0)
    
    # Build quantity selection buttons with only the specified options
    keyboard = [
        [InlineKeyboardButton("10 grams - ₱1,000", callback_data="qty_10")],
        [InlineKeyboardButton("50 grams - ₱5,000", callback_data="qty_50")],
        [InlineKeyboardButton("100 grams - ₱8,000 (Save ₱2,000!)", callback_data="qty_100")],
        [InlineKeyboardButton("300 grams - ₱24,000 (Save ₱6,000 + Free Shipping!)", callback_data="qty_300")],
        [create_button("back", "back_to_categories", "Back")]
    ]
    
    # Display local products with quantity options
    await query.edit_message_text(
        f"{EMOJI['local']} {product_name}\n\n"
        f"Please select quantity:\n\n"
        f"• Every 10 grams costs ₱1,000\n"
        f"• 100 grams: 20% discount (₱8,000 instead of ₱10,000)\n"
        f"• 300 grams: 20% discount + Free Shipping (₱24,000 instead of ₱30,000)",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return QUANTITY

async def select_product(update: Update, context: ContextTypes.DEFAULT_TYPE, inventory_manager, loggers):
    """
    Handle product selection after strain type or browse options.
    """
    # Track state for debugging
    await debug_state_tracking(update, context)
    
    query = update.callback_query
    await query.answer()
    
    selection = query.data
    print(f"DEBUG PRODUCT: Product selection callback with data: {selection}")
    
    # Check if this callback was already processed
    callback_id = query.id
    processed_callbacks = context.user_data.get("processed_callbacks", set())
    if callback_id in processed_callbacks:
        print(f"DEBUG: Skipping already processed callback: {callback_id}")
        return PRODUCT_SELECTION
        
    # Mark this callback as processed
    processed_callbacks.add(callback_id)
    context.user_data["processed_callbacks"] = processed_callbacks
    
    # Keep the size of processed_callbacks manageable
    if len(processed_callbacks) > 100:
        processed_callbacks = set(list(processed_callbacks)[-50:])
        context.user_data["processed_callbacks"] = processed_callbacks
    
    # Handle back navigation
    if selection == "back_to_browse":
        return await handle_back_navigation(update, context, inventory_manager, loggers)
        
    if selection == "back_to_categories":
        return await back_to_categories(update, context, inventory_manager, loggers)
    
    if selection == "back_to_strain":
        # Go back to strain selection
        if "strain_type" in context.user_data:
            del context.user_data["strain_type"]
        
        # Get category to pass to the strain selection
        category = context.user_data.get("category")
        if not category:
            return await back_to_categories(update, context, inventory_manager, loggers)
            
        # Build the strain selection keyboard
        keyboard = keyboard = get_common_buttons("strain_buttons")
        
        try:
            await query.edit_message_text(
                f"{EMOJI['buds']} Select Strain Type:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return STRAIN_TYPE
        except Exception as e:
            loggers["errors"].error(f"Error going back to strain selection: {e}")
            # Try with a fresh message instead of editing
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"{EMOJI['buds']} Select Strain Type:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return STRAIN_TYPE
    
    # If it's a direct product selection
    category = context.user_data.get("category")
    
    # Set location for tracking
    context.user_data["current_location"] = f"product_{selection}"
    
    # Find the product
    products_by_tag, products_by_strain, all_products = await inventory_manager.get_inventory_safe()
    
    selected_product = None
    for p in all_products:
        if p.get("key") == selection:
            selected_product = p
            break
            
    if not selected_product:
        await query.edit_message_text(
            "Sorry, this product is no longer available.",
            reply_markup=create_button_layout([
                [create_button("back", "back_to_browse", "Back to Browse")],
                [create_button("back", "back_to_categories", "Back to Categories")]
            ])
        )
        return PRODUCT_SELECTION
        
    # Store product details
    context.user_data["product_key"] = selection
    context.user_data["product_name"] = selected_product.get("name")
    context.user_data["product_price"] = selected_product.get("price", 0)
    context.user_data["product_stock"] = selected_product.get("stock", 0)
    
    # Ask for quantity
    product_unit = PRODUCTS[category].get("unit", "units") if category in PRODUCTS else "units"
    min_order = PRODUCTS[category].get("min_order", 1) if category in PRODUCTS else 1
    
    # Log the product selection
    loggers["main"].info(
        f"User {query.from_user.id} selected product: {selected_product.get('name')} ({selection})"
    )
    
    try:
        await query.edit_message_text(
            f"{EMOJI.get(category, '🌿')} {selected_product.get('name')}\n\n"
            f"Price: ₱{selected_product.get('price', 0):,.0f}\n"
            f"Stock: {selected_product.get('stock', 0)} {product_unit}\n\n"
            f"Please enter the quantity (minimum {min_order} {product_unit}):",
            reply_markup=create_button_layout([
                [create_button("back", "back_to_browse", "Back to Browse")],
                [create_button("back", "back_to_categories", "Back to Categories")]
            ])
        )
    except TelegramError as e:
        # Handle message editing errors
        if "message is not modified" in str(e).lower():
            print(f"DEBUG: Message not modified (identical content)")
        else:
            # Log other errors and try sending a new message
            loggers["errors"].error(f"Error displaying product details: {e}")
            # Try sending a new message instead
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"{EMOJI.get(category, '🌿')} {selected_product.get('name')}\n\n"
                     f"Price: ₱{selected_product.get('price', 0):,.0f}\n"
                     f"Stock: {selected_product.get('stock', 0)} {product_unit}\n\n"
                     f"Please enter the quantity (minimum {min_order} {product_unit}):",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Browse", callback_data="back_to_browse")],
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Categories", callback_data="back_to_categories")]
                ])
            )    
    return QUANTITY

async def handle_quantity_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, inventory_manager, loggers):
    """
    Handle quantity button selection for local products.
    
    Args:
        update: Telegram update
        context: Conversation context
        inventory_manager: Inventory manager instance
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state
    """
    query = update.callback_query
    await query.answer()
    
    # Get the selected quantity from callback data
    quantity_data = query.data
    
    if quantity_data == "back_to_categories":
        return await start(update, context, inventory_manager, loggers)
    
    # Extract quantity value from callback data (e.g., "qty_100" -> 100)
    quantity = int(quantity_data.split("_")[1])
    
    # Store the quantity
    context.user_data["parsed_quantity"] = quantity
    
    # Get category and product details
    category = context.user_data.get("category")
    product_key = context.user_data.get("product_key")
    product_name = context.user_data.get("product_name")
    
    try:
        # Calculate price with possible discount handling
        price_result = await inventory_manager.calculate_price(
            category, product_key, quantity
        )
        
        # Handle both 2-value and 4-value returns
        if len(price_result) == 4:
            total_price, unit_price, regular_price, discount_info = price_result
        else:
            total_price, unit_price = price_result
            regular_price = None
            discount_info = ""
            
    except Exception as e:
        loggers["errors"].error(f"Error calculating price: {str(e)}")
        await query.edit_message_text(
            f"{EMOJI['error']} Sorry, there was an error processing your selection. Please try again."
        )
        return CATEGORY
    
    # Store prices in context
    context.user_data["unit_price"] = unit_price
    context.user_data["total_price"] = total_price
    context.user_data["regular_price"] = regular_price
    context.user_data["discount_info"] = discount_info
    
    # Get product details
    product = PRODUCTS.get(category, {})
    unit = product.get("unit", "units")
    
    # Build checkout summary with discount if applicable
    if quantity in [100, 300]:
        summary = (
            f"{EMOJI['cart']} Checkout Summary:\n"
            f"- Category: {category.capitalize()}\n"
            f"- Product: {product_name}\n"
            f"- Quantity: {quantity} {unit}\n"
            f"- Regular Price: ₱{regular_price:,.0f}\n"
            f"- Discounted Price: ₱{total_price:,.0f} {discount_info}\n\n"
        )
    else:
        summary = (
            f"{EMOJI['cart']} Checkout Summary:\n"
            f"- Category: {category.capitalize()}\n"
            f"- Product: {product_name}\n"
            f"- Quantity: {quantity} {unit}\n"
            f"- Unit Price: ₱{unit_price:,.0f} per 10g\n"
            f"- Total: ₱{total_price:,.0f}\n\n"
        )
    
    # Create confirmation buttons
    keyboard = [
        [InlineKeyboardButton(f"{EMOJI['success']} Confirm Selection", callback_data="confirm")],
        [InlineKeyboardButton(f"{EMOJI['error']} Cancel", callback_data="cancel")],
    ]
    
    # Log the selection
    loggers["main"].info(
        f"User {query.from_user.id} selected quantity {quantity} of {product_name} "
        f"for ₱{total_price:,.0f}"
    )
    
    await query.edit_message_text(
        summary, 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return CONFIRM

async def input_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE, inventory_manager, loggers):
    """
    Handle quantity input from user.
    
    Args:
        update: Telegram update
        context: Conversation context
        inventory_manager: Inventory manager instance
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state
    """
    user = update.message.from_user
    quantity_text = update.message.text.lower()
    
    # Get category and product details from context
    category = context.user_data.get("category")
    product_key = context.user_data.get("product_key")
    product_name = context.user_data.get("product_name")
    
    # Validate quantity
    is_valid, result = validate_quantity(quantity_text, category)
    
    if not is_valid:
        await update.message.reply_text(f"{EMOJI['warning']} {result} Please try again.")
        return QUANTITY
        
    quantity = result
    
    # Calculate price with discount handling
    try:
        # Calculate price with possible discount handling
        price_result = await inventory_manager.calculate_price(
            category, product_key, quantity
        )
        
        # Handle both 2-value and 4-value returns
        if len(price_result) == 4:
            total_price, unit_price, regular_price, discount_info = price_result
        else:
            total_price, unit_price = price_result
            regular_price = None
            discount_info = ""
            
    except Exception as e:
        loggers["errors"].error(f"Error calculating price: {str(e)}")
        await update.message.reply_text(
            f"{EMOJI['error']} Sorry, there was an error processing your selection. Please try again."
        )
        return CATEGORY
    
    if total_price == 0:
        await update.message.reply_text(ERRORS["invalid_category"])
        return CATEGORY
    
    # Check stock availability
    product_stock = context.user_data.get("product_stock", 0)
    if quantity > product_stock:
        await update.message.reply_text(
            f"{EMOJI['warning']} Sorry, we only have {product_stock} in stock. "
            f"Please enter a quantity less than or equal to {product_stock}."
        )
        return QUANTITY
    
    # Store in context
    context.user_data["parsed_quantity"] = quantity
    context.user_data["unit_price"] = unit_price
    context.user_data["total_price"] = total_price
    context.user_data["regular_price"] = regular_price
    context.user_data["discount_info"] = discount_info
    
    # Get product details
    product = PRODUCTS.get(category, {})
    unit = product.get("unit", "units")
    
    # Build checkout summary with discount if applicable
    if category == "local" and regular_price:
        summary = (
            f"{EMOJI['cart']} Checkout Summary:\n"
            f"- Category: {category.capitalize()}\n"
            f"- Product: {product_name}\n"
            f"- Quantity: {quantity} {unit}\n"
            f"- Regular Price: ₱{regular_price:,.0f}\n"
            f"- Discounted Price: ₱{total_price:,.0f} {discount_info}\n\n"
        )
    else:
        summary = (
            f"{EMOJI['cart']} Checkout Summary:\n"
            f"- Category: {category.capitalize()}\n"
            f"- Product: {product_name}\n"
            f"- Quantity: {quantity} {unit}\n"
            f"- Unit Price: ₱{unit_price:,.0f}\n"
            f"- Total: ₱{total_price:,.0f}\n\n"
        )
    
    # Create confirmation buttons
    keyboard = get_common_buttons("confirm_cancel")
    
    # Log the selection
    loggers["main"].info(
        f"User {user.id} selected quantity {quantity} of {product_name} "
        f"for ₱{total_price:,.0f}"
    )
    
    await update.message.reply_text(
        summary, 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return CONFIRM

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE, loggers):
    """
    Handle order confirmation.
    
    Args:
        update: Telegram update
        context: Conversation context
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state
    """
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm":
        # Get item details from context
        category = context.user_data.get("category", "Unknown").capitalize()
        product_name = context.user_data.get("product_name", "Unknown")
        quantity = context.user_data.get("parsed_quantity", 0)
        total_price = context.user_data.get("total_price", 0)
        regular_price = context.user_data.get("regular_price")
        discount_info = context.user_data.get("discount_info", "")
        
        # Get product unit and details
        product_info = PRODUCTS.get(category.lower(), {})
        unit = product_info.get("unit", "units")
        
        # Create item and add to cart
        current_item = {
            "category": category,
            "suboption": product_name,
            "quantity": quantity,
            "total_price": total_price,
            "unit": unit
        }
        
        # Add discount information if available
        if regular_price:
            current_item["regular_price"] = regular_price
            current_item["discount_info"] = discount_info
        
        manage_cart(context, "add", current_item)
        
        # Log the cart addition
        loggers["orders"].info(
            f"User {query.from_user.id} added to cart: {category} ({product_name}) "
            f"x{quantity} {unit} - ₱{total_price:,.0f}"
        )
        
        await query.edit_message_text(
            MESSAGES["order_added"],
            reply_markup=create_button_layout(get_common_buttons("order_actions")),
        )
        return CONFIRM
    
    elif query.data == "add_more":
        # Return to category selection
        context.user_data.pop("category", None)
        context.user_data.pop("product_key", None)
        context.user_data.pop("strain_type", None)
        context.user_data.pop("browse_by", None)
        
        # Clear discount-related data
        context.user_data.pop("regular_price", None)
        context.user_data.pop("discount_info", None)
        
        # Check available categories
        available_categories = []
        for category_id in PRODUCTS:
            has_products = await inventory_manager.category_has_products(category_id)
            if has_products:
                available_categories.append(category_id)
                
        await query.edit_message_text(
            f"{EMOJI['cart']} What would you like to add to your cart?",
            reply_markup=build_category_buttons(available_categories)
        )
        return CATEGORY
        
    elif query.data == "proceed":
        # Generate the cart summary
        cart_summary, _ = build_cart_summary(context.user_data.get("cart", []))
        
        # Show the cart summary and prompt for shipping details
        await query.edit_message_text(
            f"{cart_summary}\n{MESSAGES['checkout_prompt']}"
        )
        
        return DETAILS
        
    elif query.data == "cancel":
        # Clear the cart
        manage_cart(context, "clear")
        
        # Inform the user
        await query.edit_message_text(MESSAGES["cancel_order"])
        
        return ConversationHandler.END
    
    return CONFIRM

async def input_details(update: Update, context: ContextTypes.DEFAULT_TYPE, loggers):
    """
    Handle shipping details input.
    
    This function processes the user's shipping details input, validates it,
    and moves to the confirmation step if valid.
    
    Args:
        update: Telegram update
        context: Conversation context
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state
    """
    user = update.message.from_user
    details_text = update.message.text

    # Log the received input for debugging
    loggers["main"].info(f"User {user.id} entered shipping details: {details_text}")
    
    # Validate shipping details
    is_valid, result = validate_shipping_details(details_text)
    
    if not is_valid:
        # Log the validation failure
        loggers["main"].warning(f"Invalid shipping details from user {user.id}: {result}")
        
        # Send a detailed error message
        await update.message.reply_text(
            f"{EMOJI['error']} {result}\n\n"
            f"{EMOJI['info']} Please use this format:\n"
            f"Name / Address / Contact Number\n\n"
            f"{EMOJI['success']} Example: Juan Dela Cruz / 123 Main St, City / 09171234567"
        )
        return DETAILS
    
    # Store the validated details
    context.user_data["shipping_details"] = details_text
    context.user_data["name"] = result["name"]
    context.user_data["address"] = result["address"]
    context.user_data["contact"] = result["contact"]
    
    # Get cart and check if empty
    cart = context.user_data.get("cart", [])
    if not cart:
        await update.message.reply_text(MESSAGES["empty_cart"])
        return CATEGORY
    
    # Generate cart summary
    cart_summary, total_cost = build_cart_summary(cart)
    
    # Build complete summary
    summary = (
        f"{cart_summary}"
        f"{EMOJI['shipping']} Shipping Details:\n"
        f"{result['name']} / {result['address']} / {result['contact']}\n\n"
        f"{EMOJI['info']} If everything looks good, press 'Confirm'. "
        f"Otherwise, press 'Edit' to change the details."
    )
    
    # Log the shipping details
    loggers["orders"].info(
        f"User {user.id} entered shipping details - Name: {result['name']}"
    )
    
    await update.message.reply_text(
        summary,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{EMOJI['success']} Confirm", callback_data='confirm_details')],
            [InlineKeyboardButton(f"{EMOJI['info']} Edit", callback_data='edit_details')]
        ])
    )
    
    return CONFIRM_DETAILS

# Update the confirm_details function (around line 2771-2774)
async def confirm_details(update: Update, context: ContextTypes.DEFAULT_TYPE, loggers, admin_id):
    """
    Handle shipping details confirmation.
    
    Args:
        update: Telegram update
        context: Conversation context
        loggers: Dictionary of logger instances
        admin_id: Telegram ID of the admin
        
    Returns:
        int: Next conversation state
    """
    query = update.callback_query
    await query.answer()
    
    if query.data == 'confirm_details':
        # Get cart and user details
        cart = context.user_data.get("cart", [])
        total_cost = sum(item.get("total_price", 0) for item in cart)
        name = context.user_data.get("name", "Unknown")
        address = context.user_data.get("address", "Unknown")
        contact = context.user_data.get("contact", "Unknown")
        customer_name = update.callback_query.from_user.full_name
        
        # First show an order summary with a nice format
        order_summary = BotResponse("cart") \
            .add_header("Order Summary", "cart") \
            .add_paragraph(f"Thank you, {update.effective_user.first_name}! Here's a summary of your order:")
        
        # Add item details
        items_list = []
        for item in cart:
            category = item.get("category", "Unknown")
            product = item.get("suboption", "Unknown")
            quantity = item.get("quantity", 0)
            unit = item.get("unit", "units")
            price = item.get("total_price", 0)
            
            items_list.append(f"{quantity}x {category} ({product}) - ₱{price:,.2f}")
        
        order_summary.add_bullet_list(items_list)
        order_summary.add_divider()
        order_summary.add_paragraph(f"Total: ₱{total_cost:,.2f}")
        order_summary.add_paragraph(f"Shipping to: {mask_sensitive_data(name, 'name')}")
        order_summary.add_paragraph(f"Address: {mask_sensitive_data(address, 'address')}")
        order_summary.add_paragraph(f"Contact: {mask_sensitive_data(contact, 'phone')}")
        
        # Send the order summary message
        await query.edit_message_text(
            order_summary.get_message(),
            parse_mode=ParseMode.HTML
        )
        
        # Show typing indicator before payment instructions
        await send_typing_action(context, query.message.chat_id, 1)
        
        # Then send payment instructions with HTML parsing explicitly enabled
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=MESSAGES["payment_instructions"].format(GCASH_NUMBER),
            parse_mode=ParseMode.HTML  # Explicitly set HTML parse mode
        )
        
        # Then send the QR code
        try:
            # Only send if a QR code URL is configured
            if GCASH_QR_CODE_URL and GCASH_QR_CODE_URL != "https://example.com/gcash_qr.jpg":
                # Convert Google Drive URL to direct link format
                direct_url = convert_gdrive_url_to_direct_link(GCASH_QR_CODE_URL)
                
                # Log the URL being used
                print(f"DEBUG: Sending QR code with URL: {direct_url}")
                loggers["main"].info(f"Sending QR code with URL: {direct_url}")
                
                # Send the QR code
                await context.bot.send_photo(
                    chat_id=query.from_user.id,
                    photo=direct_url,
                    caption=f"{EMOJI['qrcode']} GCash QR Code for {GCASH_NUMBER}\nScan this code to pay directly."
                )
        except Exception as e:
            # Log the error but continue with the flow
            error_msg = f"Failed to send QR code: {type(e).__name__}: {str(e)}"
            print(f"DEBUG ERROR: {error_msg}")
            loggers["errors"].error(error_msg)
            
            # Inform the user they can still pay without QR code
            try:
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text=f"{EMOJI['info']} Please send payment to GCash number: {GCASH_NUMBER}"
                )
            except Exception:
                pass  # Ignore errors in the fallback message
    
# ---------------------------- Payment & Tracking Handlers ----------------------------
async def track_order_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wrapper for the track_order function that handles the initial /track command."""
    user_id = update.effective_user.id
    
    # Clear any previous tracking data
    if 'track_order_id' in context.user_data:
        del context.user_data['track_order_id']
    
    # Log the tracking request
    logging.info(f"User {user_id} initiated order tracking")
    
    # Always prompt the user to enter their order ID
    prompt_message = (
        f"{EMOJI['package']} <b>Track Your Order</b>\n\n"
        f"Please enter your order ID to track its status.\n"
        f"Your order ID can be found in your order confirmation message."
    )
    
    # If user has previous orders, offer a button to show recent orders
    user_orders = get_user_orders(user_id)
    
    # Create a keyboard with additional options
    keyboard = []
    
    # Add recent orders button if the user has previous orders
    if user_orders and len(user_orders) > 0:
        keyboard.append([create_button("action", "show_recent_orders", "Show My Recent Orders", f"{EMOJI['list']} Show My Recent Orders")])

    # Always add cancel button
    keyboard.append([create_button("cancel", "cancel_tracking", "Cancel")])
    
    await update.message.reply_text(
        prompt_message,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode=ParseMode.HTML
    )
    
    # Return the state for conversation handler
    return TRACK_ORDER

async def show_recent_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show a list of the user's recent orders to select from."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_orders = get_user_orders(user_id)
    
    if not user_orders or len(user_orders) == 0:
        await query.edit_message_text(
            f"{EMOJI['error']} <b>No Recent Orders</b>\n\n"
            f"You don't have any recent orders to display.\n"
            f"Please enter an order ID manually.",
            parse_mode=ParseMode.HTML
        )
        return TRACK_ORDER
    
    # Create a message showing recent orders with buttons to select
    message = f"{EMOJI['list']} <b>Your Recent Orders</b>\n\n"
    
    # Create keyboard with buttons for each order
    keyboard = []
    
    # Add up to 5 most recent orders
    for i, order in enumerate(user_orders[:5]):
        order_id = order.get('order_id')
        order_date = order.get('date', 'Unknown date')
        order_total = order.get('total', 'Unknown amount')
        
        # Add to message
        message += f"{i+1}. Order #{order_id} - {order_date} - {order_total}\n"
        
        # Add button to select this order
        keyboard.append([InlineKeyboardButton(
            f"📦 Order #{order_id}",
            callback_data=f"select_order_{order_id}"
        )])
    
    # Add a button to enter order ID manually
    keyboard.append([create_button("action", "enter_order_id", "Enter Different Order ID", f"{EMOJI['back']} Enter Different Order ID")])

    # Add cancel button
    keyboard.append([create_button("cancel", "cancel_tracking", "Cancel")])
    
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    
    return TRACK_ORDER

async def select_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle when a user selects an order from their recent orders list."""
    query = update.callback_query
    await query.answer()
    
    # Extract the order_id from the callback data
    # Format is "select_order_XXXX" where XXXX is the order ID
    callback_data = query.data
    order_id = callback_data.replace("select_order_", "")
    
    # Store the order ID in user data
    context.user_data['track_order_id'] = order_id
    
    # Process the selected order
    return await track_order(update, context)

async def enter_order_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt the user to enter an order ID manually."""
    query = update.callback_query
    await query.answer()
    
    prompt_message = (
        f"{EMOJI['id']} <b>Enter Order ID</b>\n\n"
        f"Please type your order ID below.\n"
        f"Your order ID can be found in your order confirmation message."
    )
    
    # Add cancel button
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_tracking")]]
    
    await query.edit_message_text(
        prompt_message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    
    return TRACK_ORDER

async def cancel_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the order tracking process."""
    query = update.callback_query
    await query.answer()
    
    # Clear tracking data
    if 'track_order_id' in context.user_data:
        del context.user_data['track_order_id']
    
    await query.edit_message_text(
        f"{EMOJI['cancel']} <b>Tracking Canceled</b>\n\n"
        f"You've canceled the order tracking process.\n"
        f"You can start again with the /track command anytime.",
        parse_mode=ParseMode.HTML
    )
    
    return ConversationHandler.END

# Around line 4210
async def handle_payment_screenshot(
    update: Update, context: ContextTypes.DEFAULT_TYPE, 
    google_apis, order_manager, loggers
):
    """
    Handle payment screenshot submission.
    
    Args:
        update: Telegram update
        context: Conversation context
        google_apis: GoogleAPIsManager instance
        order_manager: OrderManager instance
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state
    """
    if update.message.photo:
        user = update.message.from_user
        
        try:
            # Check rate limits
            if not check_rate_limit(context, user.id, "payment"):
                await update.message.reply_text(
                    f"{EMOJI['warning']} You've reached the maximum number of payments allowed per hour. "
                    "Please try again later."
                )
                return PAYMENT
            
            # First, send a processing message to indicate the bot is working
            processing_msg = await update.message.reply_text(
                f"{EMOJI['info']} Processing your payment screenshot and creating your order...\n"
                f"This may take a moment, please wait."
            )
            
            # Download photo
            photo = update.message.photo[-1]  # Get the largest photo
            file = await photo.get_file()
            file_bytes = await file.download_as_bytearray()
            
            # Validate the image
            is_valid, message = validate_image(file_bytes)
            if not is_valid:
                await update.message.reply_text(
                    f"{EMOJI['error']} {message}\n\n"
                    "Please send a valid image file for your payment screenshot."
                )
                return PAYMENT
            
            # Generate filename
            current_date = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            user_name = context.user_data.get("name", "Unknown")
            filename = f"Order_{current_date}_{sanitize_input(user_name)}.jpg"
            
            # Log progress for debugging
            print(f"DEBUG: Uploading payment screenshot for user {user.id}")
            loggers["main"].info(f"Processing payment screenshot for {user.id}")
            
            # Upload to Drive with extra error handling
            try:
                file_url = await google_apis.upload_payment_screenshot(file_bytes, filename)
                print(f"DEBUG: Screenshot uploaded successfully, URL: {file_url[:20]}...")
            except Exception as upload_error:
                loggers["errors"].error(f"Failed to upload payment screenshot: {str(upload_error)}")
                await update.message.reply_text(
                    f"{EMOJI['error']} There was a problem uploading your payment screenshot. "
                    "Please try again or contact support."
                )
                return PAYMENT
            
            # Store user telegram ID
            context.user_data["telegram_id"] = user.id
            
            # Validate cart and required details
            if not context.user_data.get("cart"):
                await update.message.reply_text(MESSAGES["empty_cart"])
                return PAYMENT
                
            required_fields = ["name", "address", "contact", "cart"]
            missing_fields = [field for field in required_fields if not context.user_data.get(field)]
            
            if missing_fields:
                loggers["errors"].error(f"Missing required fields for order: {missing_fields}")
                await update.message.reply_text(
                    f"{EMOJI['error']} Missing information required for order: {', '.join(missing_fields)}.\n"
                    "Please restart your order process with /start."
                )
                return ConversationHandler.END
            
            # Create order in system with enhanced logging
            print(f"DEBUG: Creating order in system for user {user.id}")
            order_id, success = await order_manager.create_order(
                context, context.user_data, file_url
            )
            
            if success and order_id:
                # Clear the cart
                manage_cart(context, "clear")
                
                # Clear conversation state markers to prevent incorrect timeout recovery
                context.user_data.pop("category", None)
                context.user_data.pop("strain_type", None) 
                context.user_data.pop("current_location", None)
                
                # Set order completion markers
                context.user_data["last_completed_order"] = order_id
                context.user_data["order_completion_time"] = time.time()  # Record completion time
                context.user_data["last_activity_time"] = time.time()  # Update activity time
                
                # Delete the processing message
                try:
                    await processing_msg.delete()
                except Exception:
                    pass  # Ignore if can't delete
                
                # Confirm to user
                await update.message.reply_text(
                    MESSAGES["order_confirmation"].format(order_id)
                )
                
                # Log the payment receipt
                loggers["payments"].info(
                    f"Payment screenshot received for order {order_id} from user {user.id}"
                )
                
                return ConversationHandler.END             
            else:
                # Log detailed error
                loggers["errors"].error(
                    f"Order creation failed for user {user.id}. "
                    f"Cart items: {len(context.user_data.get('cart', []))} "
                    f"Has file URL: {'Yes' if file_url else 'No'}"
                )
                
                # Delete the processing message
                try:
                    await processing_msg.delete()
                except Exception:
                    pass  # Ignore if can't delete
                
                # Send error message
                await update.message.reply_text(
                    f"{EMOJI['error']} There was a problem processing your order. "
                    "Please try again or contact customer support."
                )
                return PAYMENT
                
        except Exception as e:
            # Log detailed error
            loggers["errors"].error(f"Payment processing error: {str(e)}")
            
            # Send user-friendly error
            await update.message.reply_text(ERRORS["payment_processing"])
            return PAYMENT
    else:
        await update.message.reply_text(MESSAGES["invalid_payment"])
        return PAYMENT
    
def validate_image(file_bytes, max_size_mb=5):
    """
    Validate an uploaded image for security.
    
    Args:
        file_bytes (ByteArray): Raw image data
        max_size_mb (int): Maximum allowed size in MB
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if not file_bytes:
        return False, "Empty file data received"
        
    # Check file size
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > max_size_mb:
        return False, f"File too large: {size_mb:.1f}MB (max {max_size_mb}MB)"
    
    # Check minimum size to ensure it's not an empty or corrupt image
    if len(file_bytes) < 1000:  # Less than 1KB
        return False, "File too small - might be corrupt or empty"
    
    try:
        # Check file signature (magic numbers)
        # JPEG signature
        if file_bytes[:3] == b'\xFF\xD8\xFF':
            return True, "JPEG image"
        
        # PNG signature
        if file_bytes[:8] == b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A':
            return True, "PNG image"
        
        # GIF signature
        if file_bytes[:6] in (b'GIF87a', b'GIF89a'):
            return True, "GIF image"
        
        # WebP signature
        if len(file_bytes) > 12 and file_bytes[:4] == b'RIFF' and file_bytes[8:12] == b'WEBP':
            return True, "WebP image"
        
        # No valid signature found
        return False, "Invalid image format (only JPEG, PNG, GIF, and WebP images are allowed)"
        
    except Exception as e:
        return False, f"Error validating image: {str(e)}"
    
async def track_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Track the status of an order.
    
    Args:
        update: Telegram update object
        context: Context object
        
    Returns:
        int: Next conversation state
    """
    # Get the order ID from context (if set by a previous step)
    order_id = context.user_data.get('track_order_id')
    
    # Determine if this is a callback query or a direct message
    is_callback = update.callback_query is not None
    
    # If no order ID is set, prompt the user to enter one
    if not order_id:
        if is_callback:
            await update.callback_query.edit_message_text(
                f"{EMOJI['search']} Please enter your Order ID to track its status:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Main Menu", callback_data="start")]
                ])
            )
        else:
            await update.message.reply_text(
                f"{EMOJI['search']} Please enter your Order ID to track its status:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Main Menu", callback_data="start")]
                ])
            )
        return TRACK_ORDER
    
    try:
        # Initialize sheets
        sheet, _ = await google_apis.initialize_sheets()
        if not sheet:
            error_message = f"{EMOJI['error']} Failed to access order data. Please try again later."
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Main Menu", callback_data="start")]
            ])
        
            if is_callback:
                await update.callback_query.edit_message_text(error_message, reply_markup=reply_markup)
            else:
                await update.message.reply_text(error_message, reply_markup=reply_markup)
            return ConversationHandler.END
        
        # Get orders
        orders = sheet.get_all_records()
        
        # Find the order
        found_order = None
        for order in orders:
            if order.get('Order ID') == order_id and order.get('Product') == "COMPLETE ORDER":
                found_order = order
                break
        
        if not found_order:
            error_message = MESSAGES["order_not_found"].format(order_id)
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Main Menu", callback_data="start")]
            ])
            
            if is_callback:
                await update.callback_query.edit_message_text(error_message, reply_markup=reply_markup)
            else:
                await update.message.reply_text(error_message, reply_markup=reply_markup)
            
            context.user_data.pop('track_order_id', None)
            return ConversationHandler.END
        
        # Get order details
        status = found_order.get('Status', 'Pending')
        order_date = found_order.get('Order Date', 'Unknown')
        notes = found_order.get('Notes', '')
        price = found_order.get('Price', '₱0')
        tracking_link = found_order.get('Tracking Link', '')
        
        # Parse the notes field to extract items
        items_text = ""
        if notes:
            # Split notes by line
            items_list = [line.strip() for line in notes.split('\n') if line.strip()]
            
            # Format each item line
            for item in items_list:
                # Remove any leading bullets or markers
                clean_item = item.lstrip('•').strip()
                
                # Check if this is an actual item line
                if 'x ' in clean_item and ':' in clean_item:
                    try:
                        # Extract quantity, product, and price
                        quantity_part, rest = clean_item.split('x ', 1)
                        product_info, price_part = rest.split(':', 1)
                        
                        # Clean up any extra spaces
                        quantity = quantity_part.strip()
                        product = product_info.strip()
                        
                        # Format price more cleanly
                        price_match = re.search(r'(₱[\d,]+\.\d{2})', price_part)
                        price_str = price_match.group(1) if price_match else price_part.strip()
                        
                        # Check for strain in parentheses
                        if "(" in product and ")" in product:
                            product_name, strain_info = product.split("(", 1)
                            strain_info = strain_info.rstrip(")")
                            # Format as Product - Strain
                            items_text += f"• {quantity}x {product_name.strip()} - {strain_info} - {price_str}\n"
                        else:
                            items_text += f"• {quantity}x {product} - {price_str}\n"
                    except Exception as e:
                        # If parsing fails, just use the original line
                        items_text += f"• {clean_item}\n"
                        loggers["errors"].warning(f"Error parsing item line: {e}")
                else:
                    # Not a standard item line, include as is
                    items_text += f"• {clean_item}\n"
        
        if not items_text:
            items_text = "• No detailed items found"
        
        # Create the tracking message
        message = (
            f"{EMOJI['package']} <b>Order Status Update</b>\n\n"
            f"{EMOJI['id']} Order ID: {order_id}\n"
            f"{EMOJI['date']} Ordered on: {order_date}\n"
            f"{EMOJI['status']} Status: {status}\n"
            f"{EMOJI['cart']} Items:\n{items_text}\n"
            f"{EMOJI['money']} Total: {price}\n"
        )
        
        # Add tracking link if available
        if tracking_link:
            message += f"\n{EMOJI['link']} <b>Track your delivery:</b> {tracking_link}\n"
        
        # Add contextual hints based on status
        status_lower = status.lower()
        if "pending" in status_lower or "processing" in status_lower:
            message += (
                f"\n{EMOJI['info']} Your order is being processed. "
                f"We'll update you when it ships!"
            )
        elif "payment" in status_lower and "rejected" in status_lower:
            message += (
                f"\n{EMOJI['warning']} Your payment was rejected. "
                f"Please contact support for assistance."
            )
        elif "payment" in status_lower and "pending" in status_lower:
            message += (
                f"\n{EMOJI['info']} We're waiting for your payment confirmation. "
                f"Please complete payment to proceed."
            )
        elif "shipped" in status_lower or "transit" in status_lower:
            message += (
                f"\n{EMOJI['truck']} Your order is on its way! "
                f"Use the tracking link above to follow your delivery."
            )
        elif "delivered" in status_lower or "completed" in status_lower:
            message += (
                f"\n{EMOJI['party']} Your order has been delivered! "
                f"Thank you for shopping with us."
            )
        
        # Create the keyboard buttons
        keyboard = get_common_buttons("tracking_options", order_id)
        
        # Use a try-except block for sending the message to handle potential errors
        try:
            # Check if this is a refresh and if the content is the same
            force_update = context.user_data.pop("force_message_update", False)
    
            # Add a timestamp to force the message to be different if needed
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            if force_update:
                # Add a small invisible character or timestamp to force an update
                message += f"\n\n<i>Last updated: {current_time}</i>"
    
            if is_callback:
                # If this is a callback, check if message text is the same before updating
                original_text = context.user_data.get("original_message_text", "")
                if original_text == message and not force_update:
                    # Message is identical - don't attempt to edit, just answer the callback
                    loggers["main"].info(f"Skipping identical message update for order {order_id}")
                else:
                    # Message is different or we're forcing an update - proceed with edit
                    await update.callback_query.edit_message_text(
                        message,
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        disable_web_page_preview=True
                )
            else:
                await update.message.reply_text(
                    message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    disable_web_page_preview=True
            )
        except TelegramError as e:
            # Check if this is a "message not modified" error, which we can safely ignore
            if "message is not modified" in str(e).lower():
                loggers["main"].info(f"Message for order {order_id} was not modified (identical content)")
            else:
                # Log other Telegram errors
                loggers["errors"].error(f"Failed to send tracking info to user {update.effective_user.id}: {e}")
                # Send a simpler fallback message
                try:
                    if is_callback:
                        await update.callback_query.edit_message_text(
                            f"Order {order_id} status: {status}. There was an error displaying the full tracking information.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Try Again", callback_data=f"refresh_tracking_{order_id}")]])
                        )
                    else:
                        await update.message.reply_text(
                            f"Order {order_id} status: {status}. There was an error displaying the full tracking information.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Try Again", callback_data=f"refresh_tracking_{order_id}")]])
                        )
                except:
                    pass  # Last resort - at least we logged the error
    except Exception as e:
        # Log the error using your logging system
        loggers["errors"].error(f"Error accessing sheet data: {str(e)}")
    
        # Prepare user-friendly error message
        error_message = f"{EMOJI['error']} An unexpected error occurred while accessing your order. Please try again later."
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{EMOJI['back']} Back to Main Menu", callback_data="start")]
        ])
    
        # Send error message based on update type
        try:
            if is_callback:
                await update.callback_query.edit_message_text(error_message, reply_markup=reply_markup)
            else:
                await update.message.reply_text(error_message, reply_markup=reply_markup)
        except Exception as send_error:
            loggers["errors"].error(f"Failed to send error message: {str(send_error)}")
    
        return ConversationHandler.END

async def get_order_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the order ID input from the user."""
    user_id = update.effective_user.id
    order_id = update.message.text.strip()
    
    # Validate the order ID format
    if not is_valid_order_id(order_id):
        await update.message.reply_text(
            f"{EMOJI['error']} <b>Invalid Order ID</b>\n\n"
            f"The order ID you entered doesn't appear to be valid.\n"
            f"Please check your order confirmation and try again.",
            parse_mode=ParseMode.HTML
        )
        return TRACK_ORDER
    
    # Store the order ID in user data
    context.user_data['track_order_id'] = order_id
    
    # Log the tracking request
    logging.info(f"User {user_id} tracking order {order_id}")
    
    # Process the tracked order immediately
    # No need to get order details here as track_order will handle that
    return await track_order(update, context)

async def refresh_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for refreshing order tracking status.
    
    Args:
        update: Telegram update object
        context: Context object
        
    Returns:
        int: Next conversation state
    """
    query = update.callback_query
    await query.answer()
    
    # Extract order ID from callback data
    order_id = query.data.replace('refresh_tracking_', '')
    
    # Store the order ID in context
    if "track_order_id" not in context.user_data:
        context.user_data["track_order_id"] = order_id
    else:
        # Update the order ID only if it's different
        context.user_data["track_order_id"] = order_id
    
    # Store the original message text for comparison later
    if query.message:
        context.user_data["original_message_text"] = query.message.text
        context.user_data["force_message_update"] = True
    
    # Call track_order with the proper update
    return await track_order(update, context)

async def handle_order_tracking(
    update: Update, context: ContextTypes.DEFAULT_TYPE, 
    order_manager, loggers
):
    """
    Handle the order tracking response with dynamic status messages.
    
    Args:
        update: Telegram update
        context: Conversation context
        order_manager: OrderManager instance
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state
    """
    user = update.message.from_user
    order_id = update.message.text.strip()
    
    # Get order status
    status, tracking_link, order_details = await order_manager.get_order_status(order_id)
    
    if not status or not order_details:
        await update.message.reply_text(ERRORS["tracking_not_found"])
        return TRACKING
    
    # Get order details
    total = order_details.get('Price', '₱0')
    date = order_details.get('Order Date', 'N/A')
    product_summary = order_details.get('Notes', 'Multiple items')
    
    # Get status message components
    status_emoji, status_message = get_status_message(status, tracking_link)
    
    # Create a dynamic status message
    response_text = (
        f"{MESSAGES['order_status_heading']}\n\n"
        f"{EMOJI['id']} Order ID: {order_id}\n"
        f"{EMOJI['date']} Ordered on: {date}\n"
        f"{EMOJI['cart']} Items: {product_summary}\n"
        f"{EMOJI['money']} Total: {total}\n\n"
        f"{status_emoji} Current Status: {status}\n\n"
        f"{status_message}\n\n"
    )
    
    # Add tracking link section if available and order is booked
    if tracking_link and "booked" in status.lower():
        response_text += (
            f"{EMOJI['tracking']} Track your delivery: {tracking_link}\n\n"
        )
    
    response_text += f"{EMOJI['thanks']} Thank you for ordering with Ganja Paraiso! If you have any questions, feel free to contact us."
    
    # Log the successful tracking
    loggers["main"].info(f"User {user.id} tracked order {order_id}")
    
    try:
        await update.message.reply_text(response_text)
    except TelegramError as e:
        loggers["errors"].error(f"Failed to send tracking response: {e}")
        # Send simplified message as fallback
        await update.message.reply_text(
            f"Order {order_id} status: {status}. Use the /track command again if you need more details."
        )
    
    return ConversationHandler.END

# ---------------------------- Admin Panel ----------------------------
class AdminPanel:
    """Handles all admin panel functionality."""
    
    def __init__(self, bot, admin_ids, google_apis, order_manager, loggers):
        """
        Initialize the Admin Panel.
        
        Args:
            bot: The Telegram bot instance
            admin_ids: List of Telegram IDs of admin users
            google_apis: GoogleAPIsManager instance
            order_manager: OrderManager instance
            loggers: Dictionary of logger instances
        """
        self.bot = bot
        self.admin_ids = admin_ids if isinstance(admin_ids, list) else [admin_ids]
        self.google_apis = google_apis
        self.order_manager = order_manager
        self.loggers = loggers
        
    async def show_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Display the admin panel main menu."""
        user = update.message.from_user
    
        # Check if user is authorized
        if user.id not in self.admin_ids:
            await update.message.reply_text(MESSAGES["not_authorized"])
            self.loggers["admin"].warning(f"Unauthorized admin panel access attempt by user {user.id}")
            return
    
        # Check rate limits
        if not check_rate_limit(context, user.id, "admin"):
            await update.message.reply_text(
                f"{EMOJI['warning']} You've reached the maximum number of admin actions allowed per hour. "
                "Please try again later."
            )
            return
    
        # Log the admin panel access
        self.loggers["admin"].info(f"Admin {user.id} accessed admin panel")
    
        # Send welcome message with options
        await update.message.reply_text(
            MESSAGES["admin_welcome"],
            reply_markup=self._build_admin_buttons()
        )
    
    def _build_admin_buttons(self):
        """Create the admin panel main menu buttons."""
        keyboard = [
            [InlineKeyboardButton(f"{EMOJI['list']} View All Orders", callback_data='view_orders')],
            [InlineKeyboardButton(f"{EMOJI['search']} Search Order by ID", callback_data='search_order')],
            [InlineKeyboardButton(f"{EMOJI['inventory']} Manage Inventory", callback_data='manage_inventory')],
            [InlineKeyboardButton(f"{EMOJI['review']} Review Payments", callback_data='approve_payments')]
        ]
        
        return InlineKeyboardMarkup(keyboard)
        
    async def view_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Display all orders with filtering options.
        
        Args:
            update: Telegram update
            context: Conversation context
        """
        query = update.callback_query
        await query.answer()
        
        # Get filter from context or set default
        status_filter = context.user_data.get('status_filter', 'all')
        
        # Initialize sheets
        sheet, _ = await self.google_apis.initialize_sheets()
        if not sheet:
            await query.edit_message_text(
                f"{EMOJI['error']} Failed to access order data. Please try again later.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Admin Panel", callback_data='back_to_admin')]
                ])
            )
            return
        
        # Get orders
        orders = sheet.get_all_records()
        
        # Filter for main order entries only (COMPLETE ORDER)
        main_orders = []
        for order in orders:
            if 'Product' in order and order['Product'] == "COMPLETE ORDER":
                main_orders.append(order)
        
        # Apply status filter if not 'all'
        if status_filter != 'all':
            filtered_orders = []
            for order in main_orders:
                if 'Status' in order and order['Status'].lower() == status_filter.lower():
                    filtered_orders.append(order)
            main_orders = filtered_orders
        
        # Sort orders by date (newest first) if date field exists
        if main_orders and 'Order Date' in main_orders[0]:
            main_orders.sort(key=lambda x: x.get('Order Date', ''), reverse=True)
        
        # Check if we have orders to display
        if not main_orders:
            # Create filter buttons
            filter_buttons = self._build_filter_buttons(status_filter)
            keyboard = filter_buttons + [
                [create_button("back", "back_to_admin", "Back to Admin Panel")]
            ]
            
            await query.edit_message_text(
                f"No orders found with status filter: {status_filter}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # Create the orders message (showing up to 5 orders)
        message = f"{EMOJI['list']} Orders (Filter: {status_filter.upper()}):\n\n"
        
        display_orders = main_orders[:5]  # Limit to 5 orders to avoid message size limits
        
        # Create order buttons
        order_buttons = []
        for order in display_orders:
            order_id = order.get('Order ID', 'Unknown')
            customer = order.get('Customer Name', order.get('Name', 'Unknown Customer'))
            status = order.get('Status', 'Unknown')
            date = order.get('Order Date', 'N/A')
            total = order.get('Price', order.get('Total Price', '₱0'))
            
            # Add order summary to message
            message += (
                f"{EMOJI['id']} {order_id}\n"
                f"{EMOJI['customer']} {customer}\n"
                f"{EMOJI['money']} {total}\n"
                f"{EMOJI['date']} {date}\n"
                f"{EMOJI['status']} Status: {status}\n"
                f"------------------------\n"
            )
            
            # Add button for this order
            order_buttons.append([
                InlineKeyboardButton(
                    f"Manage: {order_id}", 
                    callback_data=f'manage_order_{order_id}'
                )
            ])
        
        # Create navigation buttons if there are more orders
        nav_buttons = []
        if len(main_orders) > 5:
            nav_buttons = [[
                InlineKeyboardButton("◀️ Previous", callback_data="prev_orders"),
                InlineKeyboardButton("Next ▶️", callback_data="next_orders")
            ]]
        
        # Create filter buttons
        filter_buttons = self._build_filter_buttons(status_filter)
        
        # Combine all buttons
        keyboard = (
            order_buttons + 
            nav_buttons + 
            filter_buttons + 
            [[create_button("back", "back_to_admin", "Back to Admin Panel")]]
        )
        
        self.loggers["admin"].info(f"Admin viewed orders with filter: {status_filter}")
        
        await query.edit_message_text(
            message, 
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    def _build_filter_buttons(self, current_filter):
        """
        Helper function to build status filter buttons.
        
        Args:
            current_filter: Current selected filter
            
        Returns:
            list: Rows of filter buttons
        """
        filters = [
            ("All", "filter_all"),
            ("Pending Payment", "filter_pending_payment_review"),
            ("Payment Confirmed", "filter_payment_confirmed_and_preparing_order"),
            ("Booking", "filter_booking"),
            ("Booked", "filter_booked"),
            ("Delivered", "filter_delivered")
        ]
        
        # Create filter buttons (maximum 3 per row)
        filter_buttons = []
        current_row = []
        
        for label, callback_data in filters:
            # Mark the current filter
            if (current_filter == 'all' and callback_data == 'filter_all') or \
               (callback_data[7:] == current_filter):
                label = f"✓ {label}"
            
            current_row.append(InlineKeyboardButton(label, callback_data=callback_data))
            
            # Start a new row after 3 buttons
            if len(current_row) == 3:
                filter_buttons.append(current_row)
                current_row = []
        
        # Add any remaining buttons
        if current_row:
            filter_buttons.append(current_row)
        
        return filter_buttons
    
    async def manage_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE, order_id=None):
        """
        Show order details and management options.
        
        Args:
            update: Telegram update
            context: Conversation context
            order_id: Optional order ID if not from callback query
        """
        # Determine if this was called from a callback query
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            
            # Extract order ID from callback data if not provided
            if not order_id:
                order_id = query.data.replace('manage_order_', '')
            
            # Store order ID in context
            context.user_data['current_order_id'] = order_id
        
        # Get the order details
        order_details = await self.order_manager.get_order_details(order_id)
        
        if not order_details:
            # Prepare error message
            error_message = MESSAGES["order_not_found"].format(order_id)
            back_button = create_button_layout([
                [create_button("back", "view_orders", "Back to Orders")]
            ])
            
            # Send or edit the message based on update type
            if update.callback_query:
                await update.callback_query.edit_message_text(error_message, reply_markup=back_button)
            else:
                await update.message.reply_text(error_message, reply_markup=back_button)
            return
        
        # Create detailed order message with safe gets
        customer = order_details.get('Customer Name', order_details.get('Name', 'Unknown'))
        address = order_details.get('Address', 'No address provided')
        contact = order_details.get('Contact', order_details.get('Phone', 'No contact provided'))
        status = order_details.get('Status', 'Unknown')
        date = order_details.get('Order Date', 'N/A')
        total = order_details.get('Price', order_details.get('Total Price', '₱0'))
        payment_url = order_details.get('Payment URL', 'N/A')
        tracking_link = order_details.get('Tracking Link', '')
        
        message = (
            f"{EMOJI['search']} Order Details: {order_id}\n\n"
            f"{EMOJI['customer']} Customer: {customer}\n"
            f"{EMOJI['phone']} Contact: {contact}\n"
            f"{EMOJI['address']} Address: {address}\n"
            f"{EMOJI['date']} Date: {date}\n"
            f"{EMOJI['status']} Status: {status}\n"
            f"{EMOJI['money']} Total: {total}\n\n"
        )
        
        # Add tracking link if available
        if tracking_link:
            message += f"{EMOJI['link']} Tracking: {tracking_link}\n\n"
        
        # Add order items from Notes field
        message += f"{EMOJI['cart']} Items:\n{order_details.get('Notes', '• No detailed items found')}\n"
        
        # Create management buttons
        keyboard = [
            [create_button("action", f'update_status_{order_id}', f"{EMOJI['update']} Update Status")],
            [create_button("action", f'add_tracking_{order_id}', f"{EMOJI['link']} Add/Update Tracking")],
            [create_button("action", f'view_payment_{order_id}', f"{EMOJI['screenshot']} View Payment Screenshot")]
        ]

        # Add back button
        keyboard.append([create_button("back", "view_orders", "Back to Orders")])
        
        self.loggers["admin"].info(f"Admin viewing order details for {order_id}")
        
        # Send or edit the message based on update type
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                disable_web_page_preview=True  # Prevent tracking links from generating previews
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                disable_web_page_preview=True
            )
    
    async def view_payment_screenshot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Send the payment screenshot to the admin.
        
        Args:
            update: Telegram update
            context: Conversation context
        """
        query = update.callback_query
        await query.answer()
        
        # Get order ID from context or callback data
        order_id = context.user_data.get('current_order_id')
        if not order_id:
            order_id = query.data.replace('view_payment_', '')
        
        # Get order details
        order_details = await self.order_manager.get_order_details(order_id)
        
        if not order_details:
            await query.edit_message_text(
                MESSAGES["order_not_found"].format(order_id),
                reply_markup=create_button_layout([
                    [create_button("back", "view_orders", "Back to Orders")]
                ])
            )
            return
        
        # Find payment URL
        payment_url = order_details.get('Payment URL')
        
        if not payment_url:
            await query.edit_message_text(
                ERRORS["no_screenshot"],
                reply_markup=create_button_layout([
                    [create_button("back", f'manage_order_{order_id}', "Back to Order")]
                ])
            )
            return
        
        self.loggers["admin"].info(f"Admin viewed payment screenshot for order {order_id}")
        
        # Send the payment URL
        await query.edit_message_text(
            f"{EMOJI['screenshot']} Payment Screenshot for Order {order_id}:\n\n"
            f"Link: {payment_url}\n\n"
            "You can view the screenshot by clicking the link above.",
            reply_markup=create_button_layout([
                [create_button("back", f'manage_order_{order_id}', "Back to Order")]
            ])
        )
    
    async def update_order_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle updating order status from admin panel.
        
        Args:
            update: Telegram update
            context: Conversation context
        """
        query = update.callback_query
        await query.answer()
        
        # Extract the order ID from callback data
        order_id = query.data.replace('update_status_', '')
        
        # Store the order ID in context for later use
        context.user_data['current_order_id'] = order_id
        
        # Provide status options based on STATUS dictionary
        keyboard = []
        
        for status_key, status_info in STATUS.items():
            label = status_info["label"]
            emoji = status_info["emoji"]
            keyboard.append([
                InlineKeyboardButton(f"{emoji} {label}", callback_data=f'set_status_{status_key}')
            ])
        
        # Add back button
        keyboard.append([
            create_button("back", f'manage_order_{order_id}', "Back to Order")
        ])
        
        self.loggers["admin"].info(f"Admin preparing to update status for order {order_id}")
        
        await query.edit_message_text(
            f"Select new status for Order {order_id}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def set_order_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Set the new status for an order and notify the customer.
        
        Args:
            update: Telegram update
            context: Conversation context
        """
        query = update.callback_query
        await query.answer()
        
        # Get the order ID and status key
        order_id = context.user_data.get('current_order_id')
        status_key = query.data.replace('set_status_', '')
        
        if not order_id:
            await query.edit_message_text(
            reply_markup=create_button_layout([
                [create_button("back", "back_to_admin", "Back to Admin Panel")]
            ])
        )
            return
        
        # Get the label for this status
        if status_key in STATUS:
            new_status = STATUS[status_key]["label"]
        else:
            new_status = status_key.replace('_', ' ').title()
        
        # If status is being set to "Booked", prompt for tracking
        if status_key.lower() == "booked":
            context.user_data['pending_status'] = new_status
            await query.edit_message_text(
                f"You're setting Order {order_id} to '{new_status}'.\n\n"
                f"Would you like to add a tracking link?",
                reply_markup=create_button_layout([
                    [create_button("action", "add_tracking_link", "Yes, Add Tracking Link")],
                    [create_button("action", "skip_tracking_link", "No, Skip Tracking Link")]
                ])
            )
            return
        
        # For other statuses, proceed with the update directly
        success = await self.order_manager.update_order_status(context, order_id, new_status)
        
        self.loggers["admin"].info(f"Admin updated order {order_id} status to {new_status}")
        
        if success:
            keyboard = [
                [create_button("action", f'manage_order_{order_id}', "View Order Details")],
                [create_button("back", "view_orders", "Back to Orders")]
            ]
            
            await query.edit_message_text(
                MESSAGES["status_updated"].format(new_status, order_id),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(
                ERRORS["update_failed"].format(order_id),
                reply_markup=create_button_layout([
                    [create_button("back", "view_orders", "Back to Orders")]
                ])
            )
    
    async def add_tracking_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle adding or updating tracking link.
        
        Args:
            update: Telegram update
            context: Conversation context
            
        Returns:
            int: Next conversation state or None
        """
        query = update.callback_query
        await query.answer()
        
        # Get the order ID from context or callback data
        order_id = context.user_data.get('current_order_id')
        if not order_id:
            order_id = query.data.replace('add_tracking_', '')
            context.user_data['current_order_id'] = order_id
        
        # Store that we're waiting for a tracking link
        context.user_data['awaiting_tracking_link'] = True
        context.user_data['tracking_source'] = 'direct'  # vs. from status update
        
        await query.edit_message_text(
            f"Please send the tracking link for Order {order_id} as a message.\n\n"
            f"Example: https://share.lalamove.com/...\n\n"
            f"Type 'skip' to continue without adding a link.",
            reply_markup=create_button_layout([
                [create_button("cancel", f'manage_order_{order_id}', "Cancel")]
            ])
        )
        
        return ADMIN_TRACKING
    
    async def receive_tracking_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle receiving a tracking link from admin's message.
        
        Args:
            update: Telegram update
            context: Conversation context
            
        Returns:
            None
        """
        # Only process if we're waiting for a tracking link
        if not context.user_data.get('awaiting_tracking_link'):
            return
        
        # Clear the flag
        context.user_data['awaiting_tracking_link'] = False
        
        user = update.message.from_user
        
        # Get the tracking link from the message
        tracking_link = sanitize_input(update.message.text.strip(), 200)
        
        # Skip if the admin typed 'skip'
        if tracking_link.lower() == 'skip':
            tracking_link = ""
        
        # Get the stored order details
        order_id = context.user_data.get('current_order_id')
        
        if not order_id:
            await update.message.reply_text(f"{EMOJI['error']} Error: Missing order details.")
            return
        
        # Check if this is from a status update or direct tracking link addition
        tracking_source = context.user_data.get('tracking_source', 'direct')
        
        if tracking_source == 'direct':
            # Update just the tracking link
            status, _, _ = await self.order_manager.get_order_status(order_id)
            
            if not status:
                await update.message.reply_text(MESSAGES["order_not_found"].format(order_id))
                return
            
            # Update both status and tracking
            success = await self.order_manager.update_order_status(context, order_id, status, tracking_link)
            
            self.loggers["admin"].info(f"Admin added tracking link for order {order_id}")
            
            if success:
                keyboard = [
                    [create_button("action", f'manage_order_{order_id}', "View Order Details")],
                    [create_button("back", "view_orders", "Back to Orders")]
                ]
                
                await update.message.reply_text(
                    MESSAGES["tracking_updated"].format(order_id),
                    reply_markup=create_button_layout(keyboard)
                )
            else:
                await update.message.reply_text(ERRORS["update_failed"].format(order_id))
            
        else:
            # This is from a status update
            new_status = context.user_data.get('pending_status')
            
            if not new_status:
                await update.message.reply_text(f"{EMOJI['error']} Error: Missing status information.")
                return
            
            # Update both status and tracking link
            success = await self.order_manager.update_order_status(context, order_id, new_status, tracking_link)
            
            self.loggers["admin"].info(f"Admin updated order {order_id} status to {new_status} with tracking")
            
            if success:
                keyboard = [
                    [create_button("action", f'manage_order_{order_id}', "View Order Details")],
                    [create_button("back", "view_orders", "Back to Orders")]
                ]
                
                await update.message.reply_text(
                    f"{MESSAGES['status_updated'].format(new_status, order_id)} with tracking link.",
                    reply_markup=create_button_layout(keyboard)
                )
            else:
                await update.message.reply_text(ERRORS["update_failed"].format(order_id))
    
    async def skip_tracking_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Skip adding a tracking link and proceed with the status update.
        
        Args:
            update: Telegram update
            context: Conversation context
        """
        query = update.callback_query
        await query.answer()
        
        order_id = context.user_data.get('current_order_id')
        new_status = context.user_data.get('pending_status')
        
        if not order_id:
            await query.edit_message_text(f"{EMOJI['error']} Error: Missing order details.")
            return
        
        # If this is from a status update
        if new_status:
            success = await self.order_manager.update_order_status(context, order_id, new_status, "")
            
            self.loggers["admin"].info(f"Admin updated order {order_id} status to {new_status} without tracking")
            
            if success:
                keyboard = [
                    [create_button("action", f'manage_order_{order_id}', "View Order Details")],
                    [create_button("back", "view_orders", "Back to Orders")]
                ]
                
                await query.edit_message_text(
                    MESSAGES["status_updated"].format(new_status, order_id),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await query.edit_message_text(
                    ERRORS["update_failed"].format(order_id),
                    reply_markup=create_button_layout([
                        [create_button("back", "view_orders", "Back to Orders")]
                    ])
                )
        else:
            # Direct tracking link update was cancelled
            await query.edit_message_text(
                f"Tracking link update cancelled for Order {order_id}.",
                reply_markup=create_button_layout([
                    [create_button("back", f'manage_order_{order_id}', "Back to Order")]
                ])
            )
            
    async def back_to_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Return to the admin panel.
        
        Args:
            update: Telegram update
            context: Conversation context
        """
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            MESSAGES["admin_welcome"],
            reply_markup=self._build_admin_buttons()
        )
        
    async def search_order_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Display a prompt for entering an order ID to search.
        
        Args:
            update: Telegram update
            context: Conversation context
            
        Returns:
            int: Next conversation state
        """
        query = update.callback_query
        await query.answer()
        
        # Let user know we're expecting an order ID
        await query.edit_message_text(
            f"{EMOJI['search']} Please enter the Order ID you want to search for:\n\n"
            f"Example: WW-1234-ABC",
            reply_markup=create_button_layout([
                [create_button("back", "back_to_admin", "Back to Admin Panel")]
            ])
        )
        
        # Set context to indicate we're waiting for an order ID
        context.user_data['awaiting_order_id'] = True
        
        # Return the ADMIN_SEARCH state to wait for text input
        return ADMIN_SEARCH
        
    async def handle_admin_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle order ID input for order searching.
        
        Args:
            update: Telegram update
            context: Conversation context
            
        Returns:
            int: Next conversation state
        """
        # Only process if we're awaiting an order ID
        if not context.user_data.get('awaiting_order_id', False):
            return
        
        # Clear the flag
        context.user_data['awaiting_order_id'] = False
        
        # Get the order ID from message
        order_id = update.message.text.strip()
        
        # Log the search attempt
        user = update.message.from_user
        self.loggers["admin"].info(f"Admin {user.id} searched for order {order_id}")
        
        # Get the order details directly and display using manage_order
        await self.manage_order(update, context, order_id)
        
        return ConversationHandler.END
    
    async def review_payments(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Display a list of orders with pending payment status for review.
        
        Args:
            update: Telegram update
            context: Conversation context
        """
        query = update.callback_query
        await query.answer()
        
        # Log the action
        user = query.from_user
        self.loggers["admin"].info(f"Admin {user.id} accessed payment review")
        
        # Initialize sheets
        sheet, _ = await self.google_apis.initialize_sheets()
        if not sheet:
            await query.edit_message_text(
                f"{EMOJI['error']} Failed to access order data. Please try again later.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Admin Panel", callback_data='back_to_admin')]
                ])
            )
            return
        
        # Get orders
        orders = sheet.get_all_records()
        
        # Filter for orders with pending payment status
        pending_payments = []
        for order in orders:
            if (order.get('Product') == "COMPLETE ORDER" and 
                order.get('Status', '').lower() == "pending payment review"):
                pending_payments.append(order)
        
        # Check if we have any pending payments
        if not pending_payments:
            await query.edit_message_text(
                f"{EMOJI['info']} No orders pending payment review at this time.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Admin Panel", callback_data='back_to_admin')]
                ])
            )
            return
        
        # Sort by date (newest first)
        pending_payments.sort(key=lambda x: x.get('Order Date', ''), reverse=True)
        
        # Create a message with pending payment orders (show up to 5)
        message = f"{EMOJI['payment']} Orders Pending Payment Review:\n\n"
        
        display_orders = pending_payments[:5]
        
        # Create order buttons
        payment_buttons = []
        for order in display_orders:
            order_id = order.get('Order ID', 'Unknown')
            customer = order.get('Customer Name', order.get('Name', 'Unknown Customer'))
            date = order.get('Order Date', 'N/A')
            total = order.get('Price', order.get('Total Price', '₱0'))
            
            # Add order summary to message
            message += (
                f"{EMOJI['id']} {order_id}\n"
                f"{EMOJI['customer']} {customer}\n"
                f"{EMOJI['money']} {total}\n"
                f"{EMOJI['date']} {date}\n"
                f"------------------------\n"
            )
            
            # Add button for this order
            payment_buttons.append([
                InlineKeyboardButton(
                    f"Review: {order_id}", 
                    callback_data=f'review_payment_{order_id}'
                )
            ])
        
        # Create navigation buttons if there are more orders
        nav_buttons = []
        if len(pending_payments) > 5:
            nav_buttons = [[
                InlineKeyboardButton("◀️ Previous", callback_data="prev_payments"),
                InlineKeyboardButton("Next ▶️", callback_data="next_payments")
            ]]
        
        # Combine all buttons
        keyboard = (
            payment_buttons + 
            nav_buttons + 
            [[InlineKeyboardButton(f"{EMOJI['back']} Back to Admin Panel", callback_data='back_to_admin')]]
        )
        
        await query.edit_message_text(
            message, 
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    async def review_specific_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Review a specific payment and provide options to approve or reject.
        
        Args:
            update: Telegram update
            context: Conversation context
        """
        query = update.callback_query
        await query.answer()
        
        # Extract order ID from callback data
        order_id = query.data.replace('review_payment_', '')
        
        # Store order ID in context
        context.user_data['current_order_id'] = order_id
        
        # Get order details
        order_details = await self.order_manager.get_order_details(order_id)
        
        if not order_details:
            await query.edit_message_text(
                MESSAGES["order_not_found"].format(order_id),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Payment Review", callback_data='approve_payments')]
                ])
            )
            return
        
        # Extract order information
        customer = order_details.get('Customer Name', order_details.get('Name', 'Unknown'))
        address = order_details.get('Address', 'No address provided')
        contact = order_details.get('Contact', order_details.get('Phone', 'No contact provided'))
        status = order_details.get('Status', 'Unknown')
        date = order_details.get('Order Date', 'N/A')
        total = order_details.get('Price', order_details.get('Total Price', '₱0'))
        payment_url = order_details.get('Payment URL', 'N/A')
        
        # Build message
        message = (
            f"{EMOJI['payment']} Payment Review: {order_id}\n\n"
            f"{EMOJI['customer']} Customer: {customer}\n"
            f"{EMOJI['phone']} Contact: {contact}\n"
            f"{EMOJI['address']} Address: {address}\n"
            f"{EMOJI['date']} Date: {date}\n"
            f"{EMOJI['status']} Status: {status}\n"
            f"{EMOJI['money']} Total: {total}\n\n"
            f"{EMOJI['screenshot']} Payment Screenshot: {payment_url}\n\n"
            f"{EMOJI['cart']} Items:\n{order_details.get('Notes', '• No detailed items found')}\n\n"
            f"Please verify the payment screenshot and select an action below:"
        )
        
        # Create action buttons
        keyboard = [
            [InlineKeyboardButton(f"{EMOJI['success']} Approve Payment", callback_data=f'approve_payment_{order_id}')],
            [InlineKeyboardButton(f"{EMOJI['error']} Reject Payment", callback_data=f'reject_payment_{order_id}')],
            [InlineKeyboardButton(f"{EMOJI['back']} Back to Payment Review", callback_data='approve_payments')]
        ]
        
        # Log the action
        self.loggers["admin"].info(f"Admin reviewing payment for order {order_id}")
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
        
    async def process_payment_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Process payment approval or rejection.
        
        Args:
            update: Telegram update
            context: Conversation context
        """
        query = update.callback_query
        await query.answer()
        
        # Determine action type and order ID
        action_data = query.data
        order_id = context.user_data.get('current_order_id')
        
        if not order_id:
            # Extract from callback data as fallback
            if action_data.startswith('approve_payment_'):
                order_id = action_data.replace('approve_payment_', '')
            elif action_data.startswith('reject_payment_'):
                order_id = action_data.replace('reject_payment_', '')
        
        if not order_id:
            await query.edit_message_text(
                f"{EMOJI['error']} Error: Order ID not found.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Admin Panel", callback_data='back_to_admin')]
                ])
            )
            return
        
        # Set new status based on action
        if action_data.startswith('approve_payment_'):
            new_status = STATUS["payment_confirmed"]["label"]
            action_type = "approved"
        elif action_data.startswith('reject_payment_'):
            new_status = STATUS["payment_rejected"]["label"]
            action_type = "rejected"
        else:
            await query.edit_message_text(
                f"{EMOJI['error']} Invalid action selected.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Admin Panel", callback_data='back_to_admin')]
                ])
            )
            return
        
        # Update order status
        success = await self.order_manager.update_order_status(context, order_id, new_status)
        
        if success:
            # Log the action
            self.loggers["admin"].info(f"Admin {action_type} payment for order {order_id}")
            
            keyboard = [
                [InlineKeyboardButton("Back to Payment Review", callback_data='approve_payments')],
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Admin Panel", callback_data='back_to_admin')]
            ]
            
            await query.edit_message_text(
                f"{EMOJI['success']} Payment for Order {order_id} has been {action_type}.\n\n"
                f"Status updated to: {new_status}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(
                ERRORS["update_failed"].format(order_id),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Admin Panel", callback_data='back_to_admin')]
                ])
            )

# ---------------------------- Error Handling and Middleware ----------------------------
class HealthCheckMiddleware:
    """Middleware to track response times and detect when the bot becomes unresponsive."""
    
    def __init__(self, bot, admin_ids, loggers):
        self.bot = bot
        self.admin_ids = admin_ids if isinstance(admin_ids, list) else [admin_ids]
        self.loggers = loggers
        self.response_times = deque(maxlen=100)  # Track the last 100 response times
        self.is_responding = True
        self.last_activity = time.time()
        self.watchdog_timer = None
        self.start_watchdog()
    
    async def on_pre_process_update(self, update: Update, data: dict):
        """Pre-process each update to record the start time."""
        # Store the start time in the data dictionary
        data["process_start_time"] = time.time()
        self.last_activity = time.time()
        
    async def on_post_process_update(self, update: Update, result, data: dict):
        """Post-process each update to record and analyze response time."""
        if "process_start_time" in data:
            process_time = time.time() - data["process_start_time"]
            self.response_times.append(process_time)
            
            # If response time is unusually high, log it
            if process_time > 5.0:  # More than 5 seconds to process
                self.loggers["performance"].warning(
                    f"Slow response time: {process_time:.2f}s for update {update.update_id}"
                )
                
            # Update bot status
            if not self.is_responding and process_time < 5.0:
                self.is_responding = True
                self.loggers["status"].info("Bot has resumed normal operation")
                
    def start_watchdog(self):
        """Start the watchdog timer to monitor bot health."""
        async def watchdog_check():
            while True:
                try:
                    # Check if the bot has been inactive for too long
                    if time.time() - self.last_activity > 300:  # 5 minutes
                        # Check bot responsiveness with getMe() call
                        try:
                            await asyncio.wait_for(self.bot.get_me(), timeout=5.0)
                            # If we get here, bot is responding
                            if not self.is_responding:
                                self.is_responding = True
                                self.loggers["status"].info("Bot has recovered and is now responsive")
                        except (TimeoutError, asyncio.TimeoutError):
                            # Bot is not responding
                            if self.is_responding:
                                self.is_responding = False
                                self.loggers["status"].error("Bot appears to be unresponsive")
                                # Notify admins
                                for admin_id in self.admin_ids:
                                    try:
                                        await self.bot.send_message(
                                            chat_id=admin_id,
                                            text=f"{EMOJI['alert']} *ALERT:* Bot appears to be unresponsive. Please check logs.",
                                            parse_mode=ParseMode.MARKDOWN
                                        )
                                    except Exception as e:
                                        self.loggers["errors"].error(f"Failed to notify admin {admin_id}: {e}")
                    
                    # Sleep for 1 minute before next check
                    await asyncio.sleep(60)
                except Exception as e:
                    self.loggers["errors"].error(f"Error in watchdog timer: {e}")
                    await asyncio.sleep(60)  # Sleep and retry
        
        # Start the watchdog coroutine
        self.watchdog_timer = asyncio.create_task(watchdog_check())

class ActivityTrackerMiddleware:
    """Middleware to track user activity timestamps."""
    
    async def on_pre_process_update(self, update: Update, data: dict):
        """Record user activity time for every update."""
        if update and update.effective_user:
            user_id = update.effective_user.id
            
            # Get the application context safely
            context = data.get('application_context')
            
            # Only proceed if we have a valid context with user_data
            if context and hasattr(context, 'user_data'):
                # Update the last activity time in user_data
                context.user_data['last_activity_time'] = time.time()

class ConversationTimeout(Exception):
    """Exception raised when a conversation times out."""
    pass

async def error_handler(update, context):
    """
    Global error handler for the bot.
    Logs errors and notifies users.
    
    Args:
        update: Telegram update
        context: Conversation context
    """
    # Log the error
    log_error(loggers["errors"], "error_handler", context.error)
    
    # Notify user if possible
    if update and update.effective_chat and update.effective_chat.id:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=MESSAGES["error"]
            )
        except Exception as error:
            loggers["errors"].error(f"Failed to send error message to the user: {error}")

async def enhanced_error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Enhanced error handler for catching and logging errors, and notifying users.
    
    This function handles errors that occur during bot operation, providing
    appropriate user feedback and logging for administrators. It prevents
    duplicate error messages and implements special handling for common errors.
    
    Args:
        update: Telegram update that caused the error
        context: Context with error details
    """
    # Get the exception from the context
    error = context.error
    
    # Get user and chat information
    user_id = None
    chat_id = None
    message_id = None
    
    try:
        if update and update.effective_user:
            user_id = update.effective_user.id
        if update and update.effective_chat:
            chat_id = update.effective_chat.id
        if update and update.effective_message:
            message_id = update.effective_message.message_id
    except Exception as e:
        loggers["errors"].error(f"Error retrieving user/chat information: {e}")
    
    # Generate an error key to track this specific error
    error_key = f"{chat_id}:{message_id}" if chat_id and message_id else str(error)
    
    # Initialize the processed_errors set in bot_data if it doesn't exist
    if "processed_errors" not in context.bot_data:
        context.bot_data["processed_errors"] = set()
    
    # Use a more atomic approach to check and update processed errors
    # to avoid race conditions in concurrent processing
    processed_errors = context.bot_data["processed_errors"]
    
    # First, create a copy to avoid modifying during iteration
    current_errors = processed_errors.copy()
    
    # Check if this error is already being processed
    if error_key in current_errors:
        return
    
    # Add this error to the processed set
    processed_errors.add(error_key)
    
    # Clean up processed errors periodically
    if len(processed_errors) > 100:
        # Keep only the 50 most recent items (convert to list for indexing)
        error_list = list(processed_errors)
        context.bot_data["processed_errors"] = set(error_list[-50:])
    
    # Log the error details
    error_text = f"User: {user_id} | Chat: {chat_id} | Error: {type(error).__name__}: {error}"
    loggers["errors"].error(f"Error in enhanced_error_handler | {error_text}")
    
    # Log as security event if it might be security-related
    if (isinstance(error, ValueError) and "Invalid" in str(error)) or \
       any(term in str(error).lower() for term in ["injection", "script", "attack", "overflow", "invalid token"]):
        log_security_event(
            loggers, 
            "POTENTIAL_SECURITY_ISSUE",
            user_id=user_id,
            details=f"Possible security issue: {type(error).__name__}: {str(error)}"
        )
    
    # Skip known command errors - these will be handled by command_not_found
    if isinstance(error, TelegramError) and "Command not found" in str(error):
        return
    
    # Generate a unique error reference code
    error_ref = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    loggers["errors"].error(f"Error reference: {error_ref} | {error_text}")
    
    # Send a notification to admin about the error
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"{EMOJI['error']} *BOT ERROR ALERT* {EMOJI['error']}\n\n"
                f"*Error Reference:* `{error_ref}`\n"
                f"*Type:* `{type(error).__name__}`\n"
                f"*Details:* `{error}`\n"
                f"*User ID:* `{user_id}`\n"
                f"*Chat ID:* `{chat_id}`\n"
                f"*Time:* `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
            ),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        loggers["errors"].error(f"Failed to notify admin about error: {e}")
    
    # Provide user-friendly error message and recovery options
    try:
        if chat_id:
            # Create recovery keyboard
            keyboard = [
                [InlineKeyboardButton(f"{EMOJI['restart']} Restart Conversation", callback_data="restart_conversation")],
                [InlineKeyboardButton(f"{EMOJI['help']} Get Help", callback_data="get_help")],
                [InlineKeyboardButton(f"{EMOJI['home']} Main Menu", callback_data="start")]
            ]
            
            # Determine the message based on error type
            if isinstance(error, (NetworkError, TelegramError, TimedOut)):
                error_message = (
                    f"{EMOJI['warning']} *Connection issue detected*\n\n"
                    f"The bot is having trouble connecting to Telegram servers. "
                    f"This could be due to network issues or server load.\n\n"
                    f"*What you can do:*\n"
                    f"• Wait a moment and try again\n"
                    f"• Restart the conversation using the button below\n"
                    f"• Contact support if the issue persists\n\n"
                    f"Error Reference: `{error_ref}`"
                )
            elif isinstance(error, ConversationTimeout):
                error_message = (
                    f"{EMOJI['clock']} *Conversation Timed Out*\n\n"
                    f"Your session was inactive for too long and has been reset. "
                    f"Don't worry, your data is safe!\n\n"
                    f"Use the buttons below to restart."
                )
            else:
                error_message = (
                    f"{EMOJI['error']} *Something went wrong*\n\n"
                    f"The bot encountered an unexpected error while processing your request. "
                    f"Our team has been notified and is working to fix it.\n\n"
                    f"*What you can do:*\n"
                    f"• Restart the conversation using the button below\n"
                    f"• Try again later if the issue persists\n"
                    f"• Contact support with reference code: `{error_ref}`"
                )
            
            await context.bot.send_message(
                chat_id=chat_id,
                text=error_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            
            # End any ongoing conversation
            return ConversationHandler.END
            
    except Exception as e:
        loggers["errors"].error(f"Failed to send error message to the user: {e}")

async def navigation_error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle errors that occur during navigation.
    
    Args:
        update: Telegram update
        context: Conversation context
    """
    error = context.error
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    
    # Log the error
    loggers["errors"].error(f"Navigation error for user {user_id}: {error}")
    
    # Try to recover by returning to categories
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                f"{EMOJI['error']} An error occurred while navigating. Let's start again.",
                reply_markup=build_category_buttons([k for k in PRODUCTS.keys()])
            )
        else:
            await update.message.reply_text(
                f"{EMOJI['error']} An error occurred while navigating. Let's start again.",
                reply_markup=build_category_buttons([k for k in PRODUCTS.keys()])
            )
        return CATEGORY
    except Exception as e:
        loggers["errors"].error(f"Failed to recover from navigation error: {e}")
        return ConversationHandler.END

async def check_conversation_status(context: ContextTypes.DEFAULT_TYPE):
    """
    Job to check if conversations have been idle for too long and offer recovery.
    This runs periodically to check for stuck conversations.
    
    Args:
        context: Application context containing bot data
    """
    now = time.time()
    bot = context.bot
    
    # Safely iterate through user data
    if hasattr(context.application, 'user_data'):
        for user_id, user_data in context.application.user_data.items():
            # Check if this user has been inactive for more than 10 minutes
            last_activity = user_data.get('last_activity_time', 0)
            
            if last_activity and now - last_activity > 600:  # 10 minutes
                # This user's conversation may be stalled
                try:
                    # Only send recovery message if we haven't sent one recently
                    last_recovery_sent = user_data.get('last_recovery_sent', 0)
                    if now - last_recovery_sent > 1800:  # 30 minutes
                        await bot.send_message(
                            chat_id=user_id,
                            text=(
                                f"{EMOJI['clock']} *Are you still there?*\n\n"
                                f"I noticed that our conversation has been inactive for a while. "
                                f"If you were in the middle of something and the bot stopped responding, "
                                f"you can restart our conversation using the buttons below."
                            ),
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton(f"{EMOJI['restart']} Restart Conversation", callback_data="restart_conversation")],
                                [InlineKeyboardButton(f"{EMOJI['home']} Main Menu", callback_data="start")]
                            ])
                        )
                        
                        # Update the recovery sent time
                        user_data['last_recovery_sent'] = now
                except Exception as e:
                    loggers["errors"].error(f"Failed to send recovery message to user {user_id}: {e}")

# ---------------------------- Bot Recovery & Support Functions ----------------------------
# Global start command handler that works regardless of conversation state
async def global_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Global start command that works regardless of conversation state.
    
    This handler ensures the /start command is always recognized and processed,
    even if the user is in the middle of another conversation.
    
    Args:
        update: Telegram update
        context: Conversation context
        
    Returns:
        int: Next conversation state from start_wrapper
    """
    # Log the global start command
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    loggers["main"].info(f"Global start command triggered by user {user_id}")
    
    try:
        # Clear user data to ensure fresh start
        for key in list(context.user_data.keys()):
            if key in context.user_data:
                del context.user_data[key]
        
        # Call the regular start wrapper
        return await start_wrapper(update, context)
    except Exception as e:
        # Log the error
        loggers["errors"].error(f"Error in global_start: {str(e)}")
        
        # Send user-friendly error message
        await update.message.reply_text(
            f"{EMOJI['error']} Sorry, there was an error processing your /start command.\n\n"
            f"Please try again in a moment or use /force_reset to clear your session.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['restart']} Reset Session", callback_data="restart_conversation")]
            ])
        )
        return ConversationHandler.END
    
async def handle_start_shopping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for the 'start_shopping' callback query.
    Safely redirects users to the shopping flow.
    
    Args:
        update: Telegram update with the callback query
        context: Conversation context
        
    Returns:
        int: Next conversation state
    """
    query = update.callback_query
    if not query:
        # This should never happen but we handle it just in case
        loggers["errors"].error("handle_start_shopping called with update that has no callback_query")
        return ConversationHandler.END
    
    # Answer the callback query to remove the "loading" state from the button
    await query.answer()
    
    # Log the action
    user_id = query.from_user.id if query.from_user else "Unknown"
    loggers["main"].info(f"User {user_id} clicked start_shopping button")
    
    try:
        # Clear user data to ensure a fresh start
        for key in list(context.user_data.keys()):
            if key in context.user_data:
                del context.user_data[key]
        
        # Update the message to show we're starting
        await query.edit_message_text(
            f"{EMOJI['welcome']} Starting shopping experience...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Instead of creating a new update object, simply redirect to the categories selection
        # This avoids the NoneType error by not trying to recreate the update object
        available_categories = []
        for category_id in PRODUCTS:
            try:
                has_products = await inventory_manager.category_has_products(category_id)
                if has_products:
                    available_categories.append(category_id)
            except Exception as e:
                loggers["errors"].error(f"Error checking products for {category_id}: {str(e)}")
                # If there's an error, include the category anyway to avoid blocking the flow
                available_categories.append(category_id)
        
        # Send the welcome message with categories
        await query.edit_message_text(
            MESSAGES["welcome"],
            reply_markup=build_category_buttons(available_categories)
        )
        
        # Return the category state to continue the conversation flow
        return CATEGORY
        
    except Exception as e:
        # Log the error
        loggers["errors"].error(f"Error in handle_start_shopping: {str(e)}")
        
        # Inform the user
        try:
            await query.edit_message_text(
                f"{EMOJI['error']} Sorry, there was an error starting the shopping experience.\n\n"
                f"Please try using the /start command directly.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            # If we can't edit the message, try to send a new one
            try:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"{EMOJI['error']} Sorry, there was an error. Please use /start to begin shopping.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass  # At this point, we've tried our best
        
        return ConversationHandler.END

async def restart_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for restarting the conversation when the user clicks the restart button.
    
    Args:
        update: Telegram update
        context: Context with user data
    """
    query = update.callback_query
    if query:
        await query.answer()
    
    # Clear user data
    context.user_data.clear()
    
    # Send a restart message
    restart_message = f"{EMOJI['restart']} *Conversation Restarted*\n\n" \
                      f"Your session has been reset and you can start fresh. " \
                      f"Use the menu below to continue."
    
    reply_markup = create_button_layout([
        create_button("action", "start_shopping", f"{EMOJI['browse']} Browse Products"),
        create_button("action", "track_order", f"{EMOJI['order']} Track Order"),
        create_button("action", "get_help", f"{EMOJI['help']} Help")
    ])
    
    if query:
        await query.edit_message_text(
            restart_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    else:
        # For command-based restart
        await update.message.reply_text(
            restart_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    # Don't call start_wrapper directly, just return END to exit the conversation
    return ConversationHandler.END

async def contact_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the contact support button click by directing users to PM a specific admin."""
    query = update.callback_query
    await query.answer()
    
    # Get the user's data including their order ID if available
    user_id = update.effective_user.id
    order_id = context.user_data.get('track_order_id', 'Not specified')
    
    # Prepare deep linking URL to start a chat with the support admin
    support_chat_url = f"https://t.me/{SUPPORT_ADMIN_USERNAME}"
    
    # Create the support message
    support_message = (
        f"{EMOJI['support']} <b>Need help with your order?</b>\n\n"
        f"Please contact our support admin directly through Telegram:\n\n"
        f"1️⃣ Click the button below to open a chat with our support admin\n"
        f"2️⃣ Send them your order ID (or the subject of your concern): <code>{order_id}</code>\n"
        f"3️⃣ Clearly describe your issue or question\n\n"
        f"Our support team will respond as soon as possible!"
    )
    
    # Create the keyboard with a button to open chat with support admin
    keyboard = [
        [create_button("link", None, "Chat with Support", url=support_chat_url)],
        [create_button("action", "start", "Main Menu", f"{EMOJI['home']} Main Menu")]
    ]
    
    # Log this support request
    logging.info(f"User {user_id} requested support with the subject/order {order_id}")
    
    await query.edit_message_text(
        support_message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )
    
    # If you want to notify the admin about the support request (optional)
    try:
        admin_notification = (
            f"🔔 <b>New Support Request</b>\n\n"
            f"👤 User ID: <code>{user_id}</code>\n"
            f"🧾 Subject/Order ID: <code>{order_id}</code>\n"
            f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        await context.bot.send_message(
            chat_id=SUPPORT_ADMIN_ID,
            text=admin_notification,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        # Log the error but don't disrupt the user experience
        logging.error(f"Failed to notify admin about support request: {e}")

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct support command handler."""
    user_id = update.effective_user.id
    order_id = context.user_data.get('track_order_id', 'Not specified')
    
    support_chat_url = get_support_deep_link(user_id, order_id)
    
    support_message = (
        f"{EMOJI['support']} <b>Contact Our Support</b>\n\n"
        f"For any questions or assistance with your orders, please contact our support admin directly:\n\n"
        f"• Click the button below to open a chat\n"
        f"• Your user ID: <code>{user_id}</code>\n"
        f"• Latest order ID (if any): <code>{order_id}</code>\n\n"
        f"We're here to help you have the best experience!"
    )
    
    keyboard = [
        [create_button("link", None, "Chat with Support", url=support_chat_url)],
        [create_button("action", "start", "Main Menu", f"{EMOJI['home']} Main Menu")]
    ]
    
    logging.info(f"User {user_id} accessed support command")
    
    await update.message.reply_text(
        support_message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

async def get_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for providing help when the user clicks the help button.
    
    Args:
        update: Telegram update
        context: Context with user data
    """
    query = update.callback_query
    if query:
        await query.answer()
    
    help_message = (
        f"{EMOJI['help']} *Need Help?*\n\n"
        f"Here are some common commands:\n\n"
        f"• /start - Start or restart the bot\n"
        f"• /reset - Reset your conversation if something goes wrong\n"
        f"• /help - Show this help message\n"
        f"• /contact - Contact customer support\n"
        f"• /faq - Frequently asked questions\n\n"
        f"*Having Issues?*\n"
        f"If the bot isn't responding properly, you can:\n"
        f"1. Try the /reset command\n"
        f"2. Wait a few minutes and try again\n"
        f"3. Contact our support team at support@ganjaparaiso.com\n\n"
        f"Thank you for your patience!"
    )
    
    if query:
        await query.edit_message_text(
            help_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=create_button_layout([
                [create_button("action", "restart_conversation", "Restart Bot", f"{EMOJI['restart']} Restart Bot")],
                [create_button("action", "start", "Main Menu", f"{EMOJI['home']} Main Menu")]
            ])
        )
    else:
        await update.message.reply_text(
            help_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=create_button_layout([
                [create_button("action", "restart_conversation", "Restart Bot", f"{EMOJI['restart']} Restart Bot")],
                [create_button("action", "start", "Main Menu", f"{EMOJI['home']} Main Menu")]
            ])
        )

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Command handler for /reset to allow users to manually reset their conversation.
    
    Args:
        update: Telegram update
        context: Context with user data
    """
    # Clear user data
    context.user_data.clear()
    
    await update.message.reply_text(
        f"{EMOJI['restart']} *Conversation Reset*\n\n"
        f"I've reset your session. Everything should be working properly now.\n"
        f"What would you like to do next?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{EMOJI['browse']} Browse Products", callback_data="start_shopping")],
            [InlineKeyboardButton(f"{EMOJI['order']} Track Order", callback_data="track_order")],
            [InlineKeyboardButton(f"{EMOJI['help']} Help", callback_data="get_help")]
        ])
    )
    
    return ConversationHandler.END

async def force_reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Force reset command that clears user data and ends any active conversation.
    More powerful than the regular /reset command, as it forcibly ends any conversation.
    
    Args:
        update: Telegram update
        context: Conversation context
    
    Returns:
        int: ConversationHandler.END to end any active conversation
    """
    user = update.effective_user
    
    # Log the force reset
    loggers["main"].info(f"User {user.id} executed force_reset command")
    
    # Clear user data
    context.user_data.clear()
    
    # Send confirmation with helpful next steps
    await update.message.reply_text(
        f"{EMOJI['restart']} Your session has been completely reset.\n\n"
        f"This should resolve any issues with commands not being recognized.\n\n"
        f"What would you like to do next?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{EMOJI['browse']} Start Shopping", callback_data="start_shopping")],
            [InlineKeyboardButton(f"{EMOJI['order']} Track Order", callback_data="track_order")],
            [InlineKeyboardButton(f"{EMOJI['help']} Help", callback_data="get_help")]
        ])
    )
    
    # End any active conversation
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Cancel the current conversation.
    
    Args:
        update: Telegram update
        context: Conversation context
        
    Returns:
        int: ConversationHandler.END
    """
    # Clear the user's cart
    manage_cart(context, "clear")
    
    # Log the cancellation
    user = update.message.from_user
    loggers["main"].info(f"User {user.id} cancelled their order")
    
    await update.message.reply_text(MESSAGES["cancel_order"])
    return ConversationHandler.END

async def force_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Force restart any ongoing conversation and return to the start state.
    
    This command bypasses normal conversation flow and resets everything,
    useful when users get stuck in a conversation state.
    
    Args:
        update: Telegram update
        context: Conversation context
    """
    # Clear user data
    context.user_data.clear()
    
    # Send confirmation
    await update.message.reply_text(
        f"{EMOJI['restart']} Your conversation has been completely reset.\n\n"
        f"Let's start fresh! What would you like to do?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{EMOJI['browse']} Browse Products", callback_data="start_shopping")],
            [InlineKeyboardButton(f"{EMOJI['tracking']} Track Order", callback_data="track_order")]
        ])
    )
    
    # End any conversation
    return ConversationHandler.END

async def timeout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle conversation timeout.
    
    Args:
        update: Telegram update
        context: Conversation context
        
    Returns:
        int: ConversationHandler.END
    """
    user = update.effective_user
    
    loggers["main"].info(f"Conversation timed out for user {user.id}")
    
    await context.bot.send_message(
        chat_id=user.id,
        text=ERRORS["timeout"]
    )
    return ConversationHandler.END

async def command_not_found(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle unrecognized commands with a helpful response.
    
    This function provides users with information about available commands
    when they enter a command that isn't recognized by the bot.
    
    Args:
        update: Telegram update containing message info
        context: Conversation context for user data
    """
    command = update.message.text
    user_id = update.effective_user.id
    
    # Log the unrecognized command
    loggers["main"].info(f"User {user_id} entered unrecognized command: {command}")
    
    # Create a helpful message with available commands
    available_commands = (
        f"{EMOJI['info']} Available Commands:\n\n"
        f"• /start - Start ordering\n"
        f"• /track - Track your order\n"
        f"• /categories - Browse categories\n"
        f"• /reset - Reset the conversation\n"
        f"• /help - Show this help message\n"
        f"• /support - Contact support\n\n"
        f"{EMOJI['question']} Need assistance? Use /support to get help."
    )
    
    # Send a friendly message with command suggestions
    await update.message.reply_text(
        f"{EMOJI['question']} I don't recognize the command '{command}'.\n\n{available_commands}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{EMOJI['browse']} Start Shopping", callback_data="start_shopping")],
            [InlineKeyboardButton(f"{EMOJI['tracking']} Track Order", callback_data="track_order")]
        ])
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Display a help message with available commands and usage instructions.
    
    Args:
        update: Telegram update
        context: Conversation context
    """
    help_message = (
        f"{EMOJI['help']} *GanJa Paraiso Bot Help*\n\n"
        f"*Available Commands:*\n"
        f"• /start - Start shopping or return to main menu\n"
        f"• /track - Track your order status\n"
        f"• /help - Show this help message\n"
        f"• /reset - Reset your conversation\n"
        f"• /support - Contact customer support\n\n"
        
        f"*How to Order:*\n"
        f"1. Use /start to begin ordering\n"
        f"2. Select a product category\n"
        f"3. Choose a specific product\n"
        f"4. Enter quantity\n"
        f"5. Add to cart or proceed to checkout\n"
        f"6. Enter shipping details\n"
        f"7. Send GCash payment screenshot\n\n"
        
        f"*Tracking Your Order:*\n"
        f"Use /track and enter your order ID\n\n"
        
        f"*Need Help?*\n"
        f"If you have questions or encounter issues, use the /support command to contact our customer service team."
    )
    
    # Create button options
    keyboard = [
        [InlineKeyboardButton(f"{EMOJI['browse']} Start Shopping", callback_data="start_shopping")],
        [InlineKeyboardButton(f"{EMOJI['tracking']} Track Order", callback_data="track_order")],
        [InlineKeyboardButton(f"{EMOJI['support']} Contact Support", callback_data="contact_support")]
    ]
    
    await update.message.reply_text(
        help_message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def contextual_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Provide context-sensitive help based on where the user is in the conversation.
    
    Args:
        update: Telegram update
        context: Conversation context
    """
    # Determine which state the user is in
    current_state = context.user_data.get("current_location", "")
    category = context.user_data.get("category", "")
    
    # Create base help response
    help_response = BotResponse("help").add_header("Need Help?", "help")
    
    # Add contextual guidance based on state
    if current_state == "categories" or not current_state:
        help_response.add_paragraph(
            "You're currently at the product categories menu. "
            "Select a category to browse our products."
        ).add_bullet_list([
            "Tap on any category to see products",
            "Use /track to check an existing order",
            "Use /help to see available commands"
        ])
    
    elif current_state == "strain_selection":
        help_response.add_paragraph(
            "You're selecting a strain type for your product. "
            "Different strains provide different effects:"
        ).add_bullet_list([
            "Indica: More relaxing, good for evening use",
            "Sativa: More energizing, good for daytime use",
            "Hybrid: Balanced effects, good for any time"
        ])
    
    elif "product_" in current_state:
        help_response.add_paragraph(
            "You're selecting the quantity for your product. "
            "Enter a number for the quantity you'd like to purchase."
        ).add_paragraph(
            "For premium buds, the minimum order is 1 gram. "
            "For local products, you can choose from 10g, 50g, 100g, or 300g options."
        )
    
    elif current_state == "details":
        help_response.add_paragraph(
            "You need to provide your shipping details in this format:"
        ).add_paragraph(
            "Name / Address / Contact Number"
        ).add_paragraph(
            "For example: Juan Dela Cruz / 123 Main St, City / 09171234567"
        )
    
    elif current_state == "payment":
        help_response.add_paragraph(
            "Please send a screenshot of your payment to complete the order. "
            "Make sure the payment amount and reference number are clearly visible."
        ).add_bullet_list([
            f"Send payment to GCash: {GCASH_NUMBER}",
            "Use the QR code provided for faster payment",
            "The screenshot must be a photo, not a file"
        ])
    
    else:
        # General help
        help_response.add_paragraph(
            "Here are some general tips to help you navigate our bot:"
        ).add_bullet_list([
            "Use /start to begin shopping",
            "Use /track to check an existing order",
            "Use /reset to restart the conversation if you get stuck",
            "Use /support to contact customer support"
        ])
    
    # Always add general commands at the end
    help_response.add_divider().add_paragraph(
        "Available commands:"
    ).add_bullet_list([
        "/start - Start shopping",
        "/track - Track your order",
        "/help - Show this help message",
        "/reset - Reset the conversation",
        "/support - Contact customer support"
    ])
    
    # Send the help message
    await update.message.reply_text(help_response.get_message())

async def health_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin command to check system health.
    
    Args:
        update: Telegram update
        context: Conversation context
    """
    user_id = update.message.from_user.id
    
    # Verify admin status
    if user_id != ADMIN_ID:
        await update.message.reply_text(ERRORS["not_authorized"])
        return
    
    # Start health check
    message = await update.message.reply_text(f"{EMOJI['info']} Performing system health check...")
    
    results = {
        "database": True,
        "google_sheets": True,
        "google_drive": True,
        "message_system": True
    }
    
    try:
        # Check Google Sheets connection
        sheet, _ = await google_apis.initialize_sheets()
        if not sheet:
            results["google_sheets"] = False
    except Exception as e:
        results["google_sheets"] = False
        loggers["errors"].error(f"Google Sheets health check failed: {e}")
    
    try:
        # Check Google Drive connection
        drive_service = await google_apis.get_drive_service()
        if not drive_service:
            results["google_drive"] = False
    except Exception as e:
        results["google_drive"] = False
        loggers["errors"].error(f"Google Drive health check failed: {e}")
    
    # Format results
    status_text = f"{EMOJI['search']} System Health Report:\n\n"
    for system, status in results.items():
        emoji = EMOJI["success"] if status else EMOJI["error"]
        status_text += f"{emoji} {system.replace('_', ' ').title()}: {'Online' if status else 'Offline'}\n"
    
    # Add system stats
    uptime = time.time() - context.bot_data.get("start_time", time.time())
    hours, remainder = divmod(uptime, 3600)
    minutes, seconds = divmod(remainder, 60)
    status_text += f"\n{EMOJI['time']} Uptime: {int(hours)}h {int(minutes)}m {int(seconds)}s"
    
    # Add cache statistics
    try:
        cache_stats = google_apis.get_cache_stats()
        status_text += f"\n\n{EMOJI['inventory']} Cache Statistics:"
        status_text += f"\n- Cache Hits: {cache_stats['cache_hits']}"
        status_text += f"\n- Cache Misses: {cache_stats['cache_misses']}"
        status_text += f"\n- Hit Ratio: {cache_stats['hit_ratio']:.1%}"
        status_text += f"\n- Total Requests: {cache_stats['total_requests']}"
    except Exception as e:
        status_text += f"\n\nCache statistics unavailable: {str(e)}"
    
    await message.edit_text(status_text)

# ---------------------------- Convenience Functions ----------------------------
# These wrapper functions make it easier to pass our dependencies to handlers
async def start_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Enhanced wrapper for the start command with error handling and conversation state clearing.
    
    Args:
        update: Telegram update
        context: Conversation context
        
    Returns:
        int: Next conversation state
    """
    try:
        # Log the start command
        user_id = update.effective_user.id
        loggers["main"].info(f"User {user_id} issued /start command")
        
        # Send a typing indicator for better UX
        await send_typing_action(context, update.effective_chat.id, 1)
        
        # Clear any existing conversation state
        return await start(update, context, inventory_manager, loggers)
    except Exception as e:
        # Log the error
        user_id = update.effective_user.id if update.effective_user else "Unknown"
        loggers["errors"].error(f"Error processing /start for user {user_id}: {str(e)}")
        
        # Send user-friendly error message
        try:
            # Create a friendly error response
            response = BotResponse("error") \
                .add_header("Something went wrong", "error") \
                .add_paragraph("Sorry, there was an error processing your command.") \
                .add_paragraph("Please try again in a moment or contact support if the issue persists.")
            
            await update.message.reply_text(response.get_message())
        except Exception:
            pass  # If we can't even send a message, don't crash
        
        return ConversationHandler.END

async def choose_category_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await debug_state_tracking(update, context)
    return await choose_category(update, context, inventory_manager, loggers)

async def choose_strain_type_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await debug_state_tracking(update, context)
    return await choose_strain_type(update, context, inventory_manager, loggers)

async def browse_carts_by_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await debug_state_tracking(update, context)
    return await browse_carts_by(update, context, inventory_manager, loggers)

async def select_product_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await debug_state_tracking(update, context)
    return await select_product(update, context, inventory_manager, loggers)

async def input_quantity_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await debug_state_tracking(update, context)
    return await input_quantity(update, context, inventory_manager, loggers)

async def confirm_order_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await debug_state_tracking(update, context)
    return await confirm_order(update, context, loggers)

async def input_details_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await debug_state_tracking(update, context)
    return await input_details(update, context, loggers)

async def confirm_details_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await debug_state_tracking(update, context)
    return await confirm_details(update, context, loggers, ADMIN_ID)

async def handle_payment_screenshot_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await debug_state_tracking(update, context)
    return await handle_payment_screenshot(update, context, google_apis, order_manager, loggers)

async def handle_order_tracking_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await debug_state_tracking(update, context)
    return await handle_order_tracking(update, context, order_manager, loggers)

async def handle_quantity_selection_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await debug_state_tracking(update, context)
    return await handle_quantity_selection(update, context, inventory_manager, loggers)

async def handle_back_navigation_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await debug_state_tracking(update, context)
    return await handle_back_navigation(update, context, inventory_manager, loggers)

async def back_to_categories_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await debug_state_tracking(update, context)
    return await back_to_categories(update, context, inventory_manager, loggers)

# ---------------------------- Bot Setup ----------------------------

# ==========================================================================
# DEBUGGING AND DIAGNOSTIC FUNCTIONS
# ==========================================================================

def memory_usage_report() -> Dict[str, Union[int, float]]:
    """
    Get a report of current memory usage.
    
    This function reports system resource usage by the bot process.
    If psutil is not available, returns limited information.
    
    Returns:
        Dict[str, Union[int, float]]: Memory usage statistics
    """
    if not PSUTIL_AVAILABLE:
        # Return basic information without psutil
        try:
            # Try using the resource module as fallback
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return {
                "memory_usage": usage.ru_maxrss / 1024,  # Convert to MB (system-dependent)
                "user_cpu_time": usage.ru_utime,
                "system_cpu_time": usage.ru_stime,
                "note": "Limited stats (psutil not installed)"
            }
        except (ImportError, AttributeError):
            # If resource module also not available (Windows without psutil)
            return {
                "note": "Memory stats unavailable (psutil not installed)",
                "recommendation": "Install psutil for more detailed system statistics"
            }
            
    # If psutil is available
    import gc
    
    # Force garbage collection
    gc.collect()
    
    # Get current process
    process = psutil.Process(os.getpid())
    
    # Get memory info
    memory_info = process.memory_info()
    
    return {
        "rss": memory_info.rss / 1024 / 1024,  # RSS in MB
        "vms": memory_info.vms / 1024 / 1024,  # VMS in MB
        "percent": process.memory_percent(),
        "num_threads": process.num_threads(),
        "open_files": len(process.open_files()),
    }

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Admin command to get debugging information.
    
    This command provides system statistics and bot performance metrics.
    Only available to the administrator.
    
    Args:
        update: Telegram update
        context: Conversation context
    """
    user_id = update.effective_user.id
    
    # Only allow the admin to use this command
    if user_id != ADMIN_ID:
        await update.message.reply_text(ERRORS["not_authorized"])
        return
        
    try:
        # Create base debug report
        report = BotResponse("debug").add_header("Debug Information", "debug")
        
        # Get memory usage report
        mem_usage = memory_usage_report()
        
        # Format the report
        report.add_paragraph("System Status:")
        
        # Add memory usage stats if available
        if "rss" in mem_usage:
            report.add_bullet_list([
                f"Memory usage: {mem_usage['rss']:.2f} MB RSS",
                f"Memory percent: {mem_usage['percent']:.1f}%",
                f"Threads: {mem_usage['num_threads']}",
                f"Open files: {mem_usage['open_files']}",
            ])
        elif "memory_usage" in mem_usage:
            report.add_bullet_list([
                f"Memory usage: {mem_usage['memory_usage']:.2f} MB",
                f"User CPU time: {mem_usage['user_cpu_time']:.2f}s",
                f"System CPU time: {mem_usage['system_cpu_time']:.2f}s",
            ])
        else:
            report.add_paragraph(mem_usage.get("note", "No memory statistics available"))
            if "recommendation" in mem_usage:
                report.add_paragraph(f"💡 {mem_usage['recommendation']}")
        
        # Add persistence file info
        try:
            persistence_size = get_persistence_file_size()
            report.add_bullet_list([
                f"Persistence file: {persistence_size:.2f} MB",
                f"Uptime: {time.time() - context.bot_data.get('start_time', time.time()):.1f} seconds",
            ])
        except Exception as e:
            report.add_paragraph(f"Could not get persistence file info: {str(e)}")
        
        # Add cache stats if available
        try:
            if 'google_apis' in globals():
                cache_stats = google_apis.get_cache_stats()
                report.add_paragraph("Cache Statistics:") \
                    .add_bullet_list([
                        f"Hit ratio: {cache_stats['hit_ratio']:.1%}",
                        f"Cache hits: {cache_stats['cache_hits']}",
                        f"Cache misses: {cache_stats['cache_misses']}",
                        f"Total requests: {cache_stats['total_requests']}",
                    ])
        except Exception:
            pass
            
        # Add active user count
        active_users = 0
        if "sessions" in context.bot_data:
            active_users = len(context.bot_data["sessions"])
            
        report.add_paragraph("User Statistics:") \
            .add_bullet_list([
                f"Active users: {active_users}",
            ])
            
        # Send the report
        await update.message.reply_text(report.get_message())
            
    except Exception as e:
        await update.message.reply_text(
            f"{EMOJI['error']} Error generating debug report: {str(e)}"
        )

async def debug_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Enhanced debug handler that traces all callback queries and provides state info.
    This helps identify issues with callbacks not being properly handled.
    """
    query = update.callback_query
    if not query:
        return
    
    # Track state
    await debug_state_tracking(update, context)
    
    # Check if this callback was already processed
    callback_id = query.id
    processed_callbacks = context.user_data.get("processed_callbacks", set())
    if callback_id in processed_callbacks:
        print(f"DEBUG CALLBACK: Skipping already processed callback: {callback_id}")
        return
    
    # Check if this is a common callback that should be handled by specific handlers
    common_callbacks = ["indica", "sativa", "hybrid", "back_to_categories", "back_to_strain"]
    if query.data in common_callbacks:
        # These are handled by specific handlers, don't attempt to handle again
        print(f"DEBUG CALLBACK: Ignoring common callback: {query.data}")
        await query.answer()  # Just answer the callback to prevent spinning
        return
        
    print(f"DEBUG CALLBACK: Received unhandled callback with data: {query.data}")
    print(f"DEBUG CALLBACK: Current location: {context.user_data.get('current_location', 'Unknown')}")
    print(f"DEBUG CALLBACK: Current category: {context.user_data.get('category', 'None')}")
    print(f"DEBUG CALLBACK: Current strain_type: {context.user_data.get('strain_type', 'None')}")
    
    # Always answer the callback to prevent the loading spinner
    await query.answer()

    # Try smart handling based on context
    current_location = context.user_data.get("current_location", "Unknown")
    category = context.user_data.get("category", "None")
    
    if query.data in ["indica", "sativa", "hybrid"] and category == "buds":
        print(f"DEBUG CALLBACK: Attempting to manually handle strain selection: {query.data}")
        try:
            # Manually initiate strain type handling
            return await choose_strain_type_wrapper(update, context)
        except Exception as e:
            print(f"DEBUG CALLBACK ERROR: Failed to handle strain selection: {str(e)}")
    
    elif query.data.startswith("back_to_"):
        print(f"DEBUG CALLBACK: Attempting to handle back navigation: {query.data}")
        try:
            return await handle_back_navigation_wrapper(update, context)
        except Exception as e:
            print(f"DEBUG CALLBACK ERROR: Failed to handle navigation: {str(e)}")
    
    # Try to handle product selection for any unhandled callback that seems like a product key
    elif current_location and current_location.startswith("strain_selection") and category:
        print(f"DEBUG CALLBACK: Attempting to handle product selection: {query.data}")
        try:
            # Update location to help with tracking
            context.user_data["current_location"] = f"product_{query.data}"
            return await select_product_wrapper(update, context)
        except Exception as e:
            print(f"DEBUG CALLBACK ERROR: Failed to handle product selection: {str(e)}")
    
    # Don't modify the message or do anything else
    return

async def debug_state_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Middleware-like function to track conversation states.
    Call this at the beginning of key handler functions.
    
    Args:
        update: Telegram update
        context: Conversation context
    """
    user_id = update.effective_user.id if update.effective_user else "Unknown"
    chat_id = update.effective_chat.id if update.effective_chat else "Unknown"
    
    # Get current location from context
    current_location = context.user_data.get("current_location", "Unknown")
    category = context.user_data.get("category", "None")
    
    # Determine what type of update this is
    update_type = "Unknown"
    callback_data = None
    
    if update.message:
        update_type = f"Message: {update.message.text[:20]}..." if update.message.text else "Message (non-text)"
    elif update.callback_query:
        update_type = "Callback Query"
        callback_data = update.callback_query.data
    
    # Log the state
    print(f"DEBUG STATE: User {user_id} | Chat {chat_id} | Location: {current_location} | Category: {category} | Update: {update_type} | Callback: {callback_data}")

async def post_init(application: Application):
    """
    Runs after application is initialized but before polling starts.
    Use this to perform initialization tasks.
    """
    print("DEBUG: Application initialized, performing post-init tasks")
    
    # Delete persistence file if it might be causing issues
    if os.path.exists("bot_persistence") and os.environ.get("RESET_PERSISTENCE") == "true":
        print("DEBUG: Removing persistence file due to RESET_PERSISTENCE flag")
        try:
            os.rename("bot_persistence", f"bot_persistence_backup_{int(time.time())}")
            print("DEBUG: Persistence file backed up and removed")
        except Exception as e:
            print(f"DEBUG: Error backing up persistence file: {e}")
    
    print("DEBUG: Post-init tasks complete, bot ready to start")

def get_recovery_message(user_data):
    """
    Generate an appropriate recovery message based on user's conversation state.
    
    Args:
        user_data (dict): The user's conversation data
        
    Returns:
        str: Context-appropriate recovery message
    """
    current_location = user_data.get('current_location', '')
    category = user_data.get('category', '')
    
    # Default message
    message = (
        f"{EMOJI['warning']} It looks like your conversation with me may have stalled.\n\n"
        f"This could be due to a temporary issue. Please try again by using one of the options below."
    )
    
    # Customize message based on context
    if category == 'buds':
        message = (
            f"{EMOJI['warning']} It looks like your Premium Buds selection may have stalled.\n\n"
            f"This could be due to a temporary issue. Please try again by using one of the options below."
        )
    elif category == 'carts':
        message = (
            f"{EMOJI['warning']} It looks like your Carts selection may have stalled.\n\n"
            f"This could be due to a temporary issue. Please try again by using one of the options below."
        )
    elif current_location == 'details':
        message = (
            f"{EMOJI['warning']} It looks like you were in the middle of entering shipping details.\n\n"
            f"Would you like to restart the process?"
        )
    elif current_location == 'payment':
        message = (
            f"{EMOJI['warning']} It looks like you were in the middle of submitting a payment.\n\n"
            f"If you already completed your payment, you can track your order with the /track command."
        )
        
    return message

def main():
    """Set up the bot and start polling."""
    global loggers, google_apis, inventory_manager, order_manager, admin_panel
    
    # Set up logging
    loggers = setup_logging()
    loggers["main"].info("Bot starting up...")
    
    # Handle missing token
    if not TOKEN:
        error_msg = "No bot token found in configuration"
        loggers["errors"].error(error_msg)
        print(f"Error: {error_msg}. Please set the TELEGRAM_BOT_TOKEN environment variable.")
        sys.exit(1)

    # Support multiple admin IDs
    # Get admin IDs from environment variable - expect comma-separated list
    admin_ids_str = os.getenv("ADMIN_TELEGRAM_IDS", str(ADMIN_ID))
    admin_ids = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip().isdigit()]
    
    # Ensure at least the primary admin ID is included
    if ADMIN_ID not in admin_ids:
        admin_ids.append(ADMIN_ID)
    
    loggers["main"].info(f"Configured admin IDs: {admin_ids}")
    
    # Create persistence object to save conversation states
    persistence = PicklePersistence(filepath="bot_persistence")
    
    try:
        # Initialize application with persistence and concurrency
        # Add the post_init parameter to the ApplicationBuilder
        app = ApplicationBuilder().token(TOKEN) \
                               .persistence(persistence) \
                               .concurrent_updates(True) \
                               .post_init(post_init) \
                               .build()
        
        # Store start time
        app.bot_data["start_time"] = time.time()
        # Initialize processed errors set
        app.bot_data["processed_errors"] = set()
        
        # Initialize services
        google_apis = GoogleAPIsManager(loggers)
        inventory_manager = InventoryManager(google_apis, loggers)
        order_manager = OrderManager(google_apis, loggers)
        
        # Create admin panel with multiple admin IDs
        admin_panel = AdminPanel(app.bot, admin_ids, google_apis, order_manager, loggers)
        
        # Set up error handlers
        app.add_error_handler(enhanced_error_handler)
        app.add_error_handler(error_handler)
        
        # Add recovery command handlers
        app.add_handler(CommandHandler("reset", reset_command))
        app.add_handler(CommandHandler("help", help_command))
        app.add_handler(CommandHandler("support", support_command))
        app.add_handler(CommandHandler("context", contextual_help))  # Short command for contextual help
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^\?$"), contextual_help))  # Handle "?" as message
        app.add_handler(CommandHandler("debug", debug_command))  # Debug command for admin
        app.add_handler(CallbackQueryHandler(restart_conversation, pattern="^restart_conversation$"))
        app.add_handler(CallbackQueryHandler(get_help, pattern="^get_help$"))
        
        # Updated with more specific pattern
        app.add_handler(CallbackQueryHandler(refresh_tracking, pattern="^refresh_tracking_[A-Z0-9-]+$"))
        app.add_handler(CallbackQueryHandler(contact_support, pattern="^contact_support$"))
        
        # Make patterns more specific
        app.add_handler(CallbackQueryHandler(start_wrapper, pattern="^start$"))
        app.add_handler(CallbackQueryHandler(select_order, pattern="^select_order_[A-Z0-9-]+$"))
        app.add_handler(CallbackQueryHandler(cancel_tracking, pattern="^cancel_tracking$"))
        app.add_handler(CallbackQueryHandler(show_recent_orders, pattern="^show_recent_orders$"))
        app.add_handler(CallbackQueryHandler(enter_order_id, pattern="^enter_order_id$"))
        app.add_handler(CallbackQueryHandler(handle_start_shopping, pattern="^start_shopping$"))
        
        # Schedule periodic checks for stuck conversations
        job_queue = app.job_queue
        job_queue.run_repeating(check_conversation_status, interval=600, first=600)  # Every 10 minutes
        
        async def timeout_recovery_job(context: ContextTypes.DEFAULT_TYPE):
            """
            Periodic job to detect and recover from stalled conversations.
            Uses smart detection to avoid false positives while helping users
            who might be stuck in a conversation flow.
            """
            now = time.time()
            bot = context.bot
            
            # Safely iterate through user data
            if hasattr(context.application, 'user_data'):
                for user_id, user_data in context.application.user_data.items():
                    try:
                        # Check if this user has been inactive for a significant period
                        last_activity = user_data.get('last_activity_time', 0)
                        
                        # Skip users with recent activity (less than 3 minutes)
                        if now - last_activity < 180:  # 3 minutes
                            continue
                            
                        # Skip users who have recently completed an order
                        if user_data.get('last_completed_order') and now - user_data.get('order_completion_time', 0) < 600:  # 10 minutes
                            continue
                        
                        # Skip users who recently received a recovery message
                        if user_data.get('recovery_sent_recently'):
                            continue
                        
                        # Detect if user is in the middle of a conversation
                        current_location = user_data.get('current_location')
                        category = user_data.get('category')
                        
                        # Only send recovery for users who appear to be in an active conversation flow
                        if current_location or category:
                            # Log the potentially stalled conversation 
                            current_state = f"location:{current_location}, category:{category}"
                            loggers["main"].warning(f"Detected potentially stalled conversation for user {user_id}: {current_state}")
                            print(f"DEBUG: Sending recovery message for stalled conversation to user {user_id}")
                            
                            # Mark as recently notified to prevent spam
                            user_data['recovery_sent_recently'] = True
                            user_data['recovery_sent_time'] = now
                            
                            # Create appropriate recovery message based on conversation state
                            recovery_message = get_recovery_message(user_data)
                            
                            # Send recovery message
                            await bot.send_message(
                                chat_id=user_id,
                                text=recovery_message,
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton(f"{EMOJI['restart']} Start Over", callback_data="restart_conversation")],
                                    [InlineKeyboardButton(f"{EMOJI['browse']} Browse Categories", callback_data="back_to_categories")]
                                ])
                            )
                        
                        # Clean up old recovery flags (after 10 minutes)
                        elif user_data.get('recovery_sent_recently') and now - user_data.get('recovery_sent_time', 0) > 600:
                            user_data['recovery_sent_recently'] = False
                        
                    except Exception as e:
                        loggers["errors"].error(f"Error in timeout recovery for user {user_id}: {str(e)}")
                        continue  # Continue checking other users

        # Add this line to your job_queue setup in main()
        job_queue.run_repeating(timeout_recovery_job, interval=60, first=90)  # Run every minute, start after 90 seconds
        
        async def cleanup_job(context: ContextTypes.DEFAULT_TYPE):
            """Periodic job to clean up resources and prevent memory leaks"""
            try:
                # Clean up old sessions
                try:
                    session_cleanup_count = cleanup_old_sessions(context)
                    if session_cleanup_count > 0:
                        loggers["main"].info(f"Cleaned up {session_cleanup_count} old sessions")
                except Exception as e:
                    loggers["errors"].error(f"Error cleaning up sessions: {e}")
        
                # Clean up abandoned carts
                try:
                    cart_cleanup_count = await cleanup_abandoned_carts(context, order_manager, loggers)
                    if cart_cleanup_count > 0:
                        loggers["main"].info(f"Cleaned up {cart_cleanup_count} abandoned carts")
                except Exception as e:
                    loggers["errors"].error(f"Error cleaning up carts: {e}")
        
                # Check persistence file size
                try:
                    persistence_size = get_persistence_file_size()
                    if persistence_size > 10:  # If larger than 10MB
                        loggers["main"].info(f"Persistence file size: {persistence_size:.2f}MB, attempting cleanup")
                        success, old_size, new_size = cleanup_persistence_file(context, loggers)
                        if success:
                            reduction = old_size - new_size
                            reduction_pct = (reduction / old_size) * 100 if old_size > 0 else 0
                            loggers["main"].info(
                                f"Persistence cleanup successful. Reduced by {reduction:.2f}MB ({reduction_pct:.1f}%)"
                            )
                except Exception as e:
                    loggers["errors"].error(f"Error in persistence cleanup: {e}")
            
            except Exception as e:
                loggers["errors"].error(f"Error in cleanup job: {e}")

        # Schedule cleanup every 12 hours
        job_queue.run_repeating(cleanup_job, interval=43200, first=3600)  # 12 hours, first run after 1 hour

        # Set up conversation handler for main ordering flow
        conversation_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start_wrapper)],
            states={
                CATEGORY: [
                    # Match any callback in CATEGORY state
                    CallbackQueryHandler(choose_category_wrapper)
                ],
                STRAIN_TYPE: [
                    # Only handle specific strain type patterns to avoid processing unrelated callbacks
                    CallbackQueryHandler(choose_strain_type_wrapper, pattern="^(indica|sativa|hybrid|back_to_categories)$")
                ],
                BROWSE_BY: [
                    # Match all callbacks in BROWSE_BY state
                    CallbackQueryHandler(browse_carts_by_wrapper)
                ],
                PRODUCT_SELECTION: [
                    # Directly call select_product_wrapper without any tuple wrapping
                    CallbackQueryHandler(select_product_wrapper)
                ],
                QUANTITY: [
                    CallbackQueryHandler(handle_back_navigation_wrapper, pattern="^back_"),
                    CallbackQueryHandler(handle_quantity_selection_wrapper, pattern="^qty_"),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, input_quantity_wrapper)
                ],
                CONFIRM: [
                    CallbackQueryHandler(confirm_order_wrapper)
                ],
                DETAILS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, input_details_wrapper)
                ],
                CONFIRM_DETAILS: [
                    CallbackQueryHandler(confirm_details_wrapper)
                ],
                PAYMENT: [
                    MessageHandler(filters.PHOTO, handle_payment_screenshot_wrapper),
                    CallbackQueryHandler(handle_back_navigation_wrapper, pattern="^back_")
                ]
            },
            fallbacks=[
                CommandHandler("cancel", cancel),
                CommandHandler("categories", back_to_categories_wrapper),
                CommandHandler("start", start_wrapper),
                # Match restart_conversation explicitly
                CallbackQueryHandler(restart_conversation, pattern=r"^restart_conversation$")
            ],
            name="ordering_conversation",
            persistent=True,
            conversation_timeout=900  # 15 minutes timeout
        )

        # Order tracking conversation handler
        tracking_handler = ConversationHandler(
            entry_points=[CommandHandler("track", track_order_wrapper)],
            states={
                TRACK_ORDER: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, get_order_id),
                    CallbackQueryHandler(show_recent_orders, pattern="^show_recent_orders$"),
                    CallbackQueryHandler(enter_order_id, pattern="^enter_order_id$"),
                    CallbackQueryHandler(select_order, pattern="^select_order_"),
                    CallbackQueryHandler(cancel_tracking, pattern="^cancel_tracking$")
                ],
                TRACKING: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_order_tracking_wrapper)
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            name="tracking_conversation",
            persistent=True,
            conversation_timeout=300  # 5 minutes timeout
        )  

        # Admin tracking link input handler
        admin_tracking_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_panel.add_tracking_link, pattern="^add_tracking_")],
            states={
                ADMIN_TRACKING: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_panel.receive_tracking_link)]
            },
            fallbacks=[
                CallbackQueryHandler(admin_panel.skip_tracking_link, pattern="^skip_tracking_link$"),
                CommandHandler("cancel", cancel)
            ],
            name="admin_tracking_conversation",
            persistent=True,
            conversation_timeout=300  # 5 minutes timeout
        )

        # Admin search conversation handler
        admin_search_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(admin_panel.search_order_prompt, pattern="^search_order$")],
            states={
                ADMIN_SEARCH: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_panel.handle_admin_search)
                ],
            },
            fallbacks=[
                CommandHandler("cancel", cancel),
                CallbackQueryHandler(admin_panel.back_to_admin, pattern="^back_to_admin$")
            ],
            name="admin_search_conversation",
            persistent=True,
            conversation_timeout=300  # 5 minutes timeout
        )

        # ====== START OF NEW CODE FOR HANDLER REGISTRATION ======
        
        # First register the main conversation handler (highest priority)
        print("DEBUG: Registering main conversation handler")
        app.add_handler(conversation_handler, group=0)  # Use group 0 for highest priority
        
        # Register order tracking handler
        print("DEBUG: Registering tracking handler")
        app.add_handler(tracking_handler)
        
        # Register admin handlers
        print("DEBUG: Registering admin handlers")
        app.add_handler(admin_tracking_handler)
        app.add_handler(CommandHandler("admin", lambda update, context: admin_panel.show_panel(update, context)))
        app.add_handler(CommandHandler("health", health_check))
        
        # Register admin panel callback handlers
        print("DEBUG: Registering admin callback handlers")
        app.add_handler(CallbackQueryHandler(admin_panel.back_to_admin, pattern="^back_to_admin$"))
        app.add_handler(CallbackQueryHandler(admin_panel.view_orders, pattern="^view_orders$"))
        app.add_handler(CallbackQueryHandler(lambda update, context: admin_panel.view_orders(update, context), pattern="^filter_[a-z_]+$"))
        app.add_handler(CallbackQueryHandler(lambda update, context: admin_panel.manage_order(update, context), pattern="^manage_order_[A-Z0-9-]+$"))
        app.add_handler(CallbackQueryHandler(admin_panel.update_order_status, pattern="^update_status_[A-Z0-9-]+$"))
        app.add_handler(CallbackQueryHandler(admin_panel.view_payment_screenshot, pattern="^view_payment_[A-Z0-9-]+$"))
        app.add_handler(CallbackQueryHandler(admin_panel.set_order_status, pattern="^set_status_[a-z_]+$"))
        app.add_handler(CallbackQueryHandler(admin_panel.skip_tracking_link, pattern="^skip_tracking_link$"))
        app.add_handler(CallbackQueryHandler(admin_panel.add_tracking_link, pattern="^add_tracking_link$"))
        app.add_handler(admin_search_handler)
        app.add_handler(CallbackQueryHandler(admin_panel.review_payments, pattern="^approve_payments$"))
        app.add_handler(CallbackQueryHandler(admin_panel.review_specific_payment, pattern="^review_payment_[A-Z0-9-]+$"))
        app.add_handler(CallbackQueryHandler(admin_panel.process_payment_action, pattern="^(approve|reject)_payment_[A-Z0-9-]+$"))
        
        # Register utility and recovery commands
        print("DEBUG: Registering utility handlers")
        app.add_handler(CommandHandler("restart", force_restart))
        app.add_handler(CommandHandler("force_reset", force_reset_command))
        app.add_handler(CommandHandler("categories", back_to_categories_wrapper))
        
        # Register global start command handler
        app.add_handler(CommandHandler("start", lambda update, context: (context.user_data.clear(), start_wrapper(update, context)),
                                      filters=~filters.UpdateType.EDITED_MESSAGE))
        
        # Register the unknown command handler
        print("DEBUG: Registering unknown command handler")
        unknown_command_handler = MessageHandler(
            filters.COMMAND & ~filters.UpdateType.EDITED_MESSAGE, 
            command_not_found
        )
        app.add_handler(unknown_command_handler)
        
        # Finally, register the debug callback handler as the LAST handler
        print("DEBUG: Registering debug callback handler as fallback")
        app.add_handler(CallbackQueryHandler(debug_callback), group=999)  # Use high group number to ensure it runs last
        
        # Debug registered handlers
        print("DEBUG: Registered handlers:")
        for group in app.handlers.keys():
            print(f"DEBUG: - Group {group} has {len(app.handlers[group])} handlers")
            
        # ====== END OF NEW CODE FOR HANDLER REGISTRATION ======

        # Log the startup
        loggers["main"].info("Bot is running with debugging enabled...")
        print("Bot is running with debugging enabled...")
        
        # Start the bot
        app.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        loggers["errors"].critical(f"Critical error starting bot: {type(e).__name__}: {e}")
        print(f"Critical error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
