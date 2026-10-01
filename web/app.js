// Voice loop: mic -> text -> /api/ask -> text -> speech.
// The robot's animation is driven entirely by one attribute, so every path
// through the app only has to call setState().

const stage = document.getElementById('stage');
const caption = document.getElementById('caption');
const heardEl = document.getElementById('heard');
const answerEl = document.getElementById('answer');
const chips = document.getElementById('chips');
const chipsLabel = document.getElementById('chipsLabel');
const topics = document.getElementById('topics');
const speechEl = document.getElementById('speech');
const centreEl = document.querySelector('.centre');
const productsEl = document.getElementById('products');
const health = document.getElementById('health');
const healthText = document.getElementById('healthText');
const form = document.getElementById('form');
const input = document.getElementById('q');
const mic = document.getElementById('mic');
const speakToggle = document.getElementById('speak');
const statusEl = document.getElementById('status');

let offlineStt = false;
let listening = false;

const CAPTIONS = {
  idle: '',
  listening: 'Listening…',
  thinking: 'Searching my knowledge…',
  speaking: '',
  clarifying: '',
  refusing: '',
};

// The backend decides what kind of reply this is; the robot only has to wear
// the matching face. One map, so the pose can never disagree with the answer.
const MODE_STATE = {
  answer: 'speaking',
  clarify: 'clarifying',
  refer: 'refusing',
  chat: 'speaking',
};

// Shown before the first question. Chosen to cover the four things people
// actually open this for: the company, the range, picking one, and buying.
const STARTERS = [
  'What does Arnobot do?',
  'What robots do you make?',
  'Which robot should I choose?',
  'Which robot carries the most?',
  'Which industries do you serve?',
  'Can I get a demo?',
];

// Suggestions compete with the answer while it is being delivered, but a
// clarification or a referral is *asking* for one — those keep them up.
const BUSY = new Set(['listening', 'thinking', 'speaking']);

function setState(state) {
  stage.dataset.state = state;
  caption.textContent = CAPTIONS[state] ?? '';
  // The rail is a fixture — dimmed while the robot works, never removed.
  chips.classList.toggle('dim', BUSY.has(state));
}

// `list` empty falls back to the starter set, so the rail is never a dead end.
function renderChips(list, label) {
  const items = list && list.length ? list : STARTERS;
  chips.replaceChildren(
    ...items.map((text) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'chip';
      button.textContent = text;
      return button;
    }),
  );
  chipsLabel.textContent = items === STARTERS ? 'Ask me' : label;
}

// A profile runs several times the length of an ordinary answer. The speech
// area scrolls, but its scrollbar is hidden, so fade the last line whenever
// there is more below — otherwise a cut-off answer looks like a finished one.
function fitAnswer() {
  // The dial gives up height before the answer does.
  centreEl.classList.toggle('long', answerEl.textContent.length > 360);

  // Two frames: the first lets the new text and the resized dial lay out, the
  // second measures. Measuring in a single frame catches the old layout and
  // fades answers that fit perfectly well.
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      speechEl.classList.toggle(
        'more',
        speechEl.scrollHeight > speechEl.clientHeight + 8,
      );
    });
  });
}

// A narrower window rewraps the answer, which can push it into overflow.
window.addEventListener('resize', fitAnswer);

// The status line is for faults only — it stays blank while everything works.
function setStatus(text = '') {
  statusEl.textContent = text;
}

// Replay the entrance animation on each new line of text.
function reveal(el, text) {
  el.textContent = text;
  el.classList.remove('in');
  void el.offsetWidth; // force reflow so the animation restarts
  el.classList.add('in');
}

// Speech synthesis uses the OS voices — nothing leaves the machine.
function speak(text, onDone) {
  if (!speakToggle.checked || !window.speechSynthesis) {
    // Nothing to say aloud, but the pose still has to register. Snapping
    // straight back to idle means the clarifying and refusing faces are never
    // actually seen with voice off — so hold for roughly a read.
    setTimeout(onDone, Math.min(1400 + text.length * 14, 7000));
    return;
  }
  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.rate = 1.03;
  utter.onend = onDone;
  utter.onerror = onDone;
  speechSynthesis.speak(utter);
  // Safety net: if the voice engine never fires onend, don't freeze the robot.
  setTimeout(onDone, Math.min(2000 + text.length * 90, 20000));
}

function once(fn) {
  let done = false;
  return () => { if (!done) { done = true; fn(); } };
}

// --- closing line ---------------------------------------------------------
// After an answer, if the room goes quiet, the robot thanks the visitor and
// re-opens the floor. Once per answer: a assistant that keeps saying thank you
// into an empty room is worse than one that says nothing.
let closingLine = '';
let closingDelay = 25000;
let closingTimer = null;
let closingOwed = false;

function cancelClosing() {
  clearTimeout(closingTimer);
  closingTimer = null;
}

function armClosing() {
  cancelClosing();
  if (!closingOwed || !closingLine) return;
  closingTimer = setTimeout(() => {
    // Never talk over someone, and never talk to a tab nobody is looking at.
    if (stage.dataset.state !== 'idle' || document.hidden) return;
    closingOwed = false;
    heardEl.textContent = '';
    answerEl.classList.remove('none', 'asking');
    reveal(answerEl, closingLine);
    fitAnswer();
    renderChips(null);
    setState('speaking');
    speak(closingLine, once(() => setState('idle')));
  }, closingDelay);
}

async function ask(question) {
  cancelClosing();
  // A tapped or typed question while the mic is open replaces the spoken one.
  if (listening) {
    stopMicUi();
    try { recognizer?.abort(); } catch (err) { /* already stopped */ }
  }
  answerEl.classList.remove('greeting', 'none', 'asking');
  reveal(heardEl, question);
  answerEl.textContent = '';
  setState('thinking');

  let data;
  try {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    });
    data = await res.json();
  } catch (err) {
    reveal(answerEl, 'I cannot reach my backend right now.');
    answerEl.classList.add('none');
    renderChips(STARTERS);
    setState('refusing');
    return;
  }

  reveal(answerEl, data.answer);
  answerEl.classList.toggle('none', data.mode === 'refer');
  answerEl.classList.toggle('asking', data.mode === 'clarify');
  fitAnswer();

  // Rendered before setState so the label is in place when visibility is set.
  renderChips(data.followups, data.mode === 'clarify' ? 'Did you mean' : 'Ask me next');
  setState(MODE_STATE[data.mode] || (data.answered ? 'speaking' : 'refusing'));

  // A clarification is a question *to* the visitor — thanking them while
  // waiting on their reply would be talking past them. Small talk already
  // re-opens the floor in its own words.
  closingOwed = data.mode === 'answer' || data.mode === 'refer';

  // Only the answer is spoken. The suggestions are on screen to be tapped.
  speak(data.answer, once(() => { setState('idle'); armClosing(); }));
}

form.addEventListener('submit', (e) => {
  e.preventDefault();
  const question = input.value.trim();
  if (!question) return;
  input.value = '';
  ask(question);
});

// One handler per list — the rail's dynamic group, the fixed topics, and the
// product cards all route to the same ask() the mic uses.
for (const list of [chips, topics]) {
  list.addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (chip) ask(chip.textContent.trim());
  });
}

productsEl.addEventListener('click', (e) => {
  const card = e.target.closest('.product');
  if (card) ask(card.dataset.ask);
});


// --- speech input ---------------------------------------------------------
// The browser recogniser in single-shot mode gives up at the first pause —
// often two or three seconds in, before a visitor has finished thinking of
// the question. So it runs continuously, is restarted whenever the browser
// ends it early, and *we* decide when the question is over: a pause after
// speech, a longer wait if nothing has been said yet, and a hard cap.
const SILENCE_AFTER_SPEECH_MS = 2500;
const WAIT_FOR_SPEECH_MS = 9000;
const MAX_LISTEN_MS = 30000;

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null;
let committed = '';   // final text from earlier recogniser sessions
let pending = '';     // text from the current session, final + interim
let silenceTimer = null;
let capTimer = null;

function heardSoFar() {
  return `${committed} ${pending}`.replace(/\s+/g, ' ').trim();
}

function armSilence(ms) {
  clearTimeout(silenceTimer);
  silenceTimer = setTimeout(finishListening, ms);
}

function stopMicUi() {
  listening = false;
  mic.classList.remove('on');
  mic.setAttribute('aria-label', 'Speak');
  clearTimeout(silenceTimer);
  clearTimeout(capTimer);
}

// Ends the turn: ask whatever was heard, or say nothing was.
function finishListening() {
  if (!listening) return;
  const question = heardSoFar();
  stopMicUi();
  try { recognizer?.abort(); } catch (err) { /* already stopped */ }
  if (question) {
    ask(question);
  } else {
    heardEl.textContent = '';
    setState('idle');
    setStatus("Didn't catch that — tap the mic and try again");
  }
}

if (Recognition) {
  recognizer = new Recognition();
  recognizer.lang = 'en-IN';
  recognizer.interimResults = true;
  recognizer.continuous = true;
  recognizer.maxAlternatives = 1;

  recognizer.onresult = (e) => {
    let text = '';
    for (let i = 0; i < e.results.length; i += 1) text += e.results[i][0].transcript;
    pending = text;
    heardEl.textContent = heardSoFar();
    // Each new word pushes the deadline back; only a real pause ends the turn.
    if (heardSoFar()) armSilence(SILENCE_AFTER_SPEECH_MS);
  };
  recognizer.onerror = (e) => {
    // Silence and our own abort are not failures — the timers own the ending.
    if (e.error === 'no-speech' || e.error === 'aborted') return;
    stopMicUi();
    setState('idle');
    setStatus(
      e.error === 'not-allowed' || e.error === 'service-not-allowed'
        ? 'Microphone access is blocked — allow it in the browser settings'
        : `Microphone error: ${e.error}`,
    );
  };
  recognizer.onend = () => {
    if (!listening) {
      if (stage.dataset.state === 'listening') setState('idle');
      return;
    }
    // The browser ended the session on its own: keep what it heard and carry on.
    committed = heardSoFar();
    pending = '';
    try { recognizer.start(); } catch (err) { finishListening(); }
  };
}

// Offline path: record audio and transcribe locally via /api/stt.
let recorder = null;
let clips = [];

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  recorder = new MediaRecorder(stream);
  clips = [];
  recorder.ondataavailable = (e) => clips.push(e.data);
  recorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    setState('thinking');
    const body = new FormData();
    body.append('audio', new Blob(clips, { type: 'audio/webm' }), 'clip.webm');
    try {
      const data = await (await fetch('/api/stt', { method: 'POST', body })).json();
      if (data.text) ask(data.text);
      else { setState('idle'); setStatus("didn't catch that"); }
    } catch (err) {
      setState('idle');
      setStatus('transcription failed');
    }
  };
  recorder.start();
}

mic.addEventListener('click', async () => {
  // Tapping again means "I'm done" — send what was heard straight away.
  if (listening) {
    if (offlineStt) { stopMicUi(); recorder?.stop(); } else finishListening();
    return;
  }
  try {
    cancelClosing();
    window.speechSynthesis?.cancel();
    listening = true;
    committed = '';
    pending = '';
    mic.classList.add('on');
    mic.setAttribute('aria-label', 'Stop and send');
    setState('listening');
    setStatus();
    answerEl.classList.remove('greeting', 'none', 'asking');
    heardEl.textContent = '';
    answerEl.textContent = '';
    if (offlineStt) {
      await startRecording();
      capTimer = setTimeout(() => { stopMicUi(); recorder?.stop(); }, MAX_LISTEN_MS);
    } else {
      recognizer.start();
      armSilence(WAIT_FOR_SPEECH_MS);
      capTimer = setTimeout(finishListening, MAX_LISTEN_MS);
    }
  } catch (err) {
    stopMicUi();
    setState('idle');
    setStatus('Microphone unavailable');
  }
});

// --- full screen ----------------------------------------------------------
// Built to stand on a kiosk screen: one tap (or F) hides the browser chrome.
const fullscreenBtn = document.getElementById('fullscreen');

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen?.();
  else document.documentElement.requestFullscreen?.().catch(() => {});
}

fullscreenBtn.addEventListener('click', toggleFullscreen);
document.addEventListener('fullscreenchange', () => {
  fullscreenBtn.setAttribute(
    'aria-label', document.fullscreenElement ? 'Exit full screen' : 'Enter full screen',
  );
});
document.addEventListener('keydown', (e) => {
  if (e.key.toLowerCase() === 'f' && e.target === document.body) toggleFullscreen();
});
// Browsers without the API (iPhone Safari) already run full screen from the
// home screen, so the button would do nothing there.
if (!document.documentElement.requestFullscreen) fullscreenBtn.hidden = true;

// --- boot -----------------------------------------------------------------
function renderProducts(list) {
  productsEl.replaceChildren(
    ...list.map((product) => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'product';
      card.dataset.ask = product.ask;
      const badge = document.createElement('span');
      badge.className = 'p-badge';
      badge.setAttribute('aria-hidden', 'true');
      badge.textContent = product.name.charAt(0).toUpperCase();
      const text = document.createElement('span');
      text.className = 'p-text';
      const name = document.createElement('span');
      name.className = 'p-name';
      name.textContent = product.name;
      const kind = document.createElement('span');
      kind.className = 'p-kind';
      kind.textContent = product.kind;
      text.append(name, kind);
      card.append(badge, text);
      return card;
    }),
  );
}

async function boot() {
  try {
    const info = await (await fetch('/api/health')).json();
    offlineStt = info.offline_stt;
    closingLine = info.closing || '';
    closingDelay = info.closing_delay_ms || closingDelay;
    health.dataset.ok = 'true';
    healthText.textContent = 'Online';
    if (info.chunks === 0) setStatus('no knowledge indexed');
    if (!offlineStt && !Recognition) {
      mic.disabled = true;
      setStatus('mic needs Chrome or Edge — typing works');
    }
  } catch (err) {
    health.dataset.ok = 'false';
    healthText.textContent = 'Offline';
    setStatus('backend not responding');
  }

  // Separate try: a missing product list should not make a working assistant
  // look broken. The strip just stays empty.
  try {
    const data = await (await fetch('/api/products')).json();
    renderProducts(data.products || []);
  } catch (err) {
    productsEl.hidden = true;
  }
}

// Dev hook: /#state=clarifying freezes the robot in one pose for inspection.
const forced = location.hash.match(/state=(\w+)/);
renderChips(STARTERS);
setState(forced ? forced[1] : 'idle');
answerEl.classList.add('in');

if (!forced) {
  boot().then(() => {
    // Deep link: /?q=who+is+the+CEO asks on load.
    const preset = new URLSearchParams(location.search).get('q');
    if (preset) ask(preset);
  });
}
