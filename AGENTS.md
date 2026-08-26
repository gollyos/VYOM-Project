# AGENTS.md — VYOM Multi-Agent Coordination Contract

> **HAR AGENT (Hermes / ZCode / Claude Code / freebuff / koi bhi) PEHLE YE FILE PADHEGA.**
> Is repo pe multiple agents kaam karte hain. Ye contract owner (Gunjan) ka hai
> taaki wo ek dusre ka kaam barbaad na karein.

## Owner ka Goal (ek line me)

VYOM = real personal JARVIS: **bolo → samjhe → REAL kaam kare → verify ho → bataye.**
"Real work" ka matlab: Chrome khula, file bani, research me real sources aaye,
trade paper-executed hua. "Tests pass ho gaye" output nahi hai.

## GOLDEN RULES (todna = kaam reject)

1. **LANE ME HI KAAM KARO.** Neeche lane table dekho. Lane ke bahar ki file
   edit = conflict = owner ka time barbaad.
2. **UNCOMMITTED KAAM KABHI MAT CHHODO.** Adhura feature? Commit karke
   TASKBOARD.md me "in-progress" likho — labeled adhura commit behtar hai
   gayab code se.
3. **DEFINITION OF DONE (har feature):**
   - Code + tests likhe
   - `python -m pytest tests/ -q --basetemp="C:/Users/GunjanAdmin/.vyom-pytest-tmp/<lane>"` full green
   - Frontend chhua to `npm run build` green
   - **LIVE verify**: Brain boot + ek real command end-to-end
   - Ledger (`VYOM_IMPLEMENTATION_STATUS.md`) ek line update
4. **"PASS" BOLNE SE PEHLE PROOF.** Claim = commit hash ya test count ke saath.
   Andaze ("ye ho gaya hoga") mana.
5. **QUOTA REALITY:** Free-tier Gemini limited hai (pacing/caching built hai —
   `app/routing/quota_budgeter.py`, dashboard `/api/quota`). Naya LLM-call
   loop tabhi banao jab quota impact soch liya ho.
6. **Runtime data kabhi commit mat karo** (data/logs, data/memory-vault,
   data/response-cache, data/quota-usage.json, .freebuff/, data/meta_learning).

## LANES (directory ownership — ek lane, ek agent, ek time)

| Lane | Directories |
|---|---|
| **BRAIN** — runtime, memory, routing, providers, tools, research | `services/brain/app/{runtime,memory,routing,providers,tools_builtin,research,persistence,core}` |
| **FRONTEND** — UI, voice UX, 3D biome, Tauri | `src/`, `src-tauri/` |
| **SUBSYSTEMS** — trading, CRM, automation, phase engines, agents | `services/brain/app/{phase8,phase9,phase10,phase11,phase13,crm,trading,agency,automation,agents,adaptive}` |
| **VERIFY** — tests, live checks, installer, deploy | `tests/`, `scripts/`, `deploy/`, `package.json`, `pyproject.toml` |

**Lane lena hai:** TASKBOARD.md me naam + lane + "in-progress (HH:MM)" likho.
Khatam: "done" + commit hash. Same lane pe do agents = dono ka kaam reject.

## Har session START pe (is order me)

1. `git log --oneline -10` — kisi aur ne kya kiya?
2. `git status` — uncommitted mile? Owner ke liye preserve karo
   (commit message: "preserve: parallel work") — DELETE/discard KABHI nahi.
3. `TASKBOARD.md` padho — open items?
4. Lane ke andar kaam shuru.

## Har session END pe

1. Full suite + build green
2. Commit(s)
3. TASKBOARD.md + ledger update

## Required context before implementation

1. Treat `docs/VYOM_PROJECT_MEMORY.md` as the repository-local product
   requirements source of truth. Its historical source is
   `C:\Users\GunjanAdmin\Downloads\VYOM_PROJECT_MEMORY.md`.
2. Read `VYOM_IMPLEMENTATION_STATUS.md` to learn what is already implemented,
   verified, deferred, or limited.
3. Do not repeat a full audit of completed work unless a relevant regression
   or contradiction is found.

## Required status maintenance

After every material implementation pass and before handing work back:

1. Update the timestamp and relevant status entries in `VYOM_IMPLEMENTATION_STATUS.md`.
2. Add the completed work to its change log.
3. Record only tests/builds/runtime checks that were actually performed.
4. Record unresolved errors and environmental limitations explicitly.
5. Never mark an item complete until it has been verified in proportion to its risk.

## Permanent architecture boundary

VYOM is a native desktop application built with Tauri 2, Vite, React,
TypeScript, Three.js, and React Three Fiber. Do not convert it into a website,
SaaS dashboard, Next.js application, SSR application, or marketing-page
structure. Preserve the Living Core as the home experience and add later
capabilities as modular native features only when requested.

## Owner ki bhasha

Owner Hinglish bolta hai — commands Hinglish me aayengi. UI text English me
rakho, VYOM ke jawab Hinglish-friendly hone chahiye.

## Owner priority (abhi kya sabse chahiye)

1. **LIVE end-to-end proof**: "VYOM, Chrome kholo aur YouTube pe lofi play
   karo" → VERIFIED_COMPLETE. Ye pehle, naya feature baad me.
2. Voice auto-on real window me test (`npm run desktop:build` karke installed app)
3. Morning briefing + pending-work recall live sunayi de
4. Ek real paper-trade setup paper-execute ho
5. Uske BAAD naye features (proposal pehle TASKBOARD me, phir code)
