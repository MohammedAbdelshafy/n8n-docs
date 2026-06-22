-- ============================================================
-- TRANCHI AI - Government Auction Deal Engine
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- AUCTION PROPERTIES (raw finds from gov sources)
-- ============================================================
CREATE TABLE IF NOT EXISTS auction_properties (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Property identity
    address TEXT NOT NULL,
    city TEXT,
    state TEXT,
    zip TEXT,
    county TEXT,

    -- Auction source
    source TEXT NOT NULL, -- 'HUD' | 'TAX_SALE' | 'SHERIFF' | 'FANNIE_MAE' | 'FREDDIE_MAC' | 'USDA'
    source_url TEXT,
    auction_date DATE,
    listing_id TEXT,

    -- Financials
    opening_bid NUMERIC(12,2),      -- what the gov starts bidding at
    current_bid NUMERIC(12,2),
    estimated_arv NUMERIC(12,2),    -- After Repair Value
    estimated_repairs NUMERIC(12,2),
    mao NUMERIC(12,2),              -- Maximum Allowable Offer

    -- Property details
    bedrooms INT,
    bathrooms NUMERIC(4,1),
    sqft INT,
    year_built INT,
    property_type TEXT,             -- SFR | MF | LAND | CONDO
    condition TEXT,                 -- EXCELLENT | GOOD | FAIR | POOR | TEARDOWN

    -- AI decision
    ai_status TEXT DEFAULT 'PENDING', -- PENDING | APPROVE | REJECT | REVIEW
    ai_grade TEXT,                    -- A+ | A | B+ | B | C
    ai_notes TEXT,
    sms_draft TEXT,

    -- Pipeline status
    status TEXT DEFAULT 'NEW',        -- NEW | UNDERWRITING | APPROVED | BIDDING | WON | LOST | ASSIGNED | CLOSED
    assigned_buyer_id UUID,

    CONSTRAINT valid_source CHECK (source IN ('HUD','TAX_SALE','SHERIFF','FANNIE_MAE','FREDDIE_MAC','USDA','AUCTION_COM','OTHER')),
    CONSTRAINT valid_ai_status CHECK (ai_status IN ('PENDING','APPROVE','REJECT','REVIEW')),
    CONSTRAINT valid_status CHECK (status IN ('NEW','UNDERWRITING','APPROVED','BIDDING','WON','LOST','ASSIGNED','CLOSED'))
);

-- ============================================================
-- CASH BUYERS (your exit strategy — people who buy from you)
-- ============================================================
CREATE TABLE IF NOT EXISTS cash_buyers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    name TEXT NOT NULL,
    company TEXT,
    phone TEXT,
    email TEXT,
    state TEXT,
    city TEXT,

    -- Buy box
    max_purchase_price NUMERIC(12,2),
    min_beds INT DEFAULT 2,
    preferred_states TEXT[],         -- ['TX','FL','GA']
    preferred_property_types TEXT[], -- ['SFR','MF']
    buys_as_is BOOLEAN DEFAULT TRUE,
    proof_of_funds BOOLEAN DEFAULT FALSE,

    -- Engagement
    last_contacted TIMESTAMPTZ,
    response_rate NUMERIC(4,1),      -- 0–100 %
    deals_closed INT DEFAULT 0,
    opt_in BOOLEAN DEFAULT FALSE,    -- MUST be true before outreach
    opt_in_date TIMESTAMPTZ,
    opt_out BOOLEAN DEFAULT FALSE,

    score INT DEFAULT 0,             -- scoring model 0-100
    status TEXT DEFAULT 'NEW'        -- NEW | ACTIVE | COLD | BLACKLISTED
);

-- ============================================================
-- ACTIVE DEALS (one row per deal in motion)
-- ============================================================
CREATE TABLE IF NOT EXISTS active_deals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    property_id UUID REFERENCES auction_properties(id),
    buyer_id UUID REFERENCES cash_buyers(id),

    -- Buy side
    purchase_price NUMERIC(12,2),    -- what you paid at auction
    auction_date DATE,
    closing_date_buy DATE,

    -- Sell side
    assignment_fee NUMERIC(12,2),    -- your profit
    sale_price NUMERIC(12,2),        -- what buyer pays
    closing_date_sell DATE,

    -- Costs
    title_cost NUMERIC(10,2),
    holding_cost NUMERIC(10,2),
    misc_cost NUMERIC(10,2),

    -- Net
    net_profit NUMERIC(12,2) GENERATED ALWAYS AS (
        assignment_fee - COALESCE(title_cost,0) - COALESCE(holding_cost,0) - COALESCE(misc_cost,0)
    ) STORED,

    status TEXT DEFAULT 'OPEN',      -- OPEN | UNDER_CONTRACT | ASSIGNED | CLOSED | DEAD
    notes TEXT
);

-- ============================================================
-- CLOSED DEALS (performance tracking)
-- ============================================================
CREATE TABLE IF NOT EXISTS closed_deals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    closed_at TIMESTAMPTZ DEFAULT NOW(),
    deal_id UUID REFERENCES active_deals(id),
    property_address TEXT,
    purchase_price NUMERIC(12,2),
    sale_price NUMERIC(12,2),
    net_profit NUMERIC(12,2),
    days_to_close INT,
    source TEXT
);

-- ============================================================
-- OUTREACH LOG
-- ============================================================
CREATE TABLE IF NOT EXISTS outreach_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    buyer_id UUID REFERENCES cash_buyers(id),
    property_id UUID REFERENCES auction_properties(id),
    channel TEXT,       -- SMS | EMAIL | CALL
    message TEXT,
    status TEXT,        -- SENT | DELIVERED | REPLIED | OPTED_OUT | FAILED
    reply_text TEXT,
    replied_at TIMESTAMPTZ
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX idx_auction_props_status ON auction_properties(status);
CREATE INDEX idx_auction_props_state ON auction_properties(state);
CREATE INDEX idx_auction_props_ai_status ON auction_properties(ai_status);
CREATE INDEX idx_auction_props_source ON auction_properties(source);
CREATE INDEX idx_cash_buyers_state ON cash_buyers(state);
CREATE INDEX idx_cash_buyers_opt_in ON cash_buyers(opt_in);
CREATE INDEX idx_active_deals_status ON active_deals(status);
CREATE INDEX idx_outreach_log_buyer ON outreach_log(buyer_id);

-- ============================================================
-- VIEWS
-- ============================================================

-- Daily deal dashboard
CREATE OR REPLACE VIEW v_daily_dashboard AS
SELECT
    DATE(created_at) AS day,
    COUNT(*) FILTER (WHERE ai_status = 'APPROVE') AS approved_deals,
    COUNT(*) FILTER (WHERE status = 'WON') AS auctions_won,
    COUNT(*) FILTER (WHERE status = 'ASSIGNED') AS deals_assigned,
    COUNT(*) FILTER (WHERE status = 'CLOSED') AS deals_closed,
    SUM(mao) FILTER (WHERE ai_status = 'APPROVE') AS total_mao_approved,
    SUM(estimated_arv) FILTER (WHERE ai_status = 'APPROVE') AS total_arv_pipeline
FROM auction_properties
GROUP BY DATE(created_at)
ORDER BY day DESC;

-- Best live opportunities
CREATE OR REPLACE VIEW v_hot_deals AS
SELECT
    address, city, state, source,
    opening_bid, estimated_arv, mao, estimated_repairs,
    ai_grade, sms_draft,
    (estimated_arv - opening_bid - COALESCE(estimated_repairs,0)) AS gross_spread,
    auction_date
FROM auction_properties
WHERE ai_status = 'APPROVE'
  AND status IN ('APPROVED','BIDDING')
ORDER BY gross_spread DESC;
