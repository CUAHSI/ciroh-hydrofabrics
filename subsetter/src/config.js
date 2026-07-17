import { getActiveCredentials, getActiveBearerToken } from './oidc.js';

export const S3_ORIGIN = `https://s3.hydroshare.org`;

/**
 * Returns the active S3 credentials.
 * Requires an authenticated OIDC session.
 */
export function getCredentials() {
  const authed = getActiveCredentials();
  if (authed) return { accessKey: authed.accessKey, secretKey: authed.secretKey };
  throw new Error('Authentication required');
}

// Read resource id from query params, e.g. ?resource_id=<id>
const _queryResourceId = (new URLSearchParams(window.location.search).get('resource_id') || '').trim();
export const DEFAULT_RESOURCE_ID = 'e280863b7c31415f880432764c5b8eb1';

export const VIEWER_MODE = true;
export let RESOURCE_ID = _queryResourceId || DEFAULT_RESOURCE_ID;

/** Update the active resource ID and recompute all dependent URLs. */
export function setResourceId(id) {
  RESOURCE_ID = id;
  _recomputeUrls();
}

let _bucketName = '';

/**
 * Fetch the S3 bucket name for the given resource id and recompute all
 * dependent URL exports.
 *
 * When strict=true, throws on lookup errors so callers can abort loading.
 * When strict=false, logs and keeps the previous bucket value.
 * Call this before booting the viewer.
 */
export async function initBucketName(resourceId) {
  const token = getActiveBearerToken();
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const res = await fetch(`https://hydroshare.org/hsapi/resource/s3/${resourceId}/`, { headers });
  if (!res.ok) {
    throw new Error(`S3 bucket lookup failed: ${res.status}`);
  }
  const data = await res.json();
  if (!data?.bucket) {
    throw new Error('S3 bucket lookup returned no bucket name');
  }
  _bucketName = data.bucket;
  _recomputeUrls();
}

function _recomputeUrls() {
  S3_PARQUET           = `${S3_ORIGIN}/${_bucketName}/${RESOURCE_ID}/data/contents/parquet`;
  S3_MAP               = `${S3_ORIGIN}/${_bucketName}/${RESOURCE_ID}/data/contents/map`;
  NETWORK_GRAPH_URL    = `${S3_PARQUET}/network_graph.json`;
  REF_FLOWPATHS_PMTILES_URL = `${S3_MAP}/only_geometry/reference/flowpaths.pmtiles`;
  REF_DIVIDES_PMTILES_URL   = `${S3_MAP}/only_geometry/reference/divides.pmtiles`;
  RES_DIVIDES_PMTILES_URL   = `${S3_MAP}/only_geometry/reference/divides.pmtiles`;
  RES_FLOWPATHS_PMTILES_URL = `${S3_MAP}/only_geometry/reference/flowpaths.pmtiles`;
  MERGED_PMTILES_URL   = `${S3_MAP}/merged.pmtiles`;
  VPU_PMTILES_URL      = `${S3_MAP}/only_geometry/reference/vpu.pmtiles`;
  const communityOrigin = `${S3_ORIGIN}/${_bucketName}/${RESOURCE_ID}/data/contents/community`;
  COMMUNITY_HF_ORIGIN  = communityOrigin;
  COMMUNITY_HF_MAP     = `${communityOrigin}/map`;
  COMMUNITY_HF_DIVIDES   = `${COMMUNITY_HF_MAP}/only_geometry/reference/divides.pmtiles`;
  COMMUNITY_HF_FLOWPATHS = `${COMMUNITY_HF_MAP}/only_geometry/reference/flowpaths.pmtiles`;
  PARQUET_URLS['divides']                = `${S3_PARQUET}/divides.parquet`;
  PARQUET_URLS['divide-attributes']      = `${S3_PARQUET}/divide-attributes.parquet`;
  PARQUET_URLS['flowpaths']              = `${S3_PARQUET}/flowpaths.parquet`;
  PARQUET_URLS['flowpath-attributes']    = `${S3_PARQUET}/flowpath-attributes.parquet`;
  PARQUET_URLS['flowpath-attributes-ml'] = `${S3_PARQUET}/flowpath-attributes-ml.parquet`;
  PARQUET_URLS['hydrolocations']         = `${S3_PARQUET}/hydrolocations.parquet`;
  PARQUET_URLS['nexus']                  = `${S3_PARQUET}/nexus.parquet`;
  PARQUET_URLS['pois']                   = `${S3_PARQUET}/pois.parquet`;
  PARQUET_URLS['lakes']                  = `${S3_PARQUET}/lakes.parquet`;
  PARQUET_URLS['network']                = `${S3_PARQUET}/network.parquet`;
}

export let S3_PARQUET           = `${S3_ORIGIN}/${_bucketName}/${RESOURCE_ID}/data/contents/parquet`;
export let S3_MAP               = `${S3_ORIGIN}/${_bucketName}/${RESOURCE_ID}/data/contents/map`;
export let NETWORK_GRAPH_URL    = `${S3_PARQUET}/network_graph.json`;
export let REF_FLOWPATHS_PMTILES_URL = `${S3_MAP}/only_geometry/reference/flowpaths.pmtiles`;
export let REF_DIVIDES_PMTILES_URL   = `${S3_MAP}/only_geometry/reference/divides.pmtiles`;

//researcher's pre-generated pmtiles
export let RES_DIVIDES_PMTILES_URL   = `${S3_MAP}/only_geometry/reference/divides.pmtiles`;
export let RES_FLOWPATHS_PMTILES_URL = `${S3_MAP}/only_geometry/reference/flowpaths.pmtiles`;

//styles
export let MERGED_PMTILES_URL   = `${S3_MAP}/merged.pmtiles`;
export let VPU_PMTILES_URL      = `${S3_MAP}/only_geometry/reference/vpu.pmtiles`;

//community hydrofabric reference
export let COMMUNITY_HF_ORIGIN    = `${S3_ORIGIN}/${_bucketName}/${RESOURCE_ID}/data/contents/community`;
export let COMMUNITY_HF_MAP       = `${COMMUNITY_HF_ORIGIN}/map`;
export let COMMUNITY_HF_DIVIDES   = `${COMMUNITY_HF_MAP}/only_geometry/reference/divides.pmtiles`;
export let COMMUNITY_HF_FLOWPATHS = `${COMMUNITY_HF_MAP}/only_geometry/reference/flowpaths.pmtiles`;

export let pmtilesProtocolRegistered = false;
export function isPmtilesProtocolRegistered() {
  return pmtilesProtocolRegistered;
}
export function setPmtilesProtocolRegistered(val) { pmtilesProtocolRegistered = val;}


export const PARQUET_URLS = {
  'divides':                `${S3_PARQUET}/divides.parquet`,
  'divide-attributes':      `${S3_PARQUET}/divide-attributes.parquet`,
  'flowpaths':              `${S3_PARQUET}/flowpaths.parquet`,
  'flowpath-attributes':    `${S3_PARQUET}/flowpath-attributes.parquet`,
  'flowpath-attributes-ml': `${S3_PARQUET}/flowpath-attributes-ml.parquet`,
  'hydrolocations':         `${S3_PARQUET}/hydrolocations.parquet`,
  'nexus':                  `${S3_PARQUET}/nexus.parquet`,
  'pois':                   `${S3_PARQUET}/pois.parquet`,
  'lakes':                  `${S3_PARQUET}/lakes.parquet`,
  'network':                `${S3_PARQUET}/network.parquet`,
};

export const state = {
  networkGraph: null,
  adjacency: null,
  downstream: null,


  //for selection
  outletCatId: null,
  upstreamCatIds: [],
  upstreamNumericIds: new Set(),

  //map stuff
  map: null,
  mapRight: null,
  splitActive: false,
  syncing: false,

  // hyparquet
  hp: null,
  compressors: null,
  fileHandleCache: {},

  // viewer
  inferredVpuid: null,
  researcherBbox: null,
  usingPmtiles: false,
};

// ============================================================
// LOGGING
// ============================================================
const logEl = document.getElementById('log');
export function log(msg, cls = '') {
  const span = document.createElement('span');
  span.className = cls;
  span.textContent = msg + '\n';
  logEl.appendChild(span);
  logEl.parentElement.scrollTop = logEl.parentElement.scrollHeight;
}
export function setProgress(pct) {
  document.getElementById('progress-fill').style.width = pct + '%';
}