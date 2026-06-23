-- ============================================================
-- TRANCHI AI — Seller Leads (opt-in only)
-- Run after supabase_schema.sql.
-- These are homeowners who VOLUNTARILY submitted the
-- "get a cash offer" form. Every row has consent provenance,
-- which makes the lead legally workable AND sellable.
-- ============================================================

CREATE TABLE IF NOT EXISTS seller_leads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Contact
    name TEXT NOT NULL,
    phone TEXT,
    email TEXT,

    -- Property
    property_address TEXT NOT NULL,
    city TEXT, state TEXT, zip TEXT,
    property_type TEXT,           -- SFR | MF | CONDO | LAND | MOBILE
    beds INT, baths NUMERIC(4,1),

    -- Seller situation (self-reported on the form)
    timeline TEXT,                -- ASAP | 1-3_MONTHS | 3-6_MONTHS | JUST_CURIOUS
    reason TEXT,                  -- RELOCATING | INHERITED | REPAIRS | FINANCIAL | TIRED_LANDLORD | OTHER
    asking_price NUMERIC(12,2),
    mortgage_balance NUMERIC(12,2),
    condition TEXT,               -- EXCELLENT | GOOD | FAIR | POOR

    -- Consent provenance (the part that makes it sellable)
    consent_given BOOLEAN DEFAULT FALSE,
    consent_timestamp TIMESTAMPTZ,
    consent_ip TEXT,
    consent_text TEXT,            -- exact disclosure they agreed to
    source TEXT DEFAULT 'SELLER_LANDING_PAGE',

    -- Lead lifecycle
    lead_score INT DEFAULT 0,     -- 0-100 motivation score
    status TEXT DEFAULT 'NEW',    -- NEW | CONTACTED | QUALIFIED | OFFER_MADE | SOLD_TO_BUYER | DEAD
    sold_price NUMERIC(10,2),     -- if you sell the lead, what you got for it
    sold_to TEXT,                 -- which buyer/company you sold the lead to
    sold_at TIMESTAMPTZ,

    opt_out BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_seller_leads_status ON seller_leads(status);
CREATE INDEX IF NOT EXISTS idx_seller_leads_state  ON seller_leads(state);
CREATE INDEX IF NOT EXISTS idx_seller_leads_score  ON seller_leads(lead_score DESC);

-- Lead scoring view — surfaces the hottest opt-in sellers
CREATE OR REPLACE VIEW v_hot_seller_leads AS
SELECT
    name, phone, email, property_address, city, state,
    timeline, reason, asking_price, lead_score, status, created_at
FROM seller_leads
WHERE opt_out = FALSE
  AND status NOT IN ('DEAD', 'SOLD_TO_BUYER')
ORDER BY lead_score DESC, created_at DESC;

-- RLS
ALTER TABLE seller_leads ENABLE ROW LEVEL SECURITY;
CREATE POLICY "auth read seller leads" ON seller_leads
  FOR SELECT TO authenticated USING (true);
