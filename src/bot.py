"""
Slack Bot for collecting Instagram/TikTok/YouTube URLs and adding them to Google Sheets
Responds to mentions and slash commands

Requirements:
pip install slack-bolt google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client python-dotenv

Setup:
1. Create Slack App at api.slack.com
2. Enable Bot Token Scopes: app_mentions:read, chat:write, commands
3. Enable Event Subscriptions for app_mention
4. Create Google Service Account and download credentials JSON
5. Share your Google Sheet with the service account email
"""

import os, re, logging
from datetime import datetime
from urllib.parse import urlparse

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from dotenv import load_dotenv
from googleapiclient.discovery import build
from google.oauth2 import service_account

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
logger.info("Environment variables loaded")

# Slack configuration
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")

# Google Sheets configuration  
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "Scrape Requests")

# Validate environment variables
missing_vars = []
if not SLACK_BOT_TOKEN:
    missing_vars.append("SLACK_BOT_TOKEN")
if not SLACK_APP_TOKEN:
    missing_vars.append("SLACK_APP_TOKEN")
if not SPREADSHEET_ID:
    missing_vars.append("SPREADSHEET_ID")
if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
    missing_vars.append(f"GOOGLE_CREDENTIALS_FILE ({GOOGLE_CREDENTIALS_FILE})")

if missing_vars:
    logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
    exit(1)

logger.info("All required environment variables are present")

# Initialize Slack app
app = App(token=SLACK_BOT_TOKEN)
logger.info("Slack app initialized")

# Initialize Google Sheets client
try:
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    credentials = service_account.Credentials.from_service_account_file(
        GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=credentials)
    logger.info("Google Sheets client initialized")
except Exception as e:
    logger.error(f"Failed to initialize Google Sheets client: {e}")
    exit(1)

# URL validation patterns
SUPPORTED_PLATFORMS = {
    'instagram.com': 'Instagram',
    'tiktok.com': 'TikTok', 
    'youtube.com': 'YouTube',
    'youtu.be': 'YouTube'
}

def validate_url(url):
    """Validate and normalize social media URLs"""
    try:
        # Add https if missing
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Check if it's a supported platform
        platform = None
        for supported_domain, platform_name in SUPPORTED_PLATFORMS.items():
            if supported_domain in domain:
                platform = platform_name
                break
                
        if not platform:
            return None, "Unsupported platform. Please use Instagram, TikTok, or YouTube URLs."
            
        # Basic path validation
        if not parsed.path or parsed.path == '/':
            return None, f"Invalid {platform} URL. Please provide a profile/channel URL."
            
        return url, platform
        
    except Exception as e:
        return None, f"Invalid URL format: {str(e)}"

def check_duplicate_url(url):
    """Check if URL already exists in the sheet"""
    try:
        # Get existing data
        range_name = f"{SHEET_NAME}!A:E"
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name
        ).execute()
        
        values = result.get('values', [])
        
        # Skip header row and check URLs
        for row in values[1:] if len(values) > 1 else []:
            if len(row) > 1 and row[1] == url:
                return True
                
        return False
        
    except Exception as e:
        logger.error(f"Error checking duplicates: {e}")
        return False

def get_user_name(user_id):
    """Get user's real name from Slack"""
    try:
        result = app.client.users_info(user=user_id)
        if result["ok"]:
            user = result["user"]
            # Try to get real name, fall back to display name, then username
            return user.get("real_name") or user.get("profile", {}).get("display_name") or user.get("name")
    except Exception as e:
        logger.error(f"Error fetching user info: {e}")
    return "Unknown User"

def add_to_sheet(url, platform, user_id):
    """Add URL request to Google Sheet"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_name = get_user_name(user_id)
        
        # Prepare row data
        row_data = [
            timestamp,    # Column A: Timestamp
            url,         # Column B: URL
            platform,    # Column C: Platform (Instagram/TikTok/YouTube)
            user_name,   # Column D: Requester (Actual name of the user)
            "Pending"    # Column E: Status
        ]
        
        # Append to sheet
        range_name = f"{SHEET_NAME}!A:E"
        body = {
            'values': [row_data]
        }
        
        result = sheets_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name,
            valueInputOption='RAW',
            body=body
        ).execute()
        
        return True
        
    except Exception as e:
        logger.error(f"Error adding to sheet: {e}")
        return False

def setup_sheet_headers():
    """Set up sheet headers if they don't exist"""
    try:
        headers = ["Timestamp", "URL", "Platform", "Requester", "Status"]
        
        # Check if headers exist
        range_name = f"{SHEET_NAME}!A1:E1"
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=range_name
        ).execute()
        
        values = result.get('values', [])
        
        # Add headers if sheet is empty
        if not values:
            body = {'values': [headers]}
            sheets_service.spreadsheets().values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=range_name,
                valueInputOption='RAW',
                body=body
            ).execute()
            logger.info("Sheet headers created")
            
    except Exception as e:
        logger.error(f"Error setting up headers: {e}")

@app.event("app_mention")
def handle_mention(event, say):
    """Handle @bot mentions with URLs"""
    try:
        text = event.get('text', '')
        user = event.get('user')
        
        logger.info(f"Received mention from user {user}")
        
        # Extract URLs from message
        url_pattern = r'https?://[^\s<>]+'
        urls = re.findall(url_pattern, text)
        
        if not urls:
            say(f"<@{user}> Please include a social media URL in your message.\n"
                f"Supported platforms: Instagram, TikTok, YouTube")
            return
        
        processed_urls = []
        errors = []
        
        for url in urls:
            # Remove Slack formatting
            url = url.strip('<>')
            logger.info(f"Processing URL: {url}")
            
            # Validate URL
            validated_url, result = validate_url(url)
            
            if not validated_url:
                errors.append(f"• {url}: {result}")
                continue
                
            platform = result
            
            # Check for duplicates
            if check_duplicate_url(validated_url):
                errors.append(f"• {url}: Already exists in database")
                continue
                
            # Add to sheet
            if add_to_sheet(validated_url, platform, user):
                processed_urls.append(f"• {platform}: {validated_url}")
            else:
                errors.append(f"• {url}: Failed to add to database")
        
        # Send response
        response = f"<@{user}> URL Processing Results:\n\n"
        
        if processed_urls:
            response += "✅ *Successfully Added:*\n" + "\n".join(processed_urls) + "\n\n"
            
        if errors:
            response += "❌ *Errors:*\n" + "\n".join(errors) + "\n\n"
            
        if processed_urls:
            response += "_URLs will be scraped in the next batch run (every ~6 hours)_"
        
        say(response)
        logger.info(f"Processed {len(processed_urls)} URLs successfully, {len(errors)} errors")
        
    except Exception as e:
        logger.error(f"Error handling mention: {e}")
        say(f"<@{user}> Sorry, something went wrong. Please try again later.")

@app.command("/add-influencer")
def handle_slash_command(ack, respond, command):
    """Handle /add-influencer slash command"""
    try:
        ack()
        
        url = command['text'].strip()
        user = command['user_id']
        
        logger.info(f"Received slash command from user {user}")
        
        if not url:
            respond("Please provide a URL: `/add-influencer https://instagram.com/username`")
            return
        
        # Validate URL
        validated_url, result = validate_url(url)
        
        if not validated_url:
            respond(f"❌ {result}")
            return
            
        platform = result
        
        # Check for duplicates
        if check_duplicate_url(validated_url):
            respond(f"❌ URL already exists in database: {url}")
            return
        
        # Add to sheet
        if add_to_sheet(validated_url, platform, user):
            respond(f"✅ Added {platform} URL to scrape queue!\n"
                    f"URL: {validated_url}\n"
                    f"_Will be processed in the next batch run (~6 hours)_")
            logger.info(f"Successfully added URL: {validated_url}")
        else:
            respond("❌ Failed to add URL to database. Please try again.")
            logger.error(f"Failed to add URL: {validated_url}")
            
    except Exception as e:
        logger.error(f"Error handling slash command: {e}")
        respond("❌ Sorry, something went wrong. Please try again later.")

@app.error
def global_error_handler(error, body, logger):
    """Global error handler for the app"""
    logger.error(f"Error: {error}")
    logger.error(f"Request body: {body}")

if __name__ == "__main__":
    try:
        # Setup sheet headers on startup
        setup_sheet_headers()
        logger.info("Sheet headers verified")
        
        # Start the app
        handler = SocketModeHandler(app, SLACK_APP_TOKEN)
        logger.info("⚡️ Slack bot is running!")
        handler.start()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        exit(1)