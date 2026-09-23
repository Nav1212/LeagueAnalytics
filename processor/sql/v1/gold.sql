-- Serving definitions v1 preserve the original formulas, per independent source.
CREATE TEMP TABLE _eligible_matches AS
SELECT * FROM silver_matches WHERE queue_id=420 AND duration_seconds>=300;
CREATE TEMP TABLE _eligible_players AS
SELECT p.*,m.patch FROM silver_match_participants p
JOIN _eligible_matches m USING(source,match_id)
WHERE p.normalized_role IS NOT NULL AND p.champion_id>0;

CREATE TABLE gold_patch_totals AS
SELECT source,patch,count(*)::BIGINT AS matches FROM _eligible_matches GROUP BY ALL;
CREATE TABLE gold_champion_stats AS
SELECT source,patch,champion_id,normalized_role AS role,count(*)::BIGINT AS games,
    sum(coalesce(win,false)::INTEGER)::BIGINT AS wins,
    sum(coalesce(kills,0))::BIGINT AS kills,sum(coalesce(deaths,0))::BIGINT AS deaths,
    sum(coalesce(assists,0))::BIGINT AS assists,sum(coalesce(gold_earned,0))::BIGINT AS gold,
    sum(coalesce(champion_damage,0))::BIGINT AS damage,
    sum(coalesce(lane_cs,0)+coalesce(neutral_cs,0))::BIGINT AS cs
FROM _eligible_players GROUP BY ALL;
CREATE TABLE gold_champion_bans AS
SELECT b.source,m.patch,b.champion_id,count(*)::BIGINT AS bans
FROM silver_team_bans b JOIN _eligible_matches m USING(source,match_id)
WHERE b.champion_id IS NOT NULL GROUP BY ALL;

-- Keep the legacy last-participant-in-role opponent choice, now explicit.
CREATE TEMP TABLE _opponents AS SELECT * FROM _eligible_players
QUALIFY row_number() OVER (PARTITION BY source,match_id,team_id,normalized_role ORDER BY participant_id DESC)=1;
CREATE TABLE gold_matchups AS
SELECT p.source,p.patch,p.champion_id,p.normalized_role AS role,o.champion_id AS opponent_id,
    count(*)::BIGINT AS games,sum(coalesce(p.win,false)::INTEGER)::BIGINT AS wins
FROM _eligible_players p JOIN _opponents o ON p.source=o.source AND p.match_id=o.match_id
    AND p.normalized_role=o.normalized_role AND o.team_id=CASE WHEN p.team_id=100 THEN 200 ELSE 100 END
WHERE p.champion_id<>o.champion_id GROUP BY ALL;

-- These are sorted combinations of the first three eligible FINAL inventory slots.
CREATE TEMP TABLE _inventory_combinations AS
SELECT source,match_id,participant_id,to_json(list_sort(list(item_id ORDER BY slot)[:3]))::VARCHAR AS items
FROM silver_participant_items
WHERE slot<6 AND item_id IS NOT NULL AND item_id NOT IN (3340,3363,3364,2003,2031,2033,2055,2138,2139,2140,3400)
GROUP BY ALL;
CREATE TABLE gold_builds AS
SELECT p.source,p.patch,p.champion_id,p.normalized_role AS role,i.items,
    count(*)::BIGINT AS games,sum(coalesce(p.win,false)::INTEGER)::BIGINT AS wins
FROM _eligible_players p JOIN _inventory_combinations i USING(source,match_id,participant_id) GROUP BY ALL;
CREATE TEMP TABLE _spell_combinations AS
SELECT source,match_id,participant_id,to_json(list_sort(list(coalesce(spell_id,0) ORDER BY slot)))::VARCHAR AS spells
FROM silver_participant_spells GROUP BY ALL;
CREATE TABLE gold_spell_sets AS
SELECT p.source,p.patch,p.champion_id,p.normalized_role AS role,s.spells,
    count(*)::BIGINT AS games,sum(coalesce(p.win,false)::INTEGER)::BIGINT AS wins
FROM _eligible_players p JOIN _spell_combinations s USING(source,match_id,participant_id) GROUP BY ALL;
CREATE TABLE gold_rune_sets AS
SELECT p.source,p.patch,p.champion_id,p.normalized_role AS role,r.rune_id AS keystone,sub.style_id AS sub_style,
    count(*)::BIGINT AS games,sum(coalesce(p.win,false)::INTEGER)::BIGINT AS wins
FROM _eligible_players p
JOIN silver_participant_rune_styles main USING(source,match_id,participant_id)
JOIN silver_participant_runes r ON r.source=main.source AND r.match_id=main.match_id AND r.participant_id=main.participant_id AND r.style_slot=main.style_slot AND r.selection_slot=0
JOIN silver_participant_rune_styles sub ON sub.source=p.source AND sub.match_id=p.match_id AND sub.participant_id=p.participant_id
WHERE main.designation='primaryStyle' AND sub.designation='subStyle' AND r.rune_id>0 GROUP BY ALL;

-- Immutable display snapshot: prefer retained English definitions, retain cache fallback.
CREATE TABLE gold_champions AS
SELECT ids.champion_id,coalesce(v.key,cache.key,'Champion'||ids.champion_id) AS key,
    coalesce(l.name,cache.name,v.key,'Champion '||ids.champion_id) AS name,
    coalesce(l.title,cache.title,'') AS title,
    coalesce(tags.tags,cache.tags,'[]') AS tags
FROM silver_champions ids
LEFT JOIN silver_champion_versions v USING(champion_id)
LEFT JOIN silver_champion_localizations l ON l.champion_id=v.champion_id AND l.static_version=v.static_version
LEFT JOIN (SELECT static_version,champion_id,to_json(list(tag ORDER BY tag))::VARCHAR AS tags FROM silver_champion_tags GROUP BY ALL) tags
    ON tags.static_version=v.static_version AND tags.champion_id=v.champion_id
LEFT JOIN champions cache USING(champion_id)
QUALIFY row_number() OVER (PARTITION BY ids.champion_id ORDER BY (l.locale='en_US') DESC NULLS LAST,
    try_cast(split_part(v.static_version,'.',1) AS INTEGER) DESC,
    try_cast(split_part(v.static_version,'.',2) AS INTEGER) DESC,
    try_cast(split_part(v.static_version,'.',3) AS INTEGER) DESC,l.locale)=1;

-- Public summaries only: no raw payloads or private processing metadata.
CREATE TABLE gold_source_counts AS
SELECT source,count(*)::BIGINT AS raw_matches FROM bronze_matches
WHERE source IN ('riot','demo') GROUP BY source;

CREATE TABLE gold_meta AS
SELECT key,value FROM meta WHERE key='ddragon_version';

-- Keep the complete typed style/slot structure needed by the UI, including icons.
CREATE TABLE gold_rune_catalog AS
SELECT version,locale,to_json(list(obj ORDER BY obj.id))::VARCHAR AS styles
FROM (
    SELECT version,locale,obj FROM _static_styles
    WHERE payload_id IN (
        SELECT payload_id FROM _payloads
        WHERE dataset='ddragon.runes' AND source='ddragon'
        QUALIFY row_number() OVER (
            PARTITION BY version,locale ORDER BY observed_at DESC,payload_id DESC
        )=1
    )
) GROUP BY version,locale;
