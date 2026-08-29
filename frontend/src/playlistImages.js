/**
 * PLAYLIST_IMAGES
 * ───────────────────────────────────────────────────────────────────
 * Map playlist names (or window_type as fallback) to a custom cover image.
 * Update the URLs here whenever you have your own artwork ready.
 *
 * Keys are matched in this priority order:
 *  1. Exact playlist name  (case-insensitive)
 *  2. window_type          (e.g. "mood", "recommendation")
 */
export const PLAYLIST_IMAGES = {
  // ── By name (case-insensitive) ──────────────────────────────────
  'discover weekly':      'https://images.unsplash.com/photo-1614680376739-414d95ff43df?w=600&q=80',
  'all time favorites':   'https://images.unsplash.com/photo-1493225457124-a3eb161ffa5f?w=600&q=80',
  'long drive mix':       'https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=600&q=80',
  'new wave mix':         'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=600&q=80',
  'pop mix':              'https://images.unsplash.com/photo-1470225620780-dba8ba36b745?w=600&q=80',
  'hardstyle mix':        'https://images.unsplash.com/photo-1571330735066-03aaa9429d89?w=600&q=80',

  // ── By window_type (fallback when no name match) ─────────────────
  'today':                'https://images.unsplash.com/photo-1504898770365-14faca6a7320?w=600&q=80',
  'day_of_week':          'https://images.unsplash.com/photo-1460661419201-fd4cecdf8a8b?w=600&q=80',
  'month':                'https://images.unsplash.com/photo-1446057032654-9d8885db76c6?w=600&q=80',
  'context':              'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=600&q=80',
  'all_time':             'https://images.unsplash.com/photo-1493225457124-a3eb161ffa5f?w=600&q=80',
  'mood':                 'https://images.unsplash.com/photo-1542273917363-3b1817f69a2d?w=600&q=80',
  'recommendation':       'https://images.unsplash.com/photo-1614680376739-414d95ff43df?w=600&q=80',
}

/**
 * Resolve the custom cover image for a playlist.
 * Falls back to null so callers can use a YouTube thumbnail collage instead.
 */
export function getPlaylistImage(playlist) {
  const nameLower = (playlist.name || '').toLowerCase()

  // 1. Try exact name match
  for (const [key, url] of Object.entries(PLAYLIST_IMAGES)) {
    if (nameLower.startsWith(key)) return url
  }

  // 2. Try window_type match
  if (PLAYLIST_IMAGES[playlist.window_type]) {
    return PLAYLIST_IMAGES[playlist.window_type]
  }

  return null
}
