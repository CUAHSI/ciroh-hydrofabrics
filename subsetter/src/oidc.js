// ============================================================
// HydroShare OIDC Authentication (PKCE / Authorization Code Flow)
// Fill in the four REPLACE_WITH_* constants below, then remove
// the corresponding PUBLIC_RESOURCE_* fallbacks from config.js.
// ============================================================

// ---- Stub values — replace these ----
const OIDC_CLIENT_ID          = 'tAFcAwNZ1ghmDXI5aezpotv7MuVAMo3oIlT7BHHX';
const OIDC_AUTHORIZATION_URL  = 'https://hydroshare.org/o/authorize/';  // e.g. https://www.hydroshare.org/o/authorize/
const OIDC_TOKEN_URL          = 'https://hydroshare.org/o/token/';           // e.g. https://www.hydroshare.org/o/token/
const CREDENTIALS_API_URL     = 'https://hydroshare.org/hsapi/user/service/accounts/s3/';     // returns { access_key, secret_key }

// ---- Cookie helpers ----
const CREDS_COOKIE = 'hf_s3_creds';
const COOKIE_TTL_DAYS = 30;

function saveCredentialsCookie(creds) {
  const expires = new Date(creds.expiresAt).toUTCString();
  const payload = encodeURIComponent(JSON.stringify(creds));
  document.cookie = `${CREDS_COOKIE}=${payload}; expires=${expires}; path=/; SameSite=Strict`;
}

function loadCredentialsCookie() {
  const match = document.cookie.split('; ').find(row => row.startsWith(`${CREDS_COOKIE}=`));
  if (!match) return null;
  try {
    const creds = JSON.parse(decodeURIComponent(match.split('=').slice(1).join('=')));
    if (!creds?.accessKey || !creds?.secretKey || !creds?.expiresAt) return null;
    if (creds.expiresAt <= Date.now()) { clearCredentialsCookie(); return null; }
    return creds;
  } catch { return null; }
}

function clearCredentialsCookie() {
  document.cookie = `${CREDS_COOKIE}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/; SameSite=Strict`;
}

// ---- In-memory credential store ----
// Shape: { accessKey: string, secretKey: string, expiresAt: number } | null
// Seeded from cookie on module load so credentials survive page refreshes.
let _credentials = loadCredentialsCookie();

// ---- PKCE helpers ----
function generateCodeVerifier() {
  const bytes = new Uint8Array(64);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

async function generateCodeChallenge(verifier) {
  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(verifier),
  );
  return btoa(String.fromCharCode(...new Uint8Array(digest)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

function getRedirectUri() {
  const url = new URL(window.location.href);
  url.search = '';
  url.hash = '';
  return url.toString();
}

// ---- Public API ----

/** True when valid authenticated credentials are held in memory. */
export function isAuthenticated() {
  return !!_credentials && _credentials.expiresAt > Date.now();
}

/** Returns current in-memory credentials, or null if not authenticated. */
export function getActiveCredentials() {
  return isAuthenticated() ? _credentials : null;
}

/** Returns the OIDC bearer token if authenticated, otherwise null. */
export function getActiveBearerToken() {
  return isAuthenticated() ? (_credentials?.bearerToken ?? null) : null;
}

/**
 * Kick off OIDC login. Generates a PKCE challenge, saves the verifier to
 * sessionStorage, then redirects to the authorization endpoint.
 */
export async function beginLogin() {
  const verifier  = generateCodeVerifier();
  const challenge = await generateCodeChallenge(verifier);
  const state     = crypto.randomUUID();

  sessionStorage.setItem('oidc_code_verifier', verifier);
  sessionStorage.setItem('oidc_state', state);
  sessionStorage.setItem('oidc_redirect_from', window.location.href);

  const params = new URLSearchParams({
    response_type:         'code',
    client_id:             OIDC_CLIENT_ID,
    redirect_uri:          getRedirectUri(),
    state,
    code_challenge:        challenge,
    code_challenge_method: 'S256',
  });

  window.location.href = `${OIDC_AUTHORIZATION_URL}?${params}`;
}

/**
 * Call on every page load. Detects an OIDC callback (`?code=`), exchanges
 * the code for tokens, then fetches S3 credentials from CREDENTIALS_API_URL.
 *
 * @returns {boolean} true if a callback was handled, false otherwise.
 */
export async function handleOidcCallback() {
  const params = new URLSearchParams(window.location.search);
  const code   = params.get('code');
  if (!code) return false;

  // CSRF check
  const returnedState = params.get('state');
  const savedState    = sessionStorage.getItem('oidc_state');
  if (savedState && returnedState !== savedState) {
    throw new Error('OIDC state mismatch — possible CSRF attack');
  }

  const verifier = sessionStorage.getItem('oidc_code_verifier');
  if (!verifier) throw new Error('Missing PKCE code verifier');

  // Exchange authorization code for tokens
  const tokenRes = await fetch(OIDC_TOKEN_URL, {
    method:  'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body:    new URLSearchParams({
      grant_type:    'authorization_code',
      code,
      redirect_uri:  getRedirectUri(),
      client_id:     OIDC_CLIENT_ID,
      code_verifier: verifier,
    }),
  });
  if (!tokenRes.ok) throw new Error(`Token exchange failed: ${tokenRes.status}`);
  const tokens = await tokenRes.json();

  // Fetch S3 credentials using the OIDC access token
  const credsRes = await fetch(CREDENTIALS_API_URL, {
    method: 'POST',
    headers: { Authorization: `Bearer ${tokens.access_token}` },
  });
  if (!credsRes.ok) throw new Error(`Credentials API failed: ${credsRes.status}`);
  const creds = await credsRes.json();

  _credentials = {
    accessKey:   creds.access_key,
    secretKey:   creds.secret_key,
    bearerToken: tokens.access_token,
    expiresAt:   Date.now() + COOKIE_TTL_DAYS * 24 * 60 * 60 * 1000,
  };
  saveCredentialsCookie(_credentials);

  // Clean up session storage
  sessionStorage.removeItem('oidc_code_verifier');
  sessionStorage.removeItem('oidc_state');

  // Restore the pre-login URL (strip code/state params)
  const redirectFrom = sessionStorage.getItem('oidc_redirect_from') || window.location.pathname;
  sessionStorage.removeItem('oidc_redirect_from');
  window.history.replaceState(null, '', redirectFrom);

  return true;
}

/** Clear in-memory credentials and remove the cookie. */
export function logout() {
  _credentials = null;
  clearCredentialsCookie();
}
