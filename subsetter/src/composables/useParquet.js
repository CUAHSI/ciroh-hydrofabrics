import { log, state } from '../config.js';
import { getAuthorizedS3Url } from '../auth.js';

export function useParquet() {
  async function initHyparquet() {
    if (state.hp) return;
    log('Loading hyparquet...', 'info');
    const t0 = performance.now();

    state.hp = await import('https://cdn.jsdelivr.net/npm/hyparquet/+esm');

    try {
      const hpc = await import('https://cdn.jsdelivr.net/npm/hyparquet-compressors/+esm');
      state.compressors = hpc.compressors;
      log(`  hyparquet + compressors ready (${((performance.now()-t0)/1000).toFixed(1)}s)`, 'success');
    } catch (e) {
      log(`  hyparquet ready, compressors unavailable (${e.message})`, 'info');
      state.compressors = undefined;
    }
  }

  // Deduplicate concurrent requests for the same URL
  const _inflight = new Map();

  async function getFileHandle(url) {
    if (state.fileHandleCache[url]) return state.fileHandleCache[url];
    if (_inflight.has(url)) return _inflight.get(url);

    const p = getAuthorizedS3Url(url)
      .then(authorizedUrl => state.hp.asyncBufferFromUrl({ url: authorizedUrl }))
      .then(handle => {
        state.fileHandleCache[url] = handle;
        _inflight.delete(url);
        return handle;
      })
      .catch(err => {
        _inflight.delete(url);
        throw err;
      });

    _inflight.set(url, p);
    return p;
  }

  const _td = new TextDecoder();

  function _normaliseRow(row) {
    const out = {};
    for (const [k, v] of Object.entries(row)) {
      if (typeof v === 'bigint') {
        out[k] = Number(v);
      } else if (v instanceof Uint8Array && k !== 'geom' && k !== 'geometry') {
        // Non-geometry BYTE_ARRAY columns are text
        out[k] = _td.decode(v);
      } else {
        out[k] = v;
      }
    }
    return out;
  }

  /**
   * Read rows from a remote parquet file using hyparquet's $in filter.
   * Row groups whose min/max stats don't overlap the $in values are
   * skipped entirely — no extra range request made.
   */
  async function readParquetFiltered(url, filterCol, idArray) {
    const file = await getFileHandle(url);
    const opts = {
      file,
      geoparquet: false,
      rowFormat: 'object',
      utf8: false,
      filter: { [filterCol]: { $in: idArray } },
    };
    if (state.compressors) opts.compressors = state.compressors;
    const rows = await state.hp.parquetReadObjects(opts);
    return rows.map(_normaliseRow);
  }

  /**
   * Read ALL rows from a remote parquet file (no filter).
   * Used by the viewer where the file is already a regional subset.
   */
  async function readParquetAll(url) {
    const file = await getFileHandle(url);
    const opts = {
      file,
      geoparquet: false,
      rowFormat: 'object',
      utf8: false,
    };
    if (state.compressors) opts.compressors = state.compressors;
    const rows = await state.hp.parquetReadObjects(opts);
    return rows.map(_normaliseRow);
  }

  return { initHyparquet, readParquetFiltered, readParquetAll };
}