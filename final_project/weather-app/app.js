const fs = require('fs');
const express = require('express');
const { Pool } = require('pg');
const { SSMClient, GetParameterCommand } = require('@aws-sdk/client-ssm');

const app = express();
const PORT = process.env.PORT || 3000;
const ZIP_API = process.env.ZIP_API_BASE || 'https://api.zippopotam.us';
const NWS_API = process.env.NWS_API_BASE || 'https://api.weather.gov';
// The National Weather Service asks every client to identify itself.
const USER_AGENT = process.env.NWS_USER_AGENT || '(itmo-544 weather lab, jwong18@hawk.illinoistech.edu)';

// Database settings. With no DB_HOST the service still works, it just does not store anything.
const DB_HOST = process.env.DB_HOST;
const DB_PORT = Number(process.env.DB_PORT || 5432);
const DB_NAME = process.env.DB_NAME || 'weather';
const DB_USER = process.env.DB_USER || 'weatherapp';
const DB_PASSWORD_PARAM = process.env.DB_PASSWORD_PARAM || '/itmo-544/db-password';
const DB_CA_FILE = process.env.DB_CA_FILE || '/opt/app/rds-ca.pem';
const CACHE_SECONDS = Number(process.env.CACHE_SECONDS || 600);
const DB_RETRY_MS = 30000; // after a database failure, leave the database alone for 30 seconds

const ssm = new SSMClient({ region: process.env.AWS_REGION });
const log = (event, fields = {}) => console.log(JSON.stringify({ ts: new Date().toISOString(), event, ...fields }));

class UpstreamError extends Error {
    constructor(stage, status) {
        super(`${stage}	failed`);
        this.stage = stage;
        this.status = status;
    }
}

// Fetch JSON with a timeout and one retry. Returns null on a 404, throws UpstreamError.
async function fetchJson(stage, url, headers = {}) {
    let status = 0;
    for (let attempt = 1; attempt <= 2; attempt++) {
        try {
            const res = await fetch(url, { headers, signal: AbortSignal.timeout(8000) });
            status = res.status;
            if (res.ok) return await res.json();
            if (res.status === 404) return null;
            if (res.status < 500 && res.status !== 429) break; // a client error will not fix itself
        } catch (err) {
            status = 0; // timeout or network failure
        } 
        if (attempt < 2) await new Promise((resolve) => setTimeout(resolve, 500));
    }
    throw new UpstreamError(stage, status);
}

// ---- Database helpers ------------------------------------------------------------------
let poolPromise = null;
let dbRetryAt = 0;
async function readDbPassword() {
    if (process.env.DB_PASSWORD) return process.env.DB_PASSWORD;
    const out = await ssm.send(new GetParameterCommand({ Name: DB_PASSWORD_PARAM, WithDecryption: true }));
    return out.Parameter.Value;
}

async function createPool() {
    const password = await readDbPassword();
    // Verify the server certificate against the RDS CA bundle, so the connection is encrypted
    // and we know we are talking to RDS and not to something in the middle.
    const ssl = process.env.DB_SSL === 'off' ? false : { ca: fs.readFileSync(DB_CA_FILE, 'utf8') };
    const pool = new Pool({
        host: DB_HOST, port: DB_PORT, database: DB_NAME, user: DB_USER, password, ssl,
        max: 4, connectionTimeoutMillis: 3000, idleTimeoutMillis: 30000, statement_timeout: 3000,
    });
    pool.on('error', (err) => log('db_error', { stage: 'pool', message: err.message }));
    try {
        await pool.query(`CREATE TABLE IF NOT EXISTS lookups (
            id BIGSERIAL PRIMARY KEY,
            zip CHAR(5) NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now())`);
        await pool.query('CREATE INDEX IF NOT EXISTS lookups_zip_created ON lookups (zip, created_at DESC)');
    } catch (err) {
        await pool.end().catch(() => {});
        throw err;
    }
    return pool;
}

// Returns a ready pool, or throws. A failed attempt is not remembered, so the next try starts fresh.
function getPool() {
    if (!poolPromise) {
        poolPromise = createPool().catch((err) => {
            poolPromise = null;
            throw err;
        });
    }
    return poolPromise;
}

// Run one database call. Any failure is logged, and the database is skipped for a short time,
// so a broken database costs each request nothing instead of a 3 second wait.
async function withDb(stage, fn) {
    if (!DB_HOST) return { state: 'disabled' };
    if (Date.now() < dbRetryAt) return { state: 'unavailable' };
    try {
        return { state: 'ok', value: await fn(await getPool()) };
    } catch (err) {
        dbRetryAt = Date.now() + DB_RETRY_MS;
        log('db_error', { stage, message: err.message });
        return { state: 'unavailable' };
    }
}

const findFresh = (zip, dateParam) => withDb('read', async (pool) => {
    const r = await pool.query(
        `SELECT payload FROM lookups
        WHERE zip = $1 AND payload->>'date' = $2 AND created_at > now() - make_interval(secs => $3)
        ORDER BY created_at DESC LIMIT 1`, [zip, dateParam, CACHE_SECONDS]
    );
    return r.rows.length ? r.rows[0].payload : null;
});

async function findStale(zip, targetDate) {
    const res = await withDb('stale_read', async (pool) => {
        const query = targetDate
            ? `SELECT payload, EXTRACT(EPOCH FROM (now() - created_at)) AS age_seconds
               FROM lookups
               WHERE zip = $1 AND payload->>'date' = $2 AND created_at > now() - interval '24 hours'
               ORDER BY created_at DESC LIMIT 1`
            : `SELECT payload, EXTRACT(EPOCH FROM (now() - created_at)) AS age_seconds
               FROM lookups
               WHERE zip = $1 AND created_at > now() - interval '24 hours'
               ORDER BY created_at DESC LIMIT 1`;
        const params = targetDate ? [zip, targetDate] : [zip];
        const r = await pool.query(query, params);
        return r.rows.length ? r.rows[0] : null;
    });

    if (res.state !== 'ok' || !res.value) return null;
    return {
        body: res.value.payload,
        cacheAgeMinutes: Math.max(1, Math.round(Number(res.value.age_seconds) / 60)),
    };
}

const saveLookup = (zip, payload) => withDb('write', (pool) => 
    pool.query('INSERT INTO lookups (zip, payload) VALUES ($1, $2)', [zip, JSON.stringify(payload)])
);
// ---- Database helpers ------------------------------------------------------------------

// ---- Threshold Calculators for Derived Categories --------------------------------------
function deriveRainCategory(probs, hasSnow = false) {
    if (!probs || probs.length === 0) return 'Not Available';
    if (hasSnow) return 'No';
    const maxProb = Math.max(...probs);
    if (maxProb >= 60) return 'Heavy';
    if (maxProb >= 20) return 'Mild';
    return 'No';
}

function deriveSnowCategory(probs, isSnowForecast) {
    if (!probs || probs.length === 0) return 'Not Available';
    if (!isSnowForecast) return 'No';
    const maxProb = Math.max(...probs);
    if (maxProb >= 60) return 'Heavy';
    if (maxProb >= 20) return 'Mild';
    return 'No';
}
// ---- Threshold Calculators for Derived Categories --------------------------------------

// ---- Open Meteo for UV Index & Visibility since NWS doesn't offer ----------------------
function extractHourlyMetrics(hourlyPeriods, targetDate, timeZone) {
    const morning = { temps: [], winds: [], vis: [], humidities: [], rainProbs: [], snowProbs: [], isSnow: false };
    const night = { temps: [], winds: [], vis: [], humidities: [], rainProbs: [], snowProbs: [], isSnow: false };

    for (const p of hourlyPeriods || []) {
        const local = getLocalParts(p.startTime, timeZone);
        if (local.date !== targetDate) continue;

        const bucket =
            local.hour >= 6 && local.hour <= 11
                ? morning
                : local.hour >= 18 && local.hour <= 23
                ? night
                : null;
        if (!bucket) continue;

        if (typeof p.temperature === 'number') bucket.temps.push(p.temperature);
        const w = parseWindMph(p.windSpeed);
        if (w !== null) bucket.winds.push(w);
        if (p.visibility && typeof p.visibility.value === 'number') {
            bucket.vis.push(p.visibility.value / 1609.344);
        }
        if (p.relativeHumidity && typeof p.relativeHumidity.value === 'number') {
            bucket.humidities.push(p.relativeHumidity.value);
        }

        const prob = (p.probabilityOfPrecipitation && p.probabilityOfPrecipitation.value != null) ? p.probabilityOfPrecipitation.value : null;
        const forecastText = (p.shortForecast || '').toLowerCase();
        const isSnowForecast =
            forecastText.includes('snow') || forecastText.includes('blizzard') || forecastText.includes('flurr');

        if (prob !== null) {
            if (isSnowForecast) {
                bucket.snowProbs.push(prob);
                if (prob > 0) bucket.isSnow = true;
            } else {
                bucket.rainProbs.push(prob);
            }
        }
    }
    return { morning, night };
}

function getLocalParts(isoStringOrDate, timeZone) {
    const dt = isoStringOrDate instanceof Date ? isoStringOrDate : new Date(isoStringOrDate);
    const tz = timeZone || 'America/Chicago';
    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: tz,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        hour12: false,
    }).formatToParts(dt);

    const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
    const hourNum = Number(map.hour) % 24;
    return {
        date: `${map.year}-${map.month}-${map.day}`,
        hour: hourNum,
    };
}
// ---- Open Meteo for UV Index & Visibility since NWS doesn't offer ----------------------

// ---- URL with pages to Health, History -------------------------------------------------
app.get('/', (req, res) => {
    res.json({ service: 'weather', usage: '/weather?zip=<12345>&date=<YYYY-MM-DD>', history: '/history' , health: '/health'});
});

app.get('/health', (_req, res) => {
    res.status(200).json({ status: 'ok', service: 'weather' });
});

// The ten most recent lookups that were saved in the database.
app.get('/history', async (req, res) => {
    const result = await withDb('history', async (pool) => {
        const r = await pool.query(
            `SELECT id, zip,
             payload->>'city' AS city,
             payload->>'state' AS state,
             payload->>'date' AS date,
             payload->'morning'->>'temperature' AS morning_temp,
             payload->'night'->>'temperature' AS night_temp,
             created_at
             FROM lookups ORDER BY created_at DESC LIMIT 10`
        );
        return r.rows;
    });
    if (result.state === 'disabled') return res.status(503).json({ error: 'database_disabled' });
    if (result.state === 'unavailable') return res.status(503).json({ error: 'database_unavailable' });
    
    const lines = result.value.map(row => JSON.stringify(row)).join('\n');
    return res.type('text/plain').send(`Count: ${result.value.length}\n${lines}\n`);
});
// ---- URL with pages to Health, History -------------------------------------------------

// ---- Weather Helpers -------------------------------------------------------------------
// Check Weather - Windy
function parseWindMph(windStr) {
    if (!windStr || typeof windStr !== 'string') return null;
    const matches = windStr.match(/\d+/g);
    if (!matches || matches.length === 0) return null;
    return Math.max(...matches.map(Number));
}

// Calculate Average
function avg(arr) {
    if (!arr || arr.length === 0) return null;
    const sum = arr.reduce((a, b) => a + b, 0);
    return Math.round((sum / arr.length) * 10) / 10;
}

// Value for Maximum
function maxVal(arr) {
    if (!arr || arr.length === 0) return null;
    return Math.max(...arr);
}

// Function to fetch two values: UV Index and Visibility
function extractOpenMeteoMetrics(openMeteoData, targetDate) {
    const result = { uv: { morning: null, night: null }, vis: { morning: null, night: null }, };
    const hourly = openMeteoData && openMeteoData.hourly;
    if (!hourly || !Array.isArray(hourly.time)) return result;

    const mUv = [];
    const nUv = [];
    const mVis = [];
    const nVis = [];

    for (let i = 0; i < hourly.time.length; i++) {
        const ts = hourly.time[i];
        if (ts.slice(0, 10) !== targetDate) continue;

        const hour = Number(ts.slice(11, 13));
        const uvVal = hourly.uv_index ? hourly.uv_index[i] : null;
        const visMeters = hourly.visibility ? hourly.visibility[i] : null;

        if (hour >= 6 && hour <= 11) {
            if (typeof uvVal === 'number') mUv.push(uvVal);
            if (typeof visMeters === 'number') mVis.push(visMeters / 1609.344);
        } else if (hour >= 18 && hour <= 23) {
            if (typeof uvVal === 'number') nUv.push(uvVal);
            if (typeof visMeters === 'number') nVis.push(visMeters / 1609.344);
        }
    }

    result.uv.morning = maxVal(mUv);
    result.uv.night = maxVal(nUv);
    result.vis.morning = avg(mVis);
    result.vis.night = avg(nVis);
    return result;
}

// Collect data from thid-party APIs to check if else statements before making data outputs
function supplementFromStandardPeriods(standardPeriods, targetDate, timeZone, isMorning, bucket) {
    if (bucket.temps.length > 0) return;
    const match = (standardPeriods || []).find((sp) => {
        const localDate = getLocalParts(sp.startTime, timeZone).date;
        return localDate === targetDate && (isMorning ? sp.isDaytime : !sp.isDaytime);
    });
    if (!match) return;

    if (typeof match.temperature === 'number') bucket.temps.push(match.temperature);
    const w = parseWindMph(match.windSpeed);
    if (w !== null) bucket.winds.push(w);
    if (match.relativeHumidity && typeof match.relativeHumidity.value === 'number') {
        bucket.humidities.push(match.relativeHumidity.value);
    }
    const prob = (match.probabilityOfPrecipitation && match.probabilityOfPrecipitation.value != null) ? match.probabilityOfPrecipitation.value : null;
    const forecastText = (match.shortForecast || '').toLowerCase();
    const isSnowForecast =
        forecastText.includes('snow') || forecastText.includes('blizzard') || forecastText.includes('flurr');
    if (prob !== null) {
        if (isSnowForecast) {
            bucket.snowProbs.push(prob);
            if (prob > 0) bucket.isSnow = true;
        } else {
            bucket.rainProbs.push(prob);
        }
    }
}

// Display 7-day window on screen
function buildSevenDaySummary(hourlyPeriods, standardPeriods, timeZone) {
    const dailyMap = new Map();

    for (const p of hourlyPeriods || []) {
        const localDate = getLocalParts(p.startTime, timeZone).date;
        if (!dailyMap.has(localDate)) {
            dailyMap.set(localDate, { temps: [], summary: p.shortForecast || 'Clear' });
        }
        if (typeof p.temperature === 'number') {
            dailyMap.get(localDate).temps.push(p.temperature);
        }
    }

    for (const sp of standardPeriods || []) {
        const localDate = getLocalParts(sp.startTime, timeZone).date;
        if (!dailyMap.has(localDate)) {
            dailyMap.set(localDate, { temps: [], summary: sp.shortForecast || 'Clear' });
        }
        const entry = dailyMap.get(localDate);
        if (typeof sp.temperature === 'number') {
            entry.temps.push(sp.temperature);
        }
        if (sp.isDaytime && sp.shortForecast) {
            entry.summary = sp.shortForecast;
        }
    }

    const sortedDates = Array.from(dailyMap.keys()).sort().slice(0, 7);
    return sortedDates.map((date) => {
        const data = dailyMap.get(date);
        const high = data.temps.length ? `${Math.max(...data.temps)}°F` : 'Not Available';
        const low = data.temps.length ? `${Math.min(...data.temps)}°F` : 'Not Available';
        return { date, high, low, summary: data.summary };
    });
}

const isValidZip = (zip) => /^\d{5}$/.test(zip);
// ---- Weather Helpers -------------------------------------------------------------------

// ---- Updated Weather Data Route --------------------------------------------------------
app.get('/weather', async (req, res) => {
    const zip = String(req.query.zip || '').trim();
    const rawDate = req.query.date ? String(req.query.date).trim() : null;

    if (!isValidZip(zip) || (rawDate && !/^\d{4}-\d{2}-\d{2}$/.test(rawDate))) {
        log('weather_rejected', { reason: 'invalid_parameters', zip });
        return res.status(400).json({
            error: 'invalid_zip',
            message: 'This service covers US locations only. Please enter a 5-digit US ZIP code such as 60616.',
        });
    }

    const started = Date.now();
    let effectiveDate = rawDate;

    try {
        if (effectiveDate) {
            const cached = await findFresh(zip, effectiveDate);
            if (cached.state === 'ok' && cached.value && cached.value.date === effectiveDate) {
                log('weather_success', { zip, cache: 'hit', ms: Date.now() - started });
                return res.json({ ...cached.value, cache: 'hit' });
            }
        }

        // Geocode ZIP code coordinates FIRST (fixes "lat is not defined")
        const lookup = await fetchJson('zip_lookup', `${ZIP_API}/us/${zip}`);
        if (!lookup || !lookup.places || lookup.places.length === 0) {
            log('weather_rejected', { reason: 'zip_not_found', zip });
            return res.status(404).json({ error: 'zip_not_found', message: `ZIP code ${zip} was not found.` });
        }
        const place = lookup.places[0];
        const lat = Number(place.latitude).toFixed(4);
        const lon = Number(place.longitude).toFixed(4);
        const city = place['place name'];
        const state = place['state abbreviation'];

        // Query NWS grid metadata point
        const headers = { 'User-Agent': USER_AGENT, Accept: 'application/geo+json' };
        const point = await fetchJson('nws_points', `${NWS_API}/points/${lat},${lon}`, headers);
        if (!point || !point.properties) {
            log('weather_rejected', { reason: 'no_nws_coverage', zip });
            return res.status(404).json({ error: 'no_nws_coverage' });
        }

        const timeZone = point.properties.timeZone || 'America/Chicago';
        effectiveDate = rawDate || getLocalParts(new Date(), timeZone).date;

        log('weather_request', { zip, date: effectiveDate });

        if (!rawDate) {
            const cached = await findFresh(zip, effectiveDate);
            if (cached.state === 'ok' && cached.value && cached.value.date === effectiveDate) {
                log('weather_success', { zip, cache: 'hit', ms: Date.now() - started });
                return res.json({ ...cached.value, cache: 'hit' });
            }
        }

        // Fetch NWS hourly, 12-hour standard forecast, and Open-Meteo UV/visibility in parallel
        const openMeteoUrl = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&hourly=uv_index,visibility&timezone=auto&forecast_days=7`;

        const [forecastData, standardForecastData, openMeteoData] = await Promise.all([
            fetchJson('nws_forecast_hourly', point.properties.forecastHourly, headers),
            fetchJson('nws_forecast_12h', point.properties.forecast, headers),
            fetchJson('open_meteo_uv', openMeteoUrl).catch((err) => {
                log('open_meteo_failed', { stage: err.stage, status: err.status, url: openMeteoUrl });
                return null;
            }),
        ]);

        const standardPeriods = (standardForecastData && standardForecastData.properties && standardForecastData.properties.periods) || [];
        const hourlyPeriods = (forecastData && forecastData.properties && forecastData.properties.periods) || [];

        const { morning: mBucket, night: nBucket } = extractHourlyMetrics(hourlyPeriods, effectiveDate, timeZone);
        supplementFromStandardPeriods(standardPeriods, effectiveDate, timeZone, true, mBucket);
        supplementFromStandardPeriods(standardPeriods, effectiveDate, timeZone, false, nBucket);

        const sevenDayForecast = buildSevenDaySummary(hourlyPeriods, standardPeriods, timeZone);
        const om = extractOpenMeteoMetrics(openMeteoData, effectiveDate);

        // Collect data to assign variables then print the assigned variables with whichever source from.
        const mTemp = avg(mBucket.temps);
        const nTemp = avg(nBucket.temps);
        const mWind = maxVal(mBucket.winds);
        const nWind = maxVal(nBucket.winds);
        const mHum = avg(mBucket.humidities);
        const nHum = avg(nBucket.humidities);

        let visibilitySource = 'National Weather Service API';
        let mVis = avg(mBucket.vis);
        let nVis = avg(nBucket.vis);

        if (mVis === null && om.vis.morning !== null) {
            mVis = om.vis.morning;
            visibilitySource = 'Open-Meteo API';
        }
        if (nVis === null && om.vis.night !== null) {
            nVis = om.vis.night;
            visibilitySource = 'Open-Meteo API';
        }

        const mUv = om.uv.morning;
        const nUv = om.uv.night;

        const morning = {
            temperature: mTemp !== null ? `${Math.round(mTemp)} F` : 'Not Available',
            windSpeed: mWind !== null ? `${mWind} mph` : 'Not Available',
            visibility: mVis !== null ? `${mVis} mi` : 'Not Available',
            uv: mUv !== null ? `${mUv}` : 'Not Available',
            humidity: mHum !== null ? `${Math.round(mHum)}%` : 'Not Available',
            rainCategory: deriveRainCategory(mBucket.rainProbs, mBucket.isSnow),
            snowCategory: deriveSnowCategory(mBucket.snowProbs, mBucket.isSnow),
        };

        const night = {
            temperature: nTemp !== null ? `${Math.round(nTemp)} F` : 'Not Available',
            windSpeed: nWind !== null ? `${nWind} mph` : 'Not Available',
            visibility: nVis !== null ? `${nVis} mi` : 'Not Available',
            uv: nUv !== null ? `${nUv}` : 'Not Available',
            humidity: nHum !== null ? `${Math.round(nHum)}%` : 'Not Available',
            rainCategory: deriveRainCategory(nBucket.rainProbs, nBucket.isSnow),
            snowCategory: deriveSnowCategory(nBucket.snowProbs, nBucket.isSnow),
        };

        const body = {
            zip,
            date: effectiveDate,
            city,
            state,
            lat,
            lon,
            data_source: 'National Weather Service API',
            sources: {
                temperature: 'National Weather Service API',
                windSpeed: 'National Weather Service API',
                visibility: visibilitySource,
                uv: 'Open-Meteo API',
                humidity: 'National Weather Service API',
                rainCategory: 'Derived threshold rule',
                snowCategory: 'Derived threshold rule',
            },
            sevenDayForecast,
            morning,
            night,
        };

        const saved = await saveLookup(zip, body);
        const cache = saved.state === 'ok' ? 'miss' : saved.state;
        log('weather_success', { zip, cache, ms: Date.now() - started });
        return res.json({ ...body, cache });
    } catch (err) {
        log('weather_fetch_failed', { zip, message: err.message });

        const stale = await findStale(zip, effectiveDate).catch(() => null);
        if (stale) {
            log('weather_stale_cache_used', { zip, ageMinutes: stale.cacheAgeMinutes });
            return res.status(200).json({
                ...stale.body,
                cached: true,
                stale: true,
                cacheAgeMinutes: stale.cacheAgeMinutes,
            });
        }

        return res.status(502).json({
            error: 'weather_unavailable',
            message: 'The weather service is currently unavailable. Please try again later.',
        });
    }
});
// ---- Updated Weather Data Route --------------------------------------------------------

app.listen(PORT, () => log('weather_started', { port: PORT }));