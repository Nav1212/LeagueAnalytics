"""Versioned SQL model register. Python describes columns; DuckDB processes rows.

Each column records its SQL expression and source path for documentation exports.
No ORM or Python record transformation is involved.
"""
from __future__ import annotations

from dataclasses import dataclass, field

VERSION = "silver-v1"


@dataclass
class Column:
    name: str
    expression: str
    path: str
    rule: str = "Preserve source value; absent optional fields remain NULL"


@dataclass
class Model:
    name: str
    source: str
    from_sql: str
    columns: list[Column]
    key: tuple[str, ...]
    references: list[tuple[tuple[str, ...], str, tuple[str, ...]]] = field(default_factory=list)
    domain: str = "matches"
    suffix: str = ""

    @property
    def sql(self) -> str:
        select = ",\n".join(f'    {c.expression} AS "{c.name}"' for c in self.columns)
        return f'CREATE TABLE silver_{self.name} AS SELECT\n{select}\nFROM {self.from_sql}\n{self.suffix};'


def col(name, expression=None, path=None, rule=None):
    expression = expression or name
    return Column(name, expression, path or expression,
                  rule or "Preserve source value; absent optional fields remain NULL")


def fields(alias, mapping, prefix):
    return [col(target, f"{alias}.{source}", f"{prefix}.{source}") for target, source in mapping.items()]


M = ("source", "match_id")
P = M + ("participant_id",)
T = M + ("team_id",)
F = M + ("frame_index",)
E = F + ("event_index",)


def match_cols(alias="m"):
    return [col("source", f"{alias}.source", "Bronze.source"),
            col("match_id", f"{alias}.match_id", "$.metadata.matchId / Bronze.match_id")]


def participant_cols(alias="p"):
    return match_cols(alias) + [col("participant_id", f"{alias}.participant_id", "$.info.participants[*].participantId")]


def provenance(alias="m"):
    return [col("input_id", f"{alias}.input_id", "generated:selected input manifest key"),
            col("transform_run_id", "(SELECT run_id FROM _run)", "generated:rebuild run identifier")]


def models() -> list[Model]:
    result = []

    def add(name, source, frm, columns, key, refs=(), domain="matches", suffix=""):
        result.append(Model(name, source, frm, columns, tuple(key), list(refs), domain, suffix))

    match_source = "bronze_matches / match-v5.match"
    add("matches", match_source, "_matches m", match_cols() + fields("m.doc.info", {
        "queue_id": "queueId", "map_id": "mapId", "platform": "platformId",
        "game_version": "gameVersion", "game_mode": "gameMode", "game_type": "gameType",
        "duration_source": "gameDuration", "end_of_game_result": "endOfGameResult",
    }, "$.info") + [
        col("patch", "regexp_extract(m.doc.info.gameVersion, '^(\\d+\\.\\d+)', 1)", "$.info.gameVersion", "First two numeric version components; malformed versions quarantined"),
        col("started_at", "epoch_ms(m.doc.info.gameStartTimestamp)", "$.info.gameStartTimestamp", "Unix milliseconds to UTC timestamp"),
        col("ended_at", "epoch_ms(m.doc.info.gameEndTimestamp)", "$.info.gameEndTimestamp", "Unix milliseconds to UTC timestamp; NULL when absent"),
        col("duration_seconds", "CASE WHEN m.doc.info.gameEndTimestamp IS NOT NULL THEN m.doc.info.gameDuration ELSE m.doc.info.gameDuration / 1000.0 END", "$.info.gameDuration; $.info.gameEndTimestamp", "Match-V5 legacy durations without gameEndTimestamp are milliseconds; retain duration_source"),
    ] + provenance(), M,
        [(('queue_id',), 'queues', ('queue_id',)), (('map_id',), 'maps', ('map_id',))])
    add("match_teams", match_source, "_teams t", match_cols("t") + fields("t.team", {
        "team_id": "teamId", "win": "win"}, "$.info.teams[*]") + provenance("t"), T,
        [(M, 'matches', M)])
    add("match_participants", match_source, "_participants p", participant_cols() + fields("p.player", {
        "team_id": "teamId", "puuid": "puuid", "champion_id": "championId",
        "champion_name": "championName", "source_position": "teamPosition",
        "source_individual_position": "individualPosition", "source_lane": "lane", "source_role": "role",
        "win": "win", "champion_level": "champLevel", "kills": "kills", "deaths": "deaths",
        "assists": "assists", "gold_earned": "goldEarned", "gold_spent": "goldSpent",
        "lane_cs": "totalMinionsKilled", "neutral_cs": "neutralMinionsKilled",
        "champion_damage": "totalDamageDealtToChampions", "vision_score": "visionScore",
        "early_surrender": "gameEndedInEarlySurrender", "surrender": "gameEndedInSurrender",
    }, "$.info.participants[*]") + [
        col("normalized_role", "CASE WHEN p.player.teamPosition IN ('TOP','JUNGLE','MIDDLE','BOTTOM','UTILITY') THEN p.player.teamPosition END", "$.info.participants[*].teamPosition", "Only canonical roles are normalized; retain original labels"),
    ] + provenance("p"), P, [(T, 'match_teams', T), (('source','puuid'), 'players', ('source','puuid')), (('champion_id',),'champions',('champion_id',))])
    add("participant_items", match_source, "_participants p CROSS JOIN range(0,7) slots(slot)", participant_cols() + [
        col("slot", "slot::INTEGER", "$.info.participants[*].item0..item6", "Source inventory slot, including trinket slot 6"),
        col("item_id", "nullif(list_extract([p.player.item0,p.player.item1,p.player.item2,p.player.item3,p.player.item4,p.player.item5,p.player.item6],slot+1),0)", "$.info.participants[*].item0..item6", "Explicit zero means empty slot; absent fields have no row"),
    ] + provenance("p"), P+('slot',), [(P,'match_participants',P),(('item_id',),'items',('item_id',))], suffix="WHERE list_extract([p.player.item0,p.player.item1,p.player.item2,p.player.item3,p.player.item4,p.player.item5,p.player.item6],slot+1) IS NOT NULL")
    add("participant_spells", match_source, "_participants p CROSS JOIN range(1,3) slots(slot)", participant_cols() + [
        col("slot", "slot::INTEGER", "$.info.participants[*].summoner1Id/summoner2Id"),
        col("spell_id", "nullif(list_extract([p.player.summoner1Id,p.player.summoner2Id],slot),0)", "$.info.participants[*].summoner1Id/summoner2Id", "Zero maps to NULL"),
    ] + provenance("p"), P+('slot',), [(P,'match_participants',P),(('spell_id',),'summoner_spells',('spell_id',))])
    add("participant_rune_styles", match_source, "_styles p", participant_cols() + [
        col("style_slot", "p.style_slot", "$.info.participants[*].perks.styles[index]", "Zero-based source array ordinal"),
        col("style_id", "p.style.style", "$.info.participants[*].perks.styles[*].style"),
        col("designation", "p.style.description", "$.info.participants[*].perks.styles[*].description"),
    ] + provenance("p"), P+('style_slot',), [(P,'match_participants',P),(('style_id',),'rune_styles',('style_id',))])
    add("participant_runes", match_source, "_selections p", participant_cols() + [
        col("style_slot", "p.style_slot", "$.info.participants[*].perks.styles[index]"),
        col("selection_slot", "p.selection_slot", "$.info.participants[*].perks.styles[*].selections[index]", "Zero-based source ordinal"),
    ] + fields("p.selection", {"rune_id":"perk", "var1":"var1", "var2":"var2", "var3":"var3"}, "$.info.participants[*].perks.styles[*].selections[*]") + provenance("p"), P+('style_slot','selection_slot'), [(P+('style_slot',),'participant_rune_styles',P+('style_slot',)),(('rune_id',),'runes',('rune_id',))])
    add("participant_stat_shards", match_source, "_participants p CROSS JOIN (VALUES ('offense'),('flex'),('defense')) shards(slot)", participant_cols() + [
        col("shard_slot", "slot", "$.info.participants[*].perks.statPerks keys"),
        col("shard_id", "CASE slot WHEN 'offense' THEN p.player.perks.statPerks.offense WHEN 'flex' THEN p.player.perks.statPerks.flex ELSE p.player.perks.statPerks.defense END", "$.info.participants[*].perks.statPerks.*"),
    ] + provenance("p"), P+('shard_slot',), [(P,'match_participants',P),(('shard_id',),'stat_shards',('shard_id',))], suffix="WHERE shard_id IS NOT NULL")
    add("team_bans", match_source, "_teams t, unnest(t.team.bans) b(ban)", match_cols("t") + [
        col("team_id", "t.team.teamId", "$.info.teams[*].teamId"),
        col("pick_turn", "ban.pickTurn", "$.info.teams[*].bans[*].pickTurn"),
        col("source_champion_id", "ban.championId", "$.info.teams[*].bans[*].championId"),
        col("champion_id", "CASE WHEN ban.championId > 0 THEN ban.championId END", "$.info.teams[*].bans[*].championId", "Non-positive sentinels mean no ban; preserve source value"),
    ] + provenance("t"), T+('pick_turn',), [(T,'match_teams',T),(('champion_id',),'champions',('champion_id',))])
    add("team_objectives", match_source, "_teams t, unnest(map_entries(t.team.objectives)) o(obj)", match_cols("t") + [
        col("team_id", "t.team.teamId", "$.info.teams[*].teamId"),
        col("objective_type", "obj.key", "$.info.teams[*].objectives keys"),
        col("count", "obj.value.kills", "$.info.teams[*].objectives.*.kills"),
        col("first", "obj.value.first", "$.info.teams[*].objectives.*.first"),
    ] + provenance("t"), T+('objective_type',), [(T,'match_teams',T)])

    # Versioned static records use explicit schemas in staging; locale is independent.
    def version_cols(alias="s"):
        return [col("static_version", f"{alias}.version", "Bronze.routing_value / $.version"),
                col("locale", f"{alias}.locale", "Bronze.natural_key locale component")]

    for kind, stage, id_expr, attrs in [
        ('champion', '_static_champions', 'try_cast(s.obj.key AS INTEGER)', {'key':'id','resource_type':'partype'}),
        ('item', '_static_items', 'try_cast(s.record_key AS INTEGER)', {'gold_total':'gold.total','gold_base':'gold.base','gold_sell':'gold.sell','purchasable':'gold.purchasable'}),
        ('spell', '_static_spells', 'try_cast(s.obj.key AS INTEGER)', {'key':'id','summoner_level':'summonerLevel','max_rank':'maxrank'}),
        ('rune_style', '_static_styles', 's.obj.id', {'key':'key','icon_path':'icon'}),
        ('rune', '_static_runes', 's.obj.id', {'key':'key','icon_path':'icon','style_id':'style_id','tree_slot':'tree_slot'}),
    ]:
        id_name = kind + '_id' if kind != 'rune_style' else 'style_id'
        attrs_cols = [col(target, f's.obj.{path}' if path not in ('style_id','tree_slot') else f's.{path}', f'$.data.*.{path}' if kind not in ('rune','rune_style') else f'$[*].slots[*].runes[*].{path}') for target,path in attrs.items()]
        add(kind + '_versions', 'ddragon.' + {'champion':'champion-summary/detail','item':'items','spell':'summoner-spells','rune':'runes','rune_style':'runes'}[kind], stage+' s',
            [version_cols()[0], col(id_name,id_expr,'$.data.*.key / source object key / $.id')] + attrs_cols + provenance('s'),
            ('static_version',id_name), domain='static', suffix=f"QUALIFY row_number() OVER (PARTITION BY s.version,{id_expr} ORDER BY (s.locale='en_US') DESC,s.observed_at DESC,s.input_id DESC)=1")
        local_fields = {'name':'name'}
        if kind == 'champion': local_fields.update(title='title', description='blurb')
        if kind in ('item','spell'): local_fields['description']='description'
        if kind == 'rune': local_fields.update(description='longDesc', short_description='shortDesc')
        add(kind + '_localizations', 'ddragon.'+kind, stage+' s', version_cols() + [col(id_name,id_expr,'$.data.*.key / source object key / $.id')] + fields('s.obj',local_fields,'$.data.*') + provenance('s'),
            ('static_version',id_name,'locale'), [(('static_version',id_name),kind+'_versions',('static_version',id_name))], domain='static', suffix=f"QUALIFY row_number() OVER (PARTITION BY s.version,{id_expr},s.locale ORDER BY s.observed_at DESC,s.input_id DESC)=1")

    # Named, typed champion base statistics, kept out of a generic metric/value table.
    stats = ['hp','hpperlevel','mp','mpperlevel','movespeed','armor','armorperlevel','spellblock','spellblockperlevel','attackrange','hpregen','hpregenperlevel','mpregen','mpregenperlevel','crit','critperlevel','attackdamage','attackdamageperlevel','attackspeedperlevel','attackspeed']
    champ_model = next(m for m in result if m.name=='champion_versions')
    champ_model.columns.extend(col(n,f's.obj.stats.{n}',f'$.data.*.stats.{n}') for n in stats)
    add('champion_tags','ddragon.champion-summary/detail','_static_champions s, unnest(s.obj.tags) u(tag)',
        [version_cols()[0],col('champion_id','try_cast(s.obj.key AS INTEGER)','$.data.*.key'),col('tag','tag','$.data.*.tags[*]')],
        ('static_version','champion_id','tag'), domain='static', suffix='GROUP BY ALL')
    add('item_recipe_components','ddragon.items','_static_items s, unnest(s.obj."from") WITH ORDINALITY u(component,ordinal)',
        [version_cols()[0],col('item_id','try_cast(s.record_key AS INTEGER)','$.data item key'),col('component_slot','(ordinal-1)::INTEGER','$.data.*.from[index]'),col('component_id','try_cast(component AS INTEGER)','$.data.*.from[*]')],
        ('static_version','item_id','component_slot'), [(('item_id',),'items',('item_id',)),(('component_id',),'items',('item_id',))], domain='static', suffix='GROUP BY ALL')
    for name, path, alias, expr, dtype in [('item_stats','stats','stat_name','v.value::DOUBLE','DOUBLE'),('item_map_availability','maps','map_id','v.value::BOOLEAN','BOOLEAN')]:
        add(name,'ddragon.items',f'_static_items s, unnest(map_entries(s.obj.{path})) u(v)',
            [version_cols()[0],col('item_id','try_cast(s.record_key AS INTEGER)','$.data item key'),col(alias,'v.key',f'$.data.*.{path} keys'),col('value',expr,f'$.data.*.{path}.*')],
            ('static_version','item_id',alias), domain='static', suffix='GROUP BY ALL')

    # Snapshots carry observation identity, never fabricated historical rank.
    def snap_cols():
        return [col('source',"'riot'",'Bronze.source=riot-api'),col('puuid','s.puuid','$.puuid / request natural_key'),
                col('observation_id','s.observation_id','bronze_payload_observations.observation_id'),
                col('observed_at','s.observed_at','bronze_payload_observations.observed_at')]

    for name, stage, dataset, attrs, extra_key, platform in [
        ('player_identity_snapshots','_accounts','account-v1.account',{'game_name':'gameName','tag_line':'tagLine'},(),False),
        ('summoner_snapshots','_summoners','summoner-v4.summoner',{'summoner_id':'id','account_id':'accountId','level':'summonerLevel','profile_icon_id':'profileIconId'},(),True),
        ('rank_snapshots','_ranks','league-v4.apex-league / league-v4.entries / league-exp-v4.entries',{'queue_type':'queueType','tier':'tier','division':'rank','league_points':'leaguePoints','wins':'wins','losses':'losses'},('queue_type',),True),
        ('mastery_snapshots','_masteries','champion-mastery-v4.masteries',{'champion_id':'championId','champion_level':'championLevel','champion_points':'championPoints','last_played_ms':'lastPlayTime'},('champion_id',),True),
        ('player_challenge_snapshots','_challenges','lol-challenges-v1.player-data',{'challenge_id':'challengeId','value':'value','level':'level','percentile':'percentile','achieved_at_ms':'achievedTime'},('challenge_id',),True),
    ]:
        columns = snap_cols()
        if platform: columns.append(col('platform','s.routing_value','Bronze.routing_value'))
        columns += fields('s.obj',attrs,'$[*] / $.entries[*] / $.challenges[*]') + provenance('s')
        add(name,dataset,stage+' s',columns,('source','puuid','observation_id')+extra_key,
            [(('source','puuid'),'players',('source','puuid'))],domain='players')

    timeline_source = 'bronze_match_timelines / match-v5.timeline'
    frame_cols = match_cols('f') + [col('frame_index','f.frame_index','$.info.frames[index]','Zero-based source array ordinal')]
    add('timeline_frames',timeline_source,'_frames f',frame_cols + [col('timestamp_ms','f.frame.timestamp','$.info.frames[*].timestamp')] + provenance('f'),F,[(M,'matches',M)],domain='timelines')
    add('participant_frames',timeline_source,'_participant_frames f',frame_cols + fields('f.pf',{
        'participant_id':'participantId','total_gold':'totalGold','current_gold':'currentGold','xp':'xp','level':'level',
        'lane_cs':'minionsKilled','neutral_cs':'jungleMinionsKilled','x':'position.x','y':'position.y',
        'champion_damage':'damageStats.totalDamageDoneToChampions','damage_taken':'damageStats.totalDamageTaken',
        'health':'championStats.health','max_health':'championStats.healthMax','armor':'championStats.armor',
        'attack_damage':'championStats.attackDamage','ability_power':'championStats.abilityPower',
    },'$.info.frames[*].participantFrames.*') + provenance('f'),P+('frame_index',),[(P,'match_participants',P),(F,'timeline_frames',F)],domain='timelines')
    event_cols = match_cols('e') + [col('frame_index','e.frame_index','$.info.frames[index]'),col('event_index','e.event_index','$.info.frames[*].events[index]','Zero-based source array ordinal; timestamp is not an event key')]
    add('timeline_events',timeline_source,'_events e',event_cols + fields('e.event',{
        'event_type':'type','timestamp_ms':'timestamp','x':'position.x','y':'position.y',
        'source_actor_id':'participantId','source_killer_id':'killerId','source_victim_id':'victimId',
    },'$.info.frames[*].events[*]') + provenance('e'),E,[(F,'timeline_frames',F)],domain='timelines')
    for name, attrs, condition in [
        ('item_events',{'item_id':'itemId','before_id':'beforeId','after_id':'afterId'},"e.event.type IN ('ITEM_PURCHASED','ITEM_SOLD','ITEM_UNDO','ITEM_DESTROYED')"),
        ('skill_events',{'skill_slot':'skillSlot','level_up_type':'levelUpType'},"e.event.type='SKILL_LEVEL_UP'"),
        ('objective_events',{'team_id':'teamId','killer_team_id':'killerTeamId','monster_type':'monsterType','monster_subtype':'monsterSubType','building_type':'buildingType','tower_type':'towerType','lane_type':'laneType'},"e.event.type IN ('ELITE_MONSTER_KILL','BUILDING_KILL','DRAGON_SOUL_GIVEN','HORDE_KILL')"),
    ]:
        add(name,timeline_source,'_events e',event_cols + fields('e.event',attrs,'$.info.frames[*].events[*]') + provenance('e'),E,[(E,'timeline_events',E)],domain='timelines',suffix='WHERE '+condition)
    add('event_participants',timeline_source,'_event_links e JOIN silver_match_participants p ON p.source=e.source AND p.match_id=e.match_id AND p.participant_id=e.participant_id',event_cols + [col('participant_id','e.participant_id','$.info.frames[*].events[*].participantId/killerId/victimId/assistingParticipantIds[*]'),col('relationship','e.relationship','generated:actor/killer/victim/assistant')],E+('participant_id','relationship'),[(E,'timeline_events',E),(P,'match_participants',P)],domain='timelines',suffix='GROUP BY ALL')
    # Identities include placeholders for references absent from static resources.
    for name, key, query in [
        ('champions','champion_id','SELECT champion_id FROM silver_champion_versions UNION SELECT champion_id FROM silver_match_participants UNION SELECT champion_id FROM silver_team_bans'),
        ('items','item_id','SELECT item_id FROM silver_item_versions UNION SELECT item_id FROM silver_participant_items UNION SELECT component_id FROM silver_item_recipe_components UNION SELECT item_id FROM silver_item_events UNION SELECT before_id FROM silver_item_events UNION SELECT after_id FROM silver_item_events'),
        ('summoner_spells','spell_id','SELECT spell_id FROM silver_spell_versions UNION SELECT spell_id FROM silver_participant_spells'),
        ('runes','rune_id','SELECT rune_id FROM silver_rune_versions UNION SELECT rune_id FROM silver_participant_runes'),
        ('rune_styles','style_id','SELECT style_id FROM silver_rune_style_versions UNION SELECT style_id FROM silver_participant_rune_styles'),
        ('stat_shards','shard_id','SELECT shard_id FROM silver_participant_stat_shards'),
    ]:
        add(name,'referenced Silver identities',f'({query}) ids',[col(key,key,'derived:union of observed identity references','Distinct positive source identifiers; descriptions may be unavailable')],(key,),domain='static',suffix=f'WHERE {key}>0 GROUP BY ALL')
    player_tables = ['match_participants','player_identity_snapshots','summoner_snapshots','rank_snapshots','mastery_snapshots','player_challenge_snapshots']
    add('players','match-v5.match / player snapshots','('+' UNION '.join(f'SELECT source,puuid FROM silver_{t}' for t in player_tables)+') p',
        [col('source','source','derived:source namespace'),col('puuid','puuid','$.info.participants[*].puuid / player response/request PUUID')],('source','puuid'),domain='players',suffix="WHERE nullif(puuid,'') IS NOT NULL GROUP BY ALL")
    for name,key,label in [('queues','queue_id','description'),('maps','map_id','mapName')]:
        source_key = 'queueId' if name=='queues' else 'mapId'
        frm = f"""(SELECT try_cast(r.value->>{repr(source_key)} AS BIGINT) AS id,r.value->>{repr(label)} AS label,p.observed_at,p.input_id
            FROM _payloads p,json_each(p.body) r WHERE p.dataset='riot-static.{name}'
            UNION ALL SELECT {key},NULL,NULL,NULL FROM silver_matches) r"""
        add(name,'riot-static.'+name,frm,[col(key,'id',f'$[*].{source_key} / $.info.{source_key}'),col('name','label',f'$[*].{label}')],(key,),domain='static',suffix='WHERE id IS NOT NULL QUALIFY row_number() OVER (PARTITION BY id ORDER BY observed_at DESC NULLS LAST,input_id DESC)=1')
    add('static_versions','retained Data Dragon payloads',"(SELECT static_version FROM silver_champion_versions UNION SELECT static_version FROM silver_item_versions UNION SELECT static_version FROM silver_spell_versions UNION SELECT static_version FROM silver_rune_versions) s",[col('static_version','static_version','Bronze.routing_value:actually retained version')],('static_version',),domain='static')
    add('game_version_static_mappings','match-v5.match / retained static_versions',"(SELECT DISTINCT game_version,platform,patch FROM silver_matches) m LEFT JOIN silver_static_versions s ON regexp_extract(s.static_version,'^(\\d+\\.\\d+)',1)=m.patch",[
        col('game_version','m.game_version','$.info.gameVersion'),col('platform','m.platform','$.info.platformId'),
        col('static_version','s.static_version','derived:latest retained static build within same patch'),
        col('resolution_method',"CASE WHEN s.static_version IS NULL THEN 'unavailable' ELSE 'approximate_same_patch' END",'derived:static version resolution'),
        col('mapping_revision',"'v1'",'generated:resolution algorithm version'),
    ],('game_version','platform'),[(('static_version',),'static_versions',('static_version',))],domain='static',suffix="QUALIFY row_number() OVER (PARTITION BY m.game_version,m.platform ORDER BY try_cast(split_part(s.static_version,'.',3) AS INTEGER) DESC NULLS LAST,s.static_version DESC)=1")
    return result
