const BASE = ''

async function api(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, opts)
  if (!res.ok) {
    const err = await res.text().catch(() => res.statusText)
    throw new Error(err || `HTTP ${res.status}`)
  }
  return res.json()
}

// ── Playlists ────────────────────────────────────────────────────
// Fetch the summary list first (lightweight), then load each full playlist
// in parallel so playlist.tracks is always available — same as PlaylistView.
export const fetchPlaylists = () =>
  api('/api/playlists').then(summaries =>
    Promise.all(summaries.map(s => api(`/api/playlists/${s.id}`)))
  )
export const fetchPlaylist  = (id) => api(`/api/playlists/${id}`)

// ── Tracks ───────────────────────────────────────────────────────
export const fetchTracks    = () => api('/api/tracks')
export const fetchTrack     = (id) => api(`/api/tracks/${id}`)

// ── Audio ────────────────────────────────────────────────────────
export const fetchAudioUrl  = (videoId) => api(`/api/audio/${videoId}/url`)

// ── Pipeline / Jobs ──────────────────────────────────────────────
export const triggerSessionSync      = () => api('/api/sessions/sync', { method: 'POST' })
export const triggerTrackClassify    = () => api('/api/tracks/classify', { method: 'POST' })
export const triggerTrackEmbed       = () => api('/api/tracks/embed', { method: 'POST' })
export const triggerTrackEnrich      = () => api('/api/tracks/enrich', { method: 'POST' })
export const triggerModelRefresh     = () => api('/api/playlists/recommendation-models/refresh', { method: 'POST' })
export const triggerDiscoverWeekly   = () => api('/api/playlists/discover-weekly', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ limit: 30 }) })

// ── Thumbnails (static, no request needed) ───────────────────────
export const thumbUrl = (videoId, quality = 'mqdefault') =>
  `https://img.youtube.com/vi/${videoId}/${quality}.jpg`

// ── Format helpers ───────────────────────────────────────────────
export function fmtDuration(secs) {
  if (!secs) return '—'
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export function fmtScore(score) {
  if (score == null) return '—'
  return Math.round(score * 100)
}

export const PLAYLIST_TYPE_COLOR = {
  today:          '#1a472a',
  day_of_week:    '#2d1e3a',
  month:          '#1c3a2d',
  context:        '#1c2b4a',
  all_time:       '#3a2a1c',
  mood:           '#2d1e3a',
  recommendation: '#3a1e1e',
}

export const PLAYLIST_TYPE_LABEL = {
  today:          'Daily Mix',
  day_of_week:    'Day Mix',
  month:          'Monthly Mix',
  context:        'Context Mix',
  all_time:       'All Time',
  mood:           'Mood Mix',
  recommendation: 'Discover',
}
