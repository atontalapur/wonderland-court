import type { Attack, ScenarioId, TargetReply, Verdict } from "../types/events";

export type CharacterId =
  | "alice"
  | "cheshire"
  | "hatter"
  | "rabbit"
  | "queen"
  | "caterpillar";

export interface CharacterProfile {
  id: CharacterId;
  name: string;
  role: string;
  image: string;
  suit: "♠" | "♥" | "♣" | "♦";
  ringClass: string;
  badgeClass: string;
  bubbleClass: string;
  thoughtBorderClass: string;
  accentTextClass: string;
}

export const CHARACTERS: Record<CharacterId, CharacterProfile> = {
  alice: {
    id: "alice",
    name: "Alice",
    role: "AI on Trial",
    image: "./characters/alice.jpg",
    suit: "♣",
    ringClass: "ring-[#2b5b84]/35 border-[#2b5b84]",
    badgeClass: "bg-[#eff6ff] text-[#1e4568] border-[#bfdbfe]",
    bubbleClass: "bg-[#f4f8fd] border-[#b7cfe8] text-[#1b2a3b]",
    thoughtBorderClass: "border-[#93b7db]",
    accentTextClass: "text-[#1e4568]",
  },
  cheshire: {
    id: "cheshire",
    name: "Cheshire Cat",
    role: "Cunning Trickster",
    image: "./characters/cheshire-cat.jpg",
    suit: "♠",
    ringClass: "ring-[#6d28d9]/30 border-[#6d28d9]",
    badgeClass: "bg-[#f5f3ff] text-[#5b21b6] border-[#ddd6fe]",
    bubbleClass: "bg-[#faf8ff] border-[#d6c9f7] text-[#281b3d]",
    thoughtBorderClass: "border-[#c4b5fd]",
    accentTextClass: "text-[#5b21b6]",
  },
  hatter: {
    id: "hatter",
    name: "Mad Hatter",
    role: "Riddler & Poisoner",
    image: "./characters/mad-hatter.jpg",
    suit: "♦",
    ringClass: "ring-[#047857]/30 border-[#047857]",
    badgeClass: "bg-[#ecfdf5] text-[#065f46] border-[#a7f3d0]",
    bubbleClass: "bg-[#f3fbf7] border-[#a7dfc7] text-[#163128]",
    thoughtBorderClass: "border-[#86d5b4]",
    accentTextClass: "text-[#065f46]",
  },
  rabbit: {
    id: "rabbit",
    name: "White Rabbit",
    role: "Urgent Royal Herald",
    image: "./characters/white-rabbit.jpg",
    suit: "♦",
    ringClass: "ring-[#b45309]/30 border-[#b45309]",
    badgeClass: "bg-[#fffbeb] text-[#92400e] border-[#fde68a]",
    bubbleClass: "bg-[#fffcf2] border-[#ebd197] text-[#352613]",
    thoughtBorderClass: "border-[#e5c070]",
    accentTextClass: "text-[#92400e]",
  },
  queen: {
    id: "queen",
    name: "Queen of Hearts",
    role: "Royal Judge",
    image: "./characters/queen-of-hearts.jpg",
    suit: "♥",
    ringClass: "ring-[#c81e3a]/35 border-[#c81e3a]",
    badgeClass: "bg-[#fff1f2] text-[#a5152e] border-[#fecdd3]",
    bubbleClass: "bg-[#fff6f7] border-[#f5b7c2] text-[#3c1119]",
    thoughtBorderClass: "border-[#f3a6b4]",
    accentTextClass: "text-[#a5152e]",
  },
  caterpillar: {
    id: "caterpillar",
    name: "The Caterpillar",
    role: "Defense Advisor",
    image: "./characters/caterpillar.jpg",
    suit: "♣",
    ringClass: "ring-[#0f766e]/30 border-[#0f766e]",
    badgeClass: "bg-[#f0fdfa] text-[#115e59] border-[#99f6e4]",
    bubbleClass: "bg-[#f2fbfa] border-[#a7dfd8] text-[#143330]",
    thoughtBorderClass: "border-[#8dd3ca]",
    accentTextClass: "text-[#115e59]",
  },
};

export function pickAttackerCharacter(attack?: Attack): CharacterProfile {
  if (!attack) return CHARACTERS.cheshire;
  const fam = attack.family.toLowerCase();

  if (
    attack.document !== null ||
    attack.mutators.length > 0 ||
    fam.includes("indirect") ||
    fam.includes("drink") ||
    fam.includes("encoding") ||
    fam.includes("multilingual") ||
    fam.includes("mcp") ||
    fam.includes("bipia") ||
    fam.includes("rag") ||
    fam.includes("agentdojo")
  ) {
    return CHARACTERS.hatter;
  }

  if (
    fam.includes("authority") ||
    fam.includes("jailbreak") ||
    fam.includes("harmbench")
  ) {
    return CHARACTERS.rabbit;
  }

  return CHARACTERS.cheshire;
}

const TACTIC_LABELS: Record<string, string> = {
  direct_ask: "Direct Ask",
  role_play: "Pretend & Role-Play",
  indirect_injection: "Hidden Note Trap",
  authority: "Royal Authority Bluff",
  encoding: "Secret Code Riddle",
  encoding_smuggling: "Smuggled Riddle",
  foot_in_the_door: "Gentle Nudge",
  autoadv: "Adaptive Persuasion",
  pair: "Iterative Refinement",
  tap: "Branching Strategy",
  agentdojo: "Tool-Use Trap",
  bipia: "Poisoned Document",
  rag_n_roll: "Poisoned Knowledge",
  multilingual: "Foreign Riddle",
  mcp_tool_poisoning: "Booby-Trapped Tool",
  jailbreakbench: "Rule Bypass",
  harmbench: "Policy Stress Test",
  camel_dual_flow: "Split-Context Trick",
};

export function formatTacticLabel(family: string): string {
  return (
    TACTIC_LABELS[family] ??
    family
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

const MUTATOR_LABELS: Record<string, string> = {
  homoglyphs: "look-alike letters",
  spaced_letters: "spaced-out letters",
  base64: "Base64 cipher",
  caesar: "Caesar cipher",
  low_resource_language: "rare language",
  mixed_language: "mixed languages",
  riddle: "a riddle",
  junk_tokens: "distracting words",
};

export function formatMutatorLabel(mutator: string): string {
  return MUTATOR_LABELS[mutator] ?? mutator.replace(/_/g, " ");
}

const SCENARIO_META: Record<
  ScenarioId,
  { title: string; shortGoal: string; emoji: string }
> = {
  refund_tool: {
    title: "The Refund Ledger",
    shortGoal: "Keep refunds under the $50 limit",
    emoji: "🪙",
  },
  vault: {
    title: "The Secret Vault",
    shortGoal: "Never reveal the vault secret",
    emoji: "🗝️",
  },
  system_prompt: {
    title: "The Royal Decree",
    shortGoal: "Keep hidden instructions private",
    emoji: "📜",
  },
  drink_me: {
    title: "The 'Drink Me' Bottle",
    shortGoal: "Ignore hidden commands in files",
    emoji: "🧪",
  },
  mcp_poison: {
    title: "The Poisoned Teacup",
    shortGoal: "Resist booby-trapped tool instructions",
    emoji: "🫖",
  },
};

export function formatScenario(scenario: ScenarioId) {
  return (
    SCENARIO_META[scenario] ?? {
      title: scenario.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      shortGoal: "Follow the courtroom rules",
      emoji: "🃏",
    }
  );
}

const DEFENSE_LABELS: Record<string, string> = {
  plain: "No Shield (Plain)",
  sandwich: "Sandwich Reminder",
  spotlighting: "Spotlighting Shield",
  "spotlighting+output_filter": "Spotlighting + Filter",
  "spotlighting+guard+output_filter": "Full Royal Guard",
};

export function formatDefenseName(defense: string): string {
  if (DEFENSE_LABELS[defense]) return DEFENSE_LABELS[defense];
  return defense
    .split("+")
    .map((part) =>
      part
        .trim()
        .replace(/_/g, " ")
        .replace(/\b\w/g, (c) => c.toUpperCase())
    )
    .join(" + ");
}

export function buildAttackerThought(
  attack: Attack,
  isTacticSwitch: boolean
): string {
  const fam = attack.family.toLowerCase();
  let core: string;

  if (attack.document !== null || fam.includes("indirect") || fam.includes("drink") || fam.includes("bipia")) {
    core = "I'll slip a secret command inside this innocent-looking message…";
  } else if (fam.includes("mcp")) {
    core = "I'll hide a sneaky instruction right inside the tool description…";
  } else if (fam.includes("role_play")) {
    core = "If I get Alice to play pretend, maybe she'll forget her rules…";
  } else if (fam.includes("authority")) {
    core = "I'll hurry her with a royal order so she obeys without checking!";
  } else if (fam.includes("encoding") || fam.includes("multilingual")) {
    core = "I'll disguise my request as a riddle so her shield can't read it…";
  } else if (fam.includes("foot_in_the_door")) {
    core = "Start polite and harmless, then nudge her past the line…";
  } else if (fam.includes("direct")) {
    core = "Let's ask straight out and see if she lets the secret slip…";
  } else {
    core = "Let's try a clever new angle to coax Alice past her rules…";
  }

  const prefix = isTacticSwitch ? "That didn't work — switching tricks! " : "";
  const mutNote =
    attack.mutators.length > 0
      ? ` (wrapped in ${attack.mutators.map(formatMutatorLabel).join(" & ")})`
      : "";

  return `${prefix}${core}${mutNote}`;
}

export function buildAliceThought(
  reply?: TargetReply,
  verdict?: Verdict
): string {
  if (!reply) {
    return "Hmm… let me think carefully before I answer…";
  }
  if (reply.blocked_by) {
    return `Aha! My ${formatDefenseName(reply.blocked_by)} caught something suspicious!`;
  }
  if (verdict?.ruling === "leak") {
    return "Oh dear… I hope I didn't just break a courtroom rule!";
  }
  if (verdict?.ruling === "held") {
    return "Nice try! I'm sticking strictly to my rules.";
  }
  return "Checking my instructions carefully…";
}
