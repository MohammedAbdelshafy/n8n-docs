-- Facebook group post tracker
-- Run this in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS fb_group_posts (
    id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    group_name  TEXT NOT NULL,
    post_type   TEXT NOT NULL,  -- deal | buyers | leads | collab
    state       TEXT,
    posted_at   TIMESTAMPTZ DEFAULT NOW(),
    notes       TEXT,
    responses   INT DEFAULT 0,  -- update manually as people DM you
    deals_closed INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_fb_posts_state ON fb_group_posts(state);
CREATE INDEX IF NOT EXISTS idx_fb_posts_group ON fb_group_posts(group_name);

-- RLS: same pattern as other tables
ALTER TABLE fb_group_posts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all" ON fb_group_posts
    FOR ALL TO service_role USING (true) WITH CHECK (true);
