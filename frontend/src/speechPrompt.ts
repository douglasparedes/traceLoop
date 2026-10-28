// Extract a segmentable object phrase from expert narration.
// Matches things like: "this is my flag", "here is the blue knob",
// "I'm showing the cable harness", "look at the latch".
const PATTERNS: RegExp[] = [
  /\bthis is (?:my |the |a |an )?([a-z][a-z\- ]{1,40})/i,
  /\bhere is (?:my |the |a |an )?([a-z][a-z\- ]{1,40})/i,
  /\bhere'?s (?:my |the |a |an )?([a-z][a-z\- ]{1,40})/i,
  /\bi(?:'m| am) showing (?:you )?(?:my |the |a |an )?([a-z][a-z\- ]{1,40})/i,
  /\bshowing (?:you )?(?:my |the |a |an )?([a-z][a-z\- ]{1,40})/i,
  /\blook at (?:my |the |a |an )?([a-z][a-z\- ]{1,40})/i,
  /\bwe have (?:my |the |a |an )?([a-z][a-z\- ]{1,40})/i,
];

const TRAILING = new Set(["here", "now", "today", "right", "over", "in", "on", "at", "to", "and", "so", "then", "first", "next", "please", "ok", "okay"]);
const REJECT = new Set(["it", "ready", "done", "finished", "the procedure", "a test", "the step", "step one", "step 1"]);

/** Returns the last segmentable noun phrase in the text, or null. */
export function extractObjectPhrase(text: string): string | null {
  if (!text) return null;
  let found: string | null = null;
  for (const re of PATTERNS) {
    for (const m of text.matchAll(new RegExp(re.source, "gi"))) {
      const raw = (m[1] || "").split(/[.,;:!?]/)[0].trim().toLowerCase();
      const words = raw.split(/\s+/).filter(Boolean);
      while (words.length && TRAILING.has(words[words.length - 1])) words.pop();
      const phrase = words.slice(0, 4).join(" ");
      if (phrase.length >= 3 && !REJECT.has(phrase)) found = phrase;
    }
  }
  return found;
}

/** Prompt simplification ladder for SAM no-match recovery. */
export function promptVariants(prompt: string): string[] {
  const p = prompt.trim().toLowerCase().replace(/\s+/g, " ");
  if (!p) return [];
  const words = p.split(" ");
  const out: string[] = [p];
  if (words.length >= 3) out.push(words.slice(1).join(" ")); // drop adjective: blue adjustment knob -> adjustment knob
  if (words.length >= 2) out.push(words.slice(-2).join(" "));
  out.push(words[words.length - 1]); // head noun
  return [...new Set(out.filter((v) => v.length >= 2))];
}
