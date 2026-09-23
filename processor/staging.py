"""Bulk typed JSON extraction for SQL model version 1."""
from __future__ import annotations

import json

INT = "BIGINT"
STR = "VARCHAR"
BOOL = "BOOLEAN"
DOUBLE = "DOUBLE"


def structure(names, kind):
    return {name: kind for name in names.split()}


PLAYER = {
    **structure("participantId teamId championId champLevel kills deaths assists goldEarned goldSpent totalMinionsKilled neutralMinionsKilled totalDamageDealtToChampions visionScore item0 item1 item2 item3 item4 item5 item6 summoner1Id summoner2Id", INT),
    **structure("puuid championName teamPosition individualPosition lane role", STR),
    **structure("win gameEndedInEarlySurrender gameEndedInSurrender", BOOL),
    "perks": {"statPerks": structure("offense flex defense", INT), "styles": [{
        "style": INT, "description": STR, "selections": [structure("perk var1 var2 var3", INT)]}]},
}
TEAM = {"teamId": INT, "win": BOOL, "bans": [structure("championId pickTurn", INT)],
        "objectives": ("MAP", {"first": BOOL, "kills": INT})}
MATCH = {"metadata": {"matchId": STR}, "info": {
    **structure("queueId mapId gameDuration gameStartTimestamp gameEndTimestamp", INT),
    **structure("platformId gameVersion gameMode gameType endOfGameResult", STR),
    "participants": [PLAYER], "teams": [TEAM],
}}
EVENT = {
    **structure("type levelUpType monsterType monsterSubType buildingType towerType laneType", STR),
    **structure("timestamp participantId killerId victimId itemId beforeId afterId skillSlot teamId killerTeamId", INT),
    "position": structure("x y", INT), "assistingParticipantIds": [INT],
}
FRAME_PLAYER = {**structure("participantId totalGold currentGold xp level minionsKilled jungleMinionsKilled", INT),
                "position": structure("x y", INT),
                "damageStats": structure("totalDamageDoneToChampions totalDamageTaken", INT),
                "championStats": structure("health healthMax armor attackDamage abilityPower", DOUBLE)}
TIMELINE = {"metadata": {"matchId": STR}, "info": {"frameInterval": INT, "frames": [{
    "timestamp": INT, "participantFrames": {},
    "events": [EVENT]}]}}


def sql_type(schema):
    if isinstance(schema, str): return schema
    if isinstance(schema, tuple): return f"MAP(VARCHAR, {sql_type(schema[1])})"
    if isinstance(schema, list): return sql_type(schema[0]) + "[]"
    return "STRUCT(" + ",".join('"'+k+'" '+sql_type(v) for k,v in schema.items()) + ")"


TIMELINE['info']['frames'][0]['participantFrames'] = ("MAP", FRAME_PLAYER)
CHAMPION = {**structure("key id name title blurb partype", STR), "tags":[STR],
            "stats": structure("hp hpperlevel mp mpperlevel movespeed armor armorperlevel spellblock spellblockperlevel attackrange hpregen hpregenperlevel mpregen mpregenperlevel crit critperlevel attackdamage attackdamageperlevel attackspeedperlevel attackspeed", DOUBLE)}
ITEM = {**structure("name description",STR), "from":[STR], "gold":{**structure("total base sell",INT),'purchasable':BOOL}, "stats":("MAP", DOUBLE), "maps":("MAP", BOOL)}
SPELL = {**structure("id key name description",STR),**structure("summonerLevel maxrank",INT)}
RUNE = {"id":INT, **structure("key name icon longDesc shortDesc",STR)}
STYLE = {"id":INT, **structure("key name icon",STR),"slots":[{"runes":[RUNE]}]}
ACCOUNT = structure("puuid gameName tagLine",STR)
SUMMONER = {**structure("puuid id accountId",STR),**structure("summonerLevel profileIconId",INT)}
RANK = {**structure("puuid queueType tier rank",STR),**structure("leaguePoints wins losses",INT)}
MASTERY = {"puuid":STR,**structure("championId championLevel championPoints lastPlayTime",INT)}
CHALLENGE = {"level":STR,**structure("challengeId achievedTime",INT),**structure("value percentile",DOUBLE)}


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def transform_schema(schema):
    if isinstance(schema, tuple): return sql_type(schema)
    if isinstance(schema, list): return [transform_schema(schema[0])]
    if isinstance(schema, dict): return {key: transform_schema(child) for key, child in schema.items()}
    return schema


def nullable_object_sql(value, schema, depth=0):
    """Fill missing keys with JSON null, preserving provided values for strict casts.

    Scalar/lambda expressions keep this linear in input size. Correlated json_tree
    joins retain entire match documents as join keys and spill excessively at scale.
    """
    if isinstance(schema, str): return value
    entry = f"json_entry_{depth}"
    if isinstance(schema, list):
        expected = "ARRAY"
        child = nullable_object_sql(entry, schema[0], depth + 1)
        normalized = f"to_json(list_transform(try_cast({value} AS JSON[]), {entry} -> {child}))"
    elif isinstance(schema, tuple):
        expected = "OBJECT"
        child = nullable_object_sql(f"{entry}.value", schema[1], depth + 1)
        normalized = f"""to_json(map_from_entries(list_transform(
            map_entries(try_cast({value} AS MAP(VARCHAR, JSON))),
            {entry} -> struct_pack(key := {entry}.key, value := {child}))))"""
    else:
        expected = "OBJECT"
        fields = []
        for key, child_schema in schema.items():
            child_value = f"json_extract({value}, {literal('$.' + key)})"
            fields.extend([literal(key), nullable_object_sql(child_value, child_schema, depth + 1)])
        normalized = f"json_object({','.join(fields)})"
    # Wrong container types are passed through so the strict transform rejects
    # them, rather than silently turning malformed input into empty collections.
    return f"CASE WHEN json_type({value}) = '{expected}' THEN {normalized} ELSE {value} END"


def parse_sql(value, schema):
    normalized = nullable_object_sql(f"try_cast({value} AS JSON)", schema)
    return f"try(json_transform_strict({normalized}, {literal(json.dumps(transform_schema(schema)))}))"


def stage(c):
    c.execute("""
        CREATE TABLE silver_quality_issues (
            severity VARCHAR, input_id VARCHAR, source_path VARCHAR, rule VARCHAR, detail VARCHAR
        );
        CREATE TEMP VIEW _payloads AS
        SELECT p.*, 'payload:'||p.payload_id AS input_id,
            try_cast(p.response_json AS JSON) AS body,
            coalesce(o.observed_at,try_cast(p.fetched_at AS TIMESTAMPTZ)) AS observed_at,
            split_part(p.natural_key,':',2) AS locale, p.routing_value AS version
        FROM bronze_payloads p LEFT JOIN (
            SELECT payload_id,max(try_cast(observed_at AS TIMESTAMPTZ)) AS observed_at
            FROM bronze_payload_observations GROUP BY payload_id
        ) o USING(payload_id);
        CREATE TABLE silver_transform_inputs AS
        SELECT input_id, 'bronze_payloads' AS source_table, source, dataset,
            natural_key, routing_value, payload_id, content_sha256, observed_at
        FROM _payloads
        UNION ALL
        SELECT 'match:'||source||':'||match_id,'bronze_matches',source,'match-v5.match',match_id,'',NULL,sha256(json),try_cast(fetched_at AS TIMESTAMPTZ)
        FROM bronze_matches
        UNION ALL
        SELECT 'timeline:'||source||':'||match_id,'bronze_match_timelines',source,'match-v5.timeline',match_id,'',NULL,sha256(json),try_cast(fetched_at AS TIMESTAMPTZ)
        FROM bronze_match_timelines;
        CREATE TEMP TABLE _observations AS SELECT p.payload_id,p.input_id,p.dataset,p.routing_value,
            p.natural_key,p.observed_at,p.version,p.locale,o.observation_id,
            try_cast(o.observed_at AS TIMESTAMPTZ) AS snapshot_at
        FROM _payloads p JOIN bronze_payload_observations o USING(payload_id);
    """)
    for name, keyed, dataset, schema in [('_match_candidates','bronze_matches','match-v5.match',MATCH),('_timeline_candidates','bronze_match_timelines','match-v5.timeline',TIMELINE)]:
        prefix = 'match' if keyed=='bronze_matches' else 'timeline'
        c.execute(f"""CREATE TEMP TABLE {name} AS
            SELECT *, {parse_sql('raw',schema)} AS doc FROM (
                SELECT source,match_id,json AS raw,'{prefix}:'||source||':'||match_id AS input_id,
                    try_cast(fetched_at AS TIMESTAMPTZ) AS observed_at,0 AS priority,0::BIGINT AS payload_id
                FROM {keyed}
                UNION ALL SELECT 'riot',natural_key,response_json,input_id,observed_at,1,payload_id
                FROM _payloads WHERE dataset={literal(dataset)} AND source='riot-api'
            ) QUALIFY row_number() OVER (PARTITION BY source,match_id ORDER BY observed_at DESC NULLS LAST,priority DESC,payload_id DESC)=1""")
        c.execute(f"""INSERT INTO silver_quality_issues SELECT 'error',input_id,'$',
            'invalid_document','Malformed JSON, incompatible field types, missing info, or inconsistent match identity'
            FROM {name} WHERE doc IS NULL OR doc.info IS NULL
              OR doc.metadata.matchId IS DISTINCT FROM match_id OR source NOT IN ('riot','demo')""")
    c.execute("""
        INSERT INTO silver_quality_issues
        SELECT 'error',input_id,'$.info','invalid_match','Missing participants/teams, invalid version, duration or duplicate/local keys'
        FROM _match_candidates WHERE doc IS NOT NULL AND (
            doc.info.participants IS NULL OR len(doc.info.participants)=0 OR doc.info.teams IS NULL OR len(doc.info.teams)=0
            OR NOT coalesce(regexp_matches(doc.info.gameVersion,'^\\d+\\.\\d+'),false)
            OR doc.info.gameDuration IS NULL OR doc.info.gameDuration<0
            OR EXISTS (SELECT 1 FROM unnest(doc.info.participants) u(p) WHERE p.participantId IS NULL OR p.participantId<=0 OR p.teamId IS NULL OR p.championId IS NULL OR p.championId<=0)
            OR EXISTS (SELECT 1 FROM unnest(doc.info.participants) u(p) GROUP BY p.participantId HAVING count(*)>1)
            OR EXISTS (SELECT 1 FROM unnest(doc.info.teams) u(t) GROUP BY t.teamId HAVING count(*)>1)
            OR EXISTS (SELECT 1 FROM unnest(doc.info.participants) u(p) WHERE NOT list_contains(list_transform(doc.info.teams,t->t.teamId),p.teamId))
        );
        CREATE TEMP TABLE _matches AS SELECT * FROM _match_candidates m
            WHERE NOT EXISTS (SELECT 1 FROM silver_quality_issues q WHERE q.input_id=m.input_id AND severity='error');
        CREATE TEMP TABLE _participants AS SELECT m.source,m.match_id,m.input_id,
            p AS player,p.participantId AS participant_id FROM _matches m,unnest(m.doc.info.participants) u(p);
        CREATE TEMP TABLE _teams AS SELECT m.source,m.match_id,m.input_id,t AS team FROM _matches m,unnest(m.doc.info.teams) u(t);
        CREATE TEMP TABLE _styles AS SELECT p.*,s AS style,(ordinal-1)::INTEGER AS style_slot
            FROM _participants p,unnest(p.player.perks.styles) WITH ORDINALITY u(s,ordinal);
        CREATE TEMP TABLE _selections AS SELECT p.*,s AS selection,(ordinal-1)::INTEGER AS selection_slot
            FROM _styles p,unnest(p.style.selections) WITH ORDINALITY u(s,ordinal);
        INSERT INTO silver_quality_issues SELECT 'error',input_id,'$.info.frames','missing_frames','Missing frame array'
            FROM _timeline_candidates WHERE doc IS NOT NULL AND doc.info.frames IS NULL;
        INSERT INTO silver_quality_issues SELECT 'pending',t.input_id,'$.metadata.matchId','missing_match','Timeline awaits a valid matching match'
            FROM _timeline_candidates t WHERE NOT EXISTS (SELECT 1 FROM _matches m WHERE m.source=t.source AND m.match_id=t.match_id);
        CREATE TEMP TABLE _timelines AS SELECT t.* FROM _timeline_candidates t
            WHERE NOT EXISTS (SELECT 1 FROM silver_quality_issues q WHERE q.input_id=t.input_id AND severity IN ('error','pending'));
        CREATE TEMP TABLE _frames AS SELECT t.source,t.match_id,t.input_id,f AS frame,(ordinal-1)::INTEGER AS frame_index
            FROM _timelines t,unnest(t.doc.info.frames) WITH ORDINALITY u(f,ordinal);
        CREATE TEMP TABLE _participant_frames AS SELECT f.*,entry.value AS pf
            FROM _frames f,unnest(map_entries(f.frame.participantFrames)) u(entry);
        CREATE TEMP TABLE _events AS SELECT f.source,f.match_id,f.input_id,f.frame_index,e AS event,(ordinal-1)::INTEGER AS event_index
            FROM _frames f,unnest(f.frame.events) WITH ORDINALITY u(e,ordinal);
        CREATE TEMP TABLE _event_links AS
            SELECT e.*,event.participantId AS participant_id,'actor' AS relationship FROM _events e
            UNION ALL SELECT e.*,event.killerId,'killer' FROM _events e
            UNION ALL SELECT e.*,event.victimId,'victim' FROM _events e
            UNION ALL SELECT e.*,a,'assistant' FROM _events e,unnest(event.assistingParticipantIds) u(a);
    """)

    # Static payloads contain a data object; its values are parsed once per record.
    for name, datasets, schema in [('_static_champions', ['ddragon.champion-summary','ddragon.champion-detail'],CHAMPION),('_static_items',['ddragon.items'],ITEM),('_static_spells',['ddragon.summoner-spells'],SPELL)]:
        stage_records(c,name,datasets,schema,"json_each(p.body,'$.data')",'r.value','r.key')
    stage_records(c,'_static_styles',['ddragon.runes'],STYLE,"json_each(p.body)",'r.value','r.key')
    c.execute("""CREATE TEMP TABLE _static_runes AS SELECT s.* EXCLUDE(obj),s.obj.id AS style_id,
        (ordinal-1)::INTEGER AS tree_slot,rune AS obj
        FROM _static_styles s,unnest(s.obj.slots) WITH ORDINALITY u(slot,ordinal),unnest(slot.runes) rr(rune)""")
    for name,dataset,schema,frm in [
        ('_accounts','account-v1.account',ACCOUNT,''),('_summoners','summoner-v4.summoner',SUMMONER,''),
        ('_masteries','champion-mastery-v4.masteries',MASTERY,',json_each(p.body) r'),
        ('_challenges','lol-challenges-v1.player-data',CHALLENGE,",json_each(p.body,'$.challenges') r"),
    ]:
        raw = 'r.value' if frm else 'p.body'
        puuid = 'coalesce(nullif(obj.puuid,\'\'),p.natural_key)' if 'puuid' in schema else 'p.natural_key'
        c.execute(f"""CREATE TEMP TABLE {name}_parsed AS SELECT p.payload_id,{parse_sql(raw,schema)} AS obj
            FROM _payloads p {frm} WHERE p.dataset={literal(dataset)}""")
        c.execute(f"""CREATE TEMP TABLE {name} AS SELECT p.* EXCLUDE(observed_at),p.snapshot_at AS observed_at,
            r.obj,{puuid} AS puuid FROM _observations p JOIN {name}_parsed r USING(payload_id) WHERE r.obj IS NOT NULL""")
        c.execute(f"""INSERT INTO silver_quality_issues SELECT 'error','payload:'||payload_id,'$',
            'invalid_record','Invalid typed snapshot record' FROM {name}_parsed WHERE obj IS NULL""")
    c.execute(f"""CREATE TEMP TABLE _rank_parsed AS SELECT p.payload_id,
        struct_update({parse_sql('r.value',RANK)},
            queueType:=coalesce(r.value->>'queueType',p.body->>'queue',split_part(p.natural_key,':',1)),
            tier:=coalesce(r.value->>'tier',p.body->>'tier',split_part(p.natural_key,':',2))) AS obj
        FROM _payloads p,json_each(CASE WHEN p.dataset='league-v4.apex-league' THEN p.body->'entries' ELSE p.body END) r
        WHERE p.dataset IN ('league-v4.apex-league','league-v4.entries','league-exp-v4.entries');
        CREATE TEMP TABLE _ranks AS SELECT p.* EXCLUDE(observed_at),p.snapshot_at AS observed_at,r.obj,r.obj.puuid AS puuid
            FROM _observations p JOIN _rank_parsed r USING(payload_id) WHERE nullif(r.obj.puuid,'') IS NOT NULL;
        INSERT INTO silver_quality_issues SELECT 'error','payload:'||payload_id,'$[*].puuid','missing_player_identity','Cannot attribute rank record without PUUID'
            FROM _rank_parsed WHERE nullif(obj.puuid,'') IS NULL;
    """)
    # Do not silently treat invalid payloads or wrong container shapes as empty data.
    c.execute("""INSERT INTO silver_quality_issues SELECT 'error',input_id,'$','invalid_payload','Malformed JSON or incompatible root container'
        FROM _payloads WHERE
        (dataset IN ('ddragon.champion-summary','ddragon.champion-detail','ddragon.items','ddragon.summoner-spells') AND
            (body IS NULL OR json_type(body,'$.data') IS DISTINCT FROM 'OBJECT'))
        OR (dataset IN ('ddragon.runes','league-v4.entries','league-exp-v4.entries','champion-mastery-v4.masteries','riot-static.queues','riot-static.maps') AND
            (body IS NULL OR json_type(body) IS DISTINCT FROM 'ARRAY'))
        OR (dataset IN ('account-v1.account','summoner-v4.summoner','league-v4.apex-league','lol-challenges-v1.player-data') AND
            (body IS NULL OR json_type(body) IS DISTINCT FROM 'OBJECT'));
        INSERT INTO silver_quality_issues SELECT 'error',input_id,'$','invalid_observation_time','Missing or invalid input timestamp'
            FROM silver_transform_inputs WHERE observed_at IS NULL;
    """)


def stage_records(c,name,datasets,schema,records,value,key):
    names = ','.join(literal(d) for d in datasets)
    c.execute(f"""CREATE TEMP TABLE {name}_parsed AS SELECT p.payload_id,p.input_id,p.dataset,p.version,p.locale,p.observed_at,
        {key} AS record_key,{parse_sql(value,schema)} AS obj
        FROM _payloads p,{records} r WHERE p.dataset IN ({names})""")
    c.execute(f"""INSERT INTO silver_quality_issues SELECT 'error',input_id,'$.data.*','invalid_static_record','Incompatible typed static record'
        FROM {name}_parsed WHERE obj IS NULL;
        CREATE TEMP TABLE {name} AS SELECT * FROM {name}_parsed WHERE obj IS NOT NULL""")
