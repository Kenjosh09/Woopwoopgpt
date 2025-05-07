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
from io import BytesIO
from datetime import datetime
from logging.handlers import RotatingFileHandler
from collections import deque
import string
from typing import Optional, Tuple, Dict, Any, List

# Import Telegram components
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes,
    filters, Application, PicklePersistence, TypeHandler
)
from telegram.error import NetworkError, TelegramError, TimedOut

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
GCASH_QR_CODE_URL = os.getenv("GCASH_QR_CODE_URL", "https://drive.google.com/file/d/1kePOFyVimpLVnnp_-HEb3cihvIHJ2P4X/view?usp=drive_link")

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
    "update": "💫"
}

# Add additional emojis if not present
if "restart" not in EMOJI:
    EMOJI.update({
        "restart": "🔄",
        "help": "❓",
        "home": "🏠",
        "browse": "🛒",
        "clock": "⏰", 
        "package": "📦",
        "truck": "🚚",
        "party": "🎉",
        "support": "🧑‍💼"
    })

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
            # Set up authentication for Google Sheets using google-auth
            scope = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/drive']
            creds = service_account.Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS_FILE,
                scopes=scope
            )
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
                self._inventory_sheet = spreadsheet.add_worksheet("Inventory", 100, 10)
                # Initialize inventory headers with new columns
                self._inventory_sheet.append_row([
                    "Name", "Strain", "Type", "Tag", "Price", "Stock", 
                    "Weight", "Brand", "Description", "Image_URL"
                ])
            
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
        Fetch inventory data from Google Sheets including tags and stock.
        Handles errors with graceful fallback to default inventory.
        
        Returns:
            tuple: (products_by_tag, products_by_strain, all_products)
        """
        products_by_tag = {'buds': [], 'local': [], 'carts': [], 'edibs': []}
        products_by_strain = {'indica': [], 'sativa': [], 'hybrid': []}
        all_products = []
        
        try:
            # Initialize sheets
            _, inventory_sheet = await self.initialize_sheets()
            
            if not inventory_sheet:
                return self._create_default_inventory()
            
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
            
            return products_by_tag, products_by_strain, all_products
            
        except Exception as e:
            self.loggers["errors"].error(f"Error fetching inventory: {e}")
            # Fallback to default inventory
            return self._create_default_inventory()
            
    def _create_default_inventory(self):
        """Create a default inventory when API access fails."""
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
                    
                    # Exponential backoff with jitter
                    base_wait = 2 ** retry_count
                    jitter = random.uniform(0, 0.5 * base_wait)
                    wait_time = base_wait + jitter
                    
                    self.loggers["errors"].warning(
                        f"Drive upload attempt {retry_count}/{max_retries} failed: {e}. "
                        f"Retrying in {wait_time:.2f} seconds"
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
        now = time.time()
        
        # Check when this API was last accessed
        if api_name in self.last_request_time:
            elapsed = now - self.last_request_time[api_name]
            if elapsed < self.min_request_interval:
                await asyncio.sleep(self.min_request_interval - elapsed)
        
        # Update the last request time
        self.last_request_time[api_name] = time.time()

# ---------------------------- Utility Functions ----------------------------
def is_valid_order_id(order_id):
    """Validate the format of an order ID."""
    # Check for valid order ID pattern (WW-XXXX-YYY format)
    return bool(order_id and re.match(r'^WW-\d{4}-[A-Z]{3}$', order_id))

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
    keyboard = []
    
    for product_id in available_categories:
        if product_id in PRODUCTS:
            product = PRODUCTS[product_id]
            button_text = f"{product['emoji']} {product['name']}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=product_id)])
    
    # Add cancel button
    keyboard.append([InlineKeyboardButton(f"{EMOJI['error']} Cancel", callback_data="cancel")])
    
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
    Validate shipping details format with enhanced flexibility.
    
    This function checks if the user's shipping details input follows the correct format,
    while allowing for more flexibility in names, addresses and contact information.
    
    Args:
        text (str): Shipping details text in format "Name / Address / Contact"
        
    Returns:
        tuple: (is_valid, result_dict_or_error_message)
    """
    # Log the input for debugging
    logging.debug(f"Validating shipping details: {text}")
    
    # Basic format check - need two slashes to have three parts
    if text.count('/') != 2:
        return False, "Invalid format. Need exactly two '/' separators. Format: Name / Address / Contact"
    
    # Split the text by slashes and trim whitespace
    parts = [part.strip() for part in text.split('/')]
    
    # Ensure we have three parts
    if len(parts) != 3:
        return False, "Invalid format. Use: Name / Address / Contact"
        
    name, address, contact = parts
    
    # Check each part
    if not name:
        return False, "Name cannot be empty. Format: Name / Address / Contact"
    if not address:
        return False, "Address cannot be empty. Format: Name / Address / Contact"
        
    # Simplified contact validation - just ensure it has enough digits
    # Count only digits
    digit_count = sum(c.isdigit() for c in contact)
    if digit_count < 10 or digit_count > 15:
        return False, "Invalid contact number. Must have 10-15 digits. Can include +, spaces, or hyphens."
    
    # Sanitize the inputs
    name = sanitize_input(name, 50)
    address = sanitize_input(address, 100)
    contact = sanitize_input(contact, 15)
    
    # Success - return the validated details
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
    last_exception = None
    
    while retry_count < max_retries:
        try:
            return await operation()
        except (ConnectionError, TimeoutError) as e:
            last_exception = e
            retry_count += 1
            if retry_count == max_retries:
                break
                
            # Exponential backoff with jitter
            base_wait = 2 ** retry_count
            jitter = random.uniform(0, 0.5 * base_wait)
            wait_time = base_wait + jitter
            
            print(f"Operation failed, retrying in {wait_time:.2f} seconds...")
            await asyncio.sleep(wait_time)
    
    # If we get here, all retries failed
    raise last_exception

# ---------------------------- Inventory Management ----------------------------
class InventoryManager:
    """Manages product inventory and caching with stock tracking."""
    
    def __init__(self, google_apis, loggers):
        """
        Initialize the inventory manager.
        
        Args:
            google_apis: GoogleAPIsManager instance for data access
            loggers: Dictionary of logger instances for error reporting
        """
        self.google_apis = google_apis
        self.loggers = loggers
        self.cache = {
            "products_by_tag": None,
            "products_by_strain": None,
            "all_products": None,
            "last_update": 0
        }
        
    async def get_inventory(self, force_refresh=False):
        """
        Get inventory data with caching to minimize API calls.
        
        Args:
            force_refresh (bool): Force refresh the cache regardless of age
            
        Returns:
            tuple: (products_by_tag, products_by_strain, all_products)
        """
        current_time = time.time()
        cache_valid = (
            self.cache["products_by_tag"] is not None and
            self.cache["products_by_strain"] is not None and
            self.cache["all_products"] is not None and
            current_time - self.cache["last_update"] < CACHE_EXPIRY["inventory"]
        )
        
        if cache_valid and not force_refresh:
            return (
                self.cache["products_by_tag"],
                self.cache["products_by_strain"],
                self.cache["all_products"]
            )
            
        try:
            # Fetch fresh inventory data
            products_by_tag, products_by_strain, all_products = await self.google_apis.fetch_inventory()
            
            # Update cache
            self.cache["products_by_tag"] = products_by_tag
            self.cache["products_by_strain"] = products_by_strain
            self.cache["all_products"] = all_products
            self.cache["last_update"] = current_time
            
            self.loggers["main"].info("Inventory cache refreshed")
            return products_by_tag, products_by_strain, all_products
            
        except Exception as e:
            self.loggers["errors"].error(f"Error refreshing inventory: {str(e)}")
            
            # If we have cached data, use it despite expiry
            if (self.cache["products_by_tag"] and 
                self.cache["products_by_strain"] and 
                self.cache["all_products"]):
                self.loggers["main"].warning("Using expired inventory cache")
                return (
                    self.cache["products_by_tag"],
                    self.cache["products_by_strain"],
                    self.cache["all_products"]
                )
                
            # Build fallback inventory
            self.loggers["main"].warning("Using fallback inventory")
            products_by_tag, products_by_strain, all_products = self.google_apis._create_default_inventory()
            
            # Cache the fallback inventory
            self.cache["products_by_tag"] = products_by_tag
            self.cache["products_by_strain"] = products_by_strain
            self.cache["all_products"] = all_products
            self.cache["last_update"] = current_time
            
            return products_by_tag, products_by_strain, all_products
    
    async def category_has_products(self, category):
        """
        Check if a category has any products in stock.
        
        Args:
            category (str): Product category key
            
        Returns:
            bool: True if category has products in stock, False otherwise
        """
        if category not in PRODUCTS:
            return False
            
        tag = PRODUCTS[category].get("tag")
        if not tag:
            return False
            
        products_by_tag, _, _ = await self.get_inventory()
        return len(products_by_tag.get(tag, [])) > 0
    
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
            unit = item.get("unit", "gram/s")
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
    Start the ordering conversation with available categories.
    
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
    
    # Check which categories have available products
    available_categories = []
    for category_id in PRODUCTS:
        has_products = await inventory_manager.category_has_products(category_id)
        if has_products:
            available_categories.append(category_id)
    
    if not available_categories:
        await update.message.reply_text(
            f"{EMOJI['warning']} Sorry, we don't have any products in stock at the moment. "
            "Please check back later."
        )
        return ConversationHandler.END
    
    # Send welcome message with available category buttons
    await update.message.reply_text(
        MESSAGES["welcome"],
        reply_markup=build_category_buttons(available_categories)
    )
    
    return CATEGORY

async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE, inventory_manager, loggers):
    """
    Handle category selection and determine next steps based on category.
    
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
    
    # Handle cancellation
    if query.data == "cancel":
        await query.edit_message_text(MESSAGES["cancel_order"])
        return ConversationHandler.END
    
    # Get the selected category
    category = query.data
    context.user_data["category"] = category
    
    # Log the selection
    loggers["main"].info(f"User {query.from_user.id} selected category: {category}")
    
    # Get product details
    product = PRODUCTS.get(category)
    if not product:
        # Invalid category, go back to selection
        await query.edit_message_text("Invalid selection. Please try again.")
        return CATEGORY
    
    # Handle different category flows
    if category == "local":
        # For Local (BG), go directly to product selection
        return await show_local_products(update, context, inventory_manager, loggers)
    
    elif category == "carts":
        # For Carts, choose browsing option first
        browse_options = product.get("browse_options", [])
        keyboard = []
        
        for option in browse_options:
            option_text = f"Browse by {option.capitalize()}"
            keyboard.append([InlineKeyboardButton(option_text, callback_data=option)])
            
        # Add back button
        keyboard.append([InlineKeyboardButton(f"{EMOJI['back']} Back", callback_data="back_to_categories")])
        
        await query.edit_message_text(
            f"{product['emoji']} How would you like to browse {product['name']}?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return BROWSE_BY
    
    elif product.get("requires_strain_selection", False):
        # For products requiring strain selection (buds, edibles)
        keyboard = [
            [InlineKeyboardButton("🌿 Indica", callback_data="indica")],
            [InlineKeyboardButton("🌱 Sativa", callback_data="sativa")],
            [InlineKeyboardButton("🍃 Hybrid", callback_data="hybrid")],
            [InlineKeyboardButton(f"{EMOJI['back']} Back", callback_data="back_to_categories")]
        ]
        
        await query.edit_message_text(
            f"{product['emoji']} Please select the strain type for {product['name']}:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return STRAIN_TYPE
    
    # Default fallback
    await query.edit_message_text("This category is currently unavailable.")
    return CATEGORY

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
    
    # Handle different types of back navigation
    if callback_data == "back_to_browse":
        # User wants to go back to browse options
        # Clear product-specific data to avoid confusion
        context.user_data.pop("product_key", None)
        context.user_data.pop("parsed_quantity", None)
        
        # Determine which browse screen to return to
        category = context.user_data.get("category")
        strain_type = context.user_data.get("strain_type")
        
        if category == "carts":
            # For carts, go back to browse by selection
            context.user_data["current_location"] = "browse_carts"
            
            # Build the browse by buttons
            keyboard = [
                [InlineKeyboardButton("Browse by Brand", callback_data="browse_by_brand")],
                [InlineKeyboardButton("Browse by Strain", callback_data="browse_by_strain")],
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Categories", callback_data="back_to_categories")]
            ]
            
            await query.edit_message_text(
                f"{EMOJI['carts']} How would you like to browse our carts?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return BROWSE_BY
            
        elif category == "buds" and strain_type:
            # For buds, go back to strain type selection
            context.user_data["current_location"] = "strain_selection"
            
            # Build the strain type buttons
            keyboard = [
                [InlineKeyboardButton("Indica", callback_data="indica")],
                [InlineKeyboardButton("Sativa", callback_data="sativa")],
                [InlineKeyboardButton("Hybrid", callback_data="hybrid")],
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Categories", callback_data="back_to_categories")]
            ]
            
            await query.edit_message_text(
                f"{EMOJI['buds']} Select Strain Type:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return STRAIN_TYPE
            
        else:
            # Default back to categories
            return await back_to_categories(update, context, inventory_manager, loggers)
            
    elif callback_data == "back_to_categories":
        # User wants to go back to category selection
        return await back_to_categories(update, context, inventory_manager, loggers)
        
    # For any other back navigation, go back to categories as a safe default
    return await back_to_categories(update, context, inventory_manager, loggers)

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
    
    if query.data == "back_to_categories":
        # Go back to category selection
        return await start(update, context, inventory_manager, loggers)
    
    # Store the selected strain type
    strain_type = query.data
    context.user_data["strain_type"] = strain_type
    
    # Get the category
    category = context.user_data.get("category")
    if not category:
        # Something went wrong, go back to category selection
        return await start(update, context, inventory_manager, loggers)
    
    # Log the selection
    loggers["main"].info(
        f"User {query.from_user.id} selected strain type: {strain_type} for {category}"
    )
    
    # Fetch products of this strain type for the selected category
    products_by_tag, products_by_strain, _ = await inventory_manager.get_inventory()
    
    # Get the tag for this category
    tag = PRODUCTS[category].get("tag", "")
    
    # Filter products by tag and strain
    filtered_products = []
    for product in products_by_strain.get(strain_type, []):
        if product.get("tag") == tag:
            filtered_products.append(product)
    
    if not filtered_products:
        # No products available, inform the user
        await query.edit_message_text(
            f"Sorry, no {strain_type} {category} are currently in stock. Please try another option.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Strain Selection", callback_data="back_to_strain")],
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Categories", callback_data="back_to_categories")]
            ])
        )
        return STRAIN_TYPE
    
    # Build product selection keyboard
    keyboard = []
    for product in filtered_products:
        product_name = product.get("name")
        product_price = product.get("price", 0)
        product_key = product.get("key")
        
        button_text = f"{product_name} - ₱{product_price:,}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=product_key)])
    
    # Add back button
    keyboard.append([InlineKeyboardButton(f"{EMOJI['back']} Back", callback_data="back_to_strain")])
    
    # For edibles, show products and then ask for quantity
    if category == "edibles":
        await query.edit_message_text(
            f"{EMOJI['edibles']} Select an edible ({strain_type.capitalize()}):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return PRODUCT_SELECTION
    
    # For buds, show products and then ask for quantity
    await query.edit_message_text(
        f"{EMOJI['buds']} Select a {strain_type.capitalize()} strain:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
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
        [InlineKeyboardButton(f"{EMOJI['back']} Back", callback_data="back_to_categories")]
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
    Handle product selection.
    
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
    
    selection = query.data
    
    # Handle back navigation
    if selection == "back_to_browse":
        return await handle_back_navigation(update, context, inventory_manager, loggers)
        
    if selection == "back_to_categories":
        return await back_to_categories(update, context, inventory_manager, loggers)
    
    category = context.user_data.get("category")
    
    # If it's a brand or strain selection
    if selection.startswith("brand_") or selection.startswith("strain_"):
        # Extract the brand or strain
        _, value = selection.split("_", 1)
        
        # Store for later use
        context.user_data["selected_group"] = value
        context.user_data["current_location"] = f"products_{value}"
        
        # Get all products for this brand/strain
        products_by_tag, _, _ = await inventory_manager.get_inventory()
        all_products = products_by_tag.get(PRODUCTS[category]["tag"], [])
        
        # Filter by brand or strain
        filtered_products = []
        if selection.startswith("brand_"):
            filtered_products = [p for p in all_products if p.get("brand") == value]
        else:
            filtered_products = [p for p in all_products if p.get("strain") == value]
            
        # Build product buttons
        keyboard = []
        for product in filtered_products:
            product_name = product.get("name", "Unknown")
            product_key = product.get("key")
            stock = product.get("stock", 0)
            price = product.get("price", 0)
            
            if stock > 0:
                keyboard.append([
                    InlineKeyboardButton(
                        f"{product_name} - ₱{price:,.0f} ({stock} left)",
                        callback_data=product_key
                    )
                ])
                
        # Add back buttons
        keyboard.append([InlineKeyboardButton(f"{EMOJI['back']} Back to Browse", callback_data="back_to_browse")])
        keyboard.append([InlineKeyboardButton(f"{EMOJI['back']} Back to Categories", callback_data="back_to_categories")])
        
        browse_by = context.user_data.get("browse_by", "")
        if browse_by == "browse_by_brand":
            header = f"{EMOJI['carts']} {value} Products:"
        else:
            header = f"{EMOJI['carts']} {value.capitalize()} Products:"
            
        await query.edit_message_text(
            header,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return PRODUCT_SELECTION
        
    # If it's a direct product selection
    else:
        # Find the product
        products_by_tag, products_by_strain, all_products = await inventory_manager.get_inventory()
        
        selected_product = None
        for p in all_products:
            if p.get("key") == selection:
                selected_product = p
                break
                
        if not selected_product:
            await query.edit_message_text(
                "Sorry, this product is no longer available.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Browse", callback_data="back_to_browse")],
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Categories", callback_data="back_to_categories")]
                ])
            )
            return PRODUCT_SELECTION
            
        # Store product details
        context.user_data["product_key"] = selection
        context.user_data["product_name"] = selected_product.get("name")
        context.user_data["product_price"] = selected_product.get("price", 0)
        context.user_data["product_stock"] = selected_product.get("stock", 0)
        context.user_data["current_location"] = f"product_{selection}"
        
        # Ask for quantity
        product_unit = PRODUCTS[category].get("unit", "units")
        min_order = PRODUCTS[category].get("min_order", 1)
        
        await query.edit_message_text(
            f"{EMOJI[category]} {selected_product.get('name')}\n\n"
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
    keyboard = [
        [InlineKeyboardButton(f"{EMOJI['success']} Confirm Selection", callback_data="confirm")],
        [InlineKeyboardButton(f"{EMOJI['error']} Cancel", callback_data="cancel")],
    ]
    
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
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['cart']} Add More", callback_data="add_more")],
                [InlineKeyboardButton(f"{EMOJI['shipping']} Proceed to Checkout", callback_data="proceed")],
                [InlineKeyboardButton(f"{EMOJI['error']} Cancel Order", callback_data="cancel")]
            ]),
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
        
        # First send payment text with HTML parsing explicitly enabled
        await query.edit_message_text(
            MESSAGES["payment_instructions"].format(GCASH_NUMBER),
            parse_mode=ParseMode.HTML  # Explicitly set HTML parse mode
        )
        
        # Then send the QR code
        try:
            # Only send if a QR code URL is configured
            if GCASH_QR_CODE_URL and GCASH_QR_CODE_URL != "https://example.com/gcash_qr.jpg":
                await context.bot.send_photo(
                    chat_id=query.from_user.id,
                    photo=GCASH_QR_CODE_URL,
                    caption=f"{EMOJI['qrcode']} GCash QR Code for {GCASH_NUMBER}\nScan this code to pay directly."
                )
        except Exception as e:
            # Log the error but continue with the flow
            loggers["errors"].error(f"Failed to send QR code: {e}")
        
        return PAYMENT
    elif query.data == 'edit_details':
        await query.edit_message_text(MESSAGES["checkout_prompt"])
        return DETAILS
    
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
        keyboard.append([InlineKeyboardButton("📋 Show My Recent Orders", callback_data="show_recent_orders")])
    
    # Always add cancel button
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_tracking")])
    
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
    keyboard.append([InlineKeyboardButton("🔢 Enter Different Order ID", callback_data="enter_order_id")])
    
    # Add cancel button
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_tracking")])
    
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
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh Status", callback_data=f"refresh_tracking_{order_id}")],
            [InlineKeyboardButton(f"{EMOJI['support']} Need Help?", callback_data="contact_support")],
            [InlineKeyboardButton(f"{EMOJI['back']} Back to Main Menu", callback_data="start")]
        ]
        
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
        filter_buttons = self._build_filter_buttons(status_filter)
        
        # Combine all buttons
        keyboard = (
            order_buttons + 
            nav_buttons + 
            filter_buttons + 
            [[InlineKeyboardButton(f"{EMOJI['back']} Back to Admin Panel", callback_data='back_to_admin')]]
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
            back_button = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Orders", callback_data='view_orders')]
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
            [InlineKeyboardButton(f"{EMOJI['update']} Update Status", callback_data=f'update_status_{order_id}')],
            [InlineKeyboardButton(f"{EMOJI['link']} Add/Update Tracking", callback_data=f'add_tracking_{order_id}')],
            [InlineKeyboardButton(f"{EMOJI['screenshot']} View Payment Screenshot", callback_data=f'view_payment_{order_id}')]
        ]
        
        # Add back button
        keyboard.append([InlineKeyboardButton(f"{EMOJI['back']} Back to Orders", callback_data='view_orders')])
        
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
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Orders", callback_data='view_orders')]
                ])
            )
            return
        
        # Find payment URL
        payment_url = order_details.get('Payment URL')
        
        if not payment_url:
            await query.edit_message_text(
                ERRORS["no_screenshot"],
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{EMOJI['back']} Back to Order", callback_data=f'manage_order_{order_id}')]
                ])
            )
            return
        
        self.loggers["admin"].info(f"Admin viewed payment screenshot for order {order_id}")
        
        # Send the payment URL
        await query.edit_message_text(
            f"{EMOJI['screenshot']} Payment Screenshot for Order {order_id}:\n\n"
            f"Link: {payment_url}\n\n"
            "You can view the screenshot by clicking the link above.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Order", callback_data=f'manage_order_{order_id}')]
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
            InlineKeyboardButton(f"{EMOJI['back']} Back to Order", callback_data=f'manage_order_{order_id}')
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
        success = await self.order_manager.update_order_status(context, order_id, new_status)
        
        self.loggers["admin"].info(f"Admin updated order {order_id} status to {new_status}")
        
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
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['back']} Cancel", callback_data=f'manage_order_{order_id}')]
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
            success = await self.order_manager.update_order_status(context, order_id, new_status, tracking_link)
            
            self.loggers["admin"].info(f"Admin updated order {order_id} status to {new_status} with tracking")
            
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
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['back']} Back to Admin Panel", callback_data="back_to_admin")]
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
    if not hasattr(context.bot_data, "processed_errors"):
        context.bot_data["processed_errors"] = set()
    
    # If this error is already being processed, return to avoid duplicate handling
    if error_key in context.bot_data["processed_errors"]:
        return
    
    # Add this error to the processed set
    context.bot_data["processed_errors"].add(error_key)
    
    # Clean up processed errors periodically
    if len(context.bot_data["processed_errors"]) > 100:
        # Convert to list, keep only the 50 most recent items
        old_errors = list(context.bot_data["processed_errors"])
        context.bot_data["processed_errors"] = set(old_errors[-50:])
    
    # Log the error details
    error_text = f"User: {user_id} | Chat: {chat_id} | Error: {type(error).__name__}: {error}"
    loggers["errors"].error(f"Error in enhanced_error_handler | {error_text}")
    
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
    if query:
        await query.edit_message_text(
            f"{EMOJI['restart']} *Conversation Restarted*\n\n"
            f"Your session has been reset and you can start fresh. "
            f"Use the menu below to continue.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['browse']} Browse Products", callback_data="start_shopping")],
                [InlineKeyboardButton(f"{EMOJI['order']} Track Order", callback_data="track_order")],
                [InlineKeyboardButton(f"{EMOJI['help']} Help", callback_data="get_help")]
            ])
        )
    else:
        # For command-based restart
        await update.message.reply_text(
            f"{EMOJI['restart']} *Conversation Restarted*\n\n"
            f"Your session has been reset and you can start fresh. "
            f"Use the menu below to continue.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['browse']} Browse Products", callback_data="start_shopping")],
                [InlineKeyboardButton(f"{EMOJI['order']} Track Order", callback_data="track_order")],
                [InlineKeyboardButton(f"{EMOJI['help']} Help", callback_data="get_help")]
            ])
        )
    
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
        [InlineKeyboardButton("📱 Chat with Support", url=support_chat_url)],
        [InlineKeyboardButton(f"{EMOJI['back']} Back", callback_data=f"refresh_tracking_{order_id}")]
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
        [InlineKeyboardButton("📱 Chat with Support", url=support_chat_url)],
        [InlineKeyboardButton(f"{EMOJI['home']} Main Menu", callback_data="start")]
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
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['restart']} Restart Bot", callback_data="restart_conversation")],
                [InlineKeyboardButton(f"{EMOJI['home']} Main Menu", callback_data="start")]
            ])
        )
    else:
        await update.message.reply_text(
            help_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{EMOJI['restart']} Restart Bot", callback_data="restart_conversation")],
                [InlineKeyboardButton(f"{EMOJI['home']} Main Menu", callback_data="start")]
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

# ---------------------------- Convenience Functions ----------------------------
# These wrapper functions make it easier to pass our dependencies to handlers
async def start_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await start(update, context, inventory_manager, loggers)

async def choose_category_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await choose_category(update, context, inventory_manager, loggers)

async def choose_strain_type_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await choose_strain_type(update, context, inventory_manager, loggers)

async def browse_carts_by_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await browse_carts_by(update, context, inventory_manager, loggers)

async def select_product_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await select_product(update, context, inventory_manager, loggers)

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

async def handle_order_tracking_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_order_tracking(update, context, order_manager, loggers)

async def handle_quantity_selection_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_quantity_selection(update, context, inventory_manager, loggers)

async def handle_back_navigation_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_back_navigation(update, context, inventory_manager, loggers)

async def back_to_categories_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await back_to_categories(update, context, inventory_manager, loggers)

# ---------------------------- Bot Setup ----------------------------
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
        app = ApplicationBuilder().token(TOKEN).persistence(persistence).concurrent_updates(True).build()
        
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
        app.add_handler(CallbackQueryHandler(restart_conversation, pattern="^restart_conversation$"))
        app.add_handler(CallbackQueryHandler(get_help, pattern="^get_help$"))
        # Updated with more specific pattern
        app.add_handler(CallbackQueryHandler(refresh_tracking, pattern="^refresh_tracking_[A-Z0-9-]+$"))
        app.add_handler(CallbackQueryHandler(contact_support, pattern="^contact_support$"))
        # Remove the duplicate handler and make patterns more specific
        app.add_handler(CallbackQueryHandler(start_wrapper, pattern="^start$"))
        app.add_handler(CallbackQueryHandler(select_order, pattern="^select_order_[A-Z0-9-]+$"))  # Match only valid order IDs
        app.add_handler(CallbackQueryHandler(cancel_tracking, pattern="^cancel_tracking$"))
        app.add_handler(CallbackQueryHandler(show_recent_orders, pattern="^show_recent_orders$"))
        app.add_handler(CallbackQueryHandler(enter_order_id, pattern="^enter_order_id$"))

        # Schedule periodic checks for stuck conversations
        job_queue = app.job_queue
        job_queue.run_repeating(check_conversation_status, interval=600, first=600)  # Every 10 minutes
    
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
        
        # Set up conversation handler for main ordering flow
        conversation_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start_wrapper)],
            states={
                CATEGORY: [
                    CallbackQueryHandler(choose_category_wrapper)
                ],
                STRAIN_TYPE: [
                    CallbackQueryHandler(choose_strain_type_wrapper)
                ],
                BROWSE_BY: [
                    CallbackQueryHandler(browse_carts_by_wrapper)
                ],
                PRODUCT_SELECTION: [
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
        
        # Admin command handler - route to the admin panel class
        app.add_handler(CommandHandler("admin", lambda update, context: admin_panel.show_panel(update, context)))
        app.add_handler(CommandHandler("health", health_check))
        
        # Admin panel callback handlers
        app.add_handler(CallbackQueryHandler(admin_panel.back_to_admin, pattern="^back_to_admin$"))
        app.add_handler(CallbackQueryHandler(admin_panel.view_orders, pattern="^view_orders$"))
        # Updated with more specific patterns
        app.add_handler(CallbackQueryHandler(lambda update, context: admin_panel.view_orders(update, context), pattern="^filter_[a-z_]+$"))
        app.add_handler(CallbackQueryHandler(lambda update, context: admin_panel.manage_order(update, context), pattern="^manage_order_[A-Z0-9-]+$"))
        app.add_handler(CallbackQueryHandler(admin_panel.update_order_status, pattern="^update_status_[A-Z0-9-]+$"))
        app.add_handler(CallbackQueryHandler(admin_panel.view_payment_screenshot, pattern="^view_payment_[A-Z0-9-]+$"))
        app.add_handler(CallbackQueryHandler(admin_panel.set_order_status, pattern="^set_status_[a-z_]+$"))
        app.add_handler(CallbackQueryHandler(admin_panel.skip_tracking_link, pattern="^skip_tracking_link$"))
        app.add_handler(CallbackQueryHandler(admin_panel.add_tracking_link, pattern="^add_tracking_link$"))
        app.add_handler(admin_search_handler)
        app.add_handler(CallbackQueryHandler(admin_panel.review_payments, pattern="^approve_payments$"))
        # Updated with more specific patterns
        app.add_handler(CallbackQueryHandler(admin_panel.review_specific_payment, pattern="^review_payment_[A-Z0-9-]+$"))
        app.add_handler(CallbackQueryHandler(admin_panel.process_payment_action, pattern="^(approve|reject)_payment_[A-Z0-9-]+$"))
        
        # Add force restart command
        app.add_handler(CommandHandler("restart", force_restart))

        # Register the main handlers
        app.add_handler(admin_tracking_handler)
        app.add_handler(tracking_handler)
        app.add_handler(conversation_handler)
        app.add_handler(CommandHandler("categories", back_to_categories_wrapper))
        
        # Register handler for unknown commands - must be added AFTER all other command handlers
        unknown_command_handler = MessageHandler(
            filters.COMMAND & ~filters.UpdateType.EDITED_MESSAGE, 
            command_not_found
        )
        app.add_handler(unknown_command_handler)
    
        # Log the startup
        loggers["main"].info("Bot is running...")
        print("Bot is running...")
        
        # Start the bot
        app.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        loggers["errors"].critical(f"Critical error starting bot: {type(e).__name__}: {e}")
        print(f"Critical error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
