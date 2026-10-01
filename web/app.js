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
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null;

if (Recognition) {
  recognizer = new Recognition();
  recognizer.lang = 'en-IN';
  recognizer.interimResults = true;
  recognizer.continuous = false;

  recognizer.onresult = (e) => {
    const result = e.results[e.results.length - 1];
    heardEl.textContent = result[0].transcript;
    if (result.isFinal) {
      const question = result[0].transcript.trim();
      if (question) ask(question);
    }
  };
  recognizer.onerror = (e) => {
    listening = false;
    mic.classList.remove('on');
    setState('idle');
    setStatus(e.error === 'no-speech' ? "didn't catch that" : `mic: ${e.error}`);
  };
  recognizer.onend = () => {
    listening = false;
    mic.classList.remove('on');
    if (stage.dataset.state === 'listening') setState('idle');
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
  if (listening) {
    listening = false;
    mic.classList.remove('on');
    if (offlineStt) recorder?.stop(); else recognizer?.stop();
    return;
  }
  try {
    cancelClosing();
    speechSynthesis?.cancel();
    listening = true;
    mic.classList.add('on');
    setState('listening');
    setStatus();
    answerEl.classList.remove('greeting', 'none', 'asking');
    heardEl.textContent = '';
    answerEl.textContent = '';
    if (offlineStt) await startRecording(); else recognizer.start();
  } catch (err) {
    listening = false;
    mic.classList.remove('on');
    setState('idle');
    setStatus('microphone unavailable');
  }
});

// --- boot -----------------------------------------------------------------
function renderProducts(list) {
  productsEl.replaceChildren(
    ...list.map((product) => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'product';
      card.dataset.ask = product.ask;
      const name = document.createElement('span');
      name.className = 'p-name';
      name.textContent = product.name;
      const kind = document.createElement('span');
      kind.className = 'p-kind';
      kind.textContent = product.kind;
      card.append(name, kind);
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
