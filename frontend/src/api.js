const BASE_URL = import.meta.env.VITE_API_URL
// const BASE_URL = 'https://book-rec-api-286869228046.us-central1.run.app'

const DEFAULT_TIMEOUT_MS = 120000; // 2 minutes

async function fetch_api(url, options = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  // Combine timeout signal with user-provided signal
  const userSignal = options.signal;
  let combinedSignal = controller.signal;

  if (userSignal) {
    // Create a combined signal that aborts when either signal aborts
    const combinedController = new AbortController();
    combinedSignal = combinedController.signal;

    const abort = (reason) => combinedController.abort(reason);

    if (controller.signal.aborted || userSignal.aborted) {
      abort();
    } else {
      controller.signal.addEventListener('abort', () => abort('timeout'));
      userSignal.addEventListener('abort', () => abort('user_cancelled'));
    }
  }

  try {
    const res = await fetch(url, {
      ...options,
      // harmless no-op against non-ngrok backends; required so ngrok
      // doesn't serve its browser-warning interstitial instead of the API response
      headers: { ...options.headers, 'ngrok-skip-browser-warning': 'true' },
      signal: combinedSignal
    });

    clearTimeout(timeoutId);

    if (!res.ok) {
      const errorData = res.headers.get('content-type')?.includes('application/json')
        ? await res.json()
        : { error: 'Request failed' };
      // reject with a real Error (not a plain object) so callers can rely
      // on instanceof/.name checks (e.g. ChatBot.jsx's AbortError handling)
      return Promise.reject(
        Object.assign(new Error('Request failed'), { status: res.status, data: errorData })
      );
    }

    return res;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      return Promise.reject(
        Object.assign(new Error('Request timeout or cancelled'), {
          name: 'AbortError',
          status: 408,
          data: { error: 'Request timeout or cancelled' },
        })
      );
    }
    throw error;
  }
}

// TODO: implement this
async function stopChatStream(sessionId) {
  const res = await fetch_api(BASE_URL + `/session/${sessionId}/stop`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  return await res.json();
}

async function backEndPing() {
  try {
    const res = await fetch_api(BASE_URL + '/ping', { method: 'GET' });
    const data = await res.json();
    return data.status === 'ok';
  } catch (e) {
    return false;
  }
}

async function createSession() {
  const res = await fetch_api(BASE_URL + '/session/new', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  });
  return await res.json();
}

async function sendChatMessage(sessionId, message, abortSignal = null, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const res = await fetch_api(
    BASE_URL + `/session/${sessionId}/message`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
      signal: abortSignal // Pass abort signal to fetch_api
    },
    timeoutMs
  );
  return res.body;
}


async function getRecommendedBooks(sessionId) {
  const res = await fetch_api(BASE_URL + `/session/${sessionId}/recommended_books`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' }
  });
  return await res.json();
}

// Attach a like/dislike reaction to a recorded chat run
async function updateChatFeedback(chatId, { liked = null } = {}) {
  const res = await fetch_api(BASE_URL + `/chat_runs/${chatId}/feedback`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ liked })
  });
  return await res.json();
}

// Fetch recorded chat runs (newest first) for the review page; sessionId
// optionally narrows to runs whose session_id contains the search string.
async function getChatRuns(limit = 200, offset = 0, sessionId = null) {
  const params = new URLSearchParams({ limit, offset });
  if (sessionId) params.set('session_id', sessionId);
  const res = await fetch_api(BASE_URL + `/chat_runs?${params}`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' }
  });
  return await res.json();
}

// Fetch feedback/bug reports filed against one chat run
async function getFeedback(chatId) {
  const res = await fetch_api(BASE_URL + `/feedback?chat_id=${chatId}`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' }
  });
  return await res.json();
}

// File one feedback/bug report entry. chatId is optional (omit for general
// bug reports not tied to a specific query). review marks entries filed
// from the internal /review page rather than the live chat's feedback widget.
async function addFeedback({ chatId = null, sessionId = null, title, message, positive, review = false }) {
  const res = await fetch_api(BASE_URL + '/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, session_id: sessionId, title, message, positive, review })
  });
  return await res.json();
}

// Set (or change) a reviewer's like/dislike reaction to one run, scoped to
// the reviewer's own review-page session — independent of chat_runs.liked
// (the original end-user's reaction) and of any other reviewer session.
async function setReviewerReaction(chatId, sessionId, liked) {
  const res = await fetch_api(BASE_URL + '/feedback/reaction', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, session_id: sessionId, liked })
  });
  return await res.json();
}

// TODO: implment this, using sse stream for now
async function getTaskPlanDiagram(sessionId) {
  const res = await fetch_api(BASE_URL + `/diagram/${sessionId}/task_plan`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' }
  });
  return await res.json();
}

export default {
  createSession, sendChatMessage, getRecommendedBooks, backEndPing,
  updateChatFeedback, getChatRuns, getFeedback, addFeedback, setReviewerReaction
};