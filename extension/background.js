let currentSessionId = null;

// Generate a new session ID
function generateSessionId() {
    currentSessionId = crypto.randomUUID();
    return currentSessionId;
}

// Get the device ID from storage or generate a new one
function getDeviceId() {
    return new Promise((resolve) => {
        chrome.storage.local.get(['deviceId'], (result) => {
            if (result.deviceId) {
                resolve(result.deviceId);
            } else {
                const newDeviceId = crypto.randomUUID();
                chrome.storage.local.set({ deviceId: newDeviceId }, () => {
                    resolve(newDeviceId);
                });
            }
        });
    });
}

// Handle messages from content scripts
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'GET_SESSION_ID') {

        if (!currentSessionId) {
            generateSessionId();
        }
        getDeviceId().then((deviceId) => {
            sendResponse({
                sessionId: currentSessionId,
                tabId: sender.tab?.id || 'unknown',
                deviceId: deviceId
            });
        });
        return true;
    };
});


generateSessionId();

chrome.runtime.onStartup.addListener(() => {
    generateSessionId();
});