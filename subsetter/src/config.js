    const S3_PARQUET = 'https://s3.hydroshare.org/sblack/4219997533bf46a1893e9ba0232403eb/data/contents/parquet';
    const S3_MAP = 'https://s3.hydroshare.org/sblack/4219997533bf46a1893e9ba0232403eb/data/contents/map';
    const NETWORK_GRAPH_URL = `${S3_PARQUET}/network_graph.json`;

    const PARQUET_URLS = {
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

    // ============================================================
    // LOGGING
    // ============================================================
    const logEl = document.getElementById('log');
    function log(msg, cls = '') {
      const span = document.createElement('span');
      span.className = cls;
      span.textContent = msg + '\n';
      logEl.appendChild(span);
      logEl.parentElement.scrollTop = logEl.parentElement.scrollHeight;
    }
    function setProgress(pct) {
      document.getElementById('progress-fill').style.width = pct + '%';
    }