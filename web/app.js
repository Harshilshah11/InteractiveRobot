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
const sendBtn = form.querySelector('.send');
const speakToggle = document.getElementById('speak');
const statusEl = document.getElementById('status');

let listening = false;
let listenStartedAt = 0;

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
  // mirrored on <body> so the answer card and composer can follow the state
  document.body.dataset.state = state;
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
      button.style.setProperty('--i', items.indexOf(text));
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

// Answers settle in word by word. Spans carry only the timing; the text is
// unchanged, so screen readers and copy-paste see one plain sentence.
function revealWords(el, text) {
  const words = text.split(/(\s+)/);
  const step = Math.max(8, Math.min(28, 1100 / Math.max(1, words.length / 2)));
  let n = 0;
  el.replaceChildren(...words.map((w) => {
    if (/^\s+$/.test(w)) return document.createTextNode(w);
    const span = document.createElement('span');
    span.className = 'w';
    span.style.setProperty('--d', `${(n += 1) * step}ms`);
    span.textContent = w;
    return span;
  }));
  el.classList.remove('in');
}

// Speech synthesis uses the OS voices — nothing leaves the machine.
// Browsers cannot reach Siri itself, so this picks a female voice from what is
// installed: Karen (Apple, Australian English) is the chosen voice; the rest
// are fallbacks for machines without it — Apple's Premium/Enhanced voices,
// then the standard Apple ones, then Edge's neural and Chrome's online voices
// for the same page on Windows. `?voice=Name` overrides it.
const VOICE_PREFERENCE = [
  'Karen (Premium)', 'Karen (Enhanced)', 'Karen',
  'Ava (Premium)', 'Zoe (Premium)', 'Ava (Enhanced)', 'Zoe (Enhanced)',
  'Samantha (Enhanced)', 'Allison (Enhanced)', 'Susan (Enhanced)',
  'Samantha', 'Ava', 'Zoe', 'Allison', 'Susan', 'Veena', 'Moira', 'Tessa',
  'Microsoft Aria Online (Natural)', 'Microsoft Jenny Online (Natural)',
  'Microsoft Ava Online (Natural)', 'Microsoft Neerja Online (Natural)',
  'Google US English', 'Google UK English Female', 'Microsoft Zira',
];
const VOICE_RATE = 0.95; // a touch slower than conversational, so it is easy to follow
const VOICE_PITCH = 1.05;

let chosenVoice = null;

function pickVoice() {
  const voices = window.speechSynthesis?.getVoices() || [];
  if (!voices.length) return;
  const wanted = new URLSearchParams(location.search).get('voice');
  const english = voices.filter((v) => /^en[-_]/i.test(v.lang));
  const byName = (name) => english.find((v) => v.name === name)
    || english.find((v) => v.name.startsWith(`${name} `));
  chosenVoice = (wanted && voices.find((v) => v.name.toLowerCase().includes(wanted.toLowerCase())))
    || VOICE_PREFERENCE.map(byName).find(Boolean)
    || english.find((v) => /female/i.test(v.name))
    || english[0]
    || null;
}

if (window.speechSynthesis) {
  pickVoice();
  // Chrome fills the voice list asynchronously.
  speechSynthesis.addEventListener?.('voiceschanged', pickVoice);
}

// Every spoken line is a numbered turn. Cancelling speech (a new question, the
// mic, the stop button) fires the old line's end events late; the number lets
// them be ignored, so a stale callback can never knock the robot out of the
// pose it is in now.
let speechTurn = 0;

function setSpeaking(on) {
  document.body.classList.toggle('is-speaking', on);
  sendBtn.setAttribute('aria-label', on ? 'Stop speaking' : 'Send');
}

function cancelSpeech() {
  speechTurn += 1;
  window.speechSynthesis?.cancel();
  setSpeaking(false);
}

function speak(text, onDone) {
  const turn = ++speechTurn;
  const finish = () => {
    if (turn !== speechTurn) return;
    setSpeaking(false);
    onDone();
  };
  setSpeaking(true);
  if (!speakToggle.checked || !window.speechSynthesis) {
    // Nothing to say aloud, but the pose still has to register. Snapping
    // straight back to idle means the clarifying and refusing faces are never
    // actually seen with voice off — so hold for roughly a read.
    setTimeout(finish, Math.min(1400 + text.length * 14, 7000));
    return;
  }
  speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  if (!chosenVoice) pickVoice();
  if (chosenVoice) {
    utter.voice = chosenVoice;
    utter.lang = chosenVoice.lang;
  }
  utter.rate = VOICE_RATE;
  utter.pitch = VOICE_PITCH;
  utter.onend = finish;
  utter.onerror = finish;
  speechSynthesis.speak(utter);
  // Safety net: if the voice engine never fires onend, don't freeze the robot.
  // Scaled for the slower rate, so a long answer is not cut off mid-sentence.
  setTimeout(finish, Math.min(2500 + text.length * 110, 60000));
}

// The stop button: silence the answer and hand the floor back.
const READY_LINE = 'How can I help you?';

function stopSpeaking() {
  cancelSpeech();
  cancelClosing();
  heardEl.textContent = '';
  answerEl.classList.remove('none', 'asking');
  answerEl.classList.add('greeting');
  reveal(answerEl, READY_LINE);
  fitAnswer();
  renderChips(null);
  setState('speaking');
  speak(READY_LINE, () => setState('idle'));
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
  cancelSpeech();
  cancelTranscription();
  speechEl.classList.remove('greeting-mode');
  // A tapped or typed question while the mic is open replaces the spoken one.
  if (listening) {
    stopMicUi();
    stopLevelWatch();
    try { recognizer?.abort(); } catch (err) { /* already stopped */ }
    if (recorder && recorder.state !== 'inactive') {
      const rec = recorder;
      recorder = null;                     // its onstop now sees it was superseded
      rec.stop();
    }
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

  revealWords(answerEl, data.answer);
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
  // While the robot is talking, the send arrow is a stop button.
  if (document.body.classList.contains('is-speaking')) {
    stopSpeaking();
    return;
  }
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
    // The online speech service is unreachable or blocked: switch to local
    // transcription for the rest of the session and keep this turn going.
    if ((e.error === 'network' || e.error === 'service-not-allowed') && serverStt && listening) {
      useLocalStt = true;  // also stops onend from restarting the recogniser
      clearTimeout(silenceTimer);
      clearTimeout(capTimer);
      try { recognizer.abort(); } catch (err) { /* already stopped */ }
      startListening().catch(() => {
        stopMicUi();
        setState('idle');
        setStatus('Microphone unavailable');
      });
      return;
    }
    stopMicUi();
    setState('idle');
    setStatus(
      e.error === 'not-allowed' || e.error === 'service-not-allowed'
        ? 'Microphone access is blocked — allow it in the browser settings'
        : e.error === 'network'
          ? 'Voice input needs Chrome, Edge or Safari here — typing works'
          : `Microphone error: ${e.error}`,
    );
  };
  recognizer.onend = () => {
    if (useLocalStt) return;  // the local recorder has taken over this turn
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

// Offline path: record audio and transcribe on this machine via /api/stt.
// Used when the browser recogniser cannot work — Brave blocks Google's speech
// service, Firefox has none — so the mic works in every browser. The same
// rules end the turn: a pause after speech, a wait for speech, and a cap —
// measured here from the microphone level, since nothing transcribes live.
const MIN_SPEECH_MS = 300;     // this much voice before a turn counts as speech
let recorder = null;
let clips = [];
let heardVoice = false;
let levelTimer = null;
let audioCtx = null;
let micStarting = false;       // getUserMedia is in flight: ignore extra taps
let sttSeq = 0;                // only the newest transcription may ask
let sttAbort = null;

function stopLevelWatch() {
  clearInterval(levelTimer);
  levelTimer = null;
  mic.style.setProperty('--level', 0);
  audioCtx?.close().catch(() => {});
  audioCtx = null;
}

// Ends a recording turn: transcribe if anyone spoke, otherwise say so.
function finishRecording() {
  if (!listening) return;
  stopMicUi();
  stopLevelWatch();
  if (recorder && recorder.state !== 'inactive') recorder.stop();
}

// Drops an unfinished transcription, so a newer turn is never overtaken by it.
function cancelTranscription() {
  sttSeq += 1;
  sttAbort?.abort();
  sttAbort = null;
}

async function transcribe(blob) {
  cancelTranscription();
  const seq = sttSeq;
  sttAbort = new AbortController();
  setState('thinking');
  caption.textContent = 'Understanding…';
  const body = new FormData();
  body.append('audio', blob, 'clip.webm');
  try {
    const res = await fetch('/api/stt', { method: 'POST', body, signal: sttAbort.signal });
    const data = await res.json();
    if (seq !== sttSeq) return;            // a newer turn has started
    sttAbort = null;
    if (data.text) ask(data.text);
    else { setState('idle'); setStatus("Didn't catch that — tap the mic and try again"); }
  } catch (err) {
    if (seq !== sttSeq) return;
    setState('idle');
    setStatus('Transcription failed — please try again');
  }
}

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
  });
  // The visitor may have tapped stop while the permission prompt was open.
  if (!listening) { stream.getTracks().forEach((t) => t.stop()); return; }

  const rec = new MediaRecorder(stream);
  recorder = rec;
  clips = [];
  heardVoice = false;
  rec.ondataavailable = (e) => { if (e.data.size) clips.push(e.data); };
  rec.onstop = () => {
    stream.getTracks().forEach((t) => t.stop());
    if (rec !== recorder) return;          // superseded by a newer recording
    if (!heardVoice || !clips.length) {
      setState('idle');
      setStatus("Didn't catch that — tap the mic and try again");
      return;
    }
    transcribe(new Blob(clips, { type: rec.mimeType || 'audio/webm' }));
  };
  rec.start(250);

  // Voice activity from the input level. The noise floor is learned in the
  // first moments and then follows the room slowly, so a fan or traffic does
  // not count as speech and a quiet voice still does.
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 1024;
  audioCtx.createMediaStreamSource(stream).connect(analyser);
  const buf = new Float32Array(analyser.fftSize);
  const t0 = Date.now();
  let floor = 0;
  let level = 0;
  let voicedMs = 0;
  let lastVoice = 0;
  levelTimer = setInterval(() => {
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i += 1) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);
    level = level * 0.6 + rms * 0.4;
    const now = Date.now();
    // live meter on the mic button, so the visitor can see they are heard
    mic.style.setProperty('--level', Math.min(1, level * 12).toFixed(3));
    if (now - t0 < 350) { floor = Math.max(floor, level); return; }
    const voiced = level > Math.max(floor * 2.4, floor + 0.01, 0.012);
    if (voiced) {
      voicedMs += 100;
      lastVoice = now;
      if (voicedMs >= MIN_SPEECH_MS && !heardVoice) {
        heardVoice = true;
        caption.textContent = 'Listening… tap the mic when you are done';
      }
    } else {
      // follow the room: drift down quickly, up slowly
      floor = level < floor ? floor * 0.9 + level * 0.1 : floor * 0.995 + level * 0.005;
    }
    if (heardVoice && now - lastVoice > SILENCE_AFTER_SPEECH_MS) finishRecording();
    else if (!heardVoice && now - t0 > WAIT_FOR_SPEECH_MS) finishRecording();
  }, 100);
}

// Chrome-family browsers send audio to Google; Brave switches that off, so
// the recogniser there can only ever fail with "network". Go straight to the
// local path when the server offers it.
let serverStt = false;
let useLocalStt = false;

function chooseSttPath() {
  useLocalStt = serverStt && (!Recognition || Boolean(navigator.brave));
}

async function startListening() {
  if (useLocalStt) {
    await startRecording();
    if (listening) capTimer = setTimeout(finishRecording, MAX_LISTEN_MS);
  } else {
    recognizer.start();
    armSilence(WAIT_FOR_SPEECH_MS);
    capTimer = setTimeout(finishListening, MAX_LISTEN_MS);
  }
}

mic.addEventListener('click', async () => {
  if (micStarting) return;
  // Tapping again means "I'm done" — send what was heard straight away.
  if (listening) {
    if (useLocalStt) { if (Date.now() - listenStartedAt > 600) heardVoice = true; finishRecording(); }
    else finishListening();
    return;
  }
  micStarting = true;
  try {
    cancelClosing();
    cancelSpeech();
    cancelTranscription();
    listening = true;
    listenStartedAt = Date.now();
    committed = '';
    pending = '';
    mic.classList.add('on');
    mic.setAttribute('aria-label', 'Stop and send');
    setState('listening');
    setStatus();
    answerEl.classList.remove('greeting', 'none', 'asking');
    speechEl.classList.remove('greeting-mode');
    heardEl.textContent = '';
    answerEl.textContent = '';
    await startListening();
  } catch (err) {
    stopMicUi();
    stopLevelWatch();
    setState('idle');
    setStatus(
      err && err.name === 'NotAllowedError'
        ? 'Microphone access is blocked — allow it in the browser settings'
        : 'Microphone unavailable',
    );
  } finally {
    micStarting = false;
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

// --- appearance -----------------------------------------------------------
// Auto follows the system; Light and Dark pin it. Stored per screen, so a
// kiosk keeps its look across restarts.
const themeControl = document.getElementById('theme');

function applyTheme(choice) {
  if (choice === 'light' || choice === 'dark') document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
  for (const btn of themeControl.querySelectorAll('[data-theme-choice]')) {
    btn.setAttribute('aria-checked', String(btn.dataset.themeChoice === (choice || 'system')));
  }
}

themeControl.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-theme-choice]');
  if (!btn) return;
  const choice = btn.dataset.themeChoice;
  try {
    if (choice === 'system') localStorage.removeItem('theme');
    else localStorage.setItem('theme', choice);
  } catch (err) { /* storage blocked: the choice lasts for this visit */ }
  applyTheme(choice);
});

applyTheme(document.documentElement.dataset.theme || 'system');

// --- boot -----------------------------------------------------------------
function renderProducts(list) {
  productsEl.replaceChildren(
    ...list.map((product) => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'product';
      card.style.setProperty('--i', list.indexOf(product));
      card.dataset.ask = product.ask;
      // The robot's own render; falls back to its initial if the image is missing.
      const badge = document.createElement('span');
      badge.className = 'p-media';
      badge.setAttribute('aria-hidden', 'true');
      const img = document.createElement('img');
      img.src = `/static/assets/products/${product.key}.webp`;
      img.alt = '';
      img.decoding = 'async';
      img.addEventListener('error', () => {
        badge.classList.add('letter');
        badge.replaceChildren(product.name.charAt(0).toUpperCase());
      });
      badge.append(img);
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

// The contact card uses the same settings as the robot's spoken referral.
function renderContact(contact) {
  if (!contact) return;
  const set = (id, text, href) => {
    const row = document.getElementById(id);
    if (!text) { row.hidden = true; return; }
    row.querySelector('span').textContent = text;
    row.href = href;
  };
  set('contactPhone', contact.phone, `tel:${(contact.phone || '').replace(/[^+\d]/g, '')}`);
  set('contactEmail', contact.email, `mailto:${contact.email}`);
  set('contactWeb', contact.web, `https://${(contact.web || '').replace(/^https?:\/\//, '')}`);
  document.getElementById('contact').hidden = false;
}

async function boot() {
  try {
    const info = await (await fetch('/api/health')).json();
    serverStt = Boolean(info.offline_stt);
    chooseSttPath();
    closingLine = info.closing || '';
    closingDelay = info.closing_delay_ms || closingDelay;
    renderContact(info.contact);
    health.dataset.ok = 'true';
    healthText.textContent = 'Online';
    if (info.chunks === 0) setStatus('no knowledge indexed');
    if (!serverStt && !Recognition) {
      mic.disabled = true;
      setStatus('Voice input needs Chrome, Edge or Safari here — typing works');
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
speechEl.classList.add('greeting-mode');
setState(forced ? forced[1] : 'idle');
[...topics.children].forEach((chip, i) => chip.style.setProperty('--i', i + 6));
document.body.classList.add('ready');
answerEl.classList.add('in');

if (!forced) {
  boot().then(() => {
    // Deep link: /?q=who+is+the+CEO asks on load.
    const preset = new URLSearchParams(location.search).get('q');
    if (preset) ask(preset);
  });
}
