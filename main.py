# ---------------------------- Ganja Paraiso Telegram Bot ----------------------------
"""
All-in-one Telegram bot for Ganja Paraiso cannabis store.
Handles product ordering, order tracking, payment processing, and admin management.
"""
import re
import time
import random
import asyncio
import logging
import os
import sys
import io
from io import BytesIO
from datetime import datetime
from logging.handlers import RotatingFileHandler

# Import Telegram components
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    Application,
    PicklePersistence
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

# Import Google API components
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Import .env support
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ---------------------------- Constants & Configuration ----------------------------
# States for the ConversationHandler
CATEGORY, SUBOPTION, QUANTITY, CONFIRM, DETAILS, CONFIRM_DETAILS, PAYMENT, TRACKING = range(8)
ADMIN_SEARCH, ADMIN_TRACKING = 8, 9

# Get configuration from environment variables or use defaults
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7870716772:AAFn8Gjay6Ok6a3YeqU1WIZdmixQbMCHfiI")
ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "5167750837"))
GCASH_NUMBER = os.getenv("GCASH_NUMBER", "09171234567")

# Google API configuration
GOOGLE_SHEET_NAME = "Telegram Orders"
GOOGLE_CREDENTIALS_FILE = "woop-woop-project-2ba60593fd8d.json"
PAYMENT_SCREENSHOTS_FOLDER_ID = "1hIanVMnTFSnKvHESoK7mgexn_QwlmF69"

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
    "update": "💫"
}

# ---------------------------- Product Dictionary ----------------------------
PRODUCTS = {
    "buds": {
        "name": "Premium Buds",
        "emoji": EMOJI["buds"],
        "description": "High-quality cannabis flowers",
        "min_order": 1,
        "unit": "grams",
        "types": ["indica", "sativa", "hybrid"]
    },
    "local": {
        "name": "Local (BG)",
        "emoji": EMOJI["local"],
        "description": "Local budget-friendly option",
        "min_order": 10,
        "unit": "grams",
        "price_per_unit": 1000
    },
    "carts": {
        "name": "Carts/Disposables",
        "emoji": EMOJI["carts"],
        "description": "Pre-filled vape cartridges",
        "min_order": 1,
        "unit": "units",
        "options": [
            ("Brand A", "brand_a", 25),
            ("Brand B", "brand_b", 30)
        ]
    },
    "edibles": {
        "name": "Edibles",
        "emoji": EMOJI["edibles"],
        "description": "Cannabis-infused food products",
        "min_order": 1,
        "unit": "pieces",
        "options": [
            ("Premium", "premium", 15),
            ("Standard", "standard", 8)
        ]
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
        f"{EMOJI['info']} Note: If you're using the desktop app of Telegram, please select "
        "the option to compress the image when uploading or pasting your payment screenshot.\n\n"
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
    "shipping_details": r"^(?P<name>[\w\s]+)\s*/\s*(?P<address>[\w\s,]+)\s*/\s*(?P<contact>\+?\d{10,15})$",
    "quantity": r"(\d+)"
}

# ---------------------------- Rate Limiting ----------------------------
RATE_LIMITS = {
    "order": 10,    # Max 10 orders per hour
    "payment": 15,  # Max 15 payment uploads per hour
    "track": 30,    # Max 30 tracking requests per hour
    "admin": 50     # Max 50 admin actions per hour
}

# ---------------------------- Cache Configuration ----------------------------
CACHE_EXPIRY = {
    "inventory": 300,     # 5 minutes
    "order_status": 60,   # 1 minute
    "customer_info": 600  # 10 minutes
}

# ---------------------------- Default Values ----------------------------
DEFAULT_INVENTORY = [
    {"Strain": "Unknown", "Type": "indica", "Price": 2000, "Stock": 5},
    {"Strain": "Unknown", "Type": "sativa", "Price": 2000, "Stock": 5},
    {"Strain": "Unknown", "Type": "hybrid", "Price": 2000, "Stock": 5}
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
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    # Create different loggers for different concerns
    loggers = {
        "main": logging.getLogger("main"),
        "orders": logging.getLogger("orders"),
        "payments": logging.getLogger("payments"),
        "errors": logging.getLogger("errors"),
        "admin": logging.getLogger("admin")
    }
    
    # Configure each logger
    for name, logger in loggers.items():
        logger.setLevel(logging.INFO)
        
        # Create rotating file handler (10 files, 5MB each)
        handler = RotatingFileHandler(
            f"{log_dir}/{name}.log",
            maxBytes=5*1024*1024,
            backupCount=10
        )
        
        # Create formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        
        # Add handler to logger
        logger.addHandler(handler)
        
        # Also add a console handler for development
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(formatter)
        logger.addHandler(console)
    
    return loggers

def log_order(logger, order_data, action="created"):
    """
    Log order information with consistent formatting.
    
    Args:
        logger: The logger instance to use
        order_data (dict): Order information
        action (str): Action being performed on the order
    """
    order_id = order_data.get("order_id", "Unknown")
    customer = order_data.get("name", "Unknown")
    total = order_data.get("total", 0)
    
    logger.info(
        f"Order {order_id} {action} | Customer: {customer} | "
        f"Total: ₱{total:,.2f} | Items: {order_data.get('items_count', 0)}"
    )

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
    """Manage Google API connections with rate limiting and backoff."""
    
    def __init__(self, loggers):
        """
        Initialize the Google APIs Manager.
        
        Args:
            loggers (dict): Dictionary of logger instances
        """
        self.loggers = loggers
        self.last_request_time = {}
        self.min_request_interval = 1.0  # Minimum seconds between requests
        self._sheet_client = None
        self._drive_service = None
        self._sheet = None
        self._inventory_sheet = None
        self._sheet_initialized = False
        
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
            # Set up authentication for Google Sheets
            scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_FILE, scope)
            self._sheet_client = gspread.authorize(creds)
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
        if self._sheet_initialized:
            return self._sheet, self._inventory_sheet
            
        try:
            # Make a rate-limited request
            await self._rate_limit_request('sheets')
            
            # Get the spreadsheet
            client = await self.get_sheet_client()
            spreadsheet = client.open(GOOGLE_SHEET_NAME)
            
            # Get or create the main orders sheet
            try:
                self._sheet = spreadsheet.sheet1
            except:
                self._sheet = spreadsheet.add_worksheet("Orders", 1000, 20)
            
            # Get or create the inventory sheet
            try:
                self._inventory_sheet = spreadsheet.worksheet("Inventory")
            except:
                self._inventory_sheet = spreadsheet.add_worksheet("Inventory", 100, 5)
                # Initialize inventory headers
                self._inventory_sheet.append_row(["Strain", "Type", "Price", "Stock"])
            
            # Ensure the orders sheet has the correct headers
            current_headers = self._sheet.row_values(1)
            if not current_headers or len(current_headers) < len(SHEET_HEADERS):
                self._sheet.update("A1", [SHEET_HEADERS])
            
            self._sheet_initialized = True
            return self._sheet, self._inventory_sheet
            
        except Exception as e:
            self.loggers["errors"].error(f"Failed to initialize sheets: {e}")
            # Return None or provide fallback behavior
            return None, None
    
    async def fetch_inventory(self):
        """
        Fetch inventory data from Google Sheets.
        Handles errors with graceful fallback to default inventory.
        
        Returns:
            dict: Dictionary of strains organized by type
        """
        strains = {'indica': [], 'sativa': [], 'hybrid': []}
        prices = {}
        
        try:
            # Initialize sheets
            _, inventory_sheet = await self.initialize_sheets()
            
            if not inventory_sheet:
                # Fallback to default inventory
                self.loggers["errors"].warning("Using default inventory due to sheet access failure")
                for item in DEFAULT_INVENTORY:
                    strain_name = item['Strain']
                    strain_key = strain_name.lower().replace(' ', '_')
                    strains[item['Type'].lower()].append((strain_name, strain_key))
                    prices[strain_key] = item['Price']
                return strains, prices
            
            # Make a rate-limited request
            await self._rate_limit_request('inventory')
            
            # Get inventory data
            inventory_data = inventory_sheet.get_all_records()
            
            for item in inventory_data:
                if 'Stock' in item and item['Stock'] > 0:
                    strain_name = item['Strain']
                    strain_type = item.get('Type', '').lower()
                    
                    # Skip items with missing data
                    if not strain_name or not strain_type or strain_type not in strains:
                        continue
                        
                    strain_key = strain_name.lower().replace(' ', '_')
                    strains[strain_type].append((strain_name, strain_key))
                    prices[strain_key] = item['Price']
            
            return strains, prices
            
        except Exception as e:
            self.loggers["errors"].error(f"Error fetching inventory: {e}")
            # Fallback to default inventory
            self.loggers["errors"].warning("Using default inventory due to error")
            for item in DEFAULT_INVENTORY:
                strain_name = item['Strain']
                strain_key = strain_name.lower().replace(' ', '_')
                strains[item['Type'].lower()].append((strain_name, strain_key))
                prices[strain_key] = item['Price']
            return strains, prices
    
    async def upload_payment_screenshot(self, file_bytes, filename):
        """
        Upload a payment screenshot to Google Drive.
        
        Args:
            file_bytes (BytesIO): File bytes to upload
            filename (str): Name to give the file
            
        Returns:
            str: Web view link to the uploaded file
        """
        try:
            # Make a rate-limited request
            await self._rate_limit_request('drive')
            
            # Get the drive service
            drive_service = await self.get_drive_service()
            
            # Prepare file metadata
            file_metadata = {
                'name': filename,
                'mimeType': 'image/jpeg',
                'parents': [PAYMENT_SCREENSHOTS_FOLDER_ID]
            }
            
            # Create media upload object
            media = MediaIoBaseUpload(BytesIO(file_bytes), mimetype='image/jpeg')
            
            # Execute the upload with retry logic
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    drive_file = drive_service.files().create(
                        body=file_metadata, 
                        media_body=media, 
                        fields='id, webViewLink'
                    ).execute()
                    
                    return drive_file.get('webViewLink')
                except Exception as e:
                    retry_count += 1
                    if retry_count == max_retries:
                        raise
                    
                    # Exponential backoff
                    wait_time = 2 ** retry_count
                    self.loggers["errors"].warning(
                        f"Drive upload failed, retrying in {wait_time} seconds: {e}"
                    )
                    await asyncio.sleep(wait_time)
            
        except Exception as e:
            self.loggers["errors"].error(f"Failed to upload payment screenshot: {e}")
            raise
    
    async def add_order_to_sheet(self, order_data):
        """
        Add an order to the Google Sheet.
        
        Args:
            order_data (dict): Order data to add
            
        Returns:
            bool: Success status
        """
        try:
            # Initialize sheets
            sheet, _ = await self.initialize_sheets()
            
            if not sheet:
                self.loggers["errors"].error("Failed to get sheet for adding order")
                return False
            
            # Make a rate-limited request
            await self._rate_limit_request('sheets_write')
            
            # Append the row
            sheet.append_row(order_data)
            return True
            
        except Exception as e:
            self.loggers["errors"].error(f"Failed to add order to sheet: {e}")
            return False
    
    async def update_order_status(self, order_id, new_status, tracking_link=None):
        """
        Update an order's status in the sheet.
        
        Args:
            order_id (str): Order ID to update
            new_status (str): New status to set
            tracking_link (str, optional): Tracking link to add
            
        Returns:
            tuple: (success, customer_telegram_id)
        """
        try:
            # Initialize sheets
            sheet, _ = await self.initialize_sheets()
            
            if not sheet:
                self.loggers["errors"].error("Failed to get sheet for updating order status")
                return False, None
            
            # Make a rate-limited request
            await self._rate_limit_request('sheets_read')
            
            # Get all orders
            orders = sheet.get_all_records()
            
            # Find the order row
            customer_id = None
            updated = False
            row_idx = 0
            
            for idx, order in enumerate(orders, 2):  # Start from 2 to account for header row
                if (order.get('Order ID') == order_id and 
                    order.get('Product') == 'COMPLETE ORDER'):
                    
                    # Make another rate-limited request
                    await self._rate_limit_request('sheets_write')
                    
                    # Update status - use the status column index
                    status_col = SHEET_COLUMN_INDICES.get('Status', 9)  # Default to 9 if not found
                    sheet.update_cell(idx, status_col, new_status)
                    
                    # Update tracking link if provided
                    if tracking_link is not None:
                        tracking_col = SHEET_COLUMN_INDICES.get('Tracking Link', 13)
                        sheet.update_cell(idx, tracking_col, tracking_link)
                    
                    # Get customer Telegram ID
                    telegram_id_col = 'Telegram ID'
                    try:
                        customer_id = int(order.get(telegram_id_col, 0))
                    except (ValueError, TypeError):
                        customer_id = None
                    
                    updated = True
                    row_idx = idx
                    break
            
            return updated, customer_id
            
        except Exception as e:
            self.loggers["errors"].error(f"Failed to update order status: {e}")
            return False, None
    
    async def get_order_details(self, order_id):
        """
        Get details for a specific order.
        
        Args:
            order_id (str): Order ID to look up
            
        Returns:
            dict: Order details or None if not found
        """
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
                    return order
            
            return None
            
        except Exception as e:
            self.loggers["errors"].error(f"Failed to get order details: {e}")
            return None
    
    async def _rate_limit_request(self, api_name):
        """
        Enforce rate limiting for API requests.
        
        Args:
            api_name (str): Name of the API being accessed
        """
        # Ensure minimum time between requests to the same API
        now = time.time()
        if api_name in self.last_request_time:
            elapsed = now - self.last_request_time[api_name]
            if elapsed < self.min_request_interval:
                await asyncio.sleep(self.min_request_interval - elapsed)
                
        # Update the last request time
        self.last_request_time[api_name] = time.time()

# ---------------------------- Utility Functions ----------------------------
def build_category_buttons():
    """
    Build inline keyboard with product category buttons.
    
    Returns:
        InlineKeyboardMarkup: Keyboard with product category buttons
    """
    keyboard = []
    
    for product_id, product in PRODUCTS.items():
        button_text = f"{product['emoji']} {product['name']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=product_id)])
    
    return InlineKeyboardMarkup(keyboard)

def build_admin_buttons():
    """
    Build inline keyboard with admin panel options.
    
    Returns:
        InlineKeyboardMarkup: Keyboard with admin options
    """
    keyboard = [
        [InlineKeyboardButton(f"{EMOJI['list']} View All Orders", callback_data='view_orders')],
        [InlineKeyboardButton(f"{EMOJI['search']} Search Order by ID", callback_data='search_order')],
        [InlineKeyboardButton(f"{EMOJI['inventory']} Manage Inventory", callback_data='manage_inventory')],
        [InlineKeyboardButton(f"{EMOJI['review']} Review Payments", callback_data='approve_payments')]
    ]
    
    return InlineKeyboardMarkup(keyboard)

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

        # Add the item details to the summary
        summary += f"- {category} ({suboption}): {quantity} {unit} - ₱{total_price:,.2f}\n"

    # Add the total cost to the summary
    summary += f"\n{EMOJI['money']} Total Cost: ₱{total_cost:,.2f}\n"

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
    Sanitize user input to prevent injection attacks.
    
    Args:
        text (str): Text to sanitize
        max_length (int): Maximum length to allow
        
    Returns:
        str: Sanitized text
    """
    if not text:
        return ""
        
    # Remove any HTML or unwanted characters
    sanitized = re.sub(r'<[^>]*>', '', text)
    
    # Limit length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
        
    return sanitized

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
        if quantity < 10:
            return False, "Minimum order for Local (BG) is 10 grams."
        if quantity % 10 != 0:
            return False, "For Local (BG), please enter a quantity that's a multiple of 10 (e.g., 10, 20, 30)."
    
    # Product-specific validation
    if category and category in PRODUCTS:
        min_order = PRODUCTS[category].get("min_order", 1)
        unit = PRODUCTS[category].get("unit", "units")
        
        if quantity < min_order:
            return False, f"Minimum order for {PRODUCTS[category]['name']} is {min_order} {unit}."
    
    return True, quantity

def validate_shipping_details(text):
    """
    Validate shipping details format.
    
    Args:
        text (str): Shipping details text
        
    Returns:
        tuple: (is_valid, result_dict_or_error_message)
    """
    pattern = REGEX["shipping_details"]
    match = re.match(pattern, text)
    
    if not match:
        return False, "Invalid format. Use: Name / Address / Contact"
    
    # Extract the matched groups
    groups = match.groupdict()
    
    # Sanitize the inputs
    name = sanitize_input(groups.get("name", ""), 50)
    address = sanitize_input(groups.get("address", ""), 100)
    contact = sanitize_input(groups.get("contact", ""), 15)
    
    if not name or not address or not contact:
        return False, "Name, address, and contact are all required."
    
    return True, {
        "name": name,
        "address": address,
        "contact": contact
    }

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

def get_user_session(context, user_id):
    """
    Get or create a user session.
    
    Args:
        context: The conversation context
        user_id (int): User's Telegram ID
        
    Returns:
        dict: User session data
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
    return context.bot_data["sessions"][user_id]

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

async def retry_operation(operation, max_retries=3):
    """
    Retry an async operation with exponential backoff.
    
    Args:
        operation (callable): Async function to retry
        max_retries (int): Maximum number of retry attempts
        
    Returns:
        Any: Result from the operation
        
    Raises:
        Exception: The last exception encountered after all retries
    """
    retry_count = 0
    while retry_count < max_retries:
        try:
            return await operation()
        except (ConnectionError, TimeoutError) as e:
            retry_count += 1
            if retry_count == max_retries:
                raise e
            wait_time = 2 ** retry_count  # Exponential backoff
            print(f"Operation failed, retrying in {wait_time} seconds...")
            await asyncio.sleep(wait_time)

# ---------------------------- Inventory Management ----------------------------
class InventoryManager:
    """Manages product inventory and caching."""
    
    def __init__(self, google_apis, loggers):
        """
        Initialize the inventory manager.
        
        Args:
            google_apis: GoogleAPIsManager instance
            loggers: Dictionary of logger instances
        """
        self.google_apis = google_apis
        self.loggers = loggers
        self.cache = {
            "strains": None,
            "prices": None,
            "last_update": 0
        }
        
    async def get_inventory(self, force_refresh=False):
        """
        Get inventory data with caching.
        
        Args:
            force_refresh (bool): Whether to bypass cache
            
        Returns:
            tuple: (strains, prices)
        """
        current_time = time.time()
        cache_valid = (
            self.cache["strains"] is not None and
            self.cache["prices"] is not None and
            current_time - self.cache["last_update"] < CACHE_EXPIRY["inventory"]
        )
        
        if cache_valid and not force_refresh:
            return self.cache["strains"], self.cache["prices"]
            
        try:
            # Fetch fresh inventory data
            strains, prices = await self.google_apis.fetch_inventory()
            
            # Update cache
            self.cache["strains"] = strains
            self.cache["prices"] = prices
            self.cache["last_update"] = current_time
            
            self.loggers["main"].info("Inventory cache refreshed")
            return strains, prices
            
        except Exception as e:
            self.loggers["errors"].error(f"Error refreshing inventory: {e}")
            
            # If we have cached data, use it despite expiry
            if self.cache["strains"] and self.cache["prices"]:
                self.loggers["main"].warning("Using expired inventory cache")
                return self.cache["strains"], self.cache["prices"]
                
            # Build fallback inventory from product dictionary
            self.loggers["main"].warning("Using fallback inventory")
            return self._get_fallback_inventory()
    
    async def get_product_options(self, category):
        """
        Get options for a specific product category.
        
        Args:
            category (str): Product category key
            
        Returns:
            tuple: (options_list, prices_dict)
        """
        if category not in PRODUCTS:
            return [], {}
            
        product = PRODUCTS[category]
        
        # For buds, we need to fetch from inventory
        if category == "buds":
            strains, prices = await self.get_inventory()
            return self._flatten_strain_options(strains), prices
            
        # For other categories, use the predefined options
        elif "options" in product:
            options = []
            prices = {}
            
            for option in product["options"]:
                name, key, price = option
                options.append((name, key))
                prices[key] = price
                
            return options, prices
            
        # Fallback
        return [], {}
    
    def _flatten_strain_options(self, strains):
        """
        Convert strain dictionary to flat options list.
        
        Args:
            strains (dict): Strains organized by type
            
        Returns:
            list: Flat list of (name, key) tuples
        """
        options = []
        for strain_type, strain_list in strains.items():
            for strain in strain_list:
                options.append(strain)  # Already (name, key) format
        return options
    
    def _get_fallback_inventory(self):
        """
        Generate fallback inventory data from product dictionary.
        
        Returns:
            tuple: (strains, prices)
        """
        strains = {'indica': [], 'sativa': [], 'hybrid': []}
        prices = {}
        
        # Add some default strains
        for strain_type in strains:
            for i in range(1, 3):
                name = f"{strain_type.capitalize()} Strain {i}"
                key = f"{strain_type}_strain_{i}"
                strains[strain_type].append((name, key))
                prices[key] = 2000  # Default price
        
        return strains, prices
    
    async def calculate_price(self, category, suboption, quantity):
        """
        Calculate price for a product based on category, type and quantity.
        
        Args:
            category (str): Product category
            suboption (str): Product suboption
            quantity (int): Quantity
            
        Returns:
            tuple: (total_price, unit_price)
        """
        # Get product
        if category not in PRODUCTS:
            return 0, 0
            
        product = PRODUCTS[category]
        
        # Handle Local (BG)
        if category == "local":
            # Ensure minimum order
            adjusted_quantity = max(quantity, product["min_order"])
            unit_price = product["price_per_unit"]
            # Calculate based on multiples of 10
            price_factor = adjusted_quantity / product["min_order"]
            total_price = unit_price * price_factor
            return total_price, unit_price
            
        # For buds, get from inventory
        elif category == "buds":
            _, prices = await self.get_inventory()
            if suboption in prices:
                unit_price = prices[suboption]
                total_price = unit_price * quantity
                return total_price, unit_price
                
        # For other product types, fetch from options
        else:
            _, prices = await self.get_product_options(category)
            if suboption in prices:
                unit_price = prices[suboption]
                total_price = unit_price * quantity
                return total_price, unit_price
                
        # Fallback
        return 0, 0
    
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
        
        if not cart:
            self.loggers["errors"].error(f"Attempted to create order with empty cart for user {telegram_id}")
            return None, False
        
        # Format cart items in a single cell with bullet points
        cart_summary = ""
        for idx, item in enumerate(cart, 1):
            product = item.get("suboption", "Unknown")
            category = item.get("category", "Unknown")
            quantity = item.get("quantity", 0)
            unit = item.get("unit", "grams")
            item_price = item.get("total_price", 0)
            
            # Add each item with bullet points
            cart_summary += f"• {quantity}x {category} ({product}): {unit} ₱{item_price:,.2f}\n"
        
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
        
        # Add to Google Sheet
        success = await self.google_apis.add_order_to_sheet(order_data)
        
        if success:
            # Update user session data
            user_session = get_user_session(context, telegram_id)
            user_session["order_count"] += 1
            user_session["total_spent"] += total_price
            user_session["last_order_id"] = order_id
            
            # Log the successful order creation
            self.loggers["orders"].info(
                f"Order {order_id} created for {name} ({telegram_id}) | "
                f"Items: {len(cart)} | Total: ₱{total_price:,.2f}"
            )
            
            return order_id, True
        else:
            self.loggers["errors"].error(f"Failed to create order for user {telegram_id}")
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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE, inventory_manager, loggers):
    """
    Start the ordering conversation.
    
    Args:
        update: Telegram update
        context: Conversation context
        inventory_manager: Inventory manager instance
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state
    """
    user = update.message.from_user
    
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
    
    # Send welcome message with category buttons
    await update.message.reply_text(
        MESSAGES["welcome"],
        reply_markup=build_category_buttons()
    )
    
    return CATEGORY

async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE, inventory_manager, loggers):
    """
    Handle category selection.
    
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
    
    # Get the selected category
    category = query.data
    context.user_data["category"] = category
    
    # Log the selection
    loggers["main"].info(f"User {query.from_user.id} selected category: {category}")
    
    # Handle Local (BG) directly
    if category == "local":
        # Store the suboption
        context.user_data["suboption"] = "BG"
        
        # Get product details
        product = PRODUCTS["local"]
        emoji = product["emoji"]
        unit = product["unit"]
        min_order = product["min_order"]
        
        # Create the prompt
        await query.edit_message_text(
            f"{emoji} How many {unit} of BG would you like to order?\n\n"
            f"{EMOJI['info']} Note: Minimum order is {min_order} {unit} (₱1000). "
            f"Orders above {min_order} {unit} will be priced proportionally."
        )
        return QUANTITY
        
    # For other categories, show options
    options, _ = await inventory_manager.get_product_options(category)
    
    if not options:
        # Handle error case with no options
        await query.edit_message_text(
            f"{EMOJI['error']} Sorry, no options are available for this category right now."
            "Please try another category.",
            reply_markup=build_category_buttons()
        )
        return CATEGORY
        
    # Build keyboard with options
    keyboard = [[InlineKeyboardButton(name, callback_data=data)] for name, data in options]
    
    # Get emoji for selected category
    emoji = PRODUCTS[category].get("emoji", EMOJI["info"])
    
    await query.edit_message_text(
        f"{emoji} Please choose an option:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return SUBOPTION

async def choose_suboption(update: Update, context: ContextTypes.DEFAULT_TYPE, loggers):
    """
    Handle suboption selection.
    
    Args:
        update: Telegram update
        context: Conversation context
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state
    """
    query = update.callback_query
    await query.answer()
    
    # Get the selected suboption
    context.user_data["suboption"] = query.data
    
    # Get the category
    category = context.user_data.get("category")
    
    # Log the selection
    loggers["main"].info(
        f"User {query.from_user.id} selected {category} - {query.data}"
    )
    
    # Get the appropriate emoji and prompt based on category
    if category in PRODUCTS:
        product = PRODUCTS[category]
        emoji = product.get("emoji", "⚖️")
        unit = product.get("unit", "units")
        prompt = f"{emoji} How many {unit} would you like to order?"
    else:
        prompt = "⚖️ How many would you like to order?"
    
    await query.edit_message_text(prompt)
    
    return QUANTITY

async def input_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE, inventory_manager, loggers):
    """
    Handle quantity input.
    
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
    
    # Get category and suboption from context
    category = context.user_data.get("category")
    suboption = context.user_data.get("suboption")
    
    # Validate quantity
    is_valid, result = validate_quantity(quantity_text, category)
    
    if not is_valid:
        await update.message.reply_text(f"{EMOJI['warning']} {result} Please try again.")
        return QUANTITY
        
    quantity = result
    
    # Calculate price
    total_price, unit_price = await inventory_manager.calculate_price(
        category, suboption, quantity
    )
    
    if total_price == 0:
        await update.message.reply_text(ERRORS["invalid_category"])
        return CATEGORY
    
    # Store in context
    context.user_data["parsed_quantity"] = quantity
    context.user_data["unit_price"] = unit_price
    context.user_data["total_price"] = total_price
    
    # Get product details
    product = PRODUCTS.get(category, {})
    unit = product.get("unit", "units")
    
    # Build checkout summary
    summary = (
        f"{EMOJI['cart']} Checkout Summary:\n"
        f"- Category: {category.capitalize()}\n"
        f"- Option: {suboption.replace('_', ' ').capitalize()}\n"
        f"- Quantity: {quantity} {unit}\n"
        f"- Unit Price: ₱{unit_price:,.2f}\n"
        f"- Total: ₱{total_price:,.2f}\n\n"
    )
    
    # Create confirmation buttons
    keyboard = [
        [InlineKeyboardButton(f"{EMOJI['success']} Confirm Selection", callback_data="confirm")],
        [InlineKeyboardButton(f"{EMOJI['error']} Cancel", callback_data="cancel")],
    ]
    
    # Log the selection
    loggers["main"].info(
        f"User {user.id} selected quantity {quantity} of {category} ({suboption}) "
        f"for ₱{total_price:,.2f}"
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
        suboption = context.user_data.get("suboption", "Unknown").replace("_", " ").capitalize()
        quantity = context.user_data.get("parsed_quantity", 0)
        total_price = context.user_data.get("total_price", 0)
        
        # Get product unit
        product = PRODUCTS.get(category.lower(), {})
        unit = product.get("unit", "units")
        
        # Create item and add to cart
        current_item = {
            "category": category,
            "suboption": suboption,
            "quantity": quantity,
            "total_price": total_price,
            "unit": unit
        }
        
        manage_cart(context, "add", current_item)
        
        # Log the cart addition
        loggers["orders"].info(
            f"User {query.from_user.id} added to cart: {category} ({suboption}) "
            f"x{quantity} {unit} - ₱{total_price:,.2f}"
        )
        
        await query.edit_message_text(
            MESSAGES["order_added"],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['cart']} Add More", callback_data="add_more")],
                [InlineKeyboardButton(f"{EMOJI['shipping']} Proceed to Checkout", callback_data="proceed")],
                [InlineKeyboardButton(f"{EMOJI['error']} Cancel Order", callback_data="cancel")]
            ]),
        )
        return CONFIRM
    
    elif query.data == "add_more":
        # Return to category selection
        await query.edit_message_text(
            f"{EMOJI['cart']} What would you like to add to your cart?",
            reply_markup=build_category_buttons()
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
    
    Args:
        update: Telegram update
        context: Conversation context
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state
    """
    user = update.message.from_user
    details_text = update.message.text
    
    # Validate shipping details
    is_valid, result = validate_shipping_details(details_text)
    
    if not is_valid:
        await update.message.reply_text(MESSAGES["invalid_details"])
        return DETAILS
    
    # Store the details
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
        shipping_details = context.user_data.get("shipping_details", "N/A")
        customer_name = update.callback_query.from_user.full_name
        
        # Create a detailed cart summary
        cart_summary = ""
        for idx, item in enumerate(cart, 1):
            unit = item.get("unit", "units")
            cart_summary += (
                f"{idx}. {item['category']} ({item['suboption']}): "
                f"{item['quantity']} {unit} - ₱{item['total_price']:,.2f}\n"
            )
        
        # Prepare the complete summary for the admin
        summary = (
            f"{EMOJI['new']} New Order Received\n\n"
            f"{EMOJI['customer']} Customer: {customer_name}\n\n"
            f"{EMOJI['cart']} Cart Items:\n{cart_summary}\n\n"
            f"{EMOJI['money']} Total Cost: ₱{total_cost:,.2f}\n\n"
            f"{EMOJI['shipping']} Shipping Details: {shipping_details}"
        )
        
        # Log the order confirmation
        loggers["orders"].info(
            f"User {query.from_user.id} confirmed order with {len(cart)} items "
            f"totaling ₱{total_cost:,.2f}"
        )
        
        # Send summary to admin
        await context.bot.send_message(admin_id, summary)
        
        # Prompt user for payment
        await query.edit_message_text(
            MESSAGES["payment_instructions"].format(GCASH_NUMBER)
        )
        
        return PAYMENT
    elif query.data == 'edit_details':
        await query.edit_message_text(MESSAGES["checkout_prompt"])
        return DETAILS
    
# ---------------------------- Payment & Tracking Handlers ----------------------------
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
            
            # Download photo
            photo = update.message.photo[-1]
            file = await photo.get_file()
            file_bytes = await file.download_as_bytearray()
            
            # Generate filename
            current_date = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            user_name = context.user_data.get("name", "Unknown")
            filename = f"Order_{current_date}_{sanitize_input(user_name)}.jpg"
            
            # Upload to Drive
            file_url = await google_apis.upload_payment_screenshot(file_bytes, filename)
            
            # Store user telegram ID
            context.user_data["telegram_id"] = user.id
            
            # Create order in system
            order_id, success = await order_manager.create_order(
                context, context.user_data, file_url
            )
            
            if success and order_id:
                # Clear the cart
                manage_cart(context, "clear")
                
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
                await update.message.reply_text(
                    f"{EMOJI['error']} There was a problem processing your order. "
                    "Please try again or contact customer support."
                )
                return PAYMENT
                
        except Exception as e:
            loggers["errors"].error(f"Payment processing error: {str(e)}")
            await update.message.reply_text(ERRORS["payment_processing"])
            return PAYMENT
    else:
        await update.message.reply_text(MESSAGES["invalid_payment"])
        return PAYMENT

async def track_order(update: Update, context: ContextTypes.DEFAULT_TYPE, loggers):
    """
    Start the order tracking process.
    
    Args:
        update: Telegram update
        context: Conversation context
        loggers: Dictionary of logger instances
        
    Returns:
        int: Next conversation state
    """
    user = update.message.from_user
    
    # Check rate limits
    if not check_rate_limit(context, user.id, "track"):
        await update.message.reply_text(
            f"{EMOJI['warning']} You've reached the maximum number of tracking requests allowed per hour. "
            "Please try again later."
        )
        return ConversationHandler.END
    
    # Log the tracking attempt
    loggers["main"].info(f"User {user.id} initiated order tracking")
    
    await update.message.reply_text(MESSAGES["tracking_prompt"])
    return TRACKING

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
    
    await update.message.reply_text(response_text)
    return ConversationHandler.END

# ---------------------------- Admin Handlers ----------------------------
async def admin_panel(
    update: Update, context: ContextTypes.DEFAULT_TYPE, 
    admin_id, loggers
):
    """
    Admin panel entry point - checks authorization and displays admin options.
    
    Args:
        update: Telegram update
        context: Conversation context
        admin_id: Telegram ID of the admin
        loggers: Dictionary of logger instances
        
    Returns:
        None
    """
    user = update.message.from_user
    
    # Check if user is authorized
    if user.id != admin_id:
        await update.message.reply_text(MESSAGES["not_authorized"])
        loggers["admin"].warning(f"Unauthorized admin panel access attempt by user {user.id}")
        return
    
    # Check rate limits
    if not check_rate_limit(context, user.id, "admin"):
        await update.message.reply_text(
            f"{EMOJI['warning']} You've reached the maximum number of admin actions allowed per hour. "
            "Please try again later."
        )
        return
    
    # Log the admin panel access
    loggers["admin"].info(f"Admin {user.id} accessed admin panel")
    
    # Send welcome message with options
    await update.message.reply_text(
        MESSAGES["admin_welcome"],
        reply_markup=build_admin_buttons()
    )

async def view_orders(
    update: Update, context: ContextTypes.DEFAULT_TYPE, 
    google_apis, loggers
):
    """
    Display all orders with filtering options.
    
    Args:
        update: Telegram update
        context: Conversation context
        google_apis: GoogleAPIsManager instance
        loggers: Dictionary of logger instances
        
    Returns:
        None
    """
    query = update.callback_query
    await query.answer()
    
    # Get filter from context or set default
    status_filter = context.user_data.get('status_filter', 'all')
    
    # Initialize sheets
    sheet, _ = await google_apis.initialize_sheets()
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
        filter_buttons = build_filter_buttons(status_filter)
        keyboard = filter_buttons + [
            [InlineKeyboardButton(f"{EMOJI['back']} Back to Admin Panel", callback_data='back_to_admin')]
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
    filter_buttons = build_filter_buttons(status_filter)
    
    # Combine all buttons
    keyboard = (
        order_buttons + 
        nav_buttons + 
        filter_buttons + 
        [[InlineKeyboardButton(f"{EMOJI['back']} Back to Admin Panel", callback_data='back_to_admin')]]
    )
    
    loggers["admin"].info(f"Admin viewed orders with filter: {status_filter}")
    
    await query.edit_message_text(
        message, 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def build_filter_buttons(current_filter):
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

async def filter_orders(update: Update, context: ContextTypes.DEFAULT_TYPE, google_apis, loggers):
    """
    Handle order filtering by status.
    
    Args:
        update: Telegram update
        context: Conversation context
        google_apis: GoogleAPIsManager instance
        loggers: Dictionary of logger instances
        
    Returns:
        None
    """
    query = update.callback_query
    await query.answer()
    
    # Extract the filter from callback data
    filter_value = query.data.replace('filter_', '')
    
    # Store the filter in context
    context.user_data['status_filter'] = filter_value
    
    loggers["admin"].info(f"Admin set order filter to: {filter_value}")
    
    # Refresh the orders view
    await view_orders(update, context, google_apis, loggers)

async def manage_order(
    update: Update, context: ContextTypes.DEFAULT_TYPE, 
    google_apis, loggers
):
    """
    Show order details and management options.
    
    Args:
        update: Telegram update
        context: Conversation context
        google_apis: GoogleAPIsManager instance
        loggers: Dictionary of logger instances
        
    Returns:
        None
    """
    query = update.callback_query
    await query.answer()
    
    # Extract order ID from callback data
    order_id = query.data.replace('manage_order_', '')
    
    # Store order ID in context
    context.user_data['current_order_id'] = order_id
    
    # Initialize sheets
    sheet, _ = await google_apis.initialize_sheets()
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
    
    # Find main order
    main_order = None
    order_items = []
    
    for order in orders:
        if 'Order ID' in order and order['Order ID'] == order_id:
            if 'Product' in order and order['Product'] == "COMPLETE ORDER":
                main_order = order
            else:
                order_items.append(order)
    
    if not main_order:
        await query.edit_message_text(
            MESSAGES["order_not_found"].format(order_id),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Orders", callback_data='view_orders')]
            ])
        )
        return
    
    # Create detailed order message with safe gets
    customer = main_order.get('Customer Name', main_order.get('Name', 'Unknown'))
    address = main_order.get('Address', 'No address provided')
    contact = main_order.get('Contact', main_order.get('Phone', 'No contact provided'))
    status = main_order.get('Status', 'Unknown')
    date = main_order.get('Order Date', 'N/A')
    total = main_order.get('Price', main_order.get('Total Price', '₱0'))
    payment_url = main_order.get('Payment URL', 'N/A')
    tracking_link = main_order.get('Tracking Link', '')
    
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
    message += f"{EMOJI['cart']} Items:\n{main_order.get('Notes', '• No detailed items found')}\n"
    
    # Create management buttons
    keyboard = [
        [InlineKeyboardButton(f"{EMOJI['update']} Update Status", callback_data=f'update_status_{order_id}')],
        [InlineKeyboardButton(f"{EMOJI['link']} Add/Update Tracking", callback_data=f'add_tracking_{order_id}')],
        [InlineKeyboardButton(f"{EMOJI['screenshot']} View Payment Screenshot", callback_data=f'view_payment_{order_id}')]
    ]
    
    # Add back button
    keyboard.append([InlineKeyboardButton(f"{EMOJI['back']} Back to Orders", callback_data='view_orders')])
    
    loggers["admin"].info(f"Admin viewing order details for {order_id}")
    
    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True  # Prevent tracking links from generating previews
    )

async def view_payment_screenshot(
    update: Update, context: ContextTypes.DEFAULT_TYPE, 
    google_apis, loggers
):
    """
    Send the payment screenshot to the admin.
    
    Args:
        update: Telegram update
        context: Conversation context
        google_apis: GoogleAPIsManager instance
        loggers: Dictionary of logger instances
        
    Returns:
        None
    """
    query = update.callback_query
    await query.answer()
    
    # Get order ID from context or callback data
    order_id = context.user_data.get('current_order_id')
    if not order_id:
        order_id = query.data.replace('view_payment_', '')
    
    # Initialize sheets
    sheet, _ = await google_apis.initialize_sheets()
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
    
    # Find payment URL
    payment_url = None
    for order in orders:
        if order.get('Order ID') == order_id and order.get('Product') == "COMPLETE ORDER":
            payment_url = order.get('Payment URL')
            break
    
    if not payment_url:
        await query.edit_message_text(
            ERRORS["no_screenshot"],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Order", callback_data=f'manage_order_{order_id}')]
            ])
        )
        return
    
    loggers["admin"].info(f"Admin viewed payment screenshot for order {order_id}")
    
    # Send the payment URL
    await query.edit_message_text(
        f"{EMOJI['screenshot']} Payment Screenshot for Order {order_id}:\n\n"
        f"Link: {payment_url}\n\n"
        "You can view the screenshot by clicking the link above.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{EMOJI['back']} Back to Order", callback_data=f'manage_order_{order_id}')]
        ])
    )

async def update_order_status(update: Update, context: ContextTypes.DEFAULT_TYPE, loggers):
    """
    Handle updating order status from admin panel.
    
    Args:
        update: Telegram update
        context: Conversation context
        loggers: Dictionary of logger instances
        
    Returns:
        None
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
        InlineKeyboardButton(f"{EMOJI['back']} Back to Order", callback_data=f'manage_order_{order_id}')
    ])
    
    loggers["admin"].info(f"Admin preparing to update status for order {order_id}")
    
    await query.edit_message_text(
        f"Select new status for Order {order_id}:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def set_order_status(
    update: Update, context: ContextTypes.DEFAULT_TYPE, 
    order_manager, loggers
):
    """
    Set the new status for an order and notify the customer.
    
    Args:
        update: Telegram update
        context: Conversation context
        order_manager: OrderManager instance
        loggers: Dictionary of logger instances
        
    Returns:
        None
    """
    query = update.callback_query
    await query.answer()
    
    # Get the order ID and status key
    order_id = context.user_data.get('current_order_id')
    status_key = query.data.replace('set_status_', '')
    
    if not order_id:
        await query.edit_message_text(
            f"{EMOJI['error']} Error: No order selected."
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
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Yes, Add Tracking Link", callback_data='add_tracking_link')],
                [InlineKeyboardButton("No, Skip Tracking Link", callback_data='skip_tracking_link')]
            ])
        )
        return
    
    # For other statuses, proceed with the update directly
    success = await order_manager.update_order_status(context, order_id, new_status)
    
    loggers["admin"].info(f"Admin updated order {order_id} status to {new_status}")
    
    if success:
        keyboard = [
            [InlineKeyboardButton("View Order Details", callback_data=f'manage_order_{order_id}')],
            [InlineKeyboardButton(f"{EMOJI['back']} Back to Orders", callback_data='view_orders')]
        ]
        
        await query.edit_message_text(
            MESSAGES["status_updated"].format(new_status, order_id),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await query.edit_message_text(
            ERRORS["update_failed"].format(order_id),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Orders", callback_data='view_orders')]
            ])
        )

async def add_tracking_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{EMOJI['back']} Cancel", callback_data=f'manage_order_{order_id}')]
        ])
    )
    
    return ADMIN_TRACKING

async def receive_tracking_link(
    update: Update, context: ContextTypes.DEFAULT_TYPE, 
    order_manager, loggers
):
    """
    Handle receiving a tracking link from admin's message.
    
    Args:
        update: Telegram update
        context: Conversation context
        order_manager: OrderManager instance
        loggers: Dictionary of logger instances
        
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
        status, _, _ = await order_manager.get_order_status(order_id)
        
        if not status:
            await update.message.reply_text(MESSAGES["order_not_found"].format(order_id))
            return
        
        # Update both status and tracking
        success = await order_manager.update_order_status(context, order_id, status, tracking_link)
        
        loggers["admin"].info(f"Admin added tracking link for order {order_id}")
        
        if success:
            keyboard = [
                [InlineKeyboardButton("View Order Details", callback_data=f'manage_order_{order_id}')],
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Orders", callback_data='view_orders')]
            ]
            
            await update.message.reply_text(
                MESSAGES["tracking_updated"].format(order_id),
                reply_markup=InlineKeyboardMarkup(keyboard)
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
        success = await order_manager.update_order_status(context, order_id, new_status, tracking_link)
        
        loggers["admin"].info(f"Admin updated order {order_id} status to {new_status} with tracking")
        
        if success:
            keyboard = [
                [InlineKeyboardButton("View Order Details", callback_data=f'manage_order_{order_id}')],
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Orders", callback_data='view_orders')]
            ]
            
            await update.message.reply_text(
                f"{MESSAGES['status_updated'].format(new_status, order_id)} with tracking link.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await update.message.reply_text(ERRORS["update_failed"].format(order_id))

async def skip_tracking_link(
    update: Update, context: ContextTypes.DEFAULT_TYPE, 
    order_manager, loggers
):
    """
    Skip adding a tracking link and proceed with the status update.
    
    Args:
        update: Telegram update
        context: Conversation context
        order_manager: OrderManager instance
        loggers: Dictionary of logger instances
        
    Returns:
        None
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
        success = await order_manager.update_order_status(context, order_id, new_status, "")
        
        loggers["admin"].info(f"Admin updated order {order_id} status to {new_status} without tracking")
        
        if success:
            keyboard = [
                [InlineKeyboardButton("View Order Details", callback_data=f'manage_order_{order_id}')],
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Orders", callback_data='view_orders')]
            ]
            
            await query.edit_message_text(
                MESSAGES["status_updated"].format(new_status, order_id),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(
                ERRORS["update_failed"].format(order_id),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Orders", callback_data='view_orders')]
                ])
            )
    else:
        # Direct tracking link update was cancelled
        await query.edit_message_text(
            f"Tracking link update cancelled for Order {order_id}.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Order", callback_data=f'manage_order_{order_id}')]
            ])
        )

async def back_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Return to the admin panel.
    
    Args:
        update: Telegram update
        context: Conversation context
        
    Returns:
        None
    """
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        MESSAGES["admin_welcome"],
        reply_markup=build_admin_buttons()
    )

# ---------------------------- Conversation Cancellation & Utilities ----------------------------
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
    
    await message.edit_text(status_text)

# ---------------------------- Error Handling ----------------------------
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
    if update and update.effective_user:
        try:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text=ERRORS["error"]
            )
        except Exception as error:
            loggers["errors"].error(f"Failed to send error message to the user: {error}")

# ---------------------------- Convenience Functions ----------------------------
# These wrapper functions make it easier to pass our dependencies to handlers
async def start_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await start(update, context, inventory_manager, loggers)

async def choose_category_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await choose_category(update, context, inventory_manager, loggers)

async def choose_suboption_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await choose_suboption(update, context, loggers)

async def input_quantity_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await input_quantity(update, context, inventory_manager, loggers)

async def confirm_order_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await confirm_order(update, context, loggers)

async def input_details_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await input_details(update, context, loggers)

async def confirm_details_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await confirm_details(update, context, loggers, ADMIN_ID)

async def handle_payment_screenshot_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_payment_screenshot(update, context, google_apis, order_manager, loggers)

async def track_order_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await track_order(update, context, loggers)

async def handle_order_tracking_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_order_tracking(update, context, order_manager, loggers)

async def admin_panel_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await admin_panel(update, context, ADMIN_ID, loggers)

async def view_orders_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await view_orders(update, context, google_apis, loggers)

async def filter_orders_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await filter_orders(update, context, google_apis, loggers)

async def manage_order_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await manage_order(update, context, google_apis, loggers)

async def view_payment_screenshot_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await view_payment_screenshot(update, context, google_apis, loggers)

async def update_order_status_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await update_order_status(update, context, loggers)

async def set_order_status_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await set_order_status(update, context, order_manager, loggers)

async def add_tracking_link_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await add_tracking_link(update, context)

async def receive_tracking_link_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await receive_tracking_link(update, context, order_manager, loggers)

async def skip_tracking_link_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await skip_tracking_link(update, context, order_manager, loggers)

async def back_to_admin_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await back_to_admin(update, context)

# ---------------------------- Bot Setup ----------------------------
def main():
    """Set up the bot and start polling."""
    global loggers, google_apis, inventory_manager, order_manager
    
    # Set up logging
    loggers = setup_logging()
    loggers["main"].info("Bot starting up...")
    
    # Handle missing token
    if not TOKEN:
        loggers["errors"].error("No bot token found in configuration")
        print("Error: No bot token found. Please set the TELEGRAM_BOT_TOKEN environment variable.")
        sys.exit(1)
    
    # Create persistence object to save conversation states
    persistence = PicklePersistence(filepath="bot_persistence")
    
    # Initialize application with persistence and concurrency
    app = ApplicationBuilder().token(TOKEN).persistence(persistence).concurrent_updates(True).build()
    
    # Store start time
    app.bot_data["start_time"] = time.time()
    
    # Initialize services
    google_apis = GoogleAPIsManager(loggers)
    inventory_manager = InventoryManager(google_apis, loggers)
    order_manager = OrderManager(google_apis, loggers)
    
    # Set up conversation handler for main ordering flow
    conversation_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_wrapper)],
        states={
            CATEGORY: [CallbackQueryHandler(choose_category_wrapper)],
            SUBOPTION: [CallbackQueryHandler(choose_suboption_wrapper)],
            QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_quantity_wrapper)],
            CONFIRM: [CallbackQueryHandler(confirm_order_wrapper)],
            DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_details_wrapper)],
            CONFIRM_DETAILS: [CallbackQueryHandler(confirm_details_wrapper)],
            PAYMENT: [MessageHandler(filters.PHOTO, handle_payment_screenshot_wrapper)]
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
        ],
        name="ordering_conversation",
        persistent=True,
        conversation_timeout=900  # 15 minutes timeout
    )
    
    # Order tracking conversation handler
    tracking_handler = ConversationHandler(
        entry_points=[CommandHandler("track", track_order_wrapper)],
        states={
            TRACKING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_order_tracking_wrapper)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="tracking_conversation",
        persistent=True,
        conversation_timeout=300  # 5 minutes timeout
    )
    
    # Admin command handler
    app.add_handler(CommandHandler("admin", admin_panel_wrapper))
    app.add_handler(CommandHandler("health", health_check))
    
    # Admin panel callback handlers
    app.add_handler(CallbackQueryHandler(back_to_admin_wrapper, pattern="^back_to_admin$"))
    app.add_handler(CallbackQueryHandler(view_orders_wrapper, pattern="^view_orders$"))
    app.add_handler(CallbackQueryHandler(filter_orders_wrapper, pattern="^filter_"))
    app.add_handler(CallbackQueryHandler(manage_order_wrapper, pattern="^manage_order_"))
    app.add_handler(CallbackQueryHandler(update_order_status_wrapper, pattern="^update_status_"))
    app.add_handler(CallbackQueryHandler(add_tracking_link_wrapper, pattern="^add_tracking_"))
    app.add_handler(CallbackQueryHandler(view_payment_screenshot_wrapper, pattern="^view_payment_"))
    app.add_handler(CallbackQueryHandler(set_order_status_wrapper, pattern="^set_status_"))
    
    # Message handler for admin tracking link input
    def awaiting_tracking_link_filter(update):
        """Filter for messages from users awaiting tracking link input"""
        if not update.effective_chat or update.effective_chat.type != 'private':
            return False
            user_data = context.user_data if hasattr(update, 'user_data') else {}
            return user_data.get('awaiting_tracking_link', False)

# Message handler for admin tracking link input
    app.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND,
    receive_tracking_link_wrapper,
    lambda u: awaiting_tracking_link_filter(u)
), group=1)
    
    # Add the main conversation handlers
    app.add_error_handler(error_handler)
    app.add_handler(tracking_handler)
    app.add_handler(conversation_handler)
    
    # Log the startup
    loggers["main"].info("Bot is running...")
    print("Bot is running...")
    
    # Start the bot
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()