## Project name
AWDC Query Studio (placeholder — rename before the demo video if a real name is picked)

## Track
Experienced Developers — "Modernize What Matters"
(Bob account / registration: djanderson@duck.com, confirmed 2026-10-17.)

## Description 
Municipal animal shelter data is public but effectively locked behind database skills. AWDC Query Studio modernizes the Animal Welfare Data Center's legacy stack — an Oracle APEX portal and a production Flask chatbot that answers questions over APEX views through the Model Context Protocol — into a natural-language query studio for shelter intakes, outcomes, and length of stay. Shelter staff and advocates ask in plain English; queries run only against vetted, allow-listed data views, so answers are safe and checkable. IBM Bob was the development partner for this modernization: audit, rebuild, and debugging.

## What we built / improvements over the legacy app (form free-text)
- Legacy assets (pre-existing, not submitted code): an Oracle APEX portal over municipal shelter records collected via FOIA (Animal Welfare Data Center work, David Anderson, since 2024), and a production Flask chatbot (live at chat.california.vision) that already answers natural-language questions over APEX views via the Model Context Protocol, with OAuth2 sign-in — powerful, but built for one operator, not for shelter staff and advocates.
- Built in this window with IBM Bob (Fresh Code Rule — all submitted code written Sep 28–Oct 18, 2026):
  - The Query Studio layer: a public-facing studio front end over the chatbot's MCP query path, with five one-click demo questions (intake trend by month, outcomes by species, average length of stay overall/by species, dog-vs-cat outcome mix, peak intake months).
  - Bob-led audit of the legacy chatbot + APEX package (architecture, data model, PII handling) driving the modernization, preserved in `bob_sessions/`.
  - Demo dataset: the LA County slice of the YugabyteDB shelter cluster — `awdc.laas_population_data`, 59,153 records (the full cluster holds 346,734 records across seven Southern California county tables), [date range].
- Safety design: the LLM never writes free-form SQL — it calls MCP tools that query an allow-list of vetted APEX views, which is injection-safe by design and keeps answers checkable.

## How IBM Bob was used (Bob adoption = 30% of judging — paste the summary, keep the log in the README)
IBM Bob was the development partner for the whole build: auditing the legacy APEX application and data model, planning the modernization, implementing the FastAPI NL→SQL endpoint and front end, debugging, and drafting documentation. Bob session exports are preserved in the repo under `bob_sessions/`, the README carries the Bob-usage log (time, task, prompt/session, commit), and commit messages note Bob's role.


## Stack
Python · Flask · Model Context Protocol (MCP) · Oracle APEX / Oracle DB (allow-listed views, `chatbot_pkg.sql`) · LLM tool-calling (OpenAI / Google Gemini) · OAuth2 (Google, GitHub, Facebook, LinkedIn, Auth0) · Vercel serverless · IBM Bob (development partner) · GitHub
Legacy source (reference asset): github.com/calivision/awdc-chat (private) — live deployment: chat.california.vision

## Links to fill at submit time
- GitHub repo: [URL]
- Live demo: [URL]
- Demo video (YouTube, ≤3 min): [URL]
- Slide deck: PDF built at workspace/hackathons/ibm-bob-angelhack/awdc-query-studio-deck.pdf