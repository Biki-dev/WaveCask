import React, { useState } from 'react'
import {
  triggerSessionSync,
  triggerTrackClassify,
  triggerTrackEmbed,
  triggerTrackEnrich,
  triggerModelRefresh,
  triggerDiscoverWeekly
} from './api'

export default function PipelinePage({ onRefreshPlaylists }) {
  const [statuses, setStatuses] = useState({
    sync: { loading: false, success: null, message: '' },
    classify: { loading: false, success: null, message: '' },
    embed: { loading: false, success: null, message: '' },
    enrich: { loading: false, success: null, message: '' },
    models: { loading: false, success: null, message: '' },
    discover: { loading: false, success: null, message: '' },
  })

  const runJob = async (jobKey, apiFn, successMessage) => {
    setStatuses(prev => ({
      ...prev,
      [jobKey]: { loading: true, success: null, message: 'Job triggered, waiting for acknowledgment...' }
    }))
    try {
      const res = await apiFn()
      setStatuses(prev => ({
        ...prev,
        [jobKey]: {
          loading: false,
          success: true,
          message: res.message || successMessage || 'Success!'
        }
      }))
      if (onRefreshPlaylists) {
        // Refresh playlists lists/covers after models rebuild or weekly builds
        onRefreshPlaylists()
      }
    } catch (e) {
      setStatuses(prev => ({
        ...prev,
        [jobKey]: { loading: false, success: false, message: e.message || 'Failed to trigger job' }
      }))
    }
  }

  const jobsList = [
    {
      key: 'sync',
      title: '1. Sync Sessions (sync_sessions_nightly)',
      desc: 'Aggregates raw user log events into session boundaries to understand replay counts and watch durations.',
      api: triggerSessionSync,
      successMsg: 'Session sync job successfully started in the background.',
    },
    {
      key: 'classify',
      title: '2. Audio Classification (classify_tracks_nightly)',
      desc: 'Classifies pending audio stubs (determines music vs. non-music). Runs yt-dlp to download segment and classifies using the AudioCNN model.',
      api: triggerTrackClassify,
      successMsg: 'Classification job successfully started in the background.',
    },
    {
      key: 'embed',
      title: '3. Audio Embedding Generation',
      desc: 'Computes 512-dimensional OpenL3 embeddings for newly classified music tracks and saves them to the database.',
      api: triggerTrackEmbed,
      successMsg: 'Embedding generation successfully started in the background.',
    },
    {
      key: 'enrich',
      title: '4. Metadata Enrichment',
      desc: 'Retrieves rich metadata (artist, song name, release year, genre) for tracks using LLM and heuristic models.',
      api: triggerTrackEnrich,
      successMsg: 'Metadata enrichment job successfully started in the background.',
    },
    {
      key: 'models',
      title: '5. Refresh Recommendation Models',
      desc: 'Recomputes engagement features, fits track KMeans clusters, rebuilds session co-occurrences, and updates the global taste profile. Note: Runs synchronously.',
      api: triggerModelRefresh,
      successMsg: 'Recommendation models rebuilt successfully! Taste profiles updated.',
    },
    {
      key: 'discover',
      title: '6. Generate Discover Weekly',
      desc: 'Uses the global taste profile and clustering models to build the weekly curated Discover Weekly recommendation playlist.',
      api: triggerDiscoverWeekly,
      successMsg: 'Discover Weekly playlist generated/refreshed successfully!',
    },
  ]

  return (
    <div style={{ height: '100%' }}>
      <div className="content-header mood-header">
        <div className="content-header-badge">Admin Controls</div>
        <h1 className="content-header-title">System Pipeline Control</h1>
        <div className="content-header-meta">
          Trigger background nightly jobs and recompute recommender models manually
        </div>
      </div>

      <div className="content-body" style={{ maxWidth: 900 }}>
        <div className="admin-grid">
          {jobsList.map(job => {
            const status = statuses[job.key]
            return (
              <div key={job.key} className="admin-card">
                <div className="admin-card-header">
                  <h3 className="admin-card-title">{job.title}</h3>
                  <button
                    className="admin-trigger-btn"
                    disabled={status.loading}
                    onClick={() => runJob(job.key, job.api, job.successMsg)}
                  >
                    {status.loading ? 'Running...' : 'Trigger Job'}
                  </button>
                </div>
                <p className="admin-card-desc">{job.desc}</p>

                {status.message && (
                  <div className={`admin-status-box ${status.success === true ? 'success' : status.success === false ? 'error' : 'info'}`}>
                    <span className="status-indicator" />
                    <p className="status-text">{status.message}</p>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      <style>{`
        .admin-grid {
          display: flex;
          flex-direction: column;
          gap: 20px;
          margin-top: 10px;
        }
        .admin-card {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: var(--radius-md);
          padding: 24px;
          transition: border-color var(--transition);
        }
        .admin-card:hover {
          border-color: var(--border-hover);
        }
        .admin-card-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
          gap: 16px;
        }
        .admin-card-title {
          font-size: 16px;
          font-weight: 700;
          color: var(--text-primary);
        }
        .admin-card-desc {
          font-size: 13px;
          color: var(--text-secondary);
          line-height: 1.5;
          margin-bottom: 16px;
        }
        .admin-trigger-btn {
          background: var(--accent);
          color: #000000;
          border: none;
          font-weight: 700;
          font-size: 13px;
          padding: 8px 16px;
          border-radius: var(--radius-pill);
          cursor: pointer;
          transition: background var(--transition), transform 0.1s;
          white-space: nowrap;
        }
        .admin-trigger-btn:hover:not(:disabled) {
          background: var(--accent-hover);
          transform: scale(1.03);
        }
        .admin-trigger-btn:disabled {
          background: var(--text-muted);
          color: var(--bg-card);
          cursor: not-allowed;
        }
        .admin-status-box {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 12px 16px;
          border-radius: var(--radius-sm);
          font-size: 12px;
          line-height: 1.4;
        }
        .admin-status-box.info {
          background: rgba(255, 255, 255, 0.05);
          color: var(--text-secondary);
          border: 1px solid rgba(255, 255, 255, 0.1);
        }
        .admin-status-box.success {
          background: rgba(29, 185, 84, 0.1);
          color: var(--accent-hover);
          border: 1px solid rgba(29, 185, 84, 0.2);
        }
        .admin-status-box.error {
          background: rgba(235, 87, 87, 0.1);
          color: #eb5757;
          border: 1px solid rgba(235, 87, 87, 0.2);
        }
        .status-indicator {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          flex-shrink: 0;
        }
        .admin-status-box.info .status-indicator {
          background: var(--text-muted);
        }
        .admin-status-box.success .status-indicator {
          background: var(--accent);
          box-shadow: 0 0 8px var(--accent);
        }
        .admin-status-box.error .status-indicator {
          background: #eb5757;
          box-shadow: 0 0 8px #eb5757;
        }
        .status-text {
          margin: 0;
          font-family: monospace;
        }
      `}</style>
    </div>
  )
}
