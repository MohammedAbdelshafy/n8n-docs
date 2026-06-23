-- ============================================================
-- TRANCHI AI — Row Level Security
-- Run this AFTER supabase_schema.sql.
-- Locks every table so the public/anon key can read NOTHING.
-- The Python backend uses the service_role key (bypasses RLS),
-- so the pipeline keeps working. The dashboard reads via an
-- authenticated logged-in user only.
-- ============================================================

-- Enable RLS on every table
ALTER TABLE auction_properties ENABLE ROW LEVEL SECURITY;
ALTER TABLE cash_buyers        ENABLE ROW LEVEL SECURITY;
ALTER TABLE active_deals       ENABLE ROW LEVEL SECURITY;
ALTER TABLE closed_deals       ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach_log       ENABLE ROW LEVEL SECURITY;

-- ── ANON (browser, publishable key): NO access at all ────────
-- We deliberately create NO policies for the anon role.
-- With RLS on and no anon policy, the anon key returns zero rows.

-- ── AUTHENTICATED (logged-in dashboard user): read-only ──────
CREATE POLICY "auth read properties" ON auction_properties
  FOR SELECT TO authenticated USING (true);

CREATE POLICY "auth read buyers" ON cash_buyers
  FOR SELECT TO authenticated USING (true);

CREATE POLICY "auth read deals" ON active_deals
  FOR SELECT TO authenticated USING (true);

CREATE POLICY "auth read closed" ON closed_deals
  FOR SELECT TO authenticated USING (true);

CREATE POLICY "auth read outreach" ON outreach_log
  FOR SELECT TO authenticated USING (true);

-- Note: all INSERT/UPDATE/DELETE happens server-side through the
-- Python pipeline using the service_role key, which bypasses RLS.
-- The browser never writes directly, so no write policies are needed.
