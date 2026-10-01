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

// What the nav bar says the robot is doing.
const NAV_STATE = {
  idle: 'Ready',
  listening: 'Listening…',
  thinking: 'Thinking…',
  speaking: 'Speaking',
  clarifying: 'Needs a little more',
  refusing: 'Ready',
};
const navState = document.getElementById('navState');

function setState(state) {
  stage.dataset.state = state;
  if (navState) navState.textContent = NAV_STATE[state] ?? 'Ready';
  // mirrored on <body> so the answer card and composer can follow the state
  document.body.dataset.state = state;
  caption.textContent = CAPTIONS[state] ?? '';
  // The rail is a fixture — dimmed while the robot works, never removed.
  chips.classList.toggle('dim', BUSY.has(state));
}

// Each question gets an icon for its topic, so the list scans at a glance.
const ICONS = {
  company: '<path d="M4 21V5l8-3 8 3v16"/><path d="M9 21v-5h6v5M8 9h2M14 9h2M8 13h2M14 13h2"/>',
  robot: '<rect x="5" y="8" width="14" height="11" rx="3"/><path d="M12 4v4M9 13h.01M15 13h.01M9.5 16.5h5"/>',
  choose: '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
  payload: '<path d="M6 8h12l2 12H4z"/><path d="M9 8a3 3 0 0 1 6 0"/>',
  industry: '<path d="M3 21V10l6 4V10l6 4V6l6 3v12z"/>',
  demo: '<circle cx="12" cy="12" r="9"/><path d="M10 8.5v7l6-3.5z"/>',
  place: '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>',
  deploy: '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
  award: '<circle cx="12" cy="9" r="5"/><path d="M8.5 13.5L7 21l5-3 5 3-1.5-7.5"/>',
  order: '<path d="M3 4h2l2.4 11h11L21 8H6.2"/><circle cx="9" cy="19.5" r="1.3"/><circle cx="17" cy="19.5" r="1.3"/>',
  hiring: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 13h18"/>',
  people: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6"/>',
  spec: '<path d="M4 7h16M4 12h16M4 17h10"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>',
};
const ICON_RULES = [
  [/hiring|job|career|intern|work with/i, 'hiring'],
  [/award|recogni/i, 'award'],
  [/order|buy|price|cost|quot/i, 'order'],
  [/deploy|pilot|trial/i, 'deploy'],
  [/locat|where are you|address|office/i, 'place'],
  [/demo/i, 'demo'],
  [/industr|sector/i, 'industry'],
  [/carr|payload|weigh|load/i, 'payload'],
  [/choose|which robot|compare|best/i, 'choose'],
  [/founder|team|ceo|cto|who/i, 'people'],
  [/spec|size|battery|speed|range/i, 'spec'],
  [/robot|product|saibya|nexus|altius|atm|make/i, 'robot'],
  [/arnobot|company|do you do|about/i, 'company'],
];

function decorateChip(button) {
  if (button.querySelector('.chip-tx')) return button;
  const text = button.textContent.trim();
  const kind = (ICON_RULES.find(([re]) => re.test(text)) || [null, 'info'])[1];
  const ic = document.createElement('span');
  ic.className = 'chip-ic';
  ic.setAttribute('aria-hidden', 'true');
  ic.innerHTML = `<svg viewBox="0 0 24 24" width="16" height="16">${ICONS[kind]}</svg>`;
  const tx = document.createElement('span');
  tx.className = 'chip-tx';
  tx.textContent = text;
  button.replaceChildren(ic, tx);
  return button;
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
      return decorateChip(button);
    }),
  );
  const heading = items === STARTERS ? 'Ask me' : label;
  if (chipsLabel.textContent !== heading) {
    chipsLabel.textContent = heading;
    chipsLabel.classList.remove('swap');
    void chipsLabel.offsetWidth;
    chipsLabel.classList.add('swap');
  }
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
  if (card) openShowcase(card.dataset.key, card);
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

// --- product showcase -----------------------------------------------------
// A product card opens a sheet: a 360° view you can drag (or the render, where
// there is no turntable set), field photos, and the robot's own sections —
// verbatim from the data — while the robot speaks the overview.
const showcase = document.getElementById('showcase');
const scName = document.getElementById('scName');
const scKind = document.getElementById('scKind');
const scLead = document.getElementById('scLead');
const scTabs = document.getElementById('scTabs');
const scPanel = document.getElementById('scPanel');
const scThumbs = document.getElementById('scThumbs');
const scView = document.getElementById('scView');
const scSpin = document.getElementById('scSpin');
const scPhoto = document.getElementById('scPhoto');
const scVideo = document.getElementById('scVideo');
const scHint = document.getElementById('scHint');
const SPIN_STEP_PX = 7;       // drag distance per frame
const SPIN_AUTO_MS = 70;      // idle turntable speed

let scProduct = null;
let scOpener = null;
let spinFrames = [];
let spinIndex = 0;
let spinTimer = null;
let spinDrag = null;

// Figures — dimensions, weights, ranges — are set in bold so a spec reads at
// a glance. Only formatting: the words are the data's own.
const FIGURE = /(\d+(?:[.,]\d+)*(?:\s?x\s?\d+(?:[.,]\d+)*)*\s?(?:mm|kilograms?|kg|kilometres?|metres?|minutes|hours|degrees Celsius|volts?|amp-hours?|amp|megapixels?|%)?)/g;

function withFigures(text) {
  const frag = document.createDocumentFragment();
  text.split(FIGURE).forEach((part, i) => {
    if (!part) return;
    if (i % 2) {
      const strong = document.createElement('strong');
      strong.className = 'fig';
      strong.textContent = part;
      frag.append(strong);
    } else {
      frag.append(document.createTextNode(part));
    }
  });
  return frag;
}

function showFacet(facet) {
  for (const tab of scTabs.querySelectorAll('[role="tab"]')) {
    tab.setAttribute('aria-selected', String(tab.dataset.facet === facet));
  }
  let lines = (scProduct?.sections[facet] || []).slice(facet === 'overview' ? 1 : 0);
  // Attachments: the sentences that belong to a card are shown on the card.
  const cards = facet === 'attachments' ? (scProduct?.attachments || []) : [];
  if (cards.length) lines = lines.filter((line) => !cards.some((c) => c.text === line));
  const items = lines.map((line, i) => {
    const li = document.createElement('li');
    li.style.setProperty('--i', i);
    li.append(withFigures(line));
    return li;
  });
  if (cards.length) items.push(attachmentGrid(cards, items.length));
  scPanel.replaceChildren(...items);
  scPanel.classList.remove('swap');
  void scPanel.offsetWidth;
  scPanel.classList.add('swap');
}

// A grid of attachment cards: photo, name, and the data's own sentence. A card
// without a photo shows its figures instead, as a spec tile.
function attachmentGrid(cards, offset) {
  const li = document.createElement('li');
  li.className = 'sc-attgrid';
  li.append(...cards.map((card, i) => {
    const el = document.createElement('figure');
    el.className = 'sc-att';
    el.style.setProperty('--i', offset + i);
    if (card.image) {
      const img = document.createElement('img');
      img.src = card.image;
      img.alt = card.title;
      img.loading = 'lazy';
      el.append(img);
    } else {
      const tile = document.createElement('div');
      tile.className = 'sc-att-figs';
      tile.append(...(card.figures || []).map((f) => {
        const b = document.createElement('b');
        b.textContent = f;
        return b;
      }));
      el.append(tile);
    }
    const cap = document.createElement('figcaption');
    const h = document.createElement('strong');
    h.textContent = card.title;
    const p = document.createElement('span');
    p.append(withFigures(card.text));
    cap.append(h, p);
    el.append(cap);
    return el;
  }));
  return li;
}

// An attachment card opens its photo in the main view.
scPanel.addEventListener('click', (e) => {
  const card = e.target.closest('.sc-att');
  const img = card?.querySelector('img');
  if (!img) return;
  clearTimeout(mediaTimer);
  showView('photo', img.src);
  resumeMediaTourLater();
});

scTabs.addEventListener('click', (e) => {
  const tab = e.target.closest('[role="tab"]');
  if (tab) narrate(tab.dataset.facet);   // read this one, then carry on from here
});

// --- turntable
function setFrame(i) {
  if (!spinFrames.length) return;
  spinIndex = ((i % spinFrames.length) + spinFrames.length) % spinFrames.length;
  scSpin.src = spinFrames[spinIndex];
}

function startAutoSpin() {
  stopAutoSpin();
  if (spinFrames.length && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    spinTimer = setInterval(() => setFrame(spinIndex + 1), SPIN_AUTO_MS);
  }
}

function stopAutoSpin() {
  clearInterval(spinTimer);
  spinTimer = null;
}

scView.addEventListener('pointerdown', (e) => {
  if (!spinFrames.length || scView.dataset.mode !== 'spin') return;
  stopAutoSpin();
  clearTimeout(mediaTimer);
  scView.setPointerCapture(e.pointerId);
  spinDrag = { x: e.clientX, start: spinIndex };
  scView.classList.add('dragging');
  scHint.classList.add('used');
});
scView.addEventListener('pointermove', (e) => {
  if (!spinDrag) return;
  setFrame(spinDrag.start - Math.round((e.clientX - spinDrag.x) / SPIN_STEP_PX));
});
const endDrag = () => {
  if (!spinDrag) return;
  spinDrag = null;
  scView.classList.remove('dragging');
  // let go: the turntable resumes, and the tour moves on after a pause
  setTimeout(() => { if (scView.dataset.mode === 'spin' && !spinDrag) startAutoSpin(); }, 1500);
  resumeMediaTourLater();
};
scView.addEventListener('pointerup', endDrag);
scView.addEventListener('pointercancel', endDrag);

// --- view modes: 360° (or render) and photos
function showView(mode, src) {
  scView.dataset.mode = mode;
  if (mode !== 'video') scVideo.pause();
  if (mode === 'photo') {
    stopAutoSpin();
    scPhoto.src = src;
  } else if (mode === 'video') {
    stopAutoSpin();
    if (!scVideo.src.endsWith(src)) {
      scVideo.poster = posterFor(src);
      scVideo.src = src;
    }
    scVideo.currentTime = 0;
    scVideo.play().catch(() => {});
  } else {
    startAutoSpin();
  }
  scHint.hidden = !(mode === 'spin' && spinFrames.length);
  for (const t of scThumbs.children) t.setAttribute('aria-current', String(t.dataset.src === (src || 'spin')));
}

const posterFor = (video) => video.replace(/\.mp4$/, '-poster.webp');

function renderThumbs(media) {
  const items = [{ src: 'spin', img: media.spin[0] || media.render, label: media.spin.length ? '360°' : 'Model' }]
    .concat((media.videos || []).map((v, i) => ({ src: v, video: true, label: `Video ${i + 1}` })))
    .concat(media.gallery.map((g, i) => ({ src: g, img: g, label: `Photo ${i + 1}` })));
  scThumbs.replaceChildren(...items.map((item, i) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'sc-thumb';
    b.dataset.src = item.src;
    b.style.setProperty('--i', i);
    b.setAttribute('role', 'listitem');
    b.setAttribute('aria-label', item.label);
    if (item.video) {
      // poster: a still from ~1.5 s in, made once — the opening frame is often black
      const img = document.createElement('img');
      img.src = posterFor(item.src);
      img.alt = '';
      img.loading = 'lazy';
      b.append(img);
      b.classList.add('is-video');
      b.dataset.kind = 'video';
    } else {
      const img = document.createElement('img');
      img.src = item.img;
      img.alt = '';
      img.loading = 'lazy';
      b.append(img);
    }
    if (item.src === 'spin') {
      const tag = document.createElement('span');
      tag.textContent = item.label;
      b.append(tag);
    }
    return b;
  }));
}

scThumbs.addEventListener('click', (e) => {
  const t = e.target.closest('.sc-thumb');
  if (!t) return;
  // every thumbnail is a stop on the tour: jump there, and carry on from it
  playMedia(mediaItems.indexOf(t.dataset.src));
});

// --- media tour: 360° view, each video in turn, then each photo, then round
// again. A video moves on when it ends; the turntable after one slow turn; a
// photo after a few seconds.
const SPIN_DWELL_MS = 6000;
const PHOTO_DWELL_MS = 5000;
const RESUME_AFTER_MS = 7000;   // after a drag or a photo, before the tour moves on
let mediaItems = [];
let mediaIdx = 0;
let mediaTimer = null;

function playMedia(i) {
  clearTimeout(mediaTimer);
  if (!mediaItems.length || showcase.hidden) return;
  mediaIdx = ((i % mediaItems.length) + mediaItems.length) % mediaItems.length;
  const item = mediaItems[mediaIdx];
  if (item === 'spin') {
    showView('spin');
    if (mediaItems.length > 1) mediaTimer = setTimeout(() => playMedia(mediaIdx + 1), SPIN_DWELL_MS);
  } else if (item.endsWith('.mp4')) {
    showView('video', item);
  } else {
    showView('photo', item);
    mediaTimer = setTimeout(() => playMedia(mediaIdx + 1), PHOTO_DWELL_MS);
  }
}

function resumeMediaTourLater() {
  clearTimeout(mediaTimer);
  mediaTimer = setTimeout(() => playMedia(mediaIdx + 1), RESUME_AFTER_MS);
}

scVideo.addEventListener('ended', () => {
  if (!showcase.hidden && scView.dataset.mode === 'video') playMedia(mediaIdx + 1);
});
// a clip that will not play is skipped rather than left as a black frame
scVideo.addEventListener('error', () => {
  if (!showcase.hidden && scView.dataset.mode === 'video') playMedia(mediaIdx + 1);
});

// --- narration tour: read the overview, then each tab in turn. After one
// spoken pass the tabs keep cycling quietly, so the sheet stays alive on a
// kiosk without the robot talking forever.
const BASE_FACETS = ['overview', 'specs', 'features', 'uses', 'industries'];
let FACET_ORDER = BASE_FACETS;
const FACET_INTRO = {
  overview: '',
  specs: 'Specifications.',
  features: 'Key features.',
  attachments: 'Attachments.',
  uses: 'Applications.',
  industries: 'Industries.',
};
const TAB_DWELL_MS = 9000;
let tourToken = 0;
let tabTimer = null;

function currentFacet() {
  return scTabs.querySelector('[aria-selected="true"]')?.dataset.facet || 'overview';
}

function narrate(facet) {
  const token = ++tourToken;
  clearTimeout(tabTimer);
  showFacet(facet);
  const lines = [FACET_INTRO[facet], ...(scProduct?.sections[facet] || [])].filter(Boolean);
  speakInSheet(lines, () => {
    if (token !== tourToken || showcase.hidden) return;
    const next = FACET_ORDER.indexOf(facet) + 1;
    if (next < FACET_ORDER.length) narrate(FACET_ORDER[next]);
    else rotateTabs();
  });
}

function rotateTabs() {
  const token = ++tourToken;
  clearTimeout(tabTimer);
  const step = () => {
    if (token !== tourToken || showcase.hidden) return;
    const i = FACET_ORDER.indexOf(currentFacet());
    showFacet(FACET_ORDER[(i + 1) % FACET_ORDER.length]);
    tabTimer = setTimeout(step, TAB_DWELL_MS);
  };
  tabTimer = setTimeout(step, TAB_DWELL_MS);
}

function stopTours() {
  tourToken += 1;
  clearTimeout(tabTimer);
  clearTimeout(mediaTimer);
}

// --- speaking inside the sheet
function speakInSheet(lines, onDone) {
  cancelClosing();
  cancelTranscription();
  setState('speaking');
  speak(lines.join(' '), () => {
    setState('idle');
    onDone?.();
  });
}

// Stop silences the voice; the tabs carry on cycling quietly.
document.getElementById('scStop').addEventListener('click', () => {
  cancelSpeech();
  setState('idle');
  rotateTabs();
});
// The whole tour again, from the overview.
document.getElementById('scBrief').addEventListener('click', () => {
  if (scProduct) narrate('overview');
});
document.getElementById('scDemo').addEventListener('click', () => {
  closeShowcase();
  ask('Can I get a demo?');
});

async function openShowcase(key, opener) {
  let data;
  try {
    data = await (await fetch(`/api/products/${encodeURIComponent(key)}`)).json();
  } catch (err) {
    setStatus('Could not open that product — please try again');
    return;
  }
  if (!data || !data.sections) return;
  scProduct = data;
  scOpener = opener || null;
  scName.textContent = data.name;
  scKind.textContent = data.kind;
  scLead.replaceChildren(withFigures(data.sections.overview[0] || ''));

  spinFrames = data.media.spin;
  scSpin.src = spinFrames[0] || data.media.render;
  // warm the turntable so the first drag is smooth
  spinFrames.forEach((src) => { const im = new Image(); im.src = src; });
  spinIndex = 0;
  scView.classList.toggle('static', !spinFrames.length);
  renderThumbs(data.media);
  // Attachments get their own tab, after features, only where they exist.
  const hasAttachments = Boolean(data.attachments?.length);
  scTabs.querySelector('[data-facet="attachments"]').hidden = !hasAttachments;
  FACET_ORDER = hasAttachments
    ? ['overview', 'specs', 'features', 'attachments', 'uses', 'industries']
    : BASE_FACETS;
  showFacet('overview');

  showcase.hidden = false;
  document.body.classList.add('sheet-open');
  requestAnimationFrame(() => showcase.classList.add('open'));
  showcase.querySelector('.sc-close').focus({ preventScroll: true });

  mediaItems = ['spin', ...(data.media.videos || []), ...(data.media.gallery || [])];
  playMedia(0);
  narrate('overview');
}

function closeShowcase() {
  if (showcase.hidden) return;
  stopTours();
  stopAutoSpin();
  scVideo.pause();
  cancelSpeech();
  if (stage.dataset.state === 'speaking') setState('idle');
  showcase.classList.remove('open');
  document.body.classList.remove('sheet-open');
  setTimeout(() => { showcase.hidden = true; }, 380);
  scOpener?.focus({ preventScroll: true });
}

showcase.addEventListener('click', (e) => {
  if (e.target.closest('[data-close]')) closeShowcase();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !showcase.hidden) closeShowcase();
});

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
      card.dataset.key = product.key;
      card.setAttribute('aria-haspopup', 'dialog');
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
[...topics.children].forEach((chip, i) => { chip.style.setProperty('--i', i + 6); decorateChip(chip); });

// --- clock ----------------------------------------------------------------
const clockTime = document.getElementById('clockTime');
const clockDate = document.getElementById('clockDate');
function tick() {
  const now = new Date();
  clockTime.textContent = now.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' });
  clockDate.textContent = now.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' });
}
tick();
setInterval(tick, 1000);
document.body.classList.add('ready');
answerEl.classList.add('in');

if (!forced) {
  boot().then(() => {
    // Deep link: /?q=who+is+the+CEO asks on load.
    const preset = new URLSearchParams(location.search).get('q');
    if (preset) ask(preset);
  });
}
