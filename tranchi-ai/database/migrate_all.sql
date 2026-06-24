-- ============================================================
-- TRANCHI AI — COMBINED MIGRATION (idempotent, run-once)
-- Runs all 4 schema files in the correct order in a single shot.
-- Safe to re-run: every object uses IF NOT EXISTS / DROP-then-CREATE.
--   1. core schema  2. RLS  3. seller_leads  4. fb_group_tracker
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 1. CORE SCHEMA
-- ============================================================
CREATE TABLE IF NOT EXISTS auction_properties (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    address TEXT NOT NULL,
    city TEXT, state TEXT, zip TEXT, county TEXT,
    source TEXT NOT NULL,
    source_url TEXT,
    listing_id TEXT,
    auction_date TEXT,
    opening_bid NUMERIC(12,2),
    current_bid NUMERIC(12,2),
    estimated_arv NUMERIC(12,2),
    estimated_repairs NUMERIC(12,2),
    mao NUMERIC(12,2),
    bedrooms INT,
    bathrooms NUMERIC(4,1),
    sqft INT,
    year_built INT,
    property_type TEXT,
    condition TEXT,
    ai_status TEXT DEFAULT 'PENDING',
    ai_grade TEXT,
    ai_notes TEXT,
    sms_draft TEXT,
    status TEXT DEFAULT 'NEW',
    assigned_buyer_id UUID,
    CONSTRAINT valid_ai_status CHECK (ai_status IN ('PENDING','APPROVE','REJECT','REVIEW')),
    CONSTRAINT valid_status CHECK (status IN ('NEW','UNDERWRITING','APPROVED','BIDDING','WON','LOST','ASSIGNED','CLOSED'))
);

CREATE TABLE IF NOT EXISTS cash_buyers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    name TEXT NOT NULL,
    company TEXT, phone TEXT, email TEXT, state TEXT, city TEXT,
    max_purchase_price NUMERIC(12,2),
    min_beds INT DEFAULT 2,
    preferred_states TEXT[],
    preferred_property_types TEXT[],
    buys_as_is BOOLEAN DEFAULT TRUE,
    proof_of_funds BOOLEAN DEFAULT FALSE,
    last_contacted TIMESTAMPTZ,
    response_rate NUMERIC(4,1),
    deals_closed INT DEFAULT 0,
    opt_in BOOLEAN DEFAULT FALSE,
    opt_in_date TIMESTAMPTZ,
    opt_out BOOLEAN DEFAULT FALSE,
    score INT DEFAULT 0,
    status TEXT DEFAULT 'NEW'
);

CREATE TABLE IF NOT EXISTS active_deals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    property_id UUID REFERENCES auction_properties(id),
    buyer_id UUID REFERENCES cash_buyers(id),
    purchase_price NUMERIC(12,2),
    auction_date DATE,
    closing_date_buy DATE,
    assignment_fee NUMERIC(12,2),
    sale_price NUMERIC(12,2),
    closing_date_sell DATE,
    title_cost NUMERIC(10,2),
    holding_cost NUMERIC(10,2),
    misc_cost NUMERIC(10,2),
    net_profit NUMERIC(12,2) GENERATED ALWAYS AS (
        assignment_fee - COALESCE(title_cost,0) - COALESCE(holding_cost,0) - COALESCE(misc_cost,0)
    ) STORED,
    status TEXT DEFAULT 'OPEN',
    notes TEXT
);

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

CREATE TABLE IF NOT EXISTS outreach_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    buyer_id UUID REFERENCES cash_buyers(id),
    property_id UUID REFERENCES auction_properties(id),
    channel TEXT, message TEXT, status TEXT,
    reply_text TEXT, replied_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_auction_props_status    ON auction_properties(status);
CREATE INDEX IF NOT EXISTS idx_auction_props_state     ON auction_properties(state);
CREATE INDEX IF NOT EXISTS idx_auction_props_ai_status ON auction_properties(ai_status);
CREATE INDEX IF NOT EXISTS idx_auction_props_source    ON auction_properties(source);
CREATE INDEX IF NOT EXISTS idx_cash_buyers_state       ON cash_buyers(state);
CREATE INDEX IF NOT EXISTS idx_cash_buyers_opt_in      ON cash_buyers(opt_in);
CREATE INDEX IF NOT EXISTS idx_active_deals_status     ON active_deals(status);
CREATE INDEX IF NOT EXISTS idx_outreach_log_buyer      ON outreach_log(buyer_id);

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

-- ============================================================
-- 2. ROW LEVEL SECURITY
-- ============================================================
ALTER TABLE auction_properties ENABLE ROW LEVEL SECURITY;
ALTER TABLE cash_buyers        ENABLE ROW LEVEL SECURITY;
ALTER TABLE active_deals       ENABLE ROW LEVEL SECURITY;
ALTER TABLE closed_deals       ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach_log       ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "auth read properties" ON auction_properties;
CREATE POLICY "auth read properties" ON auction_properties FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "auth read buyers" ON cash_buyers;
CREATE POLICY "auth read buyers" ON cash_buyers FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "auth read deals" ON active_deals;
CREATE POLICY "auth read deals" ON active_deals FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "auth read closed" ON closed_deals;
CREATE POLICY "auth read closed" ON closed_deals FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "auth read outreach" ON outreach_log;
CREATE POLICY "auth read outreach" ON outreach_log FOR SELECT TO authenticated USING (true);

-- ============================================================
-- 3. SELLER LEADS (opt-in only)
-- ============================================================
CREATE TABLE IF NOT EXISTS seller_leads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    name TEXT NOT NULL,
    phone TEXT, email TEXT,
    property_address TEXT NOT NULL,
    city TEXT, state TEXT, zip TEXT,
    property_type TEXT,
    beds INT, baths NUMERIC(4,1),
    timeline TEXT, reason TEXT,
    asking_price NUMERIC(12,2),
    mortgage_balance NUMERIC(12,2),
    condition TEXT,
    consent_given BOOLEAN DEFAULT FALSE,
    consent_timestamp TIMESTAMPTZ,
    consent_ip TEXT,
    consent_text TEXT,
    source TEXT DEFAULT 'SELLER_LANDING_PAGE',
    lead_score INT DEFAULT 0,
    status TEXT DEFAULT 'NEW',
    sold_price NUMERIC(10,2),
    sold_to TEXT,
    sold_at TIMESTAMPTZ,
    opt_out BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_seller_leads_status ON seller_leads(status);
CREATE INDEX IF NOT EXISTS idx_seller_leads_state  ON seller_leads(state);
CREATE INDEX IF NOT EXISTS idx_seller_leads_score  ON seller_leads(lead_score DESC);

CREATE OR REPLACE VIEW v_hot_seller_leads AS
SELECT
    name, phone, email, property_address, city, state,
    timeline, reason, asking_price, lead_score, status, created_at
FROM seller_leads
WHERE opt_out = FALSE
  AND status NOT IN ('DEAD', 'SOLD_TO_BUYER')
ORDER BY lead_score DESC, created_at DESC;

ALTER TABLE seller_leads ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "auth read seller leads" ON seller_leads;
CREATE POLICY "auth read seller leads" ON seller_leads FOR SELECT TO authenticated USING (true);

-- ============================================================
-- 4. FACEBOOK GROUP POST TRACKER
-- ============================================================
CREATE TABLE IF NOT EXISTS fb_group_posts (
    id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    group_name  TEXT NOT NULL,
    post_type   TEXT NOT NULL,
    state       TEXT,
    posted_at   TIMESTAMPTZ DEFAULT NOW(),
    notes       TEXT,
    responses   INT DEFAULT 0,
    deals_closed INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_fb_posts_state ON fb_group_posts(state);
CREATE INDEX IF NOT EXISTS idx_fb_posts_group ON fb_group_posts(group_name);

ALTER TABLE fb_group_posts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all" ON fb_group_posts;
CREATE POLICY "service_role_all" ON fb_group_posts FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ============================================================
-- DONE. All tables, indexes, views, and RLS policies created.
-- ============================================================
