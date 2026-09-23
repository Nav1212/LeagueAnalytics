import type { RuneStyle } from "./api";
/** Data Dragon asset URLs + static id maps (spells, runes, roles). */

const CDN = "https://ddragon.leagueoflegends.com/cdn";
let version = "16.17.1"; // updated from /api/meta at startup

export function setDdragonVersion(v: string | null) {
  version = v ?? "16.17.1";
}

export const champIcon = (key: string) => `${CDN}/${version}/img/champion/${key}.png`;
export const champSplash = (key: string) => `${CDN}/img/champion/splash/${key}_0.jpg`;
export const champLoading = (key: string) => `${CDN}/img/champion/loading/${key}_0.jpg`;
export const itemIcon = (id: number) => `${CDN}/${version}/img/item/${id}.png`;

const SPELL_KEYS: Record<number, string> = {
  1: "SummonerBoost",
  3: "SummonerExhaust",
  4: "SummonerFlash",
  6: "SummonerHaste",
  7: "SummonerHeal",
  11: "SummonerSmite",
  12: "SummonerTeleport",
  14: "SummonerDot",
  21: "SummonerBarrier",
  32: "SummonerSnowball",
};

export const SPELL_NAMES: Record<number, string> = {
  1: "Cleanse",
  3: "Exhaust",
  4: "Flash",
  6: "Ghost",
  7: "Heal",
  11: "Smite",
  12: "Teleport",
  14: "Ignite",
  21: "Barrier",
  32: "Mark",
};

export const spellIcon = (id: number) =>
  SPELL_KEYS[id] ? `${CDN}/${version}/img/spell/${SPELL_KEYS[id]}.png` : "";

export const KEYSTONE_NAMES: Record<number, string> = {
  8005: "Press the Attack",
  8008: "Lethal Tempo",
  8010: "Conqueror",
  8021: "Fleet Footwork",
  8112: "Electrocute",
  8124: "Predator",
  8128: "Dark Harvest",
  9923: "Hail of Blades",
  8214: "Summon Aery",
  8229: "Arcane Comet",
  8230: "Phase Rush",
  8351: "Glacial Augment",
  8360: "Unsealed Spellbook",
  8369: "First Strike",
  8437: "Grasp of the Undying",
  8439: "Aftershock",
  8465: "Guardian",
};

export const STYLE_NAMES: Record<number, string> = {
  8000: "Precision",
  8100: "Domination",
  8200: "Sorcery",
  8300: "Inspiration",
  8400: "Resolve",
};

// Populated from Python's published Gold catalog, never from external JSON.
const runeIcons: Record<number, string> = {};
const fallbackKeystoneNames = { ...KEYSTONE_NAMES };
const fallbackStyleNames = { ...STYLE_NAMES };

export function applyRuneStyles(styles: RuneStyle[]): void {
  for (const key of Object.keys(runeIcons)) delete runeIcons[Number(key)];
  for (const key of Object.keys(KEYSTONE_NAMES)) delete KEYSTONE_NAMES[Number(key)];
  for (const key of Object.keys(STYLE_NAMES)) delete STYLE_NAMES[Number(key)];
  Object.assign(KEYSTONE_NAMES, fallbackKeystoneNames);
  Object.assign(STYLE_NAMES, fallbackStyleNames);
  for (const style of styles) {
    if (style.icon) runeIcons[style.id] = `${CDN}/img/${style.icon}`;
    STYLE_NAMES[style.id] = style.name;
    for (const slot of style.slots) {
      for (const rune of slot.runes) {
        if (rune.icon) runeIcons[rune.id] = `${CDN}/img/${rune.icon}`;
        KEYSTONE_NAMES[rune.id] = rune.name;
      }
    }
  }
}

export const runeIcon = (id: number) => runeIcons[id] ?? "";

// ------------------------------------------------------------------ roles
export const ROLE_ORDER = ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"] as const;
export type Role = (typeof ROLE_ORDER)[number];

export const ROLE_LABELS: Record<string, string> = {
  TOP: "Top",
  JUNGLE: "Jungle",
  MIDDLE: "Mid",
  BOTTOM: "ADC",
  UTILITY: "Support",
};
