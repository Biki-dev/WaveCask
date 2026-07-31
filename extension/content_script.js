let currentVideoId = null;
let lastProgressTime = 0;
let sessionId = null;
let userInteracted = false;
let tabId = null;
let deviceId = null;
const PROGRESS_INTERVAL_MS = 10000;

// Listen for user interactions to detect autoplay
document.addEventListener('click', () => { userInteracted = true; });
document.addEventListener('keydown', () => { userInteracted = true; });
document.addEventListener('touchstart', () => { userInteracted = true; });

// Get the video ID from the URL
function getVideoId() {
    const params = new URLSearchParams(window.location.search);
    return params.get('v');
}

// Get the video title from the page
function getVideoTitle() {
    const el = document.querySelector('h1.ytd-video-primary-info-renderer yt-formatted-string');
    return el ? el.innerText.trim() : 'Unknown Title';
}

// Get the channel name from the page
function getChannelName() {
    const el = document.querySelector('#owner #channel-name a');
    return el ? el.innerText.trim() : 'Unknown Channel';
}

// Get session ID, tab ID, and device ID from background script
function getSessionId() {
    return new Promise((resolve) => {
        chrome.runtime.sendMessage({ type: 'GET_SESSION_ID' }, (response) => {
            if (response && response.sessionId) {
                sessionId = response.sessionId;
                tabId = response.tabId || 'unknown';
                deviceId = response.deviceId || 'unknown';
                resolve(sessionId);
            } else {
                sessionId = crypto.randomUUID();
                tabId = 'unknown';
                deviceId = crypto.randomUUID();
                resolve(sessionId);
            }
        });
    });
}

// Detect if the video is autoplaying based on user interaction
function detectAutoplay() {
    const isAutoplayNow = !userInteracted;
    userInteracted = false; // Reset after detection
    return isAutoplayNow;
}

// Log event data to the console and send it to the backend
function logEvent(eventType, position, duration, isAuto = false) {
    const data = {
        video_id: currentVideoId,
        title: getVideoTitle(),
        channel: getChannelName(),
        event_type: eventType,
        session_id: sessionId,
        tab_id: tabId,
        device_id: deviceId,
        position_seconds: Math.round(position * 100) / 100,
        video_duration_seconds: duration ? Math.round(duration * 100) / 100 : null,
        is_autoplay: isAuto,
        timestamp: new Date().toISOString()
    };
    console.log('WAVECASK EVENT:', data);

    // Send data to the backend API
    fetch('http://localhost:8000/api/rawevents', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
    }).catch(err => console.error('Failed to send event to backend:', err));
}

// Attach event listeners to the video element
function attachListeners(video) {
    if (!video) return;
    if (video._autoDjAttached) return;
    video._autoDjAttached = true;

    video.addEventListener('play', () => {
        const currentId = getVideoId();
        if (currentId) {
            currentVideoId = currentId;
        }

        const auto = detectAutoplay();
        logEvent('play', video.currentTime, video.duration, auto);
    });

    video.addEventListener('pause', () => {
        logEvent('pause', video.currentTime, video.duration);
    });

    video.addEventListener('seeked', () => {
        logEvent('seeked', video.currentTime, video.duration);
    });

    video.addEventListener('ended', () => {
        logEvent('ended', video.duration, video.duration);
    });

    video.addEventListener('timeupdate', () => {
        const now = Date.now();
        if (now - lastProgressTime >= PROGRESS_INTERVAL_MS) {
            logEvent('progress', video.currentTime, video.duration);
            lastProgressTime = now;
        }
    });
}

// Initialize tracking when the page is ready
async function initTracking() {
    const videoId = getVideoId();
    if (!videoId) return;

    if (!sessionId) {
        await getSessionId();
    }

    if (currentVideoId !== videoId) {
        currentVideoId = videoId;
        lastProgressTime = 0;
        console.log(`New video detected: ${videoId} (Session: ${sessionId})`);
    }

    const video = document.querySelector('video');
    if (video) {
        attachListeners(video);
    } else {
        setTimeout(initTracking, 1000);
    }
}

// Observe URL changes to reinitialize tracking
let lastUrl = location.href;
new MutationObserver(() => {
    const url = location.href;
    if (url !== lastUrl) {
        lastUrl = url;
        setTimeout(initTracking, 500);
    }
}).observe(document, { subtree: true, childList: true });

// Listen for YouTube navigation events to reinitialize tracking
document.addEventListener('yt-navigate-finish', () => {
    setTimeout(initTracking, 500);
});

// Start tracking when the page is fully loaded
if (document.readyState === 'complete') {
    initTracking();
} else {
    window.addEventListener('load', initTracking);
}