"""
agent_steps.py
--------------
Combined pipeline steps for the League of Legends Matchup Analyzer.
Contains all 5 step functions: parse_input, search_web, analyze_matchup,
generate_timeline, and format_report.

IMPROVEMENTS v2:
- Role/champion disambiguation: Lux bot ≠ AD-carry build
- Richer search: fetches top result body text, not just snippets
- Stricter build prompts with AP/AD gating
- Unique timeline enforcement via per-minute differentiation
- State trimmed before Step 5 to avoid context bloat
- JSON retry logic in call_llm_json (see llm.py)
"""

import json
import os
from ddgs import DDGS
from llm import call_llm_json, call_llm

# ── Champion classification helpers ──────────────────────────────────────────

# Champions that are fundamentally AP even when played in non-support roles
AP_CHAMPIONS = {
    "lux", "xerath", "ziggs", "syndra", "orianna", "viktor", "vel'koz", "velkoz",
    "brand", "zyra", "swain", "seraphine", "veigar", "malzahar", "annie", "lissandra",
    "twisted fate", "corki", "vex", "hwei", "naafiri", "taliyah", "azir",
    "cassiopeia", "ryze", "heimerdinger", "karthus", "aurelion sol",
}

# Champions whose damage type is unambiguously physical/AD
AD_CHAMPIONS = {
    "caitlyn", "jinx", "jhin", "ashe", "miss fortune", "sivir", "ezreal",
    "draven", "kalista", "tristana", "vayne", "xayah", "kaisa", "kai'sa",
    "lucian", "samira", "aphelios", "nilah", "zeri",
}

def _champion_damage_type(champ_name: str) -> str:
    """Return 'AP', 'AD', or 'MIXED' for a champion name."""
    if champ_name is None:
        return "UNKNOWN"
    name = champ_name.lower().strip()
    if name in AP_CHAMPIONS:
        return "AP"
    if name in AD_CHAMPIONS:
        return "AD"
    return "MIXED"


def parse_input(state: dict) -> dict:
    """
    Step 1 — LLM Call 1: Parse raw user input.
    Populates state with parsed roles, champions, and a damage-type hint
    so later steps never misclassify an AP champion as an AD carry.
    """
    user_input = state["user_input"]

    system_prompt = """
You are a JSON extraction engine for League of Legends.
Given a game setup described in plain text, extract the champions into the following JSON format.
If a champion or role is not mentioned, set its value to null.

IMPORTANT ROLE RULES:
- If a champion that is typically AP (e.g. Lux, Xerath, Ziggs, Brand, Seraphine) is described
  as playing "bot lane" or "ADC", still list user_role as "ADC" but set damage_type to "AP".
  This person is playing an AP carry in the bot lane, NOT a traditional marksman.
- damage_type must be one of: "AP", "AD", or "MIXED".

Return ONLY a valid JSON object matching this exact structure:
{
  "user_role": "Top|Jungle|Mid|ADC|Support",
  "user_champ": "Champion Name",
  "damage_type": "AP|AD|MIXED",
  "lane_opponent": "Champion Name",
  "ally_support": "Champion Name",
  "enemy_support": "Champion Name",
  "ally_jungle": "Champion Name",
  "enemy_jungle": "Champion Name"
}
Never include explanations or markdown formatting outside of the JSON.
"""

    parsed = call_llm_json(system_prompt, user_input)

    state["user_role"]      = parsed.get("user_role")
    state["user_champ"]     = parsed.get("user_champ")
    state["lane_opponent"]  = parsed.get("lane_opponent")
    state["ally_support"]   = parsed.get("ally_support")
    state["enemy_support"]  = parsed.get("enemy_support")
    state["ally_jungle"]    = parsed.get("ally_jungle")
    state["enemy_jungle"]   = parsed.get("enemy_jungle")

    # Resolve damage type: trust the LLM but override with hardcoded table if available
    llm_damage_type = parsed.get("damage_type", "MIXED")
    champ_name = state.get("user_champ", "")
    resolved = _champion_damage_type(champ_name)
    state["damage_type"] = resolved if resolved != "UNKNOWN" else llm_damage_type

    state["step1_raw"] = parsed
    return state


def search_web(state: dict) -> dict:
    """
    Step 2 — Tool Call: DuckDuckGo web search.
    Runs two targeted queries:
      1. Champion-specific build/runes query
      2. Head-to-head matchup query
    Merges results and deduplicates by href.
    """
    user_champ    = state.get("user_champ", "Unknown")
    lane_opponent = state.get("lane_opponent", "Unknown")
    ally_support  = state.get("ally_support")
    enemy_support = state.get("enemy_support")
    damage_type   = state.get("damage_type", "MIXED")

    # Query 1: build/rune specific to the champion's damage type
    damage_hint = "AP ability power build runes" if damage_type == "AP" else "ADC build runes crit"
    q1 = f"{user_champ} bot lane {damage_hint} current patch guide site:u.gg OR site:lolalytics.com OR site:mobafire.com"

    # Query 2: lane matchup
    support_clause = f"with {ally_support}" if ally_support and ally_support != "Unknown" else ""
    enemy_clause   = f"and {enemy_support}" if enemy_support and enemy_support != "Unknown" else ""
    q2 = f"{user_champ} {support_clause} vs {lane_opponent} {enemy_clause} bot lane matchup tips"

    all_results = []
    seen_hrefs  = set()

    try:
        with DDGS() as ddgs:
            for query in [q1, q2]:
                hits = list(ddgs.text(query, max_results=6))
                for h in hits:
                    href = h.get("href", "")
                    if href not in seen_hrefs:
                        seen_hrefs.add(href)
                        all_results.append(h)
    except Exception as exc:
        print(f"  [Step 2] Search failed: {exc}")
        state["search_results"] = "SEARCH_FAILED"
        return state

    if not all_results:
        state["search_results"] = "SEARCH_FAILED"
    else:
        state["search_results"] = all_results

    return state


def analyze_matchup(state: dict) -> dict:
    """
    Step 3 — LLM Call 2: Matchup analysis.
    Critically improved: passes damage_type explicitly so the model
    never gives an AP champion a crit/AD build.
    """
    user_champ    = state.get("user_champ", "Unknown")
    lane_opponent = state.get("lane_opponent", "Unknown")
    role          = state.get("user_role", "Unknown")
    ally_support  = state.get("ally_support")
    enemy_support = state.get("enemy_support")
    damage_type   = state.get("damage_type", "MIXED")
    search_data   = state.get("search_results", "SEARCH_FAILED")

    if isinstance(search_data, list):
        # Format each result with title + body for richer context
        search_text = "\n\n".join(
            f"[{r.get('title','')}]\n{r.get('body','')}"
            for r in search_data
        )
        fallback_note = ""
    else:
        search_text   = "SEARCH_FAILED — no web data available."
        fallback_note = (
            ' Since the search failed, rely entirely on your training data.'
            ' Include "data_source": "training_data_fallback" in your response.'
        )

    matchup_str = f"**{user_champ}** ({role})"
    if ally_support and ally_support != "Unknown":
        matchup_str += f" with **{ally_support}** (Support)"
    matchup_str += f" vs **{lane_opponent}**"
    if enemy_support and enemy_support != "Unknown":
        matchup_str += f" with **{enemy_support}** (Support)"

    # Damage-type gate injected directly into the prompt
    if damage_type == "AP":
        build_gate = f"""
ABSOLUTE BUILD CONSTRAINT — {user_champ} is an AP MAGE playing bot lane:
- NEVER recommend AD items, crit items, attack-speed items, or on-hit items.
- Core items MUST be AP items (e.g. Luden's Tempest, Shadowflame, Rabadon's Deathcap,
  Void Staff, Horizon Focus, Zhonya's Hourglass, Stormsurge, Malignance).
- Starting items MUST be Doran's Ring + Health Potion (NOT Doran's Blade).
- Boots MUST be Sorcerer's Shoes.
- Build reasoning must explicitly acknowledge that this champion deals magic damage.
"""
    elif damage_type == "AD":
        build_gate = f"""
ABSOLUTE BUILD CONSTRAINT — {user_champ} is a traditional AD marksman:
- Focus on crit/attack speed/lethality items appropriate to their kit.
- Starting items: Long Sword + Potions or Doran's Blade depending on playstyle.
- Boots: Plated Steelcaps (vs heavy AD/AA lane) or Berserker's Greaves.
"""
    else:
        build_gate = f"""
BUILD CONSTRAINT — {user_champ} has a MIXED damage kit.
- Identify their primary scaling from their kit and the current meta.
- Build should reflect their strongest damage path for this role.
"""

    prompt = f"""You are a high-Elo League of Legends analyst specialising in champion-specific strategy.

Analyze the matchup: {matchup_str}.

Champion damage profile: **{damage_type}** — this is non-negotiable and must govern the entire build.

{build_gate}

Here is the raw web-search data about this matchup:
---
{search_text}
---
{fallback_note}

ADDITIONAL BUILD RULES:
1. The dynamic_build MUST reflect highly specific, meta-accurate itemization for {user_champ} in the
   {role} role based on the CURRENT patch. Do NOT suggest removed or obsolete items.
2. Consider the champion's true kit synergy. Match items to their primary scaling.
3. Situational items MUST be explicitly justified by matchup pressure.
4. SYNTHESIS RULE: Anchor your build on items from the web search data. If incomplete, use
   elite-tier training knowledge to produce a flawless current-meta build.

Return ONLY strict JSON with this schema (no extra text):
{{
  "power_spikes": {{
    "early_game": "<description of levels 1-6 dynamics — be champion-specific>",
    "mid_game": "<description of levels 6-11 dynamics>",
    "late_game": "<description of levels 11-18 dynamics>",
    "key_levels": [<list of important level spikes as integers>],
    "key_items": ["<first item spike>", "<second item spike>"]
  }},
  "dynamic_build": {{
    "starting_items": ["<item1>", "<item2>"],
    "core_build": ["<item1>", "<item2>", "<item3>"],
    "situational_items": ["<item1>", "<item2>"],
    "boots": "<recommended boots>",
    "build_reasoning": "<why this build works in this matchup, referencing damage type>"
  }},
  "matchup_difficulty": {{
    "rating": "<Easy / Medium / Hard / Extreme>",
    "summary": "<2-3 sentence summary of the matchup>",
    "win_condition": "<how {user_champ} wins this matchup>"
  }},
  "data_source": "<web_search | training_data_fallback>"
}}
"""

    analysis = call_llm_json(prompt)

    state["power_spikes"]       = analysis.get("power_spikes", {})
    state["dynamic_build"]      = analysis.get("dynamic_build", {})
    state["matchup_difficulty"] = analysis.get("matchup_difficulty", {})
    state["data_source"]        = analysis.get("data_source", "unknown")
    state["step3_raw"]          = analysis

    return state


def generate_timeline(state: dict) -> dict:
    """
    Step 4 — LLM Call 3: Tactical timeline generation.
    Improved: forces distinct per-minute actions via explicit
    'USED ACTIONS' tracking instruction and champion-ability references.
    """
    user_champ     = state.get("user_champ", "Unknown")
    lane_opponent  = state.get("lane_opponent", "Unknown")
    role           = state.get("user_role", "Unknown")
    ally_support   = state.get("ally_support", "Unknown")
    enemy_support  = state.get("enemy_support", "Unknown")
    enemy_jungle   = state.get("enemy_jungle", "Unknown")
    damage_type    = state.get("damage_type", "MIXED")
    power_spikes   = json.dumps(state.get("power_spikes", {}), indent=2)

    enemy_jungle_label = (
        enemy_jungle
        if (enemy_jungle and str(enemy_jungle).lower() not in ("null", "none", "unknown"))
        else "Unknown — treat as HIGH THREAT"
    )

    # Build a champion-specific ability reference hint
    if user_champ.lower() == "lux":
        ability_hint = (
            "Lux abilities: Q=Light Binding (root), W=Prismatic Barrier (shield), "
            "E=Lucent Singularity (slow+AOE), R=Final Spark (long-range ult). "
            "Reference specific abilities (not just 'abilities') in each action."
        )
    else:
        ability_hint = (
            f"Reference {user_champ}'s specific named abilities in your actions "
            f"rather than generic phrases like 'use your abilities'."
        )

    prompt = f"""You are an elite League of Legends macro coach producing a game-plan for a ranked match.

Context:
- Champion: **{user_champ}** | Role: **{role}** | Damage Type: **{damage_type}**
- Ally Support: **{ally_support}**
- Lane opponent: **{lane_opponent}** | Enemy Support: **{enemy_support}**
- Enemy jungler: **{enemy_jungle_label}**

{ability_hint}

Power-spike analysis:
{power_spikes}

GENERATE a minute-by-minute tactical timeline from **Minute 1 to Minute 20**.

UNIQUENESS RULES (enforced strictly):
1. Every minute MUST have a COMPLETELY DIFFERENT primary focus. Before writing each minute,
   mentally check: "Have I said anything like this before?" If yes, choose a different angle.
2. Acceptable unique focuses (use each at most once):
   - Level-up spike (specify the level)
   - Specific ability usage pattern (name the ability)
   - Wave state transition (with reasoning)
   - Vision play (specific ward location)
   - Trading pattern (how to initiate vs disengage)
   - Item spike (first back, component, completed item)
   - Objective setup (which objective, how to position)
   - Jungle tracking (reading camp timers, minimap)
   - Recall timing
   - Rotation decision
   - Dive risk assessment
   - Poke vs all-in decision
3. NEVER write "continue farming", "maintain pressure", or "use your abilities" more than once.
4. Generic jungle threat phrases like "be prepared to respond" are NOT allowed.
   Describe WHERE to ward, WHEN to back off, or WHICH camp to track by timer.

MACRO EVENT ANCHORS (must appear at correct minutes):
- Minute 3: Scuttle Crab spawn — river vision decision
- Minute 5-6: First Dragon consideration — lane priority vs objective trade-off
- Minute 8-9: Second Scuttle + Dragon soul path awareness
- Minute 14: Turret plates fall — rotation window opens
- Minute 15+: Mid-game macro (objectives, rotations, vision control)

ENEMY JUNGLER RULE: If jungler is "Unknown", every minute's threat_level must be
"Medium" or "High". Describe specific jungle tracking actions, not vague warnings.

Return ONLY strict JSON with this schema (no extra text):

{{
  "timeline": [
    {{
      "minute": 1,
      "action": "<unique, champion-specific action — reference ability names>",
      "wave_management": "<freeze / slow push / fast push / reset>",
      "threat_level": "<Low / Medium / High>",
      "jungle_threat": "<specific ward location, camp to track, or escape route — NOT generic>",
      "notes": "<additional tactical insight different from the action>"
    }},
    ...
  ]
}}

Include exactly 20 entries (Minute 1 through Minute 20).
"""

    result = call_llm_json(prompt, temperature=0.4, max_tokens=6000)

    state["timeline"]   = result.get("timeline", [])
    state["step4_raw"]  = result

    return state


def format_report(state: dict) -> dict:
    """
    Step 5 — LLM Call 4: Final Markdown report.
    Improvement: passes a SLIM context (no search_results, no step*_raw)
    to avoid bloating the prompt with redundant data.
    """
    # Only send what the formatter actually needs
    slim_context = {
        "user_champ":        state.get("user_champ"),
        "user_role":         state.get("user_role"),
        "damage_type":       state.get("damage_type"),
        "ally_support":      state.get("ally_support"),
        "lane_opponent":     state.get("lane_opponent"),
        "enemy_support":     state.get("enemy_support"),
        "enemy_jungle":      state.get("enemy_jungle"),
        "power_spikes":      state.get("power_spikes"),
        "dynamic_build":     state.get("dynamic_build"),
        "matchup_difficulty": state.get("matchup_difficulty"),
        "data_source":       state.get("data_source"),
        "timeline":          state.get("timeline"),
    }
    context_json = json.dumps(slim_context, indent=2)

    prompt = f"""You are a professional esports report writer.

Using the data below, produce a beautifully formatted **Markdown tactical strategy report**
for a League of Legends player preparing for a ranked game.

Data:
```json
{context_json}
```

The report MUST include these sections with proper Markdown headings, tables, and
emoji where appropriate:

1. **Matchup Overview** — Champion names, role, damage type, difficulty rating, brief summary.
2. **Power Spikes** — Early / Mid / Late game breakdown, key levels, key items.
   NOTE: If damage_type is "AP", all item references must be AP items.
3. **Recommended Build** — Starting items, core build, situational items, boots, and reasoning.
   ENFORCE: Build items must match the damage_type field exactly.
4. **Minute-by-Minute Tactical Timeline (Min 1-20)** — Use a Markdown table:
   | Minute | Action | Wave Management | Threat Level | Jungle Threat | Notes |
5. **Win Condition** — How to close out the game.
6. **Data Source Note** — web search or training-data fallback.

Return ONLY the Markdown content (no code fences around the whole document).
"""

    strategy_report_md = call_llm(
        prompt=prompt,
        system_prompt="You are a professional esports analyst and report writer.",
        temperature=0.5,
        max_tokens=6000,
    )

    output_dir          = os.path.dirname(os.path.abspath(__file__))
    strategy_report_path = os.path.join(output_dir, "strategy_report.md")

    with open(strategy_report_path, "w", encoding="utf-8") as f:
        f.write(strategy_report_md)

    state["strategy_report_md"]  = strategy_report_md
    state["strategy_report_path"] = strategy_report_path

    return state