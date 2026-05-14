    export const S3_PARQUET = 'https://s3.hydroshare.org/sblack/4219997533bf46a1893e9ba0232403eb/data/contents/parquet';
    export const S3_MAP = 'https://s3.hydroshare.org/sblack/4219997533bf46a1893e9ba0232403eb/data/contents/map';
    export const NETWORK_GRAPH_URL = `${S3_PARQUET}/network_graph.json`;

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
        syncing : false,

        hp : null,
        compressors : null,
        fileHandleCache : {},
    }

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