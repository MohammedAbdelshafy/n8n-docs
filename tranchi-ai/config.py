import os
from dotenv import load_dotenv

load_dotenv()

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# LLM — free providers tried first, Anthropic as fallback
# Get a free key at console.groq.com (no credit card needed)
GROQ_API_KEY      = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")  # optional paid fallback

# Email — primary outreach channel (free via Gmail SMTP)
EMAIL_ADDRESS      = os.getenv("EMAIL_ADDRESS", "")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")
REPLY_TO_EMAIL     = os.getenv("REPLY_TO_EMAIL", EMAIL_ADDRESS)
EMAIL_SMTP_HOST    = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT    = int(os.getenv("EMAIL_SMTP_PORT", "587"))

# Twilio — optional SMS (add after A2P 10DLC registration)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")

# Removed: APIFY_API_TOKEN (replaced by free Playwright scraper)
# Removed: BATCHDATA_API_KEY (replaced by free Zillow comps)

# Target states for deal hunting
TARGET_STATES = ["TX", "FL", "OH", "GA", "NC", "TN", "AZ"]

# Deal thresholds
MIN_NET_PROFIT = 10_000
MAO_MULTIPLIER = 0.70      # 70% rule
FLAT_CLOSING_COST = 3_500
FLAT_HOLDING_COST = 2_500

# Repair cost per sqft by era
REPAIR_RATE = {
    "pre_1960":   42,   # $/sqft
    "1960_1990":  27,
    "1990_2005":  16,
    "post_2005":  11,
}

CONDITION_MULTIPLIER = {
    "EXCELLENT": 0.3,
    "GOOD":      0.6,
    "FAIR":      1.0,
    "POOR":      1.5,
    "TEARDOWN":  None,   # auto-reject
}

# Auction sources to scrape daily
AUCTION_SOURCES = {
    "HUD":         "https://www.hudhomestore.gov",
    "FANNIE_MAE":  "https://www.homepath.com",
    "FREDDIE_MAC": "https://www.homesteps.com",
    "USDA":        "https://properties.sc.egov.usda.gov",
    "AUCTION_COM": "https://www.auction.com",
}

# County tax sale portals by state
TAX_SALE_PORTALS = {
    "TX": "https://www.tax-sale.info/",
    "FL": "https://www.bidspotter.com/",
    "OH": "https://ohiosherifsales.com/",
    "GA": "https://www.govease.com/",
    "NC": "https://www.tax-sale.info/",
    "TN": "https://www.tennessee.gov/treasury/",
    "AZ": "https://www.maricopa.gov/5305/Tax-Lien-Sale",
}
