Jimmy Wong\
November 19, 2026\
ITMO-544\
Final Project: Weather Advisor Application

# Deliverable #1: Architecture Document

## System Topology & Network Diagram
```
                                 [ End User Browser / Client ]
                                               |
                             HTTP :8081 (Web UI, /advice, /email)
                                               v
+-----------------------------------------------------------------------------------------------------+

| AWS VPC (Default VPC - us-east-2a & us-east-2b)                                                     |
|                                                                                                     |
|  +-----------------------------------------------------------------------------------------------+  |
|  | Internet-Facing Application Load Balancer (ALB)  [SG: alb-sg | Ingress: 0.0.0.0/0 :8080,8081] |  |
|  +------------------------------------+------------------------------------+---------------------+  |
|                                       |                                    |                        |
|                    Listener :8081     |                 Listener :8080     |                        |
|                    (Public Tier)      |                 (Internal Tier)    |                        |
|                                       v                                    v                        |
|  +-----------------------------------------+          +----------------------------------------+    |
|  | Advisor Auto Scaling Group (Min/Max: 1) |          | Weather Auto Scaling Group (Min/Max: 1)|    |
|  | EC2 t3.micro (Node.js / Express :3000)  |  HTTP    | EC2 t3.micro (Node.js / Express :3000) |    |
|  | [SG: app-sg | Ingress: alb-sg ONLY]     |--------->| [SG: app-sg | Ingress: alb-sg ONLY]    |    |
|  | [IAM Role: advisor-role]                |  :8080   | [IAM Role: weather-role]               |    |
|  +---+----------------+----------------+---+          +---+----------------+---------------+---+    |
|      |                |                |                  |                |                        |
+------|----------------|----------------|------------------|----------------|------------------------+

       |                |                |                  |                |
       v                v                v                  v                v
 [SSM Parameter]  [DynamoDB Table]   [Amazon SES]     [SSM Parameter]  [RDS PostgreSQL 15]
  /itmo-544/       LookupsCounter     Email Delivery   /itmo-544/       db.t4g.micro (Private)
  gemini-api-key   (TTL enabled)      (Sandbox/Prod)   db-password      [SG: db-sg | :5432]
       |                                                                [Ingress: app-sg ONLY]
       v                                                                     |
 [Google Gemini API]                                                         v
  gemini-3.1-flash-lite                                        [External Weather APIs (HTTPS)]
                                                                1. api.zippopotam.us (Geocoding)
                                                                2. api.weather.gov (NWS Forecast)
                                                                3. api.open-meteo.com (UV/Vis)
```

## Component Inventory

| Component | AWS Service / Tech | Purpose | Network & Security Posture |
| --------- | ------------------ | ------- | -------------------------- |
| Load Balancer | AWS ALB (internet-facing) | Routes public web traffic (:8081) to Advisor and weather queries (:8080) to Weather across 2 AZs. | Attached to `alb-sg`; accepts TCP 8080 and 8081 from 0.0.0.0/0. |
| Advisor Service | EC2 t3.micro + ASG + Node.js/Express | Serves HTML UI (`/`), JSON API (`/advice`), and email dispatch (`/email`); calls Gemini and SES. | Attached to `app-sg`; port 3000 accepts traffic only from `alb-sg`. |
| Weather Service | EC2 t3.micro + ASG + Node.js/Express | Geocodes US ZIPs, fetches NWS and Open-Meteo forecasts, computes 7 weather facts, and caches results. | Attached to app-sg; port 3000 accepts traffic only from `alb-sg`. |
| Weather Facts Cache | Amazon RDS PostgreSQL 15 (db.t4g.micro) | Stores normalized 10-item weather payloads (`lookups` table) for fast cache hits (600s) and stale fallback (24h). | Private (`PubliclyAccessible=False`), encrypted at rest; `db-sg` allows TCP 5432 only from `app-sg`. |
| Report Cache & Abuse Store | Amazon DynamoDB (`LookupsCounter`, `On-Demand`) | Stores compiled reports (`REPORT#`), atomic daily Gemini cap (`DAILY_CAP#`), and per-IP rate limits (`RATE#`) with TTLs. | Accessed via IAM role (`advisor-role`) scoped strictly to the `LookupsCounter` table ARN. |
| Secrets Store | AWS SSM Parameter Store (`SecureString`) | Stores `/itmo-544/gemini-api-key` and `/itmo-544/db-password` encrypted with KMS. | Each tier's IAM role grants `ssm:GetParameter` only on its own parameter ARN. |
| Email Service | Amazon SES | Sends formatted HTML 10-item weather reports and handles recipient verification consent. | Accessed via `advisor-role` (`ses:SendEmail`, `ses:SendRawEmail`, `ses:VerifyEmailIdentity`). |

## End-to-End Request Flows

### Flow A: Cache Miss (Full Report Generation)
1. User Submission: User submits `date`, `zip`, `gender`, and `email` via `GET /` (or `GET /advice`) on ALB port 8081.
2. Validation & Abuse Checks: Advisor validates inputs (5-digit US ZIP, 7-day calendar window, fixed category list, valid email), checks DynamoDB for a cached report (`REPORT#<zip>#<date>#<gender>`), and enforces the per-visitor minute rate limit (`RATE#REPORT#<hashed_ip>#<window>`).
3. Weather Tier Lookup: On a report cache miss, Advisor calls `GET http://<alb-dns>:8080/weather?zip=<zip>&date=<date>` with a 20-second timeout.
4. Weather Aggregation & Caching: Weather checks RDS PostgreSQL (`lookups`) for a fresh entry (`< 600s`). On a miss, it queries Zippopotam.us for (`lat`, `lon`), `NWS /points` + `/forecast/hourly` + `/forecast`, and Open-Meteo for UV index and visibility, aggregates Morning (06:00-11:59) and Night (18:00-23:59) metrics, writes the JSON payload to RDS, and returns `HTTP 200`.
5. AI Advice Generation: Advisor atomically increments `DAILY_CAP#<date>` in DynamoDB. If under `DAILY_GEMINI_CAP`, it sends only `city/state/ZIP`, `style category`, and `weather facts` to Google Gemini (`gemini-3.1-flash-lite`), validates the JSON schema, caches the combined 10-item report in DynamoDB (`TTL = 1800s`), and renders the HTML report. If Gemini fails or the cap is exceeded, Advisor seamlessly falls back to deterministic rule-based clothing and road advice.

### Flow B: Cache Hit (Fast Path)
1. Repeat Request: A user requests the same (`zip`, `date`, `gender`) within the 30-minute report TTL window.
2. DynamoDB Short-Circuit: Advisor finds a non-expired `REPORT#<zip>#<date>#<gender>` item in DynamoDB and returns it immediately (`cached: true`) without calling the Weather tier, upstream weather APIs, RDS, or Google Gemini --saving both latency and API quota.
3. Weather-Level Cache Hit: If a different gender is requested for an already-queried (`zip`, `date`) within 10 minutes (`CACHE_SECONDS=600`), Advisor calls Weather, which returns the cached row from RDS PostgreSQL (`cache: "hit"`) without hitting Zippopotam.us, NWS, or Open-Meteo.

## Data Classification & Privacy Controls

| Data Element | Sensitivity | Where Stored | Sent to Gemini? | Written to Logs? | Retention / TTL |
| ------------ | ----------- | ------------ | --------------- | ---------------- | --------------- |
| Recipient Email Address | PII (Sensitive) | In-memory during request only (sent to SES) | Never | Never | Not persisted in DB/DynamoDB
| Visitor IP Address | PII (Network) | Hashed with salt (SHA-256, truncated to 24 hex chars) in DynamoDB `RATE#` keys | Never | Never | Auto-deleted via DynamoDB TTL (~2 min / ~2 hr) |
| Clothing Category (gender) | User Preference | Part of DynamoDB cache key `REPORT#<zip>#<date>#<gender>` | Yes (as style category only) | Never | Auto-deleted via DynamoDB TTL (30 min) |
| US ZIP Code & Forecast Date | Public / Non-PII | RDS lookups & DynamoDB `REPORT#` keys | Yes (location + weather facts) | Yes (operational metrics) | RDS (24h stale window); DynamoDB (30 min TTL) |
| API Keys & DB Password | Secret Credentials | AWS SSM Parameter Store (`SecureString`) | Never (API key sent in `x-goog-api-key` header only) | Never | Persistent in SSM; cached in RAM for 300s |

## Least-Privilege IAM Mapping
No wildcard actions (* or ssm:\*) and no wildcard resources (*) appear in any IAM policy:

| Role | IAM Action | Exact Resource ARN | Code Location Requiring Permission |
| ---- | ---------- | ------------------ | ---------------------------------- |
| weather-role | ssm:GetParameter | arn:aws:ssm:<region>:<acct>:parameter/itmo-544/db-password | weather-app/app.js (readDbPassword()) |
| advisor-role | ssm:GetParameter | arn:aws:ssm:<region>:<acct>:parameter/itmo-544/gemini-api-key | advisor-app/app.js (getApiKey()) |
| advisor-role | dynamodb:GetItem, PutItem, UpdateItem | arn:aws:dynamodb:<region>:<acct>:table/LookupsCounter | advisor-app/app.js (getSavedReport(), saveReport(), checkAndIncrementGeminiCap(), checkVisitorRateLimit ()) |
| advisor-role | ses:SendEmail, SendRawEmail, VerifyEmailIdentity | arn:aws:ses:<region>:<acct>:identity/* | advisor-app/app.js (POST /email handler) |

## Architectural Decisions Tables

| \# | Decision | Choice Made	Why This Choice Fits Our Goals & Constraints | Trade-off Accepted |
| -- | -------- | -------------------------------------------------------- | ------------------ |
| 1 | Weather Facts Cache Store | RDS PostgreSQL 15 (db.t4g.micro) alongside DynamoDB for Advisor state | Reuses our proven parameterized SQL schema (`lookups` JSONB + created_at index) with TLS certificate verification (`rds-ca.pem`) and supports rich /history SQL queries plus 24-hour stale fallback. | Higher hourly cost (~$0.016/hr) and ~4-minute provisioning time compared to DynamoDB-only. |
| 2 | Advisor Cache & Rate-Limit Store | Amazon DynamoDB (`LookupsCounter`, `On-Demand`) with native TTL (`expires_at`) | Provides atomic UpdateItem counters for daily Gemini caps and per-visitor rate limits with zero server management and automatic TTL cleanup at near-zero cost. | Requires eventual consistency awareness on reads and explicit key-prefix design (`REPORT#`, `DAILY_CAP#`, `RATE#`). |
| 3 | UV Index & Visibility Gap Source | Open-Meteo Forecast API (`api.open-meteo.com`) | NWS /forecast/hourly omits UV index entirely and frequently omits hourly visibility; Open-Meteo provides free, no-key, 7-day hourly `uv_index` and `visibility` by coordinates. | Adds a third external HTTP call (mitigated by running it in `Promise.all` with NWS and failing gracefully to "Not Available"). |
| 4 | ZIP Geocoding Source | Zippopotam.us (`api.zippopotam.us/us/<zip>`) | Fast, keyless REST endpoint that validates US ZIP existence and returns exact city, state abbreviation, latitude, and longitude needed for `NWS /points/{lat},{lon}`. | Dependent on third-party uptime (mitigated by 10-minute fresh cache and 24-hour stale RDS fallback). |
| 5 | NWS Day 6-7 Horizon Gap	| Automatic fallback to NWS 12-hour `/forecast` periods (`supplementFromStandardPeriods`) | NWS `/forecast/hourly` covers ~156 hours (~6.5 days), leaving Day 7 or passed Morning hours empty; 12-hour periods cover the full 7-day window. | Day 7 uses 12-hour daytime/nighttime aggregates rather than 6-hour (06:00-11:59 / 18:00-23:59) windows. |
| 6 | Morning & Night Time Windows | Local station time (06:00-11:59 Morning, 18:00-23:59 Night) via `Intl.DateTimeFormat` | Uses the NWS point's timeZone (e.g., `America/Chicago`) so timestamps align with the traveler's local clock across all US time zones and DST shifts. | Midday (12:00-17:59) and overnight (00:00-05:59) hours are excluded from Morning/Night averages. |
| 7 | Rain & Snow Thresholds | Max PoP <20% = No, 20-59% = Mild, >=60% = Heavy (separated by forecast text) | Uses peak probability in the 6-hour window so a brief storm isn't averaged away, and checks `shortForecast` for snow/flurries so winter snow isn't double-counted as rain. | NWS PoP measures likelihood of precipitation rather than liquid accumulation depth in inches. |
| 8 | LLM Model & Output Schema | Google Gemini `gemini-3.1-flash-lite` with strict JSON schema validation | Low-latency, free-tier-friendly model with temperature: 0.1 and strict JSON parsing (`validateGeminiAdvice`) that enforces 1-2 short plain sentences under 350 chars. | Slightly less expressive prose than larger models, but far lower latency and deterministic structure. |
| 9 | AI Outage & Quota Degradation | Atomic daily cap + deterministic rule-based `fallbackAdvice()` | Prevents runaway Gemini billing/quota exhaustion and guarantees users always receive safe clothing and road advice even if Gemini times out (15s) or returns invalid JSON. | Fallback advice uses fixed temperature/precipitation rules rather than nuanced natural-language synthesis. |
| 10 | Database Outage Degradation | 30-second circuit breaker (`DB_RETRY_MS`) + 24-hour stale cache | If RDS is unreachable, Weather skips DB calls for 30s (cache: "unavailable") instead of blocking every request on connection timeouts; if upstream weather fails, stale RDS rows (<24h) are served with a warning banner. | Users may briefly see uncached live responses or slightly older forecast data during partial outages. |
| 11 | Abuse & Rate Control | Three-layer defense: DynamoDB report cache (30 min), salted IP-hash rate limits (10/min reports, 5/hr emails), and daily Gemini cap | Stops bots from draining Gemini quota or spamming SES without requiring user accounts or storing raw IP addresses. | Users behind a shared NAT/campus IP share the per-IP rate bucket. |
| 12 | Email Consent & Anti-Spam | AWS SES identity verification on first send (`VerifyEmailIdentity`) | Ensures reports are only delivered to mailboxes whose owner explicitly clicked AWS's verification link, preventing third-party email bombing. | First-time recipients must click a verification link in their inbox before clicking Email Report a second time. |
| 13 | Network Isolation | Security group chaining (`0.0.0.0/0 -> alb-sg -> app-sg -> db-sg`) | Blocks all direct internet access to EC2 port 3000 and RDS port 5432; only the ALB can reach the apps, and only the apps can reach PostgreSQL. | Operators must use AWS Systems Manager Session Manager or a temporary bastion rule for instance debugging. |
| 14 | Deployment & Boot Automation | 100% Python (`boto3 + #!/usr/bin/env python3 user-data with gzipped app payloads`) | Eliminates bash scripts completely, guarantees idempotent create/delete lifecycles, and compresses app code to stay well under EC2's 16 KB user-data limit. First boot takes ~90-120 seconds while `dnf installs Node.js` and `npm installs` production dependencies. |
| 15 | Cost & Lifecycle Management | Single t3.micro per tier + db.t4g.micro + automated teardown (`delete_stack.py` / `delete_database.py`) + `budget.py` | Keeps running cost to ~$0.087/hr (~$0.07/hr EC2/ALB + $0.016/hr RDS + $0.001/hr DynamoDB/SSM), easily staying under the $2.00 project cap. | Single-instance ASGs (Min=1, Max=1) experience brief ~2-minute recovery downtime during instance termination rather than zero-downtime failover. |

## Threat & Mitigation Table

| Threat / Abuse Vector	Attack Scenario | Control Implemented in Code & Infrastructure | Residual Risk |
| ------------------------------------- | -------------------------------------------- | ------------- |
| 1. Automated Quota / Cost Drain | Attacker floods /advice with random ZIPs to exhaust Gemini free-tier quota or run up AWS bills. | 3-layer defense in `advisor-app/app.js`: (a) 30-min DynamoDB report cache, (b) per-visitor 10 req/min rate limiter, (c) atomic `DAILY_CAP` counter in DynamoDB that degrades gracefully to local rule-based fallback. | Distributed botnet across many IPs could trigger fallback mode for the rest of the UTC day once `DAILY_GEMINI_CAP` is reached. |
| 2. Email Spam / Harassment Relay | Attacker enters a victim's email address repeatedly on `/email` to flood their inbox. | `POST` `/email` enforces 5 emails/hr per visitor hash and relies on AWS SES recipient verification (`VerifyEmailIdentityCommand`), refusing delivery until the mailbox owner confirms consent. | An unverified victim receives at most one AWS SES verification email per verification window. |
| 3. Cross-Site Scripting (XSS) & Prompt Injection | Attacker injects `<script>` tags in query parameters or Gemini returns malicious HTML/markdown in advice fields. | `escapeHtml()` sanitizes every dynamic value rendered in HTML pages and HTML emails; `validateGeminiAdvice()` enforces strict JSON schema, string types, and `MAX_ADVICE_CHARS=350`. | Plain-text output could still contain awkward phrasing if Gemini misinterprets edge-case weather strings, though it cannot execute scripts. |
| 4. Direct Instance / Database Bypass | Attacker scans EC2 public IPs on port 3000 or RDS endpoint on port 5432 to bypass ALB and rate limits.	`network.py` revokes 0.0.0.0/0 on app-sg and allows TCP 3000 only from `alb-sg`; `database.py` sets `PubliclyAccessible=False` and allows TCP 5432 only from `app-sg`. | None from external networks; internal VPC compromise would still be constrained by SG rules and TLS/password auth. |
| 5. Secret Leakage in Logs or User-Data | Gemini API key or RDS password leaks in EC2 user-data metadata, CloudWatch/journald logs, or Git commits. | Secrets live exclusively in SSM SecureString parameters; user-data passes only parameter names; `advisor-app` and `weather-app` structured logs explicitly omit secrets, emails, and IPs. | Anyone with `ssm:GetParameter` permissions on the AWS account or root shell access on the running EC2 instance can inspect runtime memory. |
| 6. PII Exposure to External AI | User email address, clothing preference tied to identity, or IP address is sent to Google Gemini. | `buildPrompt()` strips email and visitor metadata completely, sending only `{ requestedStyleCategory, location, morningWeatherFacts, nightWeatherFacts }` to Gemini. | Location + date metadata is visible to Google's API endpoint as part of the weather query. |

# Deliverable 2: Source Map & API Gap Report

## Upstream API Source Map Table
For every requested location, the Weather Data Tier (weather-app/app.js) first resolves the 5-digit US ZIP code via Zippopotam.us (GET https://api.zippopotam.us/{zip}) to obtain place name, state abbreviation, latitude, and longitude, and then resolves the NWS grid metadata via National Weather Service (GET https://api.weather.gov/{lat},{lon}) to obtain timeZone, forecastHourly, and forecast.

| \# | Report Item | Upstream Source | Endpoint & Exact JSON Field Path | Raw API Unit & Example Value | Normalized Report Output & Rule |
| -- | ----------- | --------------- | -------------------------------- | ---------------------------- | ------------------------------- |
| 1 | Temperature | National Weather Service (NWS) | forecastHourly -> properties.periods[].temperature & temperatureUnit (fallback: 12h forecast -> properties.periods[].temperature) | Degrees Fahrenheit ("F"), e.g., 42 ("F") | Arithmetic mean across the 6-hour period rounded to nearest integer ("42 F"), or "Not Available". |
| 2 | Wind Speed | National Weather Service (NWS) | forecastHourly -> properties.periods[].windSpeed (fallback: 12h forecast -> properties.periods[].windSpeed) | String in miles per hour ("10 mph" or range "10 to 15 mph") | Maximum numeric mph value across the 6-hour window ("15 mph"), or "Not Available". |
| 3 | Visibility | NWS Hourly (Primary) / Open-Meteo (Fallback) | Primary: forecastHourly -> properties.periods[].visibility.value (wmoUnit:m) ------------- Fallback: /v1/forecast -> hourly.visibility[] (meters) | Meters (16093.44 m = 10 mi; often null in NWS hourly) | Converted from meters to miles (/ 1609.344), averaged across the window ("10 mi"), or "Not Available". |
| 4 | UV Index | Open-Meteo Forecast API | GET https://api.open-meteo.com -> hourly.uv_index[] | Dimensionless UV index float (0.0 to 11.0+, e.g., 3.4 daytime, 0 at night) | Peak (maximum) UV index across the 6-hour window ("3.4"), or "Not Available" if missing. |
| 5 | Humidity | National Weather Service (NWS) | forecastHourly -> properties.periods[].relativeHumidity.value (wmoUnit:percent) | Integer percentage 0-100 (e.g., 68) | Arithmetic mean across the 6-hour window rounded to nearest integer ("68%"), or "Not Available". |
| 6 | Rain Category | Derived from NWS PoP & Forecast Text | properties.periods[].probabilityOfPrecipitation.value (0-100) + shortForecast | Percentage 0-100 (e.g., 35) + text ("Chance Light Rain") | Peak PoP when shortForecast is not snow/flurry/blizzard: <20% -> "No", 20-59% -> "Mild", >=60% -> "Heavy". |
| 7 | Snow Category | Derived from NWS PoP & Forecast Text | properties.periods[].probabilityOfPrecipitation.value (0-100) + shortForecast | Percentage 0-100 (e.g., 65) + text ("Snow Showers Likely") | Peak PoP when shortForecast contains "snow", "flurr", or "blizzard": <20% -> "No", 20-59% -> "Mild", >=60% -> "Heavy". |
| 8 | Road Conditions | Google Gemini (gemini-3.1-flash-lite) / Rule Fallback | POST /v1beta/models/gemini-3.1-flash-lite:generateContent -> candidates[0].content.parts[0].text (parsed JSON .roadConditions) | Plain-text JSON string (<= 350 chars) | Grounded 1-2 sentence road guidance; falls back to wet/slick warning if Rain or Snow is Mild/Heavy. |
| 9 | Suggested Dressing | Google Gemini (gemini-3.1-flash-lite) / Rule Fallback | POST /v1beta/models/gemini-3.1-flash-lite:generateContent -> parsed JSON .suggestedDressing | Plain-text JSON string (<= 350 chars) | Style-aware (menswear, womenswear, neutral) clothing advice; falls back to temperature-tier rules. |
| 10 | Suggested Accessories | Google Gemini (gemini-3.1-flash-lite) / Rule Fallback | POST /v1beta/models/gemini-3.1-flash-lite:generateContent -> parsed JSON .suggestedAccessories | Plain-text JSON string (<= 350 chars) | Practical accessory guidance (umbrella, gloves, sunglasses); falls back to precipitation/temperature rules. |

## Upstream API Gaps Found & Architectural Justifications
During inspection of real responses from api.weather.gov (Chicago ZIP 60616 and Miami ZIP 33101), we identified four concrete gaps in NWS data and resolved each explicitly:
1. Missing UV Index in NWS API (uv -> Open-Meteo):
	- Gap: Neither NWS `/forecast/hourly` nor NWS `/forecast` includes a UV index field.
	- Resolution: Added Open-Meteo (https://api.open-meteo.com/{lat}&longitude={lon}&hourly=uv_index,visibility&timezone=auto&forecast_days=7), which requires no API key, supports 7-day hourly forecasts globally, and executes in parallel (`Promise.all`) with NWS so it adds virtually zero latency.
2. Missing/Null Visibility in NWS Hourly Periods (visibility -> Open-Meteo Fallback):
	- Gap: NWS `/forecast/hourly` frequently omits `visibility.value` or `returns null` for extended forecast hours.
	- Resolution: `weather-app/app.js` checks NWS hourly visibility first; if mVis or nVis is null, it automatically falls back to Open-Meteo's `hourly.visibility` (converted from meters to miles) and records "Open-Meteo API" in `sources.visibility`. If both sources lack data, it outputs "Not Available" rather than inventing 0.
3. NWS 156-Hour Hourly Horizon Cutoff on Day 7 (`supplementFromStandardPeriods`):
	- Gap: `NWS /forecast/hourly` provides ~156 hourly periods (~6.5 days), leaving Day 7 of the 7-day selection window empty--and when a user queries "today" in the evening, Morning (06:00–11:59) hourly periods have already rolled off the feed.
	- Resolution: `supplementFromStandardPeriods()` falls back to NWS's 12-hour `/forecast` endpoint (`isDaytime: true for Morning, isDaytime: false for Night`) whenever hourly buckets are empty for a valid date in the 7-day window.
4. US ZIP Code to Coordinate Resolution (Zippopotam.us):
	- Gap: NWS `/points/{lat},{lon}` requires decimal latitude and longitude rather than a 5-digit US ZIP code.
	- Resolution: Used https://api.zippopotam.us/{zip} (free, no API key, fast JSON lookup) to resolve US ZIP codes to city, state, latitude, and longitude--and immediately `return 404 zip_not_found` for unassigned 5-digit numbers like 00000.

# Deliverable 3: Report Definition

1. Time Window Definitions (Local Station Time)
Every forecast timestamp from NWS (startTime, ISO-8601 with offset) is converted into the target location's IANA time zone (returned by NWS `point.properties.timeZone`, e.g., `America/Chicago` or `America/Los_Angeles`) using `Intl.DateTimeFormat` (`getLocalParts()`):
    - Morning Period: Local hours 06:00 through 11:59 (hour >= 6 && hour <= 11), representing the morning commute and early daytime window.
    - Night Period: Local hours 18:00 through 23:59 (hour >= 18 && hour <= 23), representing the evening commute and nighttime window.
    - DST & Midnight Handling: Because `Intl.DateTimeFormat` resolves timestamps against the NWS station's IANA zone name rather than a fixed UTC offset, spring-forward (02:00 -> 03:00) and fall-back (02:00 -> 01:00) Daylight Saving Time transitions and late-evening UTC date rollovers map to the exact local calendar date and hour.

2. Aggregation Rules Across Each 6-Hour Window
    - Temperature (`temperature`): Arithmetic mean of hourly temperatures in the window, rounded to the nearest integer (`Math.round(avg(temps))`), formatted as "<N> F".
    - Wind Speed (`windSpeed`): Maximum numeric wind speed parsed from hourly `windSpeed` strings (`maxVal(winds)`), formatted as "<N> mph", so peak gust/wind exposure is never hidden by averaging.
    - Visibility (`visibility`): Arithmetic mean of hourly visibility values converted from meters to statute miles (meters / 1609.344), rounded to one decimal place, formatted as "<N> mi".
    - UV Index (`uv`): Maximum hourly UV index (`maxVal(uv)`) during the window, representing peak solar UV exposure.
    - Relative Humidity (`humidity`): Arithmetic mean of hourly relative humidity percentages rounded to the nearest integer, formatted as "<N>%".
    - Missing Data Policy: If an upstream field is missing or null across the entire window, the cell displays "Not Available"--no synthetic values are ever fabricated.

3. Rain & Snow Category Threshold Rules
Hourly precipitation probabilities (`probabilityOfPrecipitation.value`, 0-100%) are partitioned by inspecting each hour's shortForecast text (case-insensitive):
    - Hours whose shortForecast contains "snow", "flurr", or "blizzard" populate `snowProbs` (and set `isSnow = true` when `prob > 0`).
    - All other hours populate `rainProbs`.

Both `deriveRainCategory()` and `deriveSnowCategory()` evaluate the peak (`maximum`) probability in the 6-hour window using deterministic boundary thresholds:
| Peak Probability (maxProb) | Category Output | Boundary Test Cases Verified |
| -------------------------- | --------------- | ---------------------------- |
| No probability values available ([]) | Not Available | Empty array [] -> "Not Available" |
| 0% to 19% (maxProb < 20) | No | 0, 19 -> "No" |
| 20% to 59% (20 <= maxProb < 60) | Mild | 20, 59 -> "Mild" |
| 60% to 100% (maxProb >= 60) | Heavy | 60, 100 -> "Heavy" |

# Deliverable 5: Test Evidence
Automated Tests Passing:
- pytest -v -m "not integration and not chaos" (55 passed)
- pytest -v -m integration (30 passed) 
- pytest -v -m chaos (2 passed)
- pytest -m chaos -s (2 passed with a timer)
- link: to the [text file](evidence/root@7a09cd284f8e-itmo-544final_project.txt)

# Deliverable 6: Cost Sheet & Budget Report

## Hourly & Total Project Spend Breakdown (`us-east-2` On-Demand Rates)
All infrastructure is provisioned programmatically via create_database.py and create_stack.py and torn down immediately after testing and demo sessions via delete_stack.py and delete_database.py.

(Tip: Run python3 budget.py --hours <your-actual-hours> and check AWS Billing -> Cost Explorer in your AWS Console to include your exact live AWS billing screenshot alongside this table.)

| AWS Resource | Configuration | Hourly Rate (USD) | Estimated Active Hours | Subtotal (USD) | Cost Control Mechanism |
| ------------ | ------------- | ----------------- | ---------------------- | -------------- | ---------------------- |
| Application Load Balancer | 1 internet-facing ALB (us-east-2a, us-east-2b) | $0.0225 / hr | 6.0 hrs | $0.1350 | Deleted via delete_stack.py after every session. |
| EC2 Instances (2 Tiers) | 2 x t3.micro (weather-asg + advisor-asg, Min=1, Max=1) | $0.0208 / hr (2 x $0.0104) | 6.0 hrs | $0.1248 | ASGs capped at MaxSize=1; instances terminated on teardown. |
| RDS PostgreSQL 15 | 1 x db.t4g.micro, Single-AZ, 20 GB gp3, 0 backup retention | $0.0160 / hr | 6.0 hrs | $0.0960 | SkipFinalSnapshot=True & DeleteAutomatedBackups=True on teardown. |
| Amazon DynamoDB | LookupsCounter (PAY_PER_REQUEST, TTL on expires_at) | ~$0.0005 / hr | 6.0 hrs | $0.0030 | On-demand billing + 30-min report TTL + table deleted on teardown. |
| Amazon SES & SSM | Standard SSM SecureString + SES Sandbox (< 50 emails) | ~$0.0005 / hr | 6.0 hrs | $0.0030 | Standard-tier SSM parameters ($0.00) + SES free-tier allowance. |
| Google Gemini API | gemini-3.1-flash-lite (< 200 requests total) | $0.0000 (Free Tier) | - | $0.0000 | Enforced by atomic DAILY_GEMINI_CAP + 30-min DynamoDB report cache. |
| Total Estimated Spend | Full Build + Integration/Chaos Tests + Live Demo | ~$0.0603 / hr | 6.0 hrs | $0.3618 | Well under the $2.00 project budget cap ($1.6382 buffer). |

# Deliverable 8: One-Page Reflection -- Scaling to 10x Traffic & Production Readiness

1. What Breaks First at 10x Traffic
If traffic increases tenfold from campus-demo volume to sustained concurrent users, three bottlenecks surface first:
    - Single-Instance ASGs (Min=1, Max=1) & Cold Boot Latency: Each tier runs on a single t3.micro instance, and new instances take ~90-120 seconds to run dnf install and npm install on boot. A traffic spike saturates CPU/network on a single node, and a single instance failure causes ~2 minutes of downtime during replacement.
    - Upstream API Rate Limits (NWS, Open-Meteo, Zippopotam.us, and Gemini): Uncached requests for distinct ZIP codes trigger three external weather HTTP calls plus one Gemini API call. At 10x traffic, DAILY_GEMINI_CAP would trip early in the day (degrading users to rule-based fallback advice), and third-party APIs (api.zippopotam.us or api.weather.gov) could throttle our NAT/instance egress IPs.
    - RDS db.t4g.micro Connection & Memory Limits: Each Node.js process opens a pg.Pool of up to 4 connections. Scaling horizontally to 10+ EC2 instances without connection pooling would exhaust db.t4g.micro memory and max_connections.

2. Scaling Plan for 10x Traffic
    - Pre-Baked Golden AMIs & Horizontal Auto Scaling: Replace runtime dnf/npm installation in EC2 user-data with a pre-built Packer AMI containing Node.js, node_modules, and the RDS CA bundle. Increase ASG capacity to MinSize=2, MaxSize=6 across us-east-2a and us-east-2b with target-tracking scaling on ALB RequestCountPerTarget and CPU utilization, cutting scale-out time from 120s to ~15s and eliminating single-instance downtime.
    - Cache Key Normalization & Pre-Warming: Normalize cache keys to (zip, date, gender) with longer TTLs (30-60 minutes) and add an AWS EventBridge scheduled worker to pre-warm top US metro ZIP codes every 30 minutes so >90% of user requests hit DynamoDB or RDS without touching external APIs.
    - Database Scaling: Add RDS Proxy in front of PostgreSQL (or migrate the lookups table to DynamoDB with TTLs) and upgrade RDS to Multi-AZ db.t4g.small with read replicas if SQL analytics are retained.

3. Production Readiness & Security Hardening
Before opening this service to the public internet in production:
    - HTTPS Everywhere & Custom Domain: Provision an ACM TLS certificate on a custom domain, attach an HTTPS :443 listener to the ALB, redirect :80 to :443, and hide internal port :8080 behind an internal ALB or VPC Service Connect so the Weather tier is unreachable from the public internet.
    - WAF & SES Production Access: Attach AWS WAF with managed rate-based rules in front of the ALB to block distributed volumetric attacks before they reach EC2, and move Amazon SES out of sandbox mode with DKIM/SPF/DMARC records, bounce/complaint SNS topics, and an unsubscribe link in every email.
    - Observability & CI/CD: Ship structured JSON logs to CloudWatch Logs with metric alarms on 5xx error rates, gemini_error spikes, and RDS connection errors, and gate all merges on automated GitHub Actions running node app.test.js and pytest -m "not integration and not chaos".



# Final Project Tree
```
📦 final_project
├─ advisor-app/
│  ├─ app.js
│  └─ package.json
├─ stack/
│  ├─ __init__.py
│  ├─ balancer.py
│  ├─ clients.py
│  ├─ compute.py
│  ├─ config.py
│  ├─ database.py
│  ├─ network.py
│  ├─ outputs.py
│  ├─ policies.py
│  ├─ runner.py
│  ├─ scaling.py
│  ├─ storage.py
│  └─ util.py
├─ testing/
│  ├─ app_smoke_test.py
│  ├─ aws_helpers.py
│  ├─ chaos_test.py
│  ├─ http_probe.py
│  └─ requirements.txt
├─ tests/
│  ├─ chaos/
│  │  ├─ __init__.py
│  │  └─ test_chaos.py
│  ├─ integration/
│  │  ├─ __init__.py
│  │  ├─ test_application.py
│  │  ├─ test_infrastructure.py
│  │  └─ test_smoke.py
│  ├─ unit/
│  │  ├─ __init__.py
│  │  ├─ conftest.py
│  │  ├─ test_config.py
│  │  ├─ test_database_with_moto.py
│  │  ├─ test_policies.py
│  │  ├─ test_stack_with_moto.py
│  │  └─ test_user_data.py
│  ├─ __init__.py
│  ├─ conftest.py
│  └─ helpers.py
├─ weather-app/
│  ├─ app.js
│  └─ package.json
├─ .env.example
├─ .gitignore
├─ budget.py
├─ create_database.py
├─ create_weather_stack.py
├─ delete_database.py
├─ delete_weather_stack.py
├─ pytest.ini
└─ requirements.txt
```
©generated by [Project Tree Generator](https://woochanleee.github.io/project-tree-generator)

## Packages Required or Upgraded or Used
- Node.js Version: v20.20.2
- Python 3.10.12
