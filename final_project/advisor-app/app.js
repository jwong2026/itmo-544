const express = require('express');
const { SSMClient, GetParameterCommand } = require('@aws-sdk/client-ssm');
const { SESClient, SendEmailCommand, VerifyEmailIdentityCommand, } = require('@aws-sdk/client-ses');
const { DynamoDBClient, GetItemCommand, PutItemCommand, UpdateItemCommand, } = require('@aws-sdk/client-dynamodb');

const app = express();
const PORT = process.env.PORT || 3000;

const WEATHER_URL = process.env.WEATHER_URL; // for example http://<alb-dns>:8080
const GEMINI_API_BASE = process.env.GEMINI_API_BASE || 'https://generativelanguage.googleapis.com';
const GEMINI_MODEL = process.env.GEMINI_MODEL || 'gemini-3.1-flash-lite';
const KEY_PARAM = process.env.GEMINI_PARAM_NAME || '/itmo-544/gemini-api-key';
const KEY_CACHE_MS = Number(process.env.KEY_CACHE_SECONDS || 300) * 1000;
const ssm = new SSMClient({ region: process.env.AWS_REGION });
let cachedKey = { value: null, at: 0 };

const ses = new SESClient({ region: process.env.AWS_REGION }); 
const SENDER_EMAIL = process.env.CONTACT_EMAIL || 'jwong18@hawk.illinoistech.edu';

const ddb = new DynamoDBClient({ region: process.env.AWS_REGION });
const DDB_TABLE_NAME = process.env.ADVISOR_TABLE_NAME || 'LookupsCounter';
const DAILY_GEMINI_CAP = Number(process.env.DAILY_GEMINI_CAP || 100);
const REPORT_CACHE_SECONDS = Number(process.env.REPORT_CACHE_SECONDS || 1800);
const MAX_ADVICE_CHARS = Number(process.env.MAX_ADVICE_CHARS || 350);

const crypto = require('crypto');
const VISITOR_REPORT_LIMIT_PER_MIN = Number(process.env.VISITOR_REPORT_LIMIT_PER_MIN || 10);
const VISITOR_EMAIL_LIMIT_PER_HOUR = Number(process.env.VISITOR_EMAIL_LIMIT_PER_HOUR || 5);
const VISITOR_HASH_SALT = process.env.VISITOR_HASH_SALT || 'itmo544-weather-advisor';

const log = (event, fields = {}) => console.log(JSON.stringify({ ts: new Date().toISOString(), event, ...fields }));

app.set('trust proxy', true);

// Ensure body-parsing middleware is enabled near the top of your file
app.use(express.urlencoded({ extended: true }));
app.use(express.json());

// ---- GEMINI API KEY ----------------------------------------------------------------
// The API key lives in SSM Parameter Store, never in user-data or an environment file.
// GEMINI_API_KEY is for running this app on your own laptop only.
async function getApiKey() {
    if (process.env.GEMINI_API_KEY) return process.env.GEMINI_API_KEY;
    if (cachedKey.value && Date.now() - cachedKey.at < KEY_CACHE_MS) return cachedKey.value;
    const out = await ssm.send(new GetParameterCommand({ Name: KEY_PARAM, WithDecryption: true }));
    cachedKey = { value: out.Parameter.Value, at: Date.now() };
    return cachedKey.value;
}
// ---- GEMINI API KEY ----------------------------------------------------------------

// ---- Prompt for Gemini -------------------------------------------------------------
const SYSTEM_PROMPT =
    'You give practical weather advice based strictly on the weather facts provided. ' +
    'Return ONLY valid JSON with no markdown fences. ' +
    'Each field must be 1 to 2 short, plain sentences under 250 characters with no markdown or lists. ' +
    'Do not repeat or invent numerical measurements. ' +
    'Expected JSON schema:\n' +
    '{\n' +
    '  "morning": {\n' +
    '    "roadConditions": "string",\n' +
    '    "suggestedDressing": "string",\n' +
    '    "suggestedAccessories": "string"\n' +
    '  },\n' +
    '  "night": {\n' +
    '    "roadConditions": "string",\n' +
    '    "suggestedDressing": "string",\n' +
    '    "suggestedAccessories": "string"\n' +
    '  }\n' +
    '}';

// Only the zip code, the forecast, the gender,  go to the AI service. Nothing about the user does.
function buildPrompt(w, gender) {
    // Stringify and format the 7 facts per column compiled by the weather data tier
    return JSON.stringify({
        requestedStyleCategory: gender,
        location: `${w.city}, ${w.state} ${w.zip}`,
        morningWeatherFacts: w.morning,
        nightWeatherFacts: w.night
    }, null, 2);
}

function validateGeminiAdvice(rawText) {
    const cleaned = rawText.replace(/^```json\s*/i, '').replace(/```\s*$/, '').trim();
    const parsed = JSON.parse(cleaned);
    const periods = ['morning', 'night'];
    const fields = ['roadConditions', 'suggestedDressing', 'suggestedAccessories'];

    for (const period of periods) {
        if (!parsed[period] || typeof parsed[period] !== 'object') {
            throw new Error(`missing_period_${period}`);
        }
        for (const field of fields) {
            const val = parsed[period][field];
            if (typeof val !== 'string' || val.trim().length === 0 || val.length > MAX_ADVICE_CHARS) {
                throw new Error(`invalid_field_${period}_${field}`);
            }
        }
    }
    return parsed;
}

async function askGemini(prompt) {
    const key = await getApiKey();
    const maxAttempts = 2;

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        try {
            const res = await fetch(`${GEMINI_API_BASE}/v1beta/models/${GEMINI_MODEL}:generateContent`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'x-goog-api-key': key },
                body: JSON.stringify({
                    systemInstruction: { parts: [{ text: SYSTEM_PROMPT }] },
                    contents: [{ parts: [{ text: prompt }] }],
                    generationConfig: {
                        maxOutputTokens: 500,
                        temperature: 0.1 // Keep responses deterministic and grounded in the data
                    },
                }),
                signal: AbortSignal.timeout(15000),
            });
            if (!res.ok) {
                const err = new Error('gemini_http_error');
                err.status = res.status;
                throw err;
            }

            const data = await res.json();
            const parts = (data.candidates && data.candidates[0] && data.candidates[0].content.parts) || [];
            let text = parts.map((p) => p.text || '').join('').trim();
            
            if (!text) {
                const err = new Error('gemini_empty_response');
                err.status = 200;
                throw err;
            }

            // Clean away markdown wrap annotations if returned by accident
            text = text.replace(/^```json/i, '').replace(/```$/, '').trim();
            try {
                return validateGeminiAdvice(text);
            } catch (parseError) {
                log('gemini_parse_failure', { message: parseError.message });
                const err = new Error('gemini_malformed_response');
                err.status = 200;
                throw err;
            }
            return text;
        } catch (err) {
            const isRetryable = err.name === 'TimeoutError' || err.status === 503 | err.status === 429;
            if (attempt < maxAttempts && isRetryable) {
                await new Promse((r) => setTimeout(r, 800));
                continue;
            }
            throw err;
        }
    }
}
// ---- Prompt for Gemini -------------------------------------------------------------

// ---- FALLBACK in case anything happen ----------------------------------------------
// Used when the AI service is unavailable, rate limited, or the key is wrong.
function generateSingleColumnFallback(facts, gender) {
    const tempNum = parseInt(facts.temperature) || 50;
    let base = 'Wear a warm jacket and long pants.';
    
    if (tempNum <= 32) base = 'Wear a heavy coat, a hat and gloves.';
    else if (tempNum <= 50) base = 'Wear a warm jacket and long pants.';
    else if (tempNum <= 68) base = 'Wear a light jacket or a sweater.';
    else if (tempNum <= 80) base = 'A t-shirt and light pants will be fine.';
    else base = 'Wear light, breathable clothes.';

    // Tailor dressing advice safely
    if (gender === 'menswear' && tempNum > 68) base = 'Wear a light short-sleeve shirt and shorts.';
    if (gender === 'womenswear' && tempNum > 68) base = 'Wear a breathable sundress or light clothing.';

    const isWet = facts.rainCategory !== 'No' || facts.snowCategory !== 'No';
    const road = isWet ? 'Roads may be wet or slick. Exercise caution.' : 'Normal road conditions.';
    const accessory = isWet ? 'Bring an umbrella or a waterproof jacket.' : 'No special accessories required.';

    return {
        roadConditions: road,
        suggestedDressing: base,
        suggestedAccessories: accessory
    };
}

function fallbackAdvice(weather, gender) {
    return {
        morning: generateSingleColumnFallback(weather.morning, gender),
        night: generateSingleColumnFallback(weather.night, gender)
    };
}
// ---- FALLBACK in case anything happen ----------------------------------------------

const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));


// Build the HTML table template generator
function buildHtmlEmailBody(body) {
    const m = body.morning || {};
    const n = body.night || {};
    
    const row = (num, name, mornVal, nightVal) => `
        <tr>
            <td style="padding:8px; border:1px solid #ddd; text-align:center;">${num}</td>
            <td style="padding:8px; border:1px solid #ddd; font-weight:bold;">${name}</td>
            <td style="padding:8px; border:1px solid #ddd;">${escapeHtml(mornVal || 'Not Available')}</td>
            <td style="padding:8px; border:1px solid #ddd;">${escapeHtml(nightVal || 'Not Available')}</td>
        </tr>`;

    const sevenDayRows = (body.sevenDayForecast || []).map(day => {
        const isSelected = day.date === body.date;
        return `
        <tr style="${isSelected ? 'background-color:#e8f4fd; font-weight:bold;' : ''}">
            <td style="padding:8px; border:1px solid #ddd;">${escapeHtml(day.date)}${isSelected ? ' (Selected)' : ''}</td>
            <td style="padding:8px; border:1px solid #ddd;">${escapeHtml(day.high)}</td>
            <td style="padding:8px; border:1px solid #ddd;">${escapeHtml(day.low)}</td>
            <td style="padding:8px; border:1px solid #ddd;">${escapeHtml(day.summary)}</td>
        </tr>`;
    }).join('');

    const sevenDayEmailSection = sevenDayRows ? `
        <h3 style="color: #2C3E50;">7-Day Forecast Window</h3>
        <table style="border-collapse: collapse; width: 100%; max-width: 600px; margin-bottom: 20px;">
            <thead>
                <tr style="background-color: #f2f2f2;">
                    <th style="padding:8px; border:1px solid #ddd; text-align:left;">Date</th>
                    <th style="padding:8px; border:1px solid #ddd; text-align:left;">High</th>
                    <th style="padding:8px; border:1px solid #ddd; text-align:left;">Low</th>
                    <th style="padding:8px; border:1px solid #ddd; text-align:left;">Conditions</th>
                </tr>
            </thead>
            <tbody>${sevenDayRows}</tbody>
        </table>` : '';

    return `
    <html>
    <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <h2 style="color: #2C3E50;">Weather Advisor Report: ${escapeHtml(body.city)}, ${escapeHtml(body.state)}</h2>
        <p><strong>Zip Code:</strong> ${escapeHtml(body.zip)} | <strong>Date Selected:</strong> ${escapeHtml(body.date)}</p>
        <hr>
        ${sevenDayEmailSection}
        <h3 style="color: #2C3E50;">Detailed Morning &amp; Night Advisory (${escapeHtml(body.date)})</h3>
        <table style="border-collapse: collapse; width: 100%; max-width: 600px; margin-bottom: 20px;">
            <thead>
                <tr style="background-color: #f2f2f2;">
                    <th style="padding:8px; border:1px solid #ddd;">#</th>
                    <th style="padding:8px; border:1px solid #ddd; text-align:left;">Weather Item</th>
                    <th style="padding:8px; border:1px solid #ddd; text-align:left;">Morning</th>
                    <th style="padding:8px; border:1px solid #ddd; text-align:left;">Night</th>
                </tr>
            </thead>
            <tbody>
                ${row(1, "Temperature", m.temperature, n.temperature)}
                ${row(2, "Wind Speed", m.windSpeed, n.windSpeed)}
                ${row(3, "Visibility", m.visibility, n.visibility)}
                ${row(4, "UV Index", m.uv, n.uv)}
                ${row(5, "Humidity", m.humidity, n.humidity)}
                ${row(6, "Rain Category", m.rainCategory, n.rainCategory)}
                ${row(7, "Snow Category", m.snowCategory, n.snowCategory)}
                ${row(8, "Road Conditions", m.roadConditions, n.roadConditions)}
                ${row(9, "Suggested Dressing", m.suggestedDressing, n.suggestedDressing)}
                ${row(10, "Suggested Accessories", m.suggestedAccessories, n.suggestedAccessories)}
            </tbody>
        </table>
        <p style="font-size: 0.85em; color: #7F8C8D;">Report generated via ${escapeHtml(body.source)} engine rules.</p>
    </body>
    </html>`;
}

// ---- validation helpers ------------------------------------------------------------
// zip code
const isValidZip = (zip) => /^\d{5}$/.test(zip);

// email address
const isValidEmail = (email) => {
    // basic regex check + character count constraint
    return typeof email === 'string' && email.length <= 100 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

// gender
const isValidGender = (gender) => ['menswear', 'womenswear', 'neutral'].includes(gender);

// date - allow yesterday in UTC so US evening timezones (CST/PST) can still query their local "today"
const isValidDate = (dateStr) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) return false;
    const inputDate = new Date(dateStr + 'T00:00:00Z');
    if (isNaN(inputDate.getTime())) return false;

    // Allow yesterday in UTC so US evening timezones (CST/PST) can still query their local "today"
    const minDate = new Date();
    minDate.setUTCHours(0, 0, 0, 0);
    minDate.setUTCDate(minDate.getUTCDate() - 1);

    const maxDate = new Date();
    maxDate.setUTCHours(23, 59, 59, 999);
    maxDate.setUTCDate(maxDate.getUTCDate() + 7);

    return inputDate >= minDate && inputDate <= maxDate;
};
// ---- validation helpers ------------------------------------------------------------

// ---- DynamoDB & Gemini Call Cap ----------------------------------------------------
async function checkAndIncrementGeminiCap(dateStr) {
    // Add an epoch timestamp calculation block 
    const oneDayFromNowEpoch = Math.floor(Date.now() / 1000) + (24 * 60 * 60);
    const params = {
        TableName: DDB_TABLE_NAME,
        Key: { 'PK': { S: `DAILY_CAP#${dateStr}` } },
        UpdateExpression: 'SET call_count = if_not_exists(call_count, :zero) + :inc, expires_at = :ttl',
        ExpressionAttributeValues: {
            ':zero': { N: '0' },
            ':inc': { N: '1' },
            ':ttl': { N: oneDayFromNowEpoch.toString() }
        },
        ReturnValues: 'UPDATED_NEW'
    };

    try {
        const result = await ddb.send(new UpdateItemCommand(params));
        const currentCount = parseInt(result.Attributes.call_count.N);
        return currentCount <= DAILY_GEMINI_CAP;
    } catch (err) {
        console.error('DynamoDB cap counting tracker error:', err.message);
        return false; // Safely default to fallback advice if the counter architecture errors out
    }
}

async function getSavedReport(zip, date, gender) {
    const pk = `REPORT#${zip}#${date}#${gender}`;
    try {
        const res = await ddb.send(
            new GetItemCommand({
                TableName: DDB_TABLE_NAME,
                Key: { PK: { S: pk } },
            })
        );
        if (!res.Item || !res.Item.report_json.S || !res.Item.expires_at.N) return null;
        if (Number(res.Item.expires_at.N) <= Math.floor(Date.now() / 1000)) return null;
        return JSON.parse(res.Item.report_json.S);
    } catch (err) {
        log('report_cache_read_error', { message: err.message });
        return null;
    }
}

async function saveReport(zip, date, gender, reportBody) {
    const pk = `REPORT#${zip}#${date}#${gender}`;
    const ttl = Math.floor(Date.now() / 1000) + REPORT_CACHE_SECONDS;
    try {
        await ddb.send(
            new PutItemCommand({
                TableName: DDB_TABLE_NAME,
                Item: {
                    PK: { S: pk },
                    report_json: { S: JSON.stringify(reportBody) },
                    expires_at: { N: String(ttl) },
                },
            })
        );
    } catch (err) {
        log('report_cache_write_error', { message: err.message });
    }
}

function hashVisitor(req) {
    const rawIp = req.ip || req.socket.remoteAddress || 'unknown';
    return crypto.createHash('sha256').update(`${VISITOR_HASH_SALT}:${rawIp}`).digest('hex').slice(0, 24);
}

async function checkVisitorRateLimit(bucketKey, maxRequests, windowSeconds) {
    const windowId = Math.floor(Date.now() / 1000 / windowSeconds);
    const pk = `RATE#${bucketKey}#${windowId}`;
    const ttl = (windowId + 2) * windowSeconds;

    try {
        const result = await ddb.send(
            new UpdateItemCommand({
                TableName: DDB_TABLE_NAME,
                Key: { PK: { S: pk } },
                UpdateExpression: 'SET req_count = if_not_exists(req_count, :zero) + :inc, expires_at = :ttl',
                ExpressionAttributeValues: {
                    ':zero': { N: '0' },
                    ':inc': { N: '1' },
                    ':ttl': { N: String(ttl) },
                },
                ReturnValues: 'UPDATED_NEW',
            })
        );
        return Number(result.Attributes.req_count.N) <= maxRequests;
    } catch (err) {
        log('rate_limit_ddb_error', { message: err.message });
        return true;
    }
}
// ---- DynamoDB & Gemini Call Cap ----------------------------------------------------

// ---- Generate Advice Outputs -------------------------------------------------------
async function getAdvice( { zip, date, gender, email, visitorId } ) {
    // Force normalization on email text safely
    const cleanEmail = String(email || '').toLowerCase().trim();
    const cleanZip = String(zip || '').trim();
    const cleanGender = String(gender || '').trim();
    const cleanDate = String(date || '').trim();

    // Multi-field Validation Checks
    if (!isValidZip(cleanZip)) {
        log('advice_rejected', { reason: 'invalid_zip', zip: cleanZip });
        return { status: 400, body: { error: 'invalid_zip', message: 'This service covers US locations only. Please enter a 5-digit US ZIP code such as 60616.', }, };
    }
    if (!isValidDate(cleanDate)) {
        log('advice_rejected', { reason: 'invalid_date', date: cleanDate });
        return { status: 400, body: { error: 'invalid_date', message: 'Date must be within the upcoming 7-day window.' } };
    }
    if (!isValidGender(cleanGender)) {
        log('advice_rejected', { reason: 'invalid_gender', gender: cleanGender });
        return { status: 400, body: { error: 'invalid_gender', message: 'Invalid clothing category selected.' } };
    }
    if (!isValidEmail(cleanEmail)) {
        log('advice_rejected', { reason: 'invalid_email' });
        return { status: 400, body: { error: 'invalid_email', message: 'Provide a valid email address.' } };
    }

    const started = Date.now();
    log('advice_request', { zip: cleanZip, date: cleanDate }); // Never log email or gender!

    const cachedReport = await getSavedReport(cleanZip, cleanDate, cleanGender);
    if (cachedReport) {
        log('advice_cache_hit', { zip: cleanZip, date: cleanDate });
        return { status: 200, body: { ...cachedReport, cached: true } };
    }

    if (visitorId) {
        const allowedReport = await checkVisitorRateLimit(
            `REPORT#${visitorId}`,
            VISITOR_REPORT_LIMIT_PER_MIN,
            60
        );
        if (!allowedReport) {
            log('visitor_rate_limited', { type: 'report', visitorId });
            return {
                status: 429,
                body: {
                    error: 'rate_limit_exceeded',
                    message: 'Too many report requests. Please wait a minute and try again.',
                },
            };
        }
    }

    let weather;
    try {
        // Query the Weather Tier using zip and date parameters
        const res = await fetch(`${WEATHER_URL}/weather?zip=${cleanZip}&date=${cleanDate}`, { 
            signal: AbortSignal.timeout(20000) 
        });
        
        if (res.status === 400 || res.status === 404) {
            log('advice_rejected', { reason: 'weather_' + res.status, zip: cleanZip });
            return { status: res.status, body: await res.json() };
        }
        if (!res.ok) throw new Error('weather_status_' + res.status);
        weather = await res.json();
    } catch (err) {
        log('weather_call_failed', { zip: cleanZip, message: err.message });
        return { status: 502, body: { error: 'weather_service_unavailable' } };
    }

    let advice, source;

    // Verify the daily AI free tier threshold limits first
    const isUnderCap = await checkAndIncrementGeminiCap(cleanDate);
    if (isUnderCap) {
        try {
            // Build prompt tailored to the clothing category choice safely
            const prompt = buildPrompt(weather, cleanGender);
            advice = await askGemini(prompt);
            source = 'gemini';
        } catch (err) {
            log('gemini_error', { zip: cleanZip, status: err.status || 0, reason: err.name === 'TimeoutError' ? 'timeout' : err.message });
            advice = fallbackAdvice(weather, cleanGender);
            source = 'fallback';
        }
    } else {
        // Fallback if the daily cap limit is hit
        log('gemini_cap_reached', { date: cleanDate });
        advice = fallbackAdvice(weather, cleanGender);
        source = 'fallback_cap_exceeded';
    }

    log('advice_success', { zip: cleanZip, source, ms: Date.now() - started });

    const reportBody = {
        ...weather,
        advice,
        source,
        model: source === 'gemini' ? GEMINI_MODEL : null,
        morning: { ...weather.morning, ...advice.morning },
        night: { ...weather.night, ...advice.night },
    };
    if (source === 'gemini') {
        await saveReport(cleanZip, cleanDate, cleanGender, reportBody);
    }
    return { status: 200, body: reportBody };
}
// ---- Generate Advice Outputs -------------------------------------------------------

// ---- URL to /health, /advice, / ----------------------------------------------------
app.get('/health', (_req, res) => {
    res.status(200).json({ status: 'ok', service: 'advisor'});
})

app.get('/advice', async (req, res) => {
    const { status, body } = await getAdvice({
        zip: req.query.zip,
        date: req.query.date,
        gender: req.query.gender,
        email: req.query.email,
        visitorId: hashVisitor(req),
    });
    res.status(status).json(body);
});

app.get('/', async (req, res) => {
    // Keep in mind time zone is based in UTC according to AWS as standard zone. 
    // Calculate 7-day date window dnyamically based on today's local date
    const today = new Date();
    const yesterday = new Date(today.getTime() - 24 * 60 * 60 * 1000);
    const formatDate = (d) => d.toISOString().split('T')[0];

    const minDate = formatDate(yesterday); 

    // Today + 6 days = 7 calendar days
    const maxDate = formatDate(new Date(today.getTime() + 6 * 24 * 60 * 60 * 1000)); 

    // Build the updated html form with the 4 required fields
    const form = `<form method="GET" action="/">
    <div>
        <label>Forecast Date: 
            <input type="date" name="date" min="${minDate}" max="${maxDate}" required>
        </label>
    </div>
    <br>
    <div>
        <label>US ZIP Code: 
            <input type="text" name="zip" pattern="[0-9]{5}" maxlength="5" placeholder="e.g. 60616" required>
        </label>
    </div>
    <br>
    <div>
        <label>Clothing Category: 
            <select name="gender" required>
                <option value="" disabled selected>-- Choose Category --</option>
                <option value="menswear">Menswear</option>
                <option value="womenswear">Womenswear</option>
                <option value="neutral">Neutral</option>
            </select>
        </label>
    </div>
    <br>
    <div>
        <label>Email Address: 
            <input type="email" name="email" placeholder="your@email.com" required>
        </label>
    </div>
    <br>
    <button type="submit">What should I wear?</button>
    </form>`;

    let result = '';

    // Simple layout handler when form is submitted
    if (req.query.zip && req.query.date && req.query.gender && req.query.email) {
        // Note: You will need to extend getAdvice() next to pass these new fields
        const { status, body } = await getAdvice({
            zip: req.query.zip,
            date: req.query.date,
            gender: req.query.gender,
            email: req.query.email,
            visitorId: hashVisitor(req),
        });

        if (status === 200) {
            const f = body.forecast;

            const cell = (val, source) => val !== undefined && val !== null 
                ? `${escapeHtml(val)} <span style="font-size:0.75em;color:#666;">(${escapeHtml(source)})</span>` 
                : `<em style="color:red;">Not Available</em>`;

            const m = body.morning || {};
            const n = body.night || {};
            const sources = body.sources || {};

            const staleBanner = body.stale
                ? `<p style="background:#fff3cd;border:1px solid #ffeeba;padding:8px;color:#856404;">
                    <strong>Notice:</strong> Live weather API is temporarily delayed. Showing cached forecast from ${escapeHtml(body.cacheAgeMinutes)} minute(s) ago.
                   </p>`
                : '';

            // Display 7-day forecast window
            const sevenDayRows = (body.sevenDayForecast || []).map(day => {
                const isSelected = day.date === req.query.date;
                const link = `/?date=${encodeURIComponent(day.date)}&zip=${encodeURIComponent(req.query.zip)}&gender=${encodeURIComponent(req.query.gender)}&email=${encodeURIComponent(req.query.email)}`;
                return `<tr style="${isSelected ? 'background-color:#e8f4fd; font-weight:bold;' : ''}">
                    <td><a href="${link}">${escapeHtml(day.date)}</a>${isSelected ? ' (Selected)' : ''}</td>
                    <td>${escapeHtml(day.high)}</td>
                    <td>${escapeHtml(day.low)}</td>
                    <td>${escapeHtml(day.summary)}</td>
                    </tr>`;
            }).join('');

            const sevenDaySection = sevenDayRows ? `
                <h3>7-Day Forecast Window</h3>
                <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%; text-align:left; margin-bottom:20px;">
                <thead>
                <tr style="background-color:#f2f2f2;">
                <th>Date (Click to View)</th>
                <th>High</th>
                <th>Low</th>
                <th>Conditions</th>
                </tr>
                </thead>
                <tbody>${sevenDayRows}</tbody>
                </table>` : '';

            result = `
            <hr>
            ${staleBanner}
            <h2>Report for ${escapeHtml(body.city)}, ${escapeHtml(body.state)} (${escapeHtml(body.zip)})</h2>
            <p><strong>Date:</strong> ${escapeHtml(req.query.date)} | <strong>Style Target:</strong> ${escapeHtml(req.query.gender)}</p>
            ${sevenDaySection}
            <h3>Detailed Morning &amp; Night Advisory (${escapeHtml(req.query.date)})</h3>
            <table border="1" cellpadding="6" style="border-collapse:collapse; width:100%; text-align:left;">
                <thead>
                    <tr style="background-color:#f2f2f2;">
                        <th>#</th>
                        <th>Weather Item</th>
                        <th>Morning Period</th>
                        <th>Night Period</th>
                    </tr>
                </thead>
                <tbody>
                    <tr><td>1</td><td><strong>Temperature</strong></td><td>${cell(m.temperature, sources.temperature || body.data_source)}</td><td>${cell(n.temperature, sources.temperature || body.data_source)}</td></tr>
                    <tr><td>2</td><td><strong>Wind Speed</strong></td><td>${cell(m.windSpeed, sources.windSpeed || body.data_source)}</td><td>${cell(n.windSpeed, sources.windSpeed || body.data_source)}</td></tr>
                    <tr><td>3</td><td><strong>Visibility</strong></td><td>${cell(m.visibility, sources.visibility || body.data_source)}</td><td>${cell(n.visibility, sources.visibility || body.data_source)}</td></tr>
                    <tr><td>4</td><td><strong>UV Index</strong></td><td>${cell(m.uv, sources.uv || 'Open-Meteo API')}</td><td>${cell(n.uv, sources.uv || 'Open-Meteo API')}</td></tr>
                    <tr><td>5</td><td><strong>Humidity</strong></td><td>${cell(m.humidity, sources.humidity || body.data_source)}</td><td>${cell(n.humidity, sources.humidity || body.data_source)}</td></tr>
                    <tr><td>6</td><td><strong>Rain Category</strong></td><td>${cell(m.rainCategory, 'Derived threshold rule')}</td><td>${cell(n.rainCategory, 'Derived threshold rule')}</td></tr>
                    <tr><td>7</td><td><strong>Snow Category</strong></td><td>${cell(m.snowCategory, 'Derived threshold rule')}</td><td>${cell(n.snowCategory, 'Derived threshold rule')}</td></tr>
                    <tr style="background-color:#fafafa;"><td>8</td><td><strong>Road Conditions</strong></td><td>${cell(m.roadConditions, body.source)}</td><td>${cell(n.roadConditions, body.source)}</td></tr>
                    <tr style="background-color:#fafafa;"><td>9</td><td><strong>Suggested Dressing</strong></td><td>${cell(m.suggestedDressing, body.source)}</td><td>${cell(n.suggestedDressing, body.source)}</td></tr>
                    <tr style="background-color:#fafafa;"><td>10</td><td><strong>Suggested Accessories</strong></td><td>${cell(m.suggestedAccessories, body.source)}</td><td>${cell(n.suggestedAccessories, body.source)}</td></tr>
                </tbody>
            </table>
            <br>
            <form method="POST" action="/email">
                <input type="hidden" name="target_email" value="${escapeHtml(req.query.email)}">
                <input type="hidden" name="zip" value="${escapeHtml(req.query.zip)}">
                <input type="hidden" name="date" value="${escapeHtml(req.query.date)}">
                <input type="hidden" name="gender" value="${escapeHtml(req.query.gender)}">
                <button type="submit">Email Report to ${escapeHtml(req.query.email)}</button>
            </form>
            <p style="font-size: 0.85em; color: #555; max-width: 650px;">
                <strong>Privacy &amp; AI Disclosure:</strong> Clothing category is used only to tailor outfit suggestions.
                Only location weather facts and your selected clothing category are sent to Google Gemini—your email address,
                IP address, and personal identity are never sent to Gemini and never written to logs.
            </p>
            <p><small>Suggestion source: ${escapeHtml(body.source)}</small></p>`;
        } else {
            result = `<p>Sorry: ${escapeHtml(body.error)}</p>`;
        }
    }

    res.send(`<h1>Weather Advisor</h1>${form}${result}`);
});

async function requestEmailConsent(cleanEmail) {
    await ses.send(
        new VerifyEmailIdentityCommand({
            EmailAddress: cleanEmail,
        })
    );
}
// ---- URL to /health, /advice, / ----------------------------------------------------

// ---- URL to /email (actually send emails to input email address) -------------------
app.post('/email', async (req, res) => {
    const cleanEmail = String(req.body.target_email || '').toLowerCase().trim();
    const cleanZip = String(req.body.zip || '').trim();
    const cleanDate = String(req.body.date || '').trim();
    const cleanGender = String(req.body.gender || '').trim();

    if (!isValidZip(cleanZip)) {
        return res.status(400).send('<h1>Invalid Request</h1><p>This service covers US locations only. Please enter a 5-digit US ZIP code such as 60616.</p><a href="/">Back</a>');
    }
    if (!isValidDate(cleanDate) || !isValidGender(cleanGender) || !isValidEmail(cleanEmail)) {
        return res.status(400).send('<h1>Invalid Request</h1><p>Please submit a valid forecast date, clothing category, and email address.</p><a href="/">Back</a>');
    }

    const visitorId = hashVisitor(req);
    const allowedEmail = await checkVisitorRateLimit(
        `EMAIL#${visitorId}`,
        VISITOR_EMAIL_LIMIT_PER_HOUR,
        3600
    );
    if (!allowedEmail) {
        log('visitor_rate_limited', { type: 'email', visitorId });
        return res.status(429).send('<h1>Rate Limit Exceeded</h1><p>You have reached the hourly limit for sending email reports. Please try again later.</p><a href="/">Back</a>');
    }

    try {
        // Compile the report first
        const compiledReport = await getAdvice({
            zip: cleanZip,
            date: cleanDate,
            gender: cleanGender,
            email: cleanEmail,
        });
        if (compiledReport.status !== 200) {
            throw new Error(compiledReport.body.message || compiledReport.body.error || 'Failed to generate report.');
        }

        // Attempt to send via SES; if unverified in sandbox, SES throws MessageRejected
        const sesParams = {
            Source: SENDER_EMAIL,
            Destination: { ToAddresses: [cleanEmail] },
            Message: {
                Subject: { Data: `Your Weather Advisor Report for ${cleanZip}` },
                Body: { Html: { Data: buildHtmlEmailBody(compiledReport.body) }, },
            },
        };

        try {
            await ses.send(new SendEmailCommand(sesParams));
        } catch (sesErr) {
            const msg = String(sesErr.message || '');
            if (sesErr.name === 'MessageRejected' || msg.includes('not verified')) {
                await requestEmailConsent(cleanEmail);
                log('email_waiting_confirmation', { zip: cleanZip });
                return res.status(202).send(`
                    <h1>Waiting for Email Confirmation</h1>
                    <p>Before we can deliver your report, <strong>${escapeHtml(cleanEmail)}</strong> must confirm consent.</p>
                    <p>We have sent a verification link from Amazon Web Services to <strong>${escapeHtml(cleanEmail)}</strong>. Please click that confirmation link in your inbox, then return to the report page and click <em>Email Report</em> again.</p>
                    <a href="/?zip=${encodeURIComponent(cleanZip)}&date=${encodeURIComponent(cleanDate)}&gender=${encodeURIComponent(cleanGender)}&email=${encodeURIComponent(cleanEmail)}">Return to Report</a>
                `);
            }
            throw sesErr;
        }

        log('email_sent_successfully', { zip: cleanZip });
        res.send(`
            <h1>Report Sent!</h1>
            <p>The weather advisory layout was successfully emailed to <strong>${escapeHtml(cleanEmail)}</strong>.</p>
            <a href="/">Generate another report</a>
        `);
    } catch (err) {
        log('email_dispatch_failed', { message: err.message });
        res.status(502).send(`<h1>Mailing Error</h1><p>Could not deliver email: ${escapeHtml(err.message)}</p>`);
    }
});
// ---- URL to /email (actually send emails to input email address) -------------------

app.listen(PORT, () => log('advisor_started', { port: PORT, model: GEMINI_MODEL }));