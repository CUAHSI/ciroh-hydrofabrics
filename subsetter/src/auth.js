import {
    COMMUNITY_HF_DIVIDES,
    COMMUNITY_HF_FLOWPATHS,
    MERGED_PMTILES_URL,
    REF_DIVIDES_PMTILES_URL,
    REF_FLOWPATHS_PMTILES_URL,
    S3_ORIGIN,
    VPU_PMTILES_URL,
    getCredentials,
} from "./config.js";

const S3_REGION = 'us-east-1';
const S3_SERVICE = 's3';
const PRESIGN_TTL_SECONDS = 3600;
const PRESIGN_REFRESH_BUFFER_MS = 5 * 60 * 1000;
const presignedUrlCache = new Map();
const encoder = new TextEncoder();

function isS3OriginUrl(url) {
    return typeof url === 'string' && url.startsWith(S3_ORIGIN);
}

function encodeRfc3986(value) {
    return encodeURIComponent(value).replace(/[!'()*]/g, (char) =>
        `%${char.charCodeAt(0).toString(16).toUpperCase()}`
    );
}

function canonicalUri(pathname) {
    return pathname
        .split('/')
        .map((segment) => encodeRfc3986(decodeURIComponent(segment)))
        .join('/');
}

function canonicalQueryString(url, extraEntries) {
    const entries = [...url.searchParams.entries(), ...extraEntries]
        .map(([key, value]) => [encodeRfc3986(key), encodeRfc3986(value)])
        .sort(([keyA, valueA], [keyB, valueB]) => {
            if (keyA === keyB) return valueA.localeCompare(valueB);
            return keyA.localeCompare(keyB);
        });

    return entries.map(([key, value]) => `${key}=${value}`).join('&');
}

function toHex(bytes) {
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function sha256Hex(value) {
    const bytes = typeof value === 'string' ? encoder.encode(value) : value;
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    return toHex(new Uint8Array(digest));
}

async function hmacSha256(key, value) {
    const rawKey = typeof key === 'string' ? encoder.encode(key) : key;
    const cryptoKey = await crypto.subtle.importKey(
        'raw',
        rawKey,
        { name: 'HMAC', hash: 'SHA-256' },
        false,
        ['sign']
    );
    const bytes = typeof value === 'string' ? encoder.encode(value) : value;
    return new Uint8Array(await crypto.subtle.sign('HMAC', cryptoKey, bytes));
}

async function getSigningKey(secretKey, dateStamp) {
    const dateKey = await hmacSha256(`AWS4${secretKey}`, dateStamp);
    const regionKey = await hmacSha256(dateKey, S3_REGION);
    const serviceKey = await hmacSha256(regionKey, S3_SERVICE);
    return hmacSha256(serviceKey, 'aws4_request');
}

function getAmzDate(date) {
    return date.toISOString().replace(/[:-]|\.\d{3}/g, '');
}

async function presignS3GetUrl(rawUrl, accessKey, secretKey) {
    const url = new URL(rawUrl);
    const now = new Date();
    const amzDate = getAmzDate(now);
    const dateStamp = amzDate.slice(0, 8);
    const credentialScope = `${dateStamp}/${S3_REGION}/${S3_SERVICE}/aws4_request`;
    const signedHeaders = 'host';
    const extraQueryEntries = [
        ['X-Amz-Algorithm', 'AWS4-HMAC-SHA256'],
        ['X-Amz-Credential', `${accessKey}/${credentialScope}`],
        ['X-Amz-Date', amzDate],
        ['X-Amz-Expires', String(PRESIGN_TTL_SECONDS)],
        ['X-Amz-SignedHeaders', signedHeaders],
    ];
    const canonicalQuery = canonicalQueryString(url, extraQueryEntries);
    const canonicalRequest = [
        'GET',
        canonicalUri(url.pathname),
        canonicalQuery,
        `host:${url.host}`,
        '',
        signedHeaders,
        'UNSIGNED-PAYLOAD',
    ].join('\n');
    const stringToSign = [
        'AWS4-HMAC-SHA256',
        amzDate,
        credentialScope,
        await sha256Hex(canonicalRequest),
    ].join('\n');
    const signingKey = await getSigningKey(secretKey, dateStamp);
    const signature = toHex(await hmacSha256(signingKey, stringToSign));

    url.search = `${canonicalQuery}&X-Amz-Signature=${signature}`;
    return url.toString();
}

export async function getAuthorizedS3Url(rawUrl) {
    if (!isS3OriginUrl(rawUrl)) return rawUrl;
    const { accessKey, secretKey } = getCredentials();
    if (!accessKey || !secretKey) return rawUrl;

    const cacheKey = `${rawUrl}::${accessKey}`;
    const cached = presignedUrlCache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now() + PRESIGN_REFRESH_BUFFER_MS) {
        return cached.url;
    }

    const signedUrl = await presignS3GetUrl(rawUrl, accessKey, secretKey);
    presignedUrlCache.set(cacheKey, {
        url: signedUrl,
        expiresAt: Date.now() + (PRESIGN_TTL_SECONDS * 1000),
    });
    return signedUrl;
}

export function clearPresignedUrlCache() {
    presignedUrlCache.clear();
}

export async function fetchWithS3Auth(url, init = {}) {
    const authorizedUrl = await getAuthorizedS3Url(url);
    return fetch(authorizedUrl, init);
}

function createCredentialedPmtilesSource(url) {
    return {
    getKey() {
        return url;
    },
    async getBytes(offset, length, signal, etag) {
        const authorizedUrl = await getAuthorizedS3Url(url);
        const headers = new Headers();
        headers.set('range', `bytes=${offset}-${offset + length - 1}`);

        const resp = await fetch(authorizedUrl, {
        signal,
        headers,
        });

        const newEtag = resp.headers.get('Etag') || undefined;
        if (resp.status === 416 || (etag && newEtag && newEtag !== etag)) {
        throw new pmtiles.EtagMismatch(`Server returned non-matching ETag ${etag}`);
        }
        if (resp.status >= 300) {
        throw new Error(`Bad response code: ${resp.status}`);
        }

        const contentLength = resp.headers.get('Content-Length');
        if (resp.status === 200 && (!contentLength || +contentLength > length)) {
        throw new Error('Server returned no content-length header or content-length exceeding request. Check that your storage backend supports HTTP Byte Serving.');
        }

        return {
        data: await resp.arrayBuffer(),
        etag: newEtag,
        cacheControl: resp.headers.get('Cache-Control') || undefined,
        expires: resp.headers.get('Expires') || undefined,
        };
    },
    };
}

let _pmtilesProtocolSignature = '';

function currentPmtilesProtocolSignature() {
    return [
        REF_FLOWPATHS_PMTILES_URL,
        REF_DIVIDES_PMTILES_URL,
        COMMUNITY_HF_FLOWPATHS,
        COMMUNITY_HF_DIVIDES,
        MERGED_PMTILES_URL,
        VPU_PMTILES_URL,
    ].join('::');
}

export function ensurePmtilesProtocol() {
    const signature = currentPmtilesProtocolSignature();
    if (_pmtilesProtocolSignature === signature) return;

    const protocol = new pmtiles.Protocol({ metadata: true });
    protocol.add(new pmtiles.PMTiles(createCredentialedPmtilesSource(REF_FLOWPATHS_PMTILES_URL)));
    protocol.add(new pmtiles.PMTiles(createCredentialedPmtilesSource(REF_DIVIDES_PMTILES_URL)));
    protocol.add(new pmtiles.PMTiles(createCredentialedPmtilesSource(COMMUNITY_HF_FLOWPATHS)));
    protocol.add(new pmtiles.PMTiles(createCredentialedPmtilesSource(COMMUNITY_HF_DIVIDES)));
    protocol.add(new pmtiles.PMTiles(createCredentialedPmtilesSource(MERGED_PMTILES_URL)));
    protocol.add(new pmtiles.PMTiles(createCredentialedPmtilesSource(VPU_PMTILES_URL)));

    maplibregl.addProtocol('pmtiles', protocol.tile);
    _pmtilesProtocolSignature = signature;
}