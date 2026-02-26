const $ = (id) => document.getElementById(id);

const PIPELINE_STEPS = [
  { name: "Embeddings", desc: "Vetorizando a pergunta.", durationMs: 2200, badge: "EMBEDDINGS" },
  { name: "Busca hibrida", desc: "Buscando candidatos no acervo.", durationMs: 3000, badge: "BUSCA" },
  { name: "Rerank", desc: "Ordenando por relevancia juridica.", durationMs: 2500, badge: "RERANK" },
  { name: "Geracao", desc: "Redigindo sintese com citacoes.", durationMs: 4000, badge: "GERACAO" },
  { name: "Validacao", desc: "Conferindo consistencia final.", durationMs: 2800, badge: "VALIDACAO" }
];
const PIPELINE_LOOP_MS = PIPELINE_STEPS.reduce((acc, step) => acc + Number(step.durationMs || 0), 0);
const PIPELINE_STAGE_TO_STEP = {
  embedding_start: 0,
  embedding_done: 0,
  retrieval_start: 1,
  retrieval_done: 1,
  rerank_start: 2,
  rerank_done: 2,
  generation_start: 3,
  generation_done: 3,
  validation_start: 4,
  done: 4
};
const PENDING_REFRESH_MS = 220;
const SESSION_STORAGE_KEY = "jurisai_session_v1";
const ONBOARDING_STORAGE_KEY = "jurisai_onboarding_seen_v1";
const ONBOARDING_KEY_VALIDATE_TIMEOUT_MS = 18000;
const ONBOARDING_KEY_STATUS_PULSE_MS = 1000;
const ONBOARDING_KEY_LONG_WAIT_SECONDS = 8;
const ONBOARDING_KEY_VERY_LONG_WAIT_SECONDS = 16;
const USER_CORPUS_INDEX_TIMEOUT_MS = 900000;
const USER_CORPUS_JOB_POLL_DEFAULT_MS = 1200;
const QUERY_STREAM_TIMEOUT_MS = 0;
const QUERY_STREAM_TIMEOUT_LABEL = "A consulta juridica";
const AUDIO_TTS_TIMEOUT_BASE_MS = 240000;
const AUDIO_TTS_TIMEOUT_PER_1000_CHARS_MS = 25000;
const AUDIO_TTS_TIMEOUT_MAX_MS = 600000;
const MAX_STORED_TURNS = 80;
const ANSWER_FONT_SCALE_MIN = 0.85;
const ANSWER_FONT_SCALE_MAX = 1.35;
const ANSWER_FONT_SCALE_STEP = 0.05;
const ANSWER_FONT_BASE_PX = 18;
const ANSWER_FONT_BASE_PX_MOBILE = 17;
const ANSWER_FONT_BASE_PX_LARGE = 19;
const DOC_REF_GROUP_RE = /\[([^\]]*(?:DOCUMENTO|DOC(?:UMENTO)?\.?)[^\]]*)\]/gi;
const DOC_REF_NUMBER_RE = /(?:DOCUMENTO|DOC(?:UMENTO)?\.?)\s*(\d+)/gi;
const RAG_SCHEMA_FALLBACK = [];
const LIBRARY_MODE_DEFAULT = "history";
const RAG_GROUP_HELP = {
  "Busca e Ranking": [
    "Aumente Candidatos Hibridos e Documentos Finais para ampliar cobertura e diversidade de precedentes.",
    "Valores maiores elevam custo e latencia da consulta.",
    "No modo padrao enriquecido, o top-k final vem mais alto para respostas mais densas."
  ].join("\n"),
  "Fontes A-E": [
    "Nivel A: fontes vinculantes fortes (sumula vinculante e controle concentrado STF).",
    "Nivel B: precedentes qualificados (tema de repercussao geral, tema repetitivo, IRDR, IAC).",
    "Nivel C: sumulas de observancia qualificada (STF/STJ).",
    "Nivel D: acordaos nao vinculantes e decisoes monocraticas (orientativos).",
    "Nivel E: material editorial (informativos e compilacoes)."
  ].join("\n"),
  "Contexto da Resposta": [
    "Para respostas mais ricas, aumente Passagens por Documento e Chars Max por Documento.",
    "Valores baixos deixam a resposta mais curta por falta de contexto textual.",
    "Ajustes muito altos aumentam custo e latencia."
  ].join("\n"),
  "Modelo de Resposta": [
    "Tokens Max da Resposta controla o tamanho maximo do texto final.",
    "Se estiver curto, aumente Tokens Max da Resposta.",
    "Se houver aviso de MAX_TOKENS, reduza Orcamento de Raciocinio (Thinking) ou troque o modelo principal."
  ].join("\n"),
  "Validacao": [
    "Limiar de Auditoria de Citacao define quando um paragrafo passa a exigir citacao explicita.",
    "Valores menores deixam a auditoria mais rigorosa e podem adicionar avisos com mais frequencia.",
    "Use esse controle para equilibrar rigor de citacao e fluidez textual."
  ].join("\n")
};
const LIBRARY_MODE_META = {
  history: {
    title: "Historico",
    hint: "Consultas recentes da sessao atual.",
    empty: "Nenhuma consulta registrada ainda."
  },
  saved: {
    title: "Salvos",
    hint: "Consultas que voce salvou para revisao rapida.",
    empty: "Nenhuma consulta salva ainda."
  }
};

const state = {
  apiBase: localStorage.getItem("jurisai_api_base") || "http://127.0.0.1:8000",
  turns: [],
  activeTurnId: null,
  answerFontScale: 1,
  onboardingSeen: localStorage.getItem(ONBOARDING_STORAGE_KEY) === "1",
  about: {
    open: false,
    activeTab: "acervo"
  },
  library: {
    open: false,
    mode: LIBRARY_MODE_DEFAULT
  },
  pendingTickerId: null,
  ragConfigVersion: "",
  ragConfigDefaults: {},
  ragConfigSchema: [],
  ragConfigValues: {},
  acervo: {
    sources: [],
    selectedSources: ["ratio"]
  },
  speech: {
    activeTurnId: null,
    mode: "",
    progressPct: 0,
    isLoading: false,
    isBuffering: false,
    isPaused: false,
    objectUrl: "",
    queue: [],
    isStreaming: false,
    streamController: null,
    abortReason: "",
    traceId: "",
    totalChunks: 0,
    bufferedChunks: 0,
    playedChunks: 0,
    currentChunkIndex: 0
  }
};

const audioPlayer = new Audio();
audioPlayer.preload = "auto";

const overlay = $("overlay");
const onboardingModal = $("onboardingModal");
const closeOnboardingBtn = $("closeOnboardingBtn");
const onboardingPrimaryBtn = $("onboardingPrimaryBtn");
const openOnboardingGuideBtn = $("openOnboardingGuideBtn");
const onboardingApiKeyInput = $("onboardingApiKeyInput");
const onboardingPersistEnv = $("onboardingPersistEnv");
const onboardingSaveKeyBtn = $("onboardingSaveKeyBtn");
const onboardingKeyStatus = $("onboardingKeyStatus");
const aboutModal = $("aboutModal");
const closeAboutBtn = $("closeAboutBtn");
const aboutTabs = $("aboutTabs");
const aboutTabButtons = Array.from(document.querySelectorAll(".about-tab[data-about-tab-target]"));
const aboutPanes = Array.from(document.querySelectorAll(".about-pane[data-about-pane]"));
const openAboutBtns = Array.from(document.querySelectorAll("[data-open-about]"));
const openAcervoBtns = Array.from(document.querySelectorAll("[data-open-acervo]"));
const copyPixKeyBtn = $("copyPixKeyBtn");
const pixKeyText = $("pixKeyText");
const settingsPanel = $("settingsPanel");
const acervoPanel = $("acervoPanel");
const evidencePanel = $("evidencePanel");
const apiBaseInput = $("apiBase");
const rerankerBackend = $("rerankerBackend");
const geminiRerankModelInput = $("geminiRerankModelInput");
const preferRecent = $("preferRecent");
const queryInput = $("queryInput");
const askBtn = $("askBtn");
const requestState = $("requestState");
const thread = $("thread");
const metricsBox = $("metricsBox");
const sourcesBox = $("sourcesBox");
const docCountTag = $("docCountTag");
const topSourceCount = $("topSourceCount");
const rerankerChipValue = $("rerankerChipValue");
const clearChatBtn = $("clearChatBtn");
const libraryPanel = $("libraryPanel");
const libraryTitle = $("libraryTitle");
const libraryCountTag = $("libraryCountTag");
const libraryHint = $("libraryHint");
const libraryList = $("libraryList");
const closeLibraryBtn = $("closeLibraryBtn");
const railModeButtons = Array.from(document.querySelectorAll(".rail-btn[data-library-mode]"));
const railAcervoButtons = Array.from(document.querySelectorAll(".rail-btn[data-open-acervo]"));
const railSettingsButtons = Array.from(document.querySelectorAll(".rail-btn[data-open-settings]"));

const toggleSettingsBtn = $("toggleSettingsBtn");
const closeSettingsBtn = $("closeSettingsBtn");
const closeAcervoBtn = $("closeAcervoBtn");
const toggleEvidenceBtn = $("toggleEvidenceBtn");
const resetRagConfigBtn = $("resetRagConfigBtn");
const saveRagConfigBtn = $("saveRagConfigBtn");
const ragConfigStatus = $("ragConfigStatus");
const ragAdvancedGroups = $("ragAdvancedGroups");
const generationModelInput = $("generationModelInput");
const generationFallbackModelInput = $("generationFallbackModelInput");
const geminiModelsList = $("geminiModelsList");
const userCorpusNameInput = $("userCorpusNameInput");
const userCorpusFilesInput = $("userCorpusFilesInput");
const userCorpusOcrMissingOnly = $("userCorpusOcrMissingOnly");
const userSourcePriorityToggle = $("userSourcePriorityToggle");
const indexUserCorpusBtn = $("indexUserCorpusBtn");
const userCorpusStatus = $("userCorpusStatus");
const userCorpusSources = $("userCorpusSources");
const sourceFiltersList = $("sourceFiltersList");
const userCorpusStages = $("userCorpusStages");

marked.setOptions({ gfm: true, breaks: false });

const USER_CORPUS_STAGE_FLOW = ["ready", "upload", "extract", "clean", "embed", "done"];
let userCorpusStageTimer = null;

function nowId() {
  return String(Date.now()) + String(Math.floor(Math.random() * 1000));
}

function safeText(value, fallback = "-") {
  const txt = String(value ?? "").trim();
  return txt || fallback;
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function dateHuman(raw) {
  const m = String(raw || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : safeText(raw, "-");
}

function formatSeconds(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return `${value.toFixed(2)}s`;
}

function normalizeLibraryMode(rawMode) {
  const mode = String(rawMode || "").trim().toLowerCase();
  if (mode === "saved" || mode === "pinned" || mode === "marked") return "saved";
  if (mode === "history") return "history";
  return LIBRARY_MODE_DEFAULT;
}

function libraryModeMeta(mode) {
  return LIBRARY_MODE_META[normalizeLibraryMode(mode)] || LIBRARY_MODE_META[LIBRARY_MODE_DEFAULT];
}

function shortText(value, maxLen = 110) {
  const clean = String(value || "").replace(/\s+/g, " ").trim();
  if (!clean) return "-";
  return clean.length > maxLen ? `${clean.slice(0, Math.max(12, maxLen - 1))}\u2026` : clean;
}

function startedAtHuman(startedAt) {
  if (!Number.isFinite(Number(startedAt))) return "-";
  try {
    return new Date(Number(startedAt)).toLocaleString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    });
  } catch (_) {
    return "-";
  }
}

function estimateTtsTimeoutMs(text) {
  const chars = String(text || "").trim().length;
  const extra = Math.ceil(chars / 1000) * AUDIO_TTS_TIMEOUT_PER_1000_CHARS_MS;
  const estimated = AUDIO_TTS_TIMEOUT_BASE_MS + extra;
  return Math.max(
    AUDIO_TTS_TIMEOUT_BASE_MS,
    Math.min(AUDIO_TTS_TIMEOUT_MAX_MS, estimated)
  );
}

function sourceSummary(turn, maxItems = 2) {
  const docs = Array.isArray(turn?.docs) ? turn.docs : [];
  if (!docs.length) return "Sem fontes associadas.";
  const head = docs.slice(0, maxItems).map((doc) => {
    const tipo = safeText(doc.tipo_label || doc.tipo, "Documento");
    const proc = safeText(doc.processo, "-");
    return `${tipo}: ${proc}`;
  });
  const hidden = docs.length - head.length;
  return hidden > 0 ? `${head.join(" | ")} | +${hidden} fonte(s)` : head.join(" | ");
}

function normalizeStoredTurn(raw) {
  if (!raw || typeof raw !== "object") return null;
  const status = raw.status === "done" || raw.status === "error" || raw.status === "pending" ? raw.status : "error";
  const turn = {
    id: String(raw.id || nowId()),
    query: String(raw.query || "").trim(),
    status,
    answer: String(raw.answer || ""),
    docs: Array.isArray(raw.docs) ? raw.docs : [],
    meta: raw.meta && typeof raw.meta === "object" ? raw.meta : {},
    explanation: String(raw.explanation || ""),
    error: String(raw.error || ""),
    startedAt: Number.isFinite(Number(raw.startedAt)) ? Number(raw.startedAt) : Date.now(),
    saved: !!(raw.saved || raw.pinned || raw.marked),
    lastAudioMode: raw.lastAudioMode === "explicacao" ? "explicacao" : "resposta"
  };
  if (!turn.query) return null;
  if (turn.status === "pending") {
    turn.status = "error";
    turn.error = turn.error || "Consulta interrompida (sessao anterior).";
  }
  return turn;
}

function loadStoredSession() {
  const fallback = {
    turns: [],
    activeTurnId: null,
    answerFontScale: 1,
    rerankerBackend: "local",
    preferRecent: true,
    preferUserSources: true,
    sourceSelection: ["ratio"],
    evidenceOpen: null,
    libraryMode: LIBRARY_MODE_DEFAULT,
    ragConfigVersion: "",
    ragConfigValues: {}
  };
  try {
    const raw = localStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw);
    const turns = Array.isArray(parsed?.turns)
      ? parsed.turns.map(normalizeStoredTurn).filter(Boolean).slice(-MAX_STORED_TURNS)
      : [];
    let activeTurnId = parsed?.activeTurnId ? String(parsed.activeTurnId) : null;
    if (activeTurnId && !turns.some((t) => t.id === activeTurnId)) {
      activeTurnId = null;
    }
    if (!activeTurnId && turns.length) {
      activeTurnId = turns[turns.length - 1].id;
    }
    return {
      turns,
      activeTurnId,
      answerFontScale: Number.isFinite(Number(parsed?.answerFontScale))
        ? Math.max(ANSWER_FONT_SCALE_MIN, Math.min(ANSWER_FONT_SCALE_MAX, Number(parsed.answerFontScale)))
        : 1,
      rerankerBackend: parsed?.rerankerBackend === "gemini" ? "gemini" : "local",
      preferRecent: typeof parsed?.preferRecent === "boolean" ? parsed.preferRecent : true,
      preferUserSources: typeof parsed?.preferUserSources === "boolean" ? parsed.preferUserSources : true,
      sourceSelection: Array.isArray(parsed?.sourceSelection)
        ? parsed.sourceSelection.map((v) => String(v || "").trim()).filter(Boolean)
        : ["ratio"],
      evidenceOpen: typeof parsed?.evidenceOpen === "boolean" ? parsed.evidenceOpen : null,
      libraryMode: normalizeLibraryMode(parsed?.libraryMode),
      ragConfigVersion: String(parsed?.ragConfigVersion || "").trim(),
      ragConfigValues: parsed?.ragConfigValues && typeof parsed.ragConfigValues === "object" ? parsed.ragConfigValues : {}
    };
  } catch (_) {
    return fallback;
  }
}

function persistSession() {
  try {
    const payload = {
      turns: state.turns.slice(-MAX_STORED_TURNS).map((turn) => ({
        id: turn.id,
        query: turn.query,
        status: turn.status,
        answer: turn.answer,
        docs: Array.isArray(turn.docs) ? turn.docs : [],
        meta: turn.meta || {},
        explanation: turn.explanation || "",
        error: turn.error || "",
        startedAt: turn.startedAt || Date.now(),
        saved: !!turn.saved,
        lastAudioMode: turn.lastAudioMode === "explicacao" ? "explicacao" : "resposta"
      })),
      activeTurnId: state.activeTurnId || null,
      answerFontScale: state.answerFontScale,
      rerankerBackend: rerankerBackend?.value === "gemini" ? "gemini" : "local",
      preferRecent: !!preferRecent?.checked,
      preferUserSources: userSourcePriorityToggle?.checked !== false,
      sourceSelection: Array.isArray(state.acervo.selectedSources) ? state.acervo.selectedSources : ["ratio"],
      evidenceOpen: document.body.dataset.evidenceOpen === "true",
      libraryMode: normalizeLibraryMode(state.library.mode),
      ragConfigVersion: String(state.ragConfigVersion || ""),
      ragConfigValues: state.ragConfigValues || {},
      savedAt: Date.now()
    };
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(payload));
  } catch (_) {
    // Ignore storage failures (private mode / quota / policies).
  }
}

function rerankerLabel(value) {
  return value === "gemini" ? "Gemini" : "Local";
}

function refreshHeaderBadges() {
  if (rerankerChipValue) {
    rerankerChipValue.textContent = rerankerLabel(rerankerBackend?.value || "local");
  }
  if (topSourceCount) {
    const turn = getTurn(state.activeTurnId);
    const count = turn?.status === "done" && Array.isArray(turn.docs) ? turn.docs.length : 0;
    topSourceCount.textContent = String(count);
  }
}

function setRequestState(text, isError = false) {
  requestState.textContent = text || "";
  requestState.className = isError ? "request-state error" : "request-state";
}

function applyAnswerFontScale() {
  const scale = Number.isFinite(Number(state.answerFontScale)) ? Number(state.answerFontScale) : 1;
  const clamped = Math.max(ANSWER_FONT_SCALE_MIN, Math.min(ANSWER_FONT_SCALE_MAX, scale));
  state.answerFontScale = Number(clamped.toFixed(2));
  document.documentElement.style.setProperty("--answer-font-scale", String(state.answerFontScale));
  document.documentElement.style.setProperty("--answer-font-size", `${(ANSWER_FONT_BASE_PX * state.answerFontScale).toFixed(2)}px`);
  document.documentElement.style.setProperty("--answer-font-size-mobile", `${(ANSWER_FONT_BASE_PX_MOBILE * state.answerFontScale).toFixed(2)}px`);
  document.documentElement.style.setProperty("--answer-font-size-large", `${(ANSWER_FONT_BASE_PX_LARGE * state.answerFontScale).toFixed(2)}px`);
}

function adjustAnswerFontScale(deltaStep) {
  const next = state.answerFontScale + (deltaStep * ANSWER_FONT_SCALE_STEP);
  const clamped = Math.max(ANSWER_FONT_SCALE_MIN, Math.min(ANSWER_FONT_SCALE_MAX, next));
  const rounded = Number(clamped.toFixed(2));
  if (rounded === state.answerFontScale) return;
  state.answerFontScale = rounded;
  applyAnswerFontScale();
  persistSession();
  renderThread({ autoscroll: false });
  setRequestState(`Fonte da resposta: ${Math.round(state.answerFontScale * 100)}%.`);
}

function setSettingsOpen(open) {
  if (open) {
    state.about.open = false;
    document.body.dataset.aboutOpen = "false";
    document.body.dataset.onboardingOpen = "false";
    state.library.open = false;
    document.body.dataset.libraryOpen = "false";
    document.body.dataset.acervoOpen = "false";
  }
  document.body.dataset.settingsOpen = open ? "true" : "false";
  refreshRailButtons();
}

function setAcervoOpen(open) {
  const isOpen = !!open;
  document.body.dataset.acervoOpen = isOpen ? "true" : "false";
  if (isOpen) {
    state.about.open = false;
    document.body.dataset.aboutOpen = "false";
    document.body.dataset.onboardingOpen = "false";
    state.library.open = false;
    document.body.dataset.libraryOpen = "false";
    document.body.dataset.settingsOpen = "false";
  }
  refreshRailButtons();
}

function setEvidenceOpen(open) {
  document.body.dataset.evidenceOpen = open ? "true" : "false";
  persistSession();
}

function refreshRailButtons() {
  railModeButtons.forEach((button) => {
    const mode = normalizeLibraryMode(button.dataset.libraryMode);
    button.classList.toggle("active", mode === state.library.mode);
  });
  const acervoOpen = document.body.dataset.acervoOpen === "true";
  railAcervoButtons.forEach((button) => {
    button.classList.toggle("active", acervoOpen);
  });
  const settingsOpen = document.body.dataset.settingsOpen === "true";
  railSettingsButtons.forEach((button) => {
    button.classList.toggle("active", settingsOpen);
  });
}

function setLibraryOpen(open) {
  state.library.open = !!open;
  document.body.dataset.libraryOpen = state.library.open ? "true" : "false";
  if (state.library.open) {
    state.about.open = false;
    document.body.dataset.aboutOpen = "false";
    document.body.dataset.onboardingOpen = "false";
    document.body.dataset.settingsOpen = "false";
    document.body.dataset.acervoOpen = "false";
    if (window.innerWidth <= 1160) {
      setEvidenceOpen(false);
    }
  }
  refreshRailButtons();
  persistSession();
}

function setLibraryMode(mode, { open = true } = {}) {
  state.library.mode = normalizeLibraryMode(mode);
  refreshRailButtons();
  renderLibraryPanel();
  if (open) {
    setLibraryOpen(true);
  } else {
    persistSession();
  }
}

function setOnboardingOpen(open, options = {}) {
  const markSeen = !!options.markSeen;
  document.body.dataset.onboardingOpen = open ? "true" : "false";
  if (open) {
    state.about.open = false;
    document.body.dataset.aboutOpen = "false";
    document.body.dataset.settingsOpen = "false";
    document.body.dataset.acervoOpen = "false";
    state.library.open = false;
    document.body.dataset.libraryOpen = "false";
    refreshRailButtons();
    return;
  }
  if (markSeen) {
    state.onboardingSeen = true;
    try {
      localStorage.setItem(ONBOARDING_STORAGE_KEY, "1");
    } catch (_) {
      // Ignore storage failures.
    }
  }
}

function setAboutActiveTab(rawTab) {
  const tab = rawTab === "estrutura" || rawTab === "autor" ? rawTab : "acervo";
  state.about.activeTab = tab;

  for (const button of aboutTabButtons) {
    const target = button.getAttribute("data-about-tab-target") || "acervo";
    const isActive = target === tab;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-selected", isActive ? "true" : "false");
  }

  for (const pane of aboutPanes) {
    const paneKey = pane.getAttribute("data-about-pane") || "";
    pane.classList.toggle("active", paneKey === tab);
  }
}

function setAboutOpen(open) {
  state.about.open = !!open;
  document.body.dataset.aboutOpen = state.about.open ? "true" : "false";
  if (!state.about.open) return;

  document.body.dataset.settingsOpen = "false";
  document.body.dataset.acervoOpen = "false";
  document.body.dataset.onboardingOpen = "false";
  state.library.open = false;
  document.body.dataset.libraryOpen = "false";
  refreshRailButtons();
  setAboutActiveTab(state.about.activeTab || "acervo");
}

function refreshIcons() {
  if (window.lucide && typeof window.lucide.createIcons === "function") {
    window.lucide.createIcons();
  }
}

function selectedValues(className) {
  return Array.from(document.querySelectorAll(`.${className}:checked`)).map((el) => el.value);
}

function selectedSourceValues() {
  return selectedValues("source-checkbox");
}

function normalizeSourceSelection(raw, availableIds) {
  const available = new Set(Array.isArray(availableIds) ? availableIds : []);
  const picked = Array.isArray(raw) ? raw.map((v) => String(v || "").trim()).filter(Boolean) : [];
  const next = picked.filter((id) => available.has(id));
  if (next.length) return next;
  if (available.has("ratio")) return ["ratio"];
  return [];
}

function renderSourceFilters() {
  if (!sourceFiltersList) return;
  const sources = Array.isArray(state.acervo.sources) ? state.acervo.sources : [];
  const visibleSources = sources.filter((src) => {
    const kind = String(src?.kind || "user").trim().toLowerCase();
    const deleted = !!src?.deleted;
    return kind === "ratio" || !deleted;
  });
  if (!visibleSources.length) {
    sourceFiltersList.innerHTML = `<p class="sources-empty">Nenhuma fonte disponivel para pesquisa.</p>`;
    return;
  }

  const selected = new Set(Array.isArray(state.acervo.selectedSources) ? state.acervo.selectedSources : []);
  sourceFiltersList.innerHTML = visibleSources.map((src) => {
    const id = String(src?.id || "").trim();
    const label = safeText(src?.label || id, id);
    const kind = String(src?.kind || "user").trim().toLowerCase();
    const checked = selected.has(id);
    const stats = kind === "user"
      ? `<span class="user-source-meta">${Number(src?.doc_count || 0)} doc(s) · ${Number(src?.chunk_count || 0)} chunk(s)</span>`
      : `<span class="user-source-meta">Base oficial</span>`;
    return `
      <div class="user-source-row">
        <label>
          <input class="source-checkbox" type="checkbox" value="${escapeHtml(id)}" ${checked ? "checked" : ""} />
          ${escapeHtml(label)}
        </label>
        ${stats}
      </div>
    `;
  }).join("");
}

function renderUserCorpusSources() {
  if (!userCorpusSources) return;
  const sources = Array.isArray(state.acervo.sources) ? state.acervo.sources : [];
  const userSources = sources.filter((src) => String(src?.kind || "user").trim().toLowerCase() === "user");
  if (!userSources.length) {
    userCorpusSources.innerHTML = `<p class="sources-empty">Nenhuma base pessoal criada ainda.</p>`;
    return;
  }

  userCorpusSources.innerHTML = userSources.map((src) => {
    const id = String(src?.id || "").trim();
    const label = safeText(src?.label || id, id);
    const deleted = !!src?.deleted;
    const actionBtn = deleted
      ? `<button class="meta-btn user-source-action" data-action="restore-source" data-source-id="${escapeHtml(id)}" type="button">Restaurar</button>`
      : `<button class="meta-btn user-source-action" data-action="delete-source" data-source-id="${escapeHtml(id)}" type="button">Excluir</button>`;
    return `
      <div class="user-source-row ${deleted ? "is-deleted" : ""}">
        <div class="user-source-main">
          <strong>${escapeHtml(label)}</strong>
          <span class="user-source-meta">${Number(src?.doc_count || 0)} doc(s) · ${Number(src?.chunk_count || 0)} chunk(s)</span>
        </div>
        ${actionBtn}
      </div>
    `;
  }).join("");
}

async function loadUserCorpusSources() {
  const base = state.apiBase.replace(/\/$/, "");
  try {
    const response = await fetch(`${base}/api/meu-acervo/sources`);
    if (!response.ok) throw new Error(String(response.status));
    const payload = await response.json();
    const sources = Array.isArray(payload?.sources) ? payload.sources : [];
    const defaults = Array.isArray(payload?.default_selected)
      ? payload.default_selected.map((v) => String(v || "").trim()).filter(Boolean)
      : ["ratio"];
    const availableIds = sources.map((src) => String(src?.id || "").trim()).filter(Boolean);

    state.acervo.sources = sources;
    state.acervo.selectedSources = normalizeSourceSelection(
      state.acervo.selectedSources?.length ? state.acervo.selectedSources : defaults,
      availableIds
    );
    renderSourceFilters();
    renderUserCorpusSources();
    persistSession();
    setUserCorpusStatus("Fontes carregadas.");
  } catch (_) {
    state.acervo.sources = [
      { id: "ratio", label: "Base Ratio (STF/STJ)", kind: "ratio", deleted: false }
    ];
    state.acervo.selectedSources = ["ratio"];
    renderSourceFilters();
    renderUserCorpusSources();
    setUserCorpusStatus("Nao foi possivel carregar fontes do Meu Acervo.", true);
  }
}

function escapeAttr(text) {
  return escapeHtml(text).replace(/\n/g, "&#10;");
}

function setRagConfigStatus(text, isError = false) {
  if (!ragConfigStatus) return;
  ragConfigStatus.textContent = text || "";
  ragConfigStatus.className = isError ? "rag-config-status error" : "rag-config-status";
}

function setUserCorpusStatus(text, isError = false) {
  if (!userCorpusStatus) return;
  userCorpusStatus.textContent = text || "";
  userCorpusStatus.className = isError ? "rag-config-status error" : "rag-config-status";
}

function stopUserCorpusStageTicker() {
  if (userCorpusStageTimer) {
    clearInterval(userCorpusStageTimer);
    userCorpusStageTimer = null;
  }
}

function setUserCorpusStage(stage, { errored = false } = {}) {
  if (!userCorpusStages) return;
  const activeIndex = USER_CORPUS_STAGE_FLOW.indexOf(stage);
  const resolvedIndex = activeIndex >= 0 ? activeIndex : 0;
  userCorpusStages.querySelectorAll("[data-index-stage]").forEach((item, idx) => {
    item.classList.remove("active", "done", "error");
    if (idx < resolvedIndex) item.classList.add("done");
    if (idx === resolvedIndex) item.classList.add("active");
  });
  if (errored) {
    const activeNode = userCorpusStages.querySelector(`[data-index-stage="${stage}"]`);
    if (activeNode) {
      activeNode.classList.add("error");
    }
  }
}

function resetUserCorpusStages() {
  stopUserCorpusStageTicker();
  setUserCorpusStage("ready");
}

function userCorpusStageFromBackend(job) {
  const status = String(job?.status || "").trim().toLowerCase();
  const stage = String(job?.stage || "").trim().toLowerCase();
  if (status === "done") return "done";
  if (status === "error") return "embed";
  if (stage === "extract") return "extract";
  if (stage === "clean") return "clean";
  if (stage === "embed" || stage === "finalize") return "embed";
  if (stage === "upload" || stage === "queued") return "upload";
  return "upload";
}

function formatEtaCompact(seconds) {
  const total = Number(seconds);
  if (!Number.isFinite(total) || total <= 0) return "";
  if (total < 60) return `~${Math.round(total)}s`;
  const mins = Math.round(total / 60);
  return `~${mins}min`;
}

function applyUserCorpusJobSnapshot(job) {
  const status = String(job?.status || "").trim().toLowerCase();
  const stage = userCorpusStageFromBackend(job);
  const progress = job?.progress && typeof job.progress === "object" ? job.progress : {};
  const processed = Math.max(0, Number(progress.processed_files || 0));
  const total = Math.max(0, Number(progress.total_files || 0));
  const indexedDocs = Math.max(0, Number(progress.indexed_docs || 0));
  const duplicates = Math.max(0, Number(progress.duplicate_files || 0));
  const skipped = Math.max(0, Number(progress.skipped_files || 0));
  const currentFile = String(progress.current_file || "").trim();
  const eta = formatEtaCompact(job?.eta_seconds);
  const stageMessage = String(job?.message || "").trim();

  if (status === "error") {
    const detail = String(job?.error?.message || stageMessage || "Falha desconhecida.");
    setUserCorpusStage(stage, { errored: true });
    setUserCorpusStatus(`Falha na indexacao: ${detail}`, true);
    return;
  }

  if (status === "done") {
    setUserCorpusStage("done");
    setUserCorpusStatus(
      `Indexacao concluida: ${indexedDocs} doc(s), ${duplicates} duplicado(s), ${skipped} ignorado(s).`
    );
    return;
  }

  setUserCorpusStage(stage);
  const etaSuffix = eta ? ` | ETA ${eta}` : "";
  const fileSuffix = currentFile ? ` | arquivo: ${currentFile}` : "";
  const progressLine = total > 0
    ? `${processed}/${total} arquivo(s) processados`
    : "Aguardando processamento do lote";
  const lead = stageMessage || "Indexando Meu Acervo";
  setUserCorpusStatus(`${lead} (${progressLine}${etaSuffix}${fileSuffix})`);
}

function sleepMs(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, Math.max(0, Number(ms || 0))));
}

async function fetchUserCorpusJobStatus(jobId) {
  const base = state.apiBase.replace(/\/$/, "");
  const response = await fetch(`${base}/api/meu-acervo/index/jobs/${encodeURIComponent(jobId)}`);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw apiErrorFromDetail(response.status, response.statusText, payload?.detail);
  }
  return payload;
}

async function pollUserCorpusJobUntilDone(jobId, pollMs = USER_CORPUS_JOB_POLL_DEFAULT_MS) {
  const startedAt = Date.now();
  while (true) {
    const job = await fetchUserCorpusJobStatus(jobId);
    applyUserCorpusJobSnapshot(job);
    const status = String(job?.status || "").trim().toLowerCase();
    if (status === "done") {
      return job;
    }
    if (status === "error") {
      const err = new Error(String(job?.error?.message || job?.message || "Falha na indexacao."));
      err.code = String(job?.error?.code || "index_job_failed");
      throw err;
    }
    if (Date.now() - startedAt > USER_CORPUS_INDEX_TIMEOUT_MS) {
      const timeoutErr = new Error(
        `A indexacao do Meu Acervo demorou mais de ${Math.round(USER_CORPUS_INDEX_TIMEOUT_MS / 1000)}s e foi interrompida.`
      );
      timeoutErr.code = "request_timeout";
      throw timeoutErr;
    }
    await sleepMs(pollMs);
  }
}

function setOnboardingKeyStatus(text, level = "info") {
  if (!onboardingKeyStatus) return;
  onboardingKeyStatus.textContent = text || "";
  onboardingKeyStatus.className = "onboarding-key-status";
  if (level === "error") onboardingKeyStatus.classList.add("error");
  if (level === "success") onboardingKeyStatus.classList.add("success");
}

function startOnboardingKeyValidationFeedback() {
  const startedAt = Date.now();

  const renderStatus = () => {
    const elapsedSec = Math.max(1, Math.floor((Date.now() - startedAt) / 1000));
    if (elapsedSec >= ONBOARDING_KEY_VERY_LONG_WAIT_SECONDS) {
      setOnboardingKeyStatus(
        `Ainda validando a chave Gemini... ${elapsedSec}s. Sem resposta da API ate agora; verifique conectividade com Google AI.`,
        "info"
      );
      return;
    }
    if (elapsedSec >= ONBOARDING_KEY_LONG_WAIT_SECONDS) {
      setOnboardingKeyStatus(
        `A validacao da chave esta demorando... ${elapsedSec}s. Isso pode ocorrer por latencia de rede ou indisponibilidade temporaria.`,
        "info"
      );
      return;
    }
    setOnboardingKeyStatus(`Validando chave Gemini... ${elapsedSec}s`, "info");
  };

  renderStatus();
  const timerId = setInterval(renderStatus, ONBOARDING_KEY_STATUS_PULSE_MS);
  return () => clearInterval(timerId);
}

function schemaItemByKey(key) {
  return (state.ragConfigSchema || []).find((item) => item?.key === key) || null;
}

function normalizeRagConfigValue(item, rawValue, fallbackValue) {
  const type = String(item?.type || "float").toLowerCase();
  const value = rawValue === undefined ? fallbackValue : rawValue;
  const min = Number(item?.min);
  const max = Number(item?.max);

  if (type === "bool") {
    if (typeof value === "boolean") return value;
    if (typeof value === "number") return value !== 0;
    const norm = String(value || "").trim().toLowerCase();
    return norm === "1" || norm === "true" || norm === "yes" || norm === "sim" || norm === "on";
  }

  if (type === "string") {
    const txt = String(value ?? "").trim();
    return txt || String(fallbackValue ?? "");
  }

  let num = Number(value);
  if (!Number.isFinite(num)) num = Number(fallbackValue);
  if (!Number.isFinite(num)) num = 0;
  if (Number.isFinite(min)) num = Math.max(min, num);
  if (Number.isFinite(max)) num = Math.min(max, num);
  if (type === "int") num = Math.round(num);
  return num;
}

function ragValueChanged(key) {
  if (!Object.prototype.hasOwnProperty.call(state.ragConfigDefaults, key)) return false;
  const current = state.ragConfigValues?.[key];
  const fallback = state.ragConfigDefaults[key];
  if (typeof fallback === "number") {
    return Number(current) !== Number(fallback);
  }
  return current !== fallback;
}

function renderRagControl(item) {
  const key = String(item?.key || "").trim();
  if (!key) return "";
  const type = String(item?.type || "float").toLowerCase();
  const label = safeText(item?.label, key);
  const detail = safeText(item?.help, "");
  const more = safeText(item?.impact_more, "Aumenta o efeito desse parametro.");
  const less = safeText(item?.impact_less, "Reduz o efeito desse parametro.");
  const helpParts = [];
  if (detail) helpParts.push(detail);
  helpParts.push(`Mais: ${more}`);
  helpParts.push(`Menos: ${less}`);
  const helpTitle = helpParts.join("\n");
  const defaults = state.ragConfigDefaults || {};
  const fallbackValue = defaults[key];
  const currentValue = normalizeRagConfigValue(item, state.ragConfigValues?.[key], fallbackValue);
  const changedClass = ragValueChanged(key) ? "changed" : "";
  const defaultText = typeof fallbackValue === "boolean"
    ? (fallbackValue ? "ligado" : "desligado")
    : String(fallbackValue ?? "-");

  if (type === "bool") {
    return `
      <article class="rag-control rag-control-toggle ${changedClass}" data-rag-key="${escapeAttr(key)}" data-rag-type="${escapeAttr(type)}">
        <label class="toggle-row rag-toggle-row">
          <span>${escapeHtml(label)}</span>
          <input data-role="bool" type="checkbox" ${currentValue ? "checked" : ""} />
        </label>
        <button class="rag-help" type="button" title="${escapeAttr(helpTitle)}">i</button>
        <p class="rag-control-meta">Padrao: ${escapeHtml(defaultText)}</p>
      </article>
    `;
  }

  if (type === "string") {
    return `
      <article class="rag-control ${changedClass}" data-rag-key="${escapeAttr(key)}" data-rag-type="${escapeAttr(type)}">
        <div class="rag-control-head">
          <span>${escapeHtml(label)}</span>
          <button class="rag-help" type="button" title="${escapeAttr(helpTitle)}">i</button>
        </div>
        <input class="rag-text" data-role="text" type="text" value="${escapeAttr(currentValue)}" />
        <p class="rag-control-meta">Padrao: ${escapeHtml(defaultText)}</p>
      </article>
    `;
  }

  const min = Number.isFinite(Number(item?.min)) ? Number(item.min) : 0;
  const max = Number.isFinite(Number(item?.max)) ? Number(item.max) : 1;
  const step = Number.isFinite(Number(item?.step)) ? Number(item.step) : (type === "int" ? 1 : 0.01);
  const val = Number(currentValue);
  return `
    <article class="rag-control ${changedClass}" data-rag-key="${escapeAttr(key)}" data-rag-type="${escapeAttr(type)}">
      <div class="rag-control-head">
        <span>${escapeHtml(label)}</span>
        <button class="rag-help" type="button" title="${escapeAttr(helpTitle)}">i</button>
      </div>
      <div class="rag-range-row">
        <input class="rag-slider" data-role="range" type="range" min="${min}" max="${max}" step="${step}" value="${val}" />
        <input class="rag-number" data-role="number" type="number" min="${min}" max="${max}" step="${step}" value="${val}" />
      </div>
      <p class="rag-control-meta">Padrao: ${escapeHtml(defaultText)}</p>
    </article>
  `;
}

function renderRagConfigControls() {
  if (!ragAdvancedGroups) return;
  const schema = Array.isArray(state.ragConfigSchema) && state.ragConfigSchema.length
    ? state.ragConfigSchema
    : RAG_SCHEMA_FALLBACK;

  if (!schema.length) {
    ragAdvancedGroups.innerHTML = `<p class="rag-empty">Nao foi possivel carregar os parametros avancados.</p>`;
    return;
  }

  const groups = new Map();
  for (const item of schema) {
    const key = String(item?.key || "");
    if (key === "generation_model" || key === "generation_fallback_model" || key === "gemini_rerank_model") {
      continue;
    }
    const group = safeText(item?.group, "Outros");
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(item);
  }

  ragAdvancedGroups.innerHTML = Array.from(groups.entries()).map(([groupName, items]) => `
    <section class="rag-group">
      <div class="rag-group-head">
        <h4>${escapeHtml(groupName)}</h4>
        ${RAG_GROUP_HELP[groupName] ? `<button class="rag-help rag-help-group" type="button" title="${escapeAttr(RAG_GROUP_HELP[groupName])}">i</button>` : ""}
      </div>
      <div class="rag-group-controls">
        ${items.map(renderRagControl).join("")}
      </div>
    </section>
  `).join("");
}

function syncGenerationModelInputsFromState() {
  if (generationModelInput) {
    generationModelInput.value = String(
      state.ragConfigValues?.generation_model
      ?? state.ragConfigDefaults?.generation_model
      ?? "gemini-3-flash-preview"
    );
  }
  if (generationFallbackModelInput) {
    generationFallbackModelInput.value = String(
      state.ragConfigValues?.generation_fallback_model
      ?? state.ragConfigDefaults?.generation_fallback_model
      ?? "gemini-2.5-flash"
    );
  }
}

function syncGenerationModelStateFromInputs() {
  const primary = String(generationModelInput?.value || "").trim();
  const fallback = String(generationFallbackModelInput?.value || "").trim();
  const defaultPrimary = String(state.ragConfigDefaults?.generation_model || "gemini-3-flash-preview").trim();
  const defaultFallback = String(state.ragConfigDefaults?.generation_fallback_model || "gemini-2.5-flash").trim();
  state.ragConfigValues.generation_model = primary || defaultPrimary;
  state.ragConfigValues.generation_fallback_model = fallback || defaultFallback;
}

function syncGeminiRerankModelInputFromState() {
  if (!geminiRerankModelInput) return;
  const value = String(
    state.ragConfigValues?.gemini_rerank_model
    ?? state.ragConfigDefaults?.gemini_rerank_model
    ?? "gemini-2.5-pro"
  ).trim();
  if (value) geminiRerankModelInput.value = value;
}

function syncGeminiRerankModelStateFromInput() {
  const value = String(geminiRerankModelInput?.value || "").trim();
  const fallback = String(state.ragConfigDefaults?.gemini_rerank_model || "gemini-2.5-pro").trim();
  state.ragConfigValues.gemini_rerank_model = value || fallback;
}

function refreshGeminiModelOptions(options) {
  if (!geminiModelsList) return;
  const values = Array.isArray(options)
    ? options.map((v) => String(v || "").trim()).filter(Boolean)
    : [];
  if (!values.length) return;
  geminiModelsList.innerHTML = values.map((value) => `<option value="${escapeAttr(value)}"></option>`).join("");
  if (geminiRerankModelInput) {
    const current = String(geminiRerankModelInput.value || "").trim();
    geminiRerankModelInput.innerHTML = values
      .map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(value)}</option>`)
      .join("");
    if (current && values.includes(current)) {
      geminiRerankModelInput.value = current;
    }
  }
}

function updateRagConfigValue(key, value) {
  const item = schemaItemByKey(key);
  if (!item) return;
  const fallback = state.ragConfigDefaults[key];
  const normalized = normalizeRagConfigValue(item, value, fallback);
  state.ragConfigValues[key] = normalized;
  persistSession();
}

function resetRagConfigToDefaults() {
  state.ragConfigValues = { ...(state.ragConfigDefaults || {}) };
  renderRagConfigControls();
  syncGenerationModelInputsFromState();
  syncGeminiRerankModelInputFromState();
  setRagConfigStatus("Parametros restaurados para o padrao.");
  persistSession();
}

async function loadRagConfigMetadata() {
  const base = state.apiBase.replace(/\/$/, "");
  try {
    const response = await fetch(`${base}/api/rag-config`);
    if (!response.ok) throw new Error(String(response.status));
    const payload = await response.json();
    const defaults = payload?.defaults && typeof payload.defaults === "object" ? payload.defaults : {};
    const schema = Array.isArray(payload?.schema) ? payload.schema : [];
    const incomingVersion = String(payload?.version || "").trim();
    const previousVersion = String(state.ragConfigVersion || "").trim();
    const resetForNewVersion = Boolean(incomingVersion && incomingVersion !== previousVersion);

    if (resetForNewVersion) {
      state.ragConfigValues = {};
    }

    state.ragConfigDefaults = { ...defaults };
    state.ragConfigSchema = schema;
    state.ragConfigVersion = incomingVersion || previousVersion;

    const nextValues = {};
    for (const item of schema) {
      const key = item?.key;
      if (!key) continue;
      const raw = Object.prototype.hasOwnProperty.call(state.ragConfigValues, key)
        ? state.ragConfigValues[key]
        : defaults[key];
      nextValues[key] = normalizeRagConfigValue(item, raw, defaults[key]);
    }
    state.ragConfigValues = nextValues;
    renderRagConfigControls();
    syncGenerationModelInputsFromState();
    syncGeminiRerankModelInputFromState();
    if (resetForNewVersion) {
      setRagConfigStatus("Preset de resposta atualizado para o modo mais rico (nova versao).");
    } else {
      setRagConfigStatus("Parametros carregados. Ajustes valem na proxima consulta.");
    }
    persistSession();
  } catch (_) {
    state.ragConfigSchema = RAG_SCHEMA_FALLBACK;
    if (!Object.keys(state.ragConfigDefaults || {}).length) {
      state.ragConfigDefaults = {};
    }
    renderRagConfigControls();
    syncGenerationModelInputsFromState();
    syncGeminiRerankModelInputFromState();
    setRagConfigStatus("Nao foi possivel carregar parametros avancados da API.", true);
  }
}

function apiPayload(query) {
  syncGenerationModelStateFromInputs();
  syncGeminiRerankModelStateFromInput();
  const tribunais = selectedValues("tribunal-checkbox");
  const tipos = selectedValues("tipo-checkbox");
  const sources = selectedSourceValues();
  state.acervo.selectedSources = sources.length ? sources : ["ratio"];
  return {
    query,
    tribunais: tribunais.length ? tribunais : null,
    tipos: tipos.length ? tipos : null,
    sources: state.acervo.selectedSources.length ? state.acervo.selectedSources : null,
    prefer_recent: !!preferRecent.checked,
    prefer_user_sources: userSourcePriorityToggle?.checked !== false,
    reranker_backend: rerankerBackend.value,
    rag_config: state.ragConfigValues
  };
}

async function postJson(path, payload, options = {}) {
  const timeoutMs = Number(options?.timeoutMs || 0);
  const timeoutLabel = String(options?.timeoutLabel || "A requisicao");
  const base = state.apiBase.replace(/\/$/, "");
  const controller = (timeoutMs > 0 && typeof AbortController === "function")
    ? new AbortController()
    : null;
  let timeoutId = null;

  if (controller && timeoutMs > 0) {
    timeoutId = setTimeout(() => {
      controller.abort();
    }, timeoutMs);
  }

  try {
    const response = await fetch(`${base}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller?.signal
    });
    const json = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = json?.detail;
      const err = apiErrorFromDetail(response.status, response.statusText, detail);
      throw err;
    }
    return json;
  } catch (err) {
    const aborted = err?.name === "AbortError" || controller?.signal?.aborted;
    if (aborted && timeoutMs > 0) {
      const timeoutErr = new Error(
        `${timeoutLabel} demorou mais de ${Math.round(timeoutMs / 1000)}s e foi interrompida.`
      );
      timeoutErr.code = "request_timeout";
      throw timeoutErr;
    }
    throw err;
  } finally {
    if (timeoutId !== null) clearTimeout(timeoutId);
  }
}

async function postFormData(path, formData, options = {}) {
  const timeoutMs = Number(options?.timeoutMs || 0);
  const timeoutLabel = String(options?.timeoutLabel || "A requisicao");
  const base = state.apiBase.replace(/\/$/, "");
  const controller = (timeoutMs > 0 && typeof AbortController === "function")
    ? new AbortController()
    : null;
  let timeoutId = null;
  if (controller && timeoutMs > 0) {
    timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  }
  try {
    const response = await fetch(`${base}${path}`, {
      method: "POST",
      body: formData,
      signal: controller?.signal
    });
    const json = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw apiErrorFromDetail(response.status, response.statusText, json?.detail);
    }
    return json;
  } catch (err) {
    const aborted = err?.name === "AbortError" || controller?.signal?.aborted;
    if (aborted && timeoutMs > 0) {
      const timeoutErr = new Error(
        `${timeoutLabel} demorou mais de ${Math.round(timeoutMs / 1000)}s e foi interrompida.`
      );
      timeoutErr.code = "request_timeout";
      throw timeoutErr;
    }
    throw err;
  } finally {
    if (timeoutId !== null) clearTimeout(timeoutId);
  }
}

function apiErrorFromDetail(status, statusText, detail) {
  let message = `${status} ${statusText || ""}`.trim();
  const traceId = detail && typeof detail === "object"
    ? String(detail.trace_id || "").trim()
    : "";
  if (detail && typeof detail === "object") {
    const baseMsg = String(detail.message || message).trim();
    const hint = String(detail.hint || "").trim();
    message = hint ? `${baseMsg} (${hint})` : baseMsg;
  } else if (detail) {
    message = String(detail);
  }
  if (traceId) {
    const marker = `[trace_id=${traceId}]`;
    if (!message.includes(marker)) {
      message = `${message} ${marker}`.trim();
    }
  }
  const err = new Error(message);
  err.code = detail && typeof detail === "object" ? String(detail.code || "") : "";
  err.hint = detail && typeof detail === "object" ? String(detail.hint || "") : "";
  err.traceId = traceId;
  err.httpStatus = Number(status || 0);
  return err;
}

async function postQueryStream(path, payload, onEvent, options = {}) {
  const timeoutMs = Number(options?.timeoutMs || QUERY_STREAM_TIMEOUT_MS);
  const timeoutLabel = String(options?.timeoutLabel || QUERY_STREAM_TIMEOUT_LABEL);
  const base = state.apiBase.replace(/\/$/, "");
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  let timeoutId = null;
  let timeoutTriggered = false;

  if (controller && timeoutMs > 0) {
    timeoutId = setTimeout(() => {
      timeoutTriggered = true;
      controller.abort();
    }, timeoutMs);
  }

  try {
    const response = await fetch(`${base}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/x-ndjson"
      },
      body: JSON.stringify(payload),
      signal: controller?.signal
    });

    if (!response.ok) {
      const json = await response.json().catch(() => ({}));
      const err = apiErrorFromDetail(response.status, response.statusText, json?.detail);
      if ([404, 405, 406, 415, 501].includes(Number(response.status))) {
        err.streamUnavailable = true;
      }
      throw err;
    }
    if (!response.body || typeof response.body.getReader !== "function") {
      const err = new Error("Streaming nao disponivel neste navegador/ambiente.");
      err.streamUnavailable = true;
      throw err;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let resultData = null;

    const consumeLine = (lineRaw) => {
      const line = String(lineRaw || "").trim();
      if (!line) return;
      let packet = null;
      try {
        packet = JSON.parse(line);
      } catch (_) {
        return;
      }
      const event = String(packet?.event || "").trim();
      if (!event || event === "heartbeat" || event === "started") return;
      if (event === "stage") {
        onEvent?.(packet);
        return;
      }
      if (event === "result") {
        resultData = packet?.data || null;
        return;
      }
      if (event === "error") {
        const err = apiErrorFromDetail(
          Number(packet?.status_code || 500),
          "StreamError",
          packet?.detail || { message: "Falha durante stream da consulta." }
        );
        throw err;
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let nlIdx = buffer.indexOf("\n");
      while (nlIdx >= 0) {
        const chunk = buffer.slice(0, nlIdx);
        buffer = buffer.slice(nlIdx + 1);
        consumeLine(chunk);
        nlIdx = buffer.indexOf("\n");
      }
    }

    const tail = decoder.decode();
    if (tail) {
      buffer += tail;
    }
    if (buffer.trim()) {
      consumeLine(buffer.trim());
    }

    if (!resultData) {
      throw new Error("Stream encerrado sem payload final de resposta.");
    }
    return resultData;
  } catch (err) {
    const aborted = err?.name === "AbortError" || controller?.signal?.aborted;
    if (aborted && timeoutMs > 0 && timeoutTriggered) {
      const timeoutErr = new Error(
        `${timeoutLabel} demorou mais de ${Math.round(timeoutMs / 1000)}s e foi interrompida.`
      );
      timeoutErr.code = "request_timeout";
      throw timeoutErr;
    }
    throw err;
  } finally {
    if (timeoutId !== null) clearTimeout(timeoutId);
  }
}

async function postNdjsonStream(path, payload, options = {}) {
  const timeoutMs = Number(options?.timeoutMs || 0);
  const timeoutLabel = String(options?.timeoutLabel || "A requisicao");
  const onEvent = options?.onEvent;
  const externalController = options?.controller || null;
  const localController = !externalController && typeof AbortController === "function"
    ? new AbortController()
    : null;
  const controller = externalController || localController;
  const signal = controller?.signal;
  let timeoutId = null;
  let timeoutTriggered = false;

  if (controller && timeoutMs > 0) {
    timeoutId = setTimeout(() => {
      timeoutTriggered = true;
      controller.abort();
    }, timeoutMs);
  }

  try {
    const base = state.apiBase.replace(/\/$/, "");
    const response = await fetch(`${base}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/x-ndjson"
      },
      body: JSON.stringify(payload),
      signal
    });

    if (!response.ok) {
      const json = await response.json().catch(() => ({}));
      throw apiErrorFromDetail(response.status, response.statusText, json?.detail);
    }
    if (!response.body || typeof response.body.getReader !== "function") {
      const err = new Error("Streaming nao disponivel neste navegador/ambiente.");
      err.streamUnavailable = true;
      throw err;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let nlIdx = buffer.indexOf("\n");
      while (nlIdx >= 0) {
        const chunk = buffer.slice(0, nlIdx);
        buffer = buffer.slice(nlIdx + 1);
        const line = String(chunk || "").trim();
        if (!line) {
          nlIdx = buffer.indexOf("\n");
          continue;
        }
        let packet = null;
        try {
          packet = JSON.parse(line);
        } catch (_) {
          nlIdx = buffer.indexOf("\n");
          continue;
        }
        const event = String(packet?.event || "");
        if (event === "error") {
          throw apiErrorFromDetail(
            Number(packet?.status_code || 500),
            "StreamError",
            packet?.detail || { message: "Falha no stream NDJSON." }
          );
        }
        if (typeof onEvent === "function") {
          await onEvent(packet);
        }
        nlIdx = buffer.indexOf("\n");
      }
    }

    const tail = decoder.decode();
    if (tail) buffer += tail;
    const line = buffer.trim();
    if (line) {
      try {
        const packet = JSON.parse(line);
        if (packet?.event === "error") {
          throw apiErrorFromDetail(
            Number(packet?.status_code || 500),
            "StreamError",
            packet?.detail || { message: "Falha no stream NDJSON." }
          );
        }
        if (typeof onEvent === "function") {
          await onEvent(packet);
        }
      } catch (err) {
        if (err instanceof Error) throw err;
      }
    }
  } catch (err) {
    const aborted = err?.name === "AbortError" || signal?.aborted;
    if (aborted && timeoutMs > 0 && timeoutTriggered) {
      const timeoutErr = new Error(
        `${timeoutLabel} demorou mais de ${Math.round(timeoutMs / 1000)}s e foi interrompida.`
      );
      timeoutErr.code = "request_timeout";
      throw timeoutErr;
    }
    throw err;
  } finally {
    if (timeoutId !== null) clearTimeout(timeoutId);
  }
}

async function fetchGeminiStatus() {
  const base = state.apiBase.replace(/\/$/, "");
  try {
    const response = await fetch(`${base}/api/gemini/status`);
    if (!response.ok) throw new Error(String(response.status));
    const payload = await response.json();
    refreshGeminiModelOptions(payload?.supported_models);
    if (payload?.has_api_key) {
      setOnboardingKeyStatus("Chave Gemini ativa. Plataforma pronta para consulta.", "success");
      return true;
    }
    setOnboardingKeyStatus("Chave Gemini ausente. Informe e valide para liberar consultas.", "error");
    return false;
  } catch (_) {
    setOnboardingKeyStatus(
      "Nao foi possivel validar a chave agora. Verifique o Guia de API key: https://ai.google.dev/gemini-api/docs/api-key",
      "error"
    );
    return false;
  }
}

async function saveGeminiKeyFromOnboarding() {
  const key = String(onboardingApiKeyInput?.value || "").trim();
  if (!key) {
    setOnboardingKeyStatus("Cole uma chave Gemini valida para continuar.", "error");
    return;
  }

  const defaultGenerationModel = String(
    state.ragConfigDefaults?.generation_model || "gemini-3-flash-preview"
  ).trim();
  const testModel = String(
    state.ragConfigValues?.generation_model
    || generationModelInput?.value
    || defaultGenerationModel
  ).trim();

  onboardingSaveKeyBtn.disabled = true;
  let stopFeedback = startOnboardingKeyValidationFeedback();
  try {
    const result = await postJson("/api/gemini/config", {
      api_key: key,
      persist_env: onboardingPersistEnv?.checked !== false,
      validate: true,
      test_model: testModel || defaultGenerationModel,
      validation_timeout_ms: ONBOARDING_KEY_VALIDATE_TIMEOUT_MS
    }, {
      timeoutMs: ONBOARDING_KEY_VALIDATE_TIMEOUT_MS,
      timeoutLabel: "A validacao da chave"
    });
    stopFeedback?.();
    stopFeedback = null;
    if (onboardingApiKeyInput) onboardingApiKeyInput.value = "";
    state.onboardingSeen = true;
    localStorage.setItem(ONBOARDING_STORAGE_KEY, "1");
    const persisted = result?.persisted_env ? " e salva em .env" : "";
    const validated = result?.validated !== false;
    const validationWarning = String(result?.validation_warning || "").trim();
    if (validated) {
      setOnboardingKeyStatus(`Chave validada${persisted}.`, "success");
      setRequestState("Chave Gemini validada. Sistema pronto para consultar.");
    } else {
      const warningSuffix = validationWarning
        ? ` Validacao pendente: ${validationWarning}`
        : " Validacao pendente: sem resposta no tempo esperado.";
      setOnboardingKeyStatus(`Chave salva${persisted}.${warningSuffix}`, "success");
      setRequestState("Chave Gemini salva. Se necessario, repita a validacao depois.", false);
    }
    await checkHealth();
    setOnboardingOpen(false, { markSeen: true });
  } catch (err) {
    stopFeedback?.();
    stopFeedback = null;
    const isTimeout = String(err?.code || "").trim() === "request_timeout";
    if (isTimeout) {
      setOnboardingKeyStatus(
        "Tempo excedido na validacao online. Tentando salvar a chave sem validar...",
        "info"
      );
      let fallbackSaveResult = null;
      try {
        fallbackSaveResult = await postJson("/api/gemini/config", {
          api_key: key,
          persist_env: onboardingPersistEnv?.checked !== false,
          validate: false,
          test_model: testModel || defaultGenerationModel,
          validation_timeout_ms: ONBOARDING_KEY_VALIDATE_TIMEOUT_MS
        }, {
          timeoutMs: Math.min(10000, ONBOARDING_KEY_VALIDATE_TIMEOUT_MS),
          timeoutLabel: "O salvamento da chave"
        });
      } catch (fallbackErr) {
        const fallbackDetail = String(fallbackErr?.message || "Falha desconhecida.");
        setOnboardingKeyStatus(
          `Falha ao salvar chave apos timeout de validacao: ${fallbackDetail}`,
          "error"
        );
        setRequestState(`Falha ao salvar chave Gemini apos timeout: ${fallbackDetail}`, true);
        return;
      }

      if (onboardingApiKeyInput) onboardingApiKeyInput.value = "";
      state.onboardingSeen = true;
      localStorage.setItem(ONBOARDING_STORAGE_KEY, "1");
      const persisted = fallbackSaveResult?.persisted_env ? " e salva em .env" : "";
      setOnboardingKeyStatus(
        `Chave salva sem validacao online${persisted}. Voce ja pode consultar; valide novamente depois.`,
        "success"
      );
      setRequestState("Chave Gemini salva sem validacao online. Sistema liberado para consulta.", false);
      await checkHealth();
      setOnboardingOpen(false, { markSeen: true });
      return;
    }

    const detail = String(err?.message || "Falha desconhecida.");
    setOnboardingKeyStatus(`Falha ao validar chave: ${detail}`, "error");
    setRequestState(`Falha ao validar chave Gemini: ${detail}`, true);
  } finally {
    stopFeedback?.();
    onboardingSaveKeyBtn.disabled = false;
  }
}

function saveRagConfigNow() {
  syncGenerationModelStateFromInputs();
  syncGeminiRerankModelStateFromInput();
  persistSession();
  setRagConfigStatus("Configuracoes salvas localmente. Aplicadas na proxima consulta.");
  setRequestState("Configuracoes do RAG salvas.");
}

async function indexUserCorpusNow() {
  resetUserCorpusStages();
  const files = Array.from(userCorpusFilesInput?.files || []);
  if (!files.length) {
    setUserCorpusStage("ready", { errored: true });
    setUserCorpusStatus("Selecione ao menos 1 PDF para indexar.", true);
    return;
  }
  const sourceName = String(userCorpusNameInput?.value || "").trim() || "Banco 1";
  const ocrMissingOnly = userCorpusOcrMissingOnly?.checked !== false;
  const confirmText = [
    `Indexar ${files.length} arquivo(s) em "${sourceName}"?`,
    "A indexacao vai consumir cota da API Gemini (OCR/limpeza/embeddings).",
    "Esta acao exige confirmacao manual."
  ].join("\n");
  if (!window.confirm(confirmText)) {
    setUserCorpusStage("ready");
    setUserCorpusStatus("Indexacao cancelada.");
    return;
  }

  const formData = new FormData();
  formData.append("confirm_index", "true");
  formData.append("source_name", sourceName);
  formData.append("ocr_missing_only", ocrMissingOnly ? "true" : "false");
  files.forEach((file) => formData.append("files", file, file.name));

  indexUserCorpusBtn.disabled = true;
  setUserCorpusStage("upload");
  setUserCorpusStatus("Enviando lote para indexacao...");
  try {
    const result = await postFormData("/api/meu-acervo/index", formData, {
      timeoutMs: Math.min(USER_CORPUS_INDEX_TIMEOUT_MS, 180000),
      timeoutLabel: "A indexacao do Meu Acervo"
    });

    const status = String(result?.status || "").trim().toLowerCase();
    if (status === "ok") {
      setUserCorpusStage("done");
      const indexedDocs = Number(result?.indexed_docs || 0);
      const duplicates = Number(result?.duplicate_files || 0);
      const skipped = Number(result?.skipped_files || 0);
      setUserCorpusStatus(
        `Indexacao concluida: ${indexedDocs} doc(s), ${duplicates} duplicado(s), ${skipped} ignorado(s).`
      );
      if (userCorpusFilesInput) userCorpusFilesInput.value = "";
      await loadUserCorpusSources();
      return;
    }

    const jobId = String(result?.job_id || "").trim();
    if (!jobId) {
      throw new Error("Backend nao retornou job_id para acompanhamento da indexacao.");
    }
    const pollEveryMs = Math.max(500, Number(result?.poll_after_ms || USER_CORPUS_JOB_POLL_DEFAULT_MS));
    const finalJob = await pollUserCorpusJobUntilDone(jobId, pollEveryMs);
    applyUserCorpusJobSnapshot(finalJob);
    if (userCorpusFilesInput) userCorpusFilesInput.value = "";
    await loadUserCorpusSources();
  } catch (err) {
    const activeNode = userCorpusStages?.querySelector("[data-index-stage].active");
    const activeStage = String(activeNode?.getAttribute("data-index-stage") || "embed");
    setUserCorpusStage(activeStage, { errored: true });
    setUserCorpusStatus(`Falha na indexacao: ${String(err?.message || err)}`, true);
  } finally {
    indexUserCorpusBtn.disabled = false;
  }
}

async function setUserSourceDeletedState(sourceId, shouldDelete) {
  const path = shouldDelete ? "/api/meu-acervo/source/delete" : "/api/meu-acervo/source/restore";
  const actionLabel = shouldDelete ? "exclusao" : "restauracao";
  try {
    await postJson(path, { source_id: sourceId });
    await loadUserCorpusSources();
    setUserCorpusStatus(`Fonte atualizada com sucesso (${actionLabel}).`);
  } catch (err) {
    setUserCorpusStatus(`Falha na ${actionLabel} da fonte: ${String(err?.message || err)}`, true);
  }
}

function docsForExplain(turn) {
  return (turn.docs || []).map((d) => ({
    tribunal: d.tribunal,
    tipo: d.tipo,
    processo: d.processo,
    data_julgamento: d.data_julgamento,
    _authority_level: d.authority_level,
    normative_statement: d.normative_statement || "",
    texto_busca: d.texto_busca || "",
    texto_integral: d.texto_integral_excerpt || ""
  }));
}

function normalizeQuoteMarkdown(text) {
  return String(text || "")
    .replace(/\r\n/g, "\n")
    .replace(/([^\n])\s>\s"/g, "$1\n> \"")
    .replace(/([^\n])\n?(>\s*"[^"\n]+")\s*(\[[^\]]+\])/g, "$1\n$2 $3");
}

function stripTechnicalTailSections(text) {
  return String(text || "")
    .replace(/\n{0,2}Documentos citados\s*\(JSON\):[\s\S]*$/i, "")
    .replace(/\n{0,2}Documentos citados:\s*[\s\S]*$/i, "")
    .trim();
}

function markdownToHtml(text) {
  const normalized = normalizeQuoteMarkdown(stripTechnicalTailSections(text));
  const html = marked.parse(normalized);
  return DOMPurify.sanitize(html);
}

function getTurn(turnId) {
  return state.turns.find((t) => t.id === turnId);
}

function normalizeAudioMode(rawMode) {
  return rawMode === "explicacao" ? "explicacao" : "resposta";
}

function getTurnAudioStore(turn) {
  if (!turn || typeof turn !== "object") return {};
  if (!turn.audioStreamByMode || typeof turn.audioStreamByMode !== "object") {
    turn.audioStreamByMode = {};
  }
  return turn.audioStreamByMode;
}

function getTurnAudioSession(turn, mode) {
  if (!turn) return null;
  const normalized = normalizeAudioMode(mode);
  const store = getTurnAudioStore(turn);
  const session = store[normalized];
  if (!session || typeof session !== "object") return null;
  if (!Array.isArray(session.chunks)) session.chunks = [];
  return session;
}

function revokeAudioChunkEntries(entries) {
  if (!Array.isArray(entries) || !entries.length) return;
  entries.forEach((entry) => {
    const url = typeof entry === "string" ? entry : String(entry?.url || "");
    if (!url) return;
    try {
      URL.revokeObjectURL(url);
    } catch (_) {
      // Ignore revocation errors.
    }
  });
}

function replaceTurnAudioSession(turn, mode) {
  if (!turn) return null;
  const normalized = normalizeAudioMode(mode);
  const store = getTurnAudioStore(turn);
  const previous = store[normalized];
  if (previous?.chunks?.length) {
    revokeAudioChunkEntries(previous.chunks);
  }
  const session = {
    mode: normalized,
    chunks: [],
    totalChunks: 0,
    complete: false,
    traceId: "",
    voice: "charon",
    mimeType: "audio/wav",
    updatedAt: Date.now()
  };
  store[normalized] = session;
  turn.lastAudioMode = normalized;
  return session;
}

function rememberStreamChunkForTurn(turn, mode, chunkEntry, options = {}) {
  if (!turn || !chunkEntry?.url) return;
  const normalized = normalizeAudioMode(mode);
  const session = getTurnAudioSession(turn, normalized) || replaceTurnAudioSession(turn, normalized);
  if (!session) return;

  const chunkIndex = Math.max(1, Number(chunkEntry.index || (session.chunks.length + 1)));
  const chunkTotal = Math.max(chunkIndex, Number(chunkEntry.total || session.totalChunks || chunkIndex));
  const existingIdx = session.chunks.findIndex((entry) => Number(entry?.index || 0) === chunkIndex);
  const normalizedEntry = {
    url: String(chunkEntry.url),
    index: chunkIndex,
    total: chunkTotal
  };
  if (existingIdx >= 0) {
    const existing = session.chunks[existingIdx];
    const oldUrl = String(existing?.url || "");
    if (oldUrl && oldUrl !== normalizedEntry.url) {
      revokeAudioChunkEntries([oldUrl]);
    }
    session.chunks[existingIdx] = normalizedEntry;
  } else {
    session.chunks.push(normalizedEntry);
  }
  session.chunks.sort((a, b) => Number(a.index || 0) - Number(b.index || 0));
  session.totalChunks = Math.max(chunkTotal, Number(session.totalChunks || 0), session.chunks.length);
  session.voice = String(options.voice || session.voice || "charon");
  session.mimeType = String(options.mimeType || session.mimeType || "audio/wav");
  session.traceId = String(options.traceId || session.traceId || "");
  session.complete = !!options.complete;
  session.updatedAt = Date.now();
  turn.lastAudioMode = normalized;
}

function getReplayQueueFromTurn(turn, mode) {
  const session = getTurnAudioSession(turn, mode);
  if (!session || !Array.isArray(session.chunks) || !session.chunks.length) return [];
  const totalChunks = Math.max(1, Number(session.totalChunks || session.chunks.length));
  return session.chunks
    .map((entry, idx) => ({
      url: String(entry?.url || ""),
      index: Math.max(1, Number(entry?.index || idx + 1)),
      total: Math.max(1, Number(entry?.total || totalChunks))
    }))
    .filter((entry) => !!entry.url)
    .sort((a, b) => a.index - b.index);
}

function hasReplayAudio(turn, mode) {
  return getReplayQueueFromTurn(turn, mode).length > 0;
}

function releaseTurnAudioCaches(turn) {
  if (!turn || typeof turn !== "object") return;
  const store = getTurnAudioStore(turn);
  Object.values(store).forEach((session) => {
    revokeAudioChunkEntries(session?.chunks || []);
  });
  turn.audioStreamByMode = {};
}

function getLatestPendingTurn() {
  for (let i = state.turns.length - 1; i >= 0; i -= 1) {
    if (state.turns[i]?.status === "pending") return state.turns[i];
  }
  return null;
}

function hasAnyTurn() {
  return state.turns.length > 0;
}

function hasPendingTurn() {
  return state.turns.some((t) => t.status === "pending");
}

function turnStatusLabel(turn) {
  if (!turn) return "Invalida";
  if (turn.status === "done") return "Concluida";
  if (turn.status === "pending") return "Em processamento";
  return "Com erro";
}

function turnsForLibrary(mode) {
  const normalized = normalizeLibraryMode(mode);
  const byDateDesc = [...state.turns].sort((a, b) => Number(b.startedAt || 0) - Number(a.startedAt || 0));
  if (normalized === "saved") return byDateDesc.filter((turn) => !!turn.saved);
  return byDateDesc;
}

function renderLibraryPanel() {
  if (!libraryList || !libraryTitle || !libraryHint || !libraryCountTag) return;
  const mode = normalizeLibraryMode(state.library.mode);
  const meta = libraryModeMeta(mode);
  const turns = turnsForLibrary(mode);

  libraryTitle.textContent = meta.title;
  libraryHint.textContent = meta.hint;
  libraryCountTag.textContent = String(turns.length);

  if (!turns.length) {
    libraryList.innerHTML = `<p class="library-empty">${escapeHtml(meta.empty)}</p>`;
    return;
  }

  libraryList.innerHTML = turns.map((turn) => {
    const isActive = turn.id === state.activeTurnId;
    const status = turnStatusLabel(turn);
    const docCount = Array.isArray(turn.docs) ? turn.docs.length : 0;
    const when = startedAtHuman(turn.startedAt);
    const sourceLine = sourceSummary(turn, 1);
    return `
      <article class="library-item ${isActive ? "active" : ""}" data-turn-id="${escapeHtml(turn.id)}">
        <p class="library-item-title">${escapeHtml(shortText(turn.query, 116))}</p>
        <div class="library-chip-row">
          <span class="library-chip">${escapeHtml(status)}</span>
          <span class="library-chip">${docCount} fonte(s)</span>
          ${turn.saved ? '<span class="library-chip">salvo</span>' : ""}
        </div>
        <p class="library-item-meta">${escapeHtml(when)}</p>
        <p class="library-item-sources">${escapeHtml(shortText(sourceLine, 84))}</p>
        <div class="library-item-actions">
          <button class="library-action" data-library-action="open-turn" data-turn="${escapeHtml(turn.id)}" type="button">Abrir</button>
          <button class="library-action ${turn.saved ? "active" : ""}" data-library-action="toggle-save" data-turn="${escapeHtml(turn.id)}" type="button">${turn.saved ? "Remover" : "Salvar"}</button>
        </div>
      </article>
    `;
  }).join("");
}

function scrollTurnIntoView(turnId) {
  if (!thread || !turnId) return;
  const escaped = window.CSS?.escape ? window.CSS.escape(turnId) : turnId.replace(/["\\]/g, "\\$&");
  const node = thread.querySelector(`[data-turn-id="${escaped}"]`);
  node?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function setActiveTurn(turnId, { scroll = false } = {}) {
  const turn = getTurn(turnId);
  if (!turn) return;
  state.activeTurnId = turn.id;
  persistSession();
  renderThread({ autoscroll: false });
  renderEvidence();
  renderLibraryPanel();
  if (scroll) {
    scrollTurnIntoView(turn.id);
  }
}

function makePipelineRuntime(mode = "simulated") {
  return {
    mode,
    activeIdx: 0,
    doneFlags: PIPELINE_STEPS.map(() => false),
    stepNotes: {},
    lastStage: "",
    updatedAt: Date.now(),
    completed: false
  };
}

function ensurePipelineRuntime(turn, modeHint = "simulated") {
  if (!turn || typeof turn !== "object") return makePipelineRuntime(modeHint);
  const runtime = turn.pipeline && typeof turn.pipeline === "object"
    ? turn.pipeline
    : makePipelineRuntime(modeHint);

  if (!Array.isArray(runtime.doneFlags) || runtime.doneFlags.length !== PIPELINE_STEPS.length) {
    runtime.doneFlags = PIPELINE_STEPS.map(() => false);
  }
  if (!runtime.stepNotes || typeof runtime.stepNotes !== "object") {
    runtime.stepNotes = {};
  }
  if (modeHint === "real") {
    runtime.mode = "real";
  } else if (!runtime.mode) {
    runtime.mode = "simulated";
  }
  if (!Number.isFinite(Number(runtime.activeIdx))) {
    runtime.activeIdx = 0;
  }
  if (typeof runtime.lastStage !== "string") {
    runtime.lastStage = "";
  }
  runtime.updatedAt = Date.now();
  turn.pipeline = runtime;
  return runtime;
}

function stageTimingFromPayload(payload, key) {
  const value = Number(payload?.timings?.[key]);
  if (!Number.isFinite(value) || value <= 0) return "";
  return `${value.toFixed(2)}s`;
}

function stageNoteForEvent(stage, payload = {}) {
  const event = String(stage || "").trim();
  if (event === "embedding_done") {
    const timing = stageTimingFromPayload(payload, "embedding");
    return timing ? `Vetorizacao concluida em ${timing}.` : "Vetorizacao concluida.";
  }
  if (event === "retrieval_done") {
    const candidates = Number(payload?.candidates);
    if (Number.isFinite(candidates) && candidates >= 0) {
      return `${candidates} candidatos recuperados.`;
    }
    return "Busca de candidatos concluida.";
  }
  if (event === "rerank_done") {
    const returned = Number(payload?.returned_docs);
    if (Number.isFinite(returned) && returned >= 0) {
      return `${returned} documentos apos rerank.`;
    }
    return "Rerank concluido.";
  }
  if (event === "generation_done") {
    const timing = stageTimingFromPayload(payload, "generation");
    return timing ? `Geracao concluida em ${timing}.` : "Geracao concluida.";
  }
  if (event === "done") {
    const timing = stageTimingFromPayload(payload, "total");
    return timing ? `Pipeline concluido em ${timing}.` : "Pipeline concluido.";
  }
  return "";
}

function applyPipelineStageEvent(turn, stage, payload = {}) {
  if (!turn || turn.status !== "pending") return;
  const event = String(stage || "").trim();
  if (!event) return;

  const runtime = ensurePipelineRuntime(turn, "real");
  runtime.lastStage = event;
  runtime.updatedAt = Date.now();

  if (event === "done") {
    runtime.doneFlags = PIPELINE_STEPS.map(() => true);
    runtime.activeIdx = PIPELINE_STEPS.length - 1;
    runtime.completed = true;
    const finalNote = stageNoteForEvent(event, payload);
    if (finalNote) runtime.stepNotes[String(PIPELINE_STEPS.length - 1)] = finalNote;
    return;
  }

  const stepIdx = PIPELINE_STAGE_TO_STEP[event];
  if (!Number.isFinite(stepIdx) || stepIdx < 0 || stepIdx >= PIPELINE_STEPS.length) return;
  const isDoneEvent = event.endsWith("_done");
  runtime.activeIdx = stepIdx;
  runtime.doneFlags[stepIdx] = isDoneEvent;

  const note = stageNoteForEvent(event, payload);
  if (note) {
    runtime.stepNotes[String(stepIdx)] = note;
  }
}

function pipelineSnapshot(turn, nowMs = Date.now()) {
  const startedAt = Number(turn?.startedAt || nowMs);
  const elapsedMs = Math.max(0, nowMs - startedAt);
  const elapsedSec = elapsedMs / 1000;
  const runtime = turn?.pipeline;

  if (runtime?.mode === "real") {
    const doneFlags = PIPELINE_STEPS.map((_, idx) => !!runtime.doneFlags?.[idx]);
    let activeIdx = Number.isFinite(Number(runtime.activeIdx)) ? Number(runtime.activeIdx) : 0;
    activeIdx = Math.max(0, Math.min(activeIdx, PIPELINE_STEPS.length - 1));

    const completed = !!runtime.completed || doneFlags.every(Boolean) || turn?.status === "done";
    if (completed) {
      for (let i = 0; i < doneFlags.length; i += 1) doneFlags[i] = true;
      activeIdx = PIPELINE_STEPS.length - 1;
    } else if (doneFlags[activeIdx]) {
      const nextIdx = doneFlags.findIndex((flag) => !flag);
      if (nextIdx >= 0) activeIdx = nextIdx;
    }

    const doneCount = doneFlags.filter(Boolean).length;
    const basePct = (doneCount / Math.max(PIPELINE_STEPS.length, 1)) * 100;
    const inFlightBoost = runtime.lastStage && !completed
      ? (100 / Math.max(PIPELINE_STEPS.length, 1)) * 0.45
      : 0;
    const progressPct = completed ? 100 : Math.min(98.5, Math.max(basePct, basePct + inFlightBoost));
    const activeStep = PIPELINE_STEPS[activeIdx] || { name: "-", badge: "PROCESSANDO" };

    return {
      elapsedSec,
      elapsedMs,
      activeIdx,
      currentStepName: String(activeStep.name || "-"),
      badge: completed ? "CONCLUIDO" : String(activeStep.badge || "PROCESSANDO"),
      activePct: 0,
      cyclePct: progressPct,
      cycleMs: 0,
      progressPct,
      stepNotes: runtime.stepNotes || {},
      doneFlags,
      useReal: true
    };
  }

  const safeLoopMs = Math.max(PIPELINE_LOOP_MS, 1);
  const cycleMs = ((elapsedMs % safeLoopMs) + safeLoopMs) % safeLoopMs;

  let activeIdx = 0;
  let consumedMs = 0;
  for (let i = 0; i < PIPELINE_STEPS.length; i += 1) {
    const durationMs = Math.max(1, Number(PIPELINE_STEPS[i]?.durationMs || 1));
    if (i === PIPELINE_STEPS.length - 1 || cycleMs < consumedMs + durationMs) {
      activeIdx = i;
      break;
    }
    consumedMs += durationMs;
  }

  const activeStep = PIPELINE_STEPS[activeIdx] || { name: "-", badge: "PROCESSANDO", durationMs: 1 };
  const activeDurationMs = Math.max(1, Number(activeStep.durationMs || 1));
  const activeElapsedMs = Math.max(0, cycleMs - consumedMs);
  const activePct = Math.max(0, Math.min(100, (activeElapsedMs / activeDurationMs) * 100));
  const cyclePct = Math.max(0, Math.min(100, (cycleMs / safeLoopMs) * 100));

  return {
    elapsedSec,
    elapsedMs,
    activeIdx,
    currentStepName: String(activeStep.name || "-"),
    badge: String(activeStep.badge || "PROCESSANDO"),
    activePct,
    cyclePct,
    cycleMs,
    progressPct: cyclePct,
    stepNotes: {},
    doneFlags: PIPELINE_STEPS.map((_, idx) => idx < activeIdx),
    useReal: false
  };
}

function pipelineStepState(stepIdx, snap) {
  if (snap?.doneFlags?.[stepIdx]) return "done";
  if (stepIdx === snap?.activeIdx) return "active";
  return "";
}

function typingDotsMarkup() {
  return '<span class="typing-dots" aria-hidden="true"><span></span><span></span><span></span></span>';
}

function pipelineStepDoneText(stepIdx, snap) {
  const note = String(snap?.stepNotes?.[String(stepIdx)] || snap?.stepNotes?.[stepIdx] || "").trim();
  if (note) return note;
  return String(PIPELINE_STEPS[stepIdx]?.desc || "");
}

function pipelineStepDesc(stepIdx, snap) {
  if (snap?.doneFlags?.[stepIdx]) {
    return escapeHtml(pipelineStepDoneText(stepIdx, snap));
  }
  if (stepIdx === snap?.activeIdx) {
    return typingDotsMarkup();
  }
  return "-";
}

function renderPendingPipeline(turn) {
  const snap = pipelineSnapshot(turn);
  const stepsHtml = PIPELINE_STEPS.map((step, idx) => {
    const state = pipelineStepState(idx, snap);
    return `
      <div class="pipeline-step ${state}" data-pipeline-step="${idx}">
        <div class="pipeline-step-left">
          <span class="pipeline-dot"></span>
          <span class="pipeline-step-name">${escapeHtml(String(step.name || "-"))}</span>
        </div>
        <span class="pipeline-step-desc" data-pipeline-desc="${idx}">${pipelineStepDesc(idx, snap)}</span>
      </div>
    `;
  }).join("");

  return `
    <div class="pipeline-card pipeline-steps-card" data-pipeline-turn="${turn.id}">
      <div class="pipeline-title">Pipeline em execucao</div>
      <div class="pipeline-progress-track" aria-hidden="true">
        <div class="pipeline-progress-fill" data-pipeline-progress style="width:${Number(snap.progressPct || 0).toFixed(1)}%;"></div>
      </div>
      <div class="pipeline-steps">
        ${stepsHtml}
      </div>
      <div class="pipeline-elapsed">
        <span>Etapa atual: <strong data-pipeline-current>${escapeHtml(snap.currentStepName)}</strong></span>
        <span><span data-pipeline-time>${snap.elapsedSec.toFixed(1)}s</span></span>
        <span class="pipeline-status-badge" data-pipeline-badge>${escapeHtml(snap.badge)}</span>
      </div>
    </div>
  `;
}

function updatePendingPipelineUI(turn) {
  if (!thread || !turn) return false;
  const escaped = window.CSS?.escape ? window.CSS.escape(turn.id) : turn.id.replace(/["\\]/g, "\\$&");
  const root = thread.querySelector(`[data-pipeline-turn="${escaped}"]`);
  if (!root) return false;

  const snap = pipelineSnapshot(turn);
  root.querySelectorAll("[data-pipeline-progress]").forEach((progress) => {
    progress.style.width = `${Number(snap.progressPct || 0).toFixed(1)}%`;
  });

  const timer = root.querySelector("[data-pipeline-time]");
  if (timer) {
    timer.textContent = `${snap.elapsedSec.toFixed(1)}s`;
  }

  const current = root.querySelector("[data-pipeline-current]");
  if (current) {
    current.textContent = snap.currentStepName;
  }

  const badge = root.querySelector("[data-pipeline-badge]");
  if (badge) {
    badge.textContent = snap.badge;
  }

  root.querySelectorAll("[data-pipeline-step]").forEach((stepNode) => {
    const idx = Number(stepNode.getAttribute("data-pipeline-step"));
    if (!Number.isFinite(idx) || idx < 0 || idx >= PIPELINE_STEPS.length) return;

    const stateClass = pipelineStepState(idx, snap);
    stepNode.classList.remove("active", "done");
    if (stateClass) stepNode.classList.add(stateClass);

    const desc = stepNode.querySelector(`[data-pipeline-desc="${idx}"]`);
    if (!desc) return;
    if (snap.doneFlags?.[idx]) {
      desc.textContent = pipelineStepDoneText(idx, snap);
    } else if (idx === snap.activeIdx) {
      desc.innerHTML = typingDotsMarkup();
    } else {
      desc.textContent = "-";
    }
  });
  return true;
}

function renderEmptyThread() {
  thread.innerHTML = `
    <section class="empty-state">
      <p>Formule sua consulta juridica para iniciar a sintese.</p>
    </section>
  `;
}

function renderTurn(turn) {
  const activeTurn = turn.id === state.activeTurnId;
  const userHtml = `
    <article class="msg msg-user">
      <div class="msg-head">
        <span class="msg-label">Consulta inicial</span>
      </div>
      <div class="answer-body">${escapeHtml(turn.query)}</div>
    </article>
  `;

  let assistantHtml = "";
  if (turn.status === "pending") {
    assistantHtml = `
      <article class="msg msg-assistant">
        <div class="msg-head">
          <span class="msg-label">Resposta em processamento</span>
        </div>
        ${renderPendingPipeline(turn)}
      </article>
    `;
  } else if (turn.status === "error") {
    assistantHtml = `
      <article class="msg msg-assistant">
        <div class="msg-head">
          <span class="msg-label">Resposta</span>
        </div>
        <p class="error-note">${escapeHtml(turn.error || "Falha ao consultar.")}</p>
      </article>
    `;
  } else {
    const sameSpeechTurn = state.speech.activeTurnId === turn.id;
    const loading = state.speech.isLoading && sameSpeechTurn;
    const buffering = state.speech.isBuffering && sameSpeechTurn;
    const paused = sameSpeechTurn && !loading && state.speech.isPaused;
    const speaking = sameSpeechTurn && !loading && !state.speech.isPaused;
    const audioActive = sameSpeechTurn || loading;
    const totalChunks = sameSpeechTurn ? Math.max(0, Number(state.speech.totalChunks || 0)) : 0;
    const bufferedChunks = sameSpeechTurn ? Math.max(0, Number(state.speech.bufferedChunks || 0)) : 0;
    const replayMode = normalizeAudioMode(
      sameSpeechTurn ? state.speech.mode : (turn.lastAudioMode || "resposta")
    );
    const canReplayAudio = hasReplayAudio(turn, replayMode);
    const mode = loading
      ? (
        buffering
          ? `Buffering de audio... ${bufferedChunks}/${Math.max(totalChunks, bufferedChunks || 1)} bloco(s)`
          : (state.speech.mode === "explicacao" ? "Preparando explicacao em audio..." : "Preparando leitura em audio...")
      )
      : speaking
        ? (state.speech.mode === "explicacao" ? "Explicacao em reproducao" : "Leitura em reproducao")
        : paused
          ? "Audio pausado"
          : "Audio: leitura e explicacao disponiveis";
    const progress = sameSpeechTurn ? state.speech.progressPct : 0;
    const bufferedPct = sameSpeechTurn
      ? Math.max(
        progress,
        totalChunks > 0 ? Math.min(100, (bufferedChunks / Math.max(totalChunks, 1)) * 100) : 0
      )
      : 0;
    const canTogglePlayback = sameSpeechTurn && !loading;
    const canShrinkFont = state.answerFontScale > ANSWER_FONT_SCALE_MIN;
    const canGrowFont = state.answerFontScale < ANSWER_FONT_SCALE_MAX;
    const answerHtml = markdownToHtml(turn.answer || "");

    assistantHtml = `
      <article class="msg msg-assistant">
        <div class="msg-head">
          <span class="msg-label">Sintese jurisprudencial</span>
          <div class="assistant-tools" role="toolbar" aria-label="Acoes de audio e organizacao">
            <button
              class="tool-btn ${speaking && state.speech.mode === "resposta" ? "active" : ""}"
              data-action="listen"
              data-turn="${turn.id}"
              type="button"
              title="O audio usa Google Cloud Text-to-Speech e requer ativacao da API no Google Cloud Console."
              ${loading ? "disabled" : ""}
            >
              <i data-lucide="volume-2"></i>
              <span>Ler em voz alta</span>
              <span class="tool-hint" aria-hidden="true">i</span>
            </button>
            <button class="tool-btn ${speaking && state.speech.mode === "explicacao" ? "active" : ""}" data-action="explain" data-turn="${turn.id}" type="button" ${loading ? "disabled" : ""}>
              <i data-lucide="sparkles"></i>
              <span>Explicar</span>
            </button>
            <button class="tool-btn replay-btn" data-action="replay-audio" data-turn="${turn.id}" data-mode="${replayMode}" type="button" ${canReplayAudio && !loading ? "" : "disabled"}>
              <i data-lucide="rotate-ccw"></i>
              <span>Reiniciar audio</span>
            </button>
            <button class="tool-btn playback-btn ${paused ? "active" : ""}" data-action="toggle-playback" data-turn="${turn.id}" type="button" ${canTogglePlayback ? "" : "disabled"}>
              <i data-lucide="${paused ? "play" : "pause"}"></i>
              <span>${paused ? "Continuar" : "Pausar"}</span>
            </button>
            <button class="tool-btn font-btn" data-action="font-down" data-turn="${turn.id}" type="button" title="Diminuir fonte da resposta" ${canShrinkFont ? "" : "disabled"}>
              <i data-lucide="minus"></i>
            </button>
            <button class="tool-btn font-btn" data-action="font-up" data-turn="${turn.id}" type="button" title="Aumentar fonte da resposta" ${canGrowFont ? "" : "disabled"}>
              <i data-lucide="plus"></i>
            </button>
            <button class="tool-btn turn-flag-btn ${turn.saved ? "active" : ""}" data-action="save-turn" data-turn="${turn.id}" type="button">
              <i data-lucide="bookmark"></i>
              <span>${turn.saved ? "Salvo" : "Salvar"}</span>
            </button>
          </div>
        </div>
        <div class="audio-mode ${buffering ? "buffering" : ""}">${escapeHtml(mode)}</div>
        <div class="audio-track ${audioActive ? "active" : ""} ${loading ? "loading" : ""} ${buffering ? "buffering" : ""}">
          <div class="audio-buffer" data-audio-buffer-turn="${turn.id}" style="width:${bufferedPct}%;"></div>
          <div class="audio-progress" data-audio-play-turn="${turn.id}" style="width:${progress}%;"></div>
        </div>
        <div class="answer-body" data-answer-turn="${turn.id}">${answerHtml}</div>
      </article>
    `;
  }

  return `
    <section class="turn-block ${activeTurn ? "active" : ""}" data-turn-id="${escapeHtml(turn.id)}">
      ${userHtml}
      ${assistantHtml}
    </section>
  `;
}

function createDocRefLink(turnId, docNum) {
  const link = document.createElement("a");
  link.href = "#";
  link.className = "doc-ref-link";
  link.dataset.turn = turnId;
  link.dataset.docIndex = docNum;
  link.setAttribute("aria-label", `Abrir DOC. ${docNum} nos anexos`);
  link.textContent = `[DOC. ${docNum}]`;
  return link;
}

function appendDocRefsFromText(text, turnId) {
  const fragment = document.createDocumentFragment();
  let cursor = 0;

  DOC_REF_GROUP_RE.lastIndex = 0;
  let groupMatch = DOC_REF_GROUP_RE.exec(text);
  while (groupMatch) {
    if (groupMatch.index > cursor) {
      fragment.appendChild(document.createTextNode(text.slice(cursor, groupMatch.index)));
    }

    const groupRaw = String(groupMatch[1] || "");
    DOC_REF_NUMBER_RE.lastIndex = 0;
    const groupNums = [];
    let innerMatch = DOC_REF_NUMBER_RE.exec(groupRaw);
    while (innerMatch) {
      groupNums.push(String(innerMatch[1] || "").trim());
      innerMatch = DOC_REF_NUMBER_RE.exec(groupRaw);
    }

    if (groupNums.length < 2) {
      const shorthandNums = Array.from(groupRaw.matchAll(/(?:[,;]|\be\b)\s*(\d+)/gi), (m) => String(m[1] || "").trim());
      groupNums.push(...shorthandNums);
    }

    const normalizedNums = [];
    const seenNums = new Set();
    for (const rawNum of groupNums) {
      const cleanNum = String(rawNum || "").trim();
      if (!cleanNum || seenNums.has(cleanNum)) continue;
      seenNums.add(cleanNum);
      normalizedNums.push(cleanNum);
    }

    if (normalizedNums.length) {
      normalizedNums.forEach((num, idx) => {
        if (idx > 0) {
          fragment.appendChild(document.createTextNode(", "));
        }
        fragment.appendChild(createDocRefLink(turnId, num));
      });
    } else {
      fragment.appendChild(document.createTextNode(groupMatch[0]));
    }

    cursor = DOC_REF_GROUP_RE.lastIndex;
    groupMatch = DOC_REF_GROUP_RE.exec(text);
  }

  const tail = text.slice(cursor);
  if (!tail) return fragment;

  DOC_REF_NUMBER_RE.lastIndex = 0;
  let plainCursor = 0;
  let plainMatch = DOC_REF_NUMBER_RE.exec(tail);
  while (plainMatch) {
    if (plainMatch.index > plainCursor) {
      fragment.appendChild(document.createTextNode(tail.slice(plainCursor, plainMatch.index)));
    }
    const docNum = String(plainMatch[1] || "").trim();
    fragment.appendChild(createDocRefLink(turnId, docNum));
    plainCursor = DOC_REF_NUMBER_RE.lastIndex;
    plainMatch = DOC_REF_NUMBER_RE.exec(tail);
  }
  if (plainCursor < tail.length) {
    fragment.appendChild(document.createTextNode(tail.slice(plainCursor)));
  }

  return fragment;
}

function enhanceAnswerDocRefs() {
  if (!thread) return;
  const answers = thread.querySelectorAll(".msg-assistant .answer-body[data-answer-turn]");
  answers.forEach((answerEl) => {
    const turnId = answerEl.getAttribute("data-answer-turn") || "";
    const walker = document.createTreeWalker(answerEl, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const parent = node.parentElement;
      if (!parent) continue;
      if (parent.closest("a, button, code, pre")) continue;
      const text = node.nodeValue || "";
      DOC_REF_GROUP_RE.lastIndex = 0;
      DOC_REF_NUMBER_RE.lastIndex = 0;
      if (DOC_REF_GROUP_RE.test(text) || DOC_REF_NUMBER_RE.test(text)) {
        textNodes.push(node);
      }
    }

    for (const node of textNodes) {
      const text = node.nodeValue || "";
      const frag = appendDocRefsFromText(text, turnId);
      node.parentNode?.replaceChild(frag, node);
    }
  });
}

function flashSourceDocCard(docIndex) {
  const raw = String(docIndex || "").trim();
  if (!raw || raw === "-") return;
  const escaped = window.CSS?.escape ? window.CSS.escape(raw) : raw.replace(/["\\]/g, "\\$&");
  const card = sourcesBox?.querySelector(`[data-doc-index="${escaped}"]`);
  if (!card) {
    setRequestState(`DOC. ${raw} nao encontrado no dossie desta resposta.`, true);
    return;
  }
  card.classList.remove("source-card-flash");
  void card.offsetWidth;
  card.classList.add("source-card-flash");
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.addEventListener("animationend", () => card.classList.remove("source-card-flash"), { once: true });
}

function focusDocReference(turnId, docIndex) {
  if (!docIndex) return;
  if (turnId && state.activeTurnId !== turnId) {
    setActiveTurn(turnId);
  }
  setEvidenceOpen(true);
  renderEvidence();
  window.setTimeout(() => flashSourceDocCard(docIndex), 120);
}

function renderThread({ autoscroll = true } = {}) {
  if (!hasAnyTurn()) {
    renderEmptyThread();
    renderLibraryPanel();
    refreshRailButtons();
    return;
  }
  thread.innerHTML = state.turns.map(renderTurn).join("");
  enhanceAnswerDocRefs();
  renderLibraryPanel();
  refreshRailButtons();
  refreshIcons();
  if (autoscroll) {
    thread.scrollTo({ top: thread.scrollHeight, behavior: "smooth" });
  }
}

function motionReduced() {
  return typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function microTypeAnswer(turnId) {
  if (!thread || motionReduced()) return;
  const turn = getTurn(turnId);
  if (!turn || turn.status !== "done") return;
  const escaped = window.CSS?.escape ? window.CSS.escape(turnId) : turnId.replace(/["\\]/g, "\\$&");
  const answerEl = thread.querySelector(`.answer-body[data-answer-turn="${escaped}"]`);
  if (!answerEl || answerEl.dataset.microtypeDone === "1" || answerEl.dataset.microtypeRunning === "1") return;

  const fullHtml = answerEl.innerHTML;
  const plain = (answerEl.textContent || "").replace(/\s+/g, " ").trim();
  if (plain.length < 72) {
    answerEl.dataset.microtypeDone = "1";
    return;
  }

  const previewLen = Math.min(220, plain.length);
  const previewText = plain.slice(0, previewLen);
  const revealMs = Math.max(520, Math.min(1100, previewLen * 7));
  const stepMs = Math.max(7, Math.round(revealMs / Math.max(1, previewText.length)));
  let idx = 0;

  answerEl.dataset.microtypeRunning = "1";
  answerEl.classList.add("microtype-running");
  answerEl.textContent = "";

  const run = () => {
    const liveNode = thread.querySelector(`.answer-body[data-answer-turn="${escaped}"]`);
    if (!liveNode) return;
    if (idx < previewText.length) {
      liveNode.textContent += previewText[idx];
      idx += 1;
      window.setTimeout(run, stepMs);
      return;
    }
    liveNode.innerHTML = fullHtml;
    liveNode.dataset.microtypeRunning = "0";
    liveNode.dataset.microtypeDone = "1";
    liveNode.classList.remove("microtype-running");
    enhanceAnswerDocRefs();
  };
  run();
}

function renderMetrics(turn) {
  if (!turn || turn.status !== "done") {
    metricsBox.innerHTML = `
      <li>Tempo de busca: <strong>-</strong></li>
      <li>Candidatos hibridos: <strong>-</strong></li>
      <li>Selecao final: <strong>-</strong></li>
    `;
    return;
  }
  const meta = turn.meta || {};
  const total = typeof meta.total_seconds === "number" ? `${meta.total_seconds.toFixed(2)}s` : "-";

  metricsBox.innerHTML = `
    <li>Tempo de busca: <strong>${escapeHtml(total)}</strong></li>
    <li>Candidatos hibridos: <strong>${escapeHtml(String(meta.candidates ?? "-"))}</strong></li>
    <li>Selecao final: <strong>${escapeHtml(String(meta.returned_docs ?? "-"))} docs</strong></li>
  `;
}

function renderSources(turn) {
  if (!turn || turn.status !== "done") {
    docCountTag.textContent = "0";
    sourcesBox.innerHTML = `<p class="sources-empty">Nenhum anexo no momento.</p>`;
    refreshHeaderBadges();
    return;
  }
  const docs = turn.docs || [];
  docCountTag.textContent = String(docs.length);
  refreshHeaderBadges();
  if (!docs.length) {
    sourcesBox.innerHTML = `<p class="sources-empty">Nenhum anexo retornado.</p>`;
    return;
  }
  sourcesBox.innerHTML = docs.map((d) => {
    const docIndex = safeText(d.index, "-");
    const title = `${safeText(d.tipo_label)}: ${safeText(d.processo)}`;
    const relatoria = `Rel: ${safeText(d.relator)}`;
    const authority = `Nivel ${safeText(d.authority_level)} (${safeText(d.authority_label)})`;
    const orgao = safeText(d.orgao_julgador || d.turma || "-", "-");
    const source = `Origem: ${safeText(d.source_label || d.source_id || "Base Ratio")}`;
    const date = dateHuman(d.data_julgamento);
    const normativeStatement = safeText(d.normative_statement, "");
    const thesisBlock = normativeStatement
      ? `
        <details class="source-thesis">
          <summary>Ver enunciado/tese</summary>
          <p>${escapeHtml(normativeStatement)}</p>
        </details>
      `
      : "";
    const link = d.inteiro_teor_url
      ? `<a class="source-link" href="${escapeHtml(d.inteiro_teor_url)}" target="_blank" rel="noopener noreferrer">Ler inteiro teor</a>`
      : "";
    return `
      <article class="source-card" data-doc-index="${escapeHtml(docIndex)}">
        <div class="source-top">
          <span class="source-doc-tag">DOC ${escapeHtml(docIndex)}</span>
          <span class="source-date">${escapeHtml(date)}</span>
        </div>
        <p class="source-title">${escapeHtml(title)}</p>
        <p class="source-orgao">${escapeHtml(orgao)}</p>
        <p class="source-detail">${escapeHtml(source)}</p>
        <p class="source-detail">${escapeHtml(authority)}</p>
        <p class="source-detail">${escapeHtml(relatoria)}</p>
        ${thesisBlock}
        <div class="source-footer">
          ${link}
          <span class="source-score">Score: ${Number(d.final_score || 0).toFixed(3)}</span>
        </div>
      </article>
    `;
  }).join("");
}

function renderEvidence() {
  const turn = getTurn(state.activeTurnId);
  renderMetrics(turn);
  renderSources(turn);
  refreshHeaderBadges();
}

function clampPct(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return 0;
  return Math.max(0, Math.min(100, num));
}

function audioBufferedPct() {
  const total = Math.max(0, Number(state.speech.totalChunks || 0));
  const buffered = Math.max(0, Number(state.speech.bufferedChunks || 0));
  if (total <= 0) {
    if (state.speech.isLoading) return Math.max(clampPct(state.speech.progressPct), 6);
    return clampPct(state.speech.progressPct);
  }
  return clampPct((buffered / Math.max(total, 1)) * 100);
}

function refreshAudioProgressUI(turnId = state.speech.activeTurnId) {
  if (!turnId) return;
  const playBar = document.querySelector(`[data-audio-play-turn="${turnId}"]`);
  if (playBar) playBar.style.width = `${clampPct(state.speech.progressPct)}%`;
  const bufferBar = document.querySelector(`[data-audio-buffer-turn="${turnId}"]`);
  if (bufferBar) {
    const bufferPct = Math.max(clampPct(state.speech.progressPct), audioBufferedPct());
    bufferBar.style.width = `${bufferPct}%`;
  }
}

function updateAudioProgress(pct) {
  state.speech.progressPct = clampPct(pct);
  refreshAudioProgressUI();
}

function abortSpeechStream(reason = "user_abort") {
  const controller = state.speech.streamController;
  state.speech.abortReason = reason;
  if (controller && typeof controller.abort === "function" && !controller.signal?.aborted) {
    controller.abort();
  }
  state.speech.streamController = null;
  state.speech.isStreaming = false;
}

function resetAudioState(revokeUrl = false) {
  const prev = state.speech.activeTurnId;
  const previousUrl = state.speech.objectUrl;
  const previousQueue = Array.isArray(state.speech.queue) ? [...state.speech.queue] : [];
  state.speech.activeTurnId = null;
  state.speech.mode = "";
  state.speech.progressPct = 0;
  state.speech.isLoading = false;
  state.speech.isBuffering = false;
  state.speech.isPaused = false;
  state.speech.objectUrl = "";
  state.speech.queue = [];
  state.speech.isStreaming = false;
  state.speech.streamController = null;
  state.speech.abortReason = "";
  state.speech.traceId = "";
  state.speech.totalChunks = 0;
  state.speech.bufferedChunks = 0;
  state.speech.playedChunks = 0;
  state.speech.currentChunkIndex = 0;
  if (prev) {
    const playBar = document.querySelector(`[data-audio-play-turn="${prev}"]`);
    if (playBar) playBar.style.width = "0%";
    const bufferBar = document.querySelector(`[data-audio-buffer-turn="${prev}"]`);
    if (bufferBar) bufferBar.style.width = "0%";
  }
  if (revokeUrl && previousUrl) {
    URL.revokeObjectURL(previousUrl);
  }
  if (revokeUrl && previousQueue.length) {
    previousQueue.forEach((url) => {
      const queuedUrl = typeof url === "string" ? url : String(url?.url || "");
      if (queuedUrl && queuedUrl !== previousUrl) {
        URL.revokeObjectURL(queuedUrl);
      }
    });
  }
}

async function playNextQueuedChunk(turnId) {
  if (state.speech.activeTurnId !== turnId) return false;
  if (!Array.isArray(state.speech.queue) || !state.speech.queue.length) return false;
  const entry = state.speech.queue.shift();
  const nextUrl = typeof entry === "string" ? entry : String(entry?.url || "");
  if (!nextUrl) return false;
  const nextIndex = Math.max(1, Number(entry?.index || (state.speech.playedChunks + 1)));
  const totalChunks = Math.max(nextIndex, Number(entry?.total || state.speech.totalChunks || nextIndex));
  state.speech.objectUrl = nextUrl;
  state.speech.currentChunkIndex = nextIndex;
  state.speech.totalChunks = totalChunks;
  state.speech.isLoading = false;
  state.speech.isBuffering = false;
  state.speech.isPaused = false;
  audioPlayer.src = nextUrl;
  await audioPlayer.play();
  renderThread({ autoscroll: false });
  refreshAudioProgressUI();
  return true;
}

function queueAudioChunkAndMaybePlay(turnId, chunkEntry) {
  if (!chunkEntry?.url || state.speech.activeTurnId !== turnId) return;
  const chunkIndex = Math.max(1, Number(chunkEntry.index || (state.speech.bufferedChunks + 1)));
  const chunkTotal = Math.max(chunkIndex, Number(chunkEntry.total || state.speech.totalChunks || chunkIndex));
  state.speech.totalChunks = Math.max(state.speech.totalChunks || 0, chunkTotal);
  state.speech.bufferedChunks = Math.max(state.speech.bufferedChunks || 0, chunkIndex);
  state.speech.queue.push({
    url: String(chunkEntry.url),
    index: chunkIndex,
    total: chunkTotal
  });
  state.speech.queue.sort((a, b) => Number(a.index || 0) - Number(b.index || 0));
  refreshAudioProgressUI(turnId);
  const shouldKickPlayback = state.speech.isLoading || audioPlayer.paused || !audioPlayer.src;
  if (shouldKickPlayback) {
    playNextQueuedChunk(turnId).catch((err) => {
      setRequestState(`Falha ao iniciar reproducao de chunk: ${String(err?.message || err)}`, true);
    });
  }
}

function stopSpeaking() {
  abortSpeechStream("user_stop");
  audioPlayer.pause();
  audioPlayer.currentTime = 0;
  resetAudioState(false);
  renderThread({ autoscroll: false });
}

async function togglePlayback(turnId) {
  const sameSpeechTurn = state.speech.activeTurnId === turnId;
  if (!sameSpeechTurn || state.speech.isLoading) return;
  try {
    if (audioPlayer.paused) {
      await audioPlayer.play();
      state.speech.isPaused = false;
      setRequestState("Reproducao retomada.");
    } else {
      audioPlayer.pause();
      state.speech.isPaused = true;
      setRequestState("Reproducao pausada.");
    }
    renderThread({ autoscroll: false });
  } catch (err) {
    setRequestState(`Falha ao controlar audio: ${err.message}`, true);
  }
}

function base64ToBlobUrl(base64, mimeType = "audio/mpeg") {
  const binary = atob(base64 || "");
  const len = binary.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  const blob = new Blob([bytes], { type: mimeType });
  return URL.createObjectURL(blob);
}

async function ensureTurnAudio(turn, mode, text) {
  turn.audioByMode = turn.audioByMode || {};
  if (turn.audioByMode[mode]) return turn.audioByMode[mode];
  const timeoutMs = estimateTtsTimeoutMs(text);
  const data = await postJson("/api/tts", { text }, {
    timeoutMs,
    timeoutLabel: "A geracao do audio"
  });
  if (!data?.audio_base64) throw new Error("Resposta TTS sem audio_base64.");
  const url = base64ToBlobUrl(data.audio_base64, data.mime_type || "audio/mpeg");
  turn.audioByMode[mode] = {
    url,
    voice: data.voice || "charon"
  };
  return turn.audioByMode[mode];
}

async function replayCachedTurnAudio(turnId, mode, options = {}) {
  const announce = options?.announce !== false;
  const turn = getTurn(turnId);
  if (!turn) return false;
  const normalizedMode = normalizeAudioMode(mode || turn.lastAudioMode || "resposta");
  const replayQueue = getReplayQueueFromTurn(turn, normalizedMode);
  if (!replayQueue.length) return false;

  abortSpeechStream("replay_cached");
  audioPlayer.pause();
  audioPlayer.currentTime = 0;
  resetAudioState(false);
  state.speech.activeTurnId = turnId;
  state.speech.mode = normalizedMode;
  state.speech.isLoading = false;
  state.speech.isBuffering = false;
  state.speech.isPaused = false;
  state.speech.isStreaming = false;
  state.speech.queue = [...replayQueue];
  state.speech.totalChunks = Math.max(1, Number(replayQueue[replayQueue.length - 1]?.total || replayQueue.length));
  state.speech.bufferedChunks = replayQueue.length;
  state.speech.playedChunks = 0;
  state.speech.currentChunkIndex = 0;
  const session = getTurnAudioSession(turn, normalizedMode);
  state.speech.traceId = String(session?.traceId || "");
  turn.lastAudioMode = normalizedMode;
  renderThread({ autoscroll: false });
  refreshAudioProgressUI(turnId);
  await playNextQueuedChunk(turnId);
  if (announce) {
    setRequestState("Reproduzindo audio ja baixado (sem nova geracao).");
  }
  return true;
}

async function startSpeaking(turnId, mode, rawText) {
  const text = String(rawText || "").trim();
  if (!text) {
    setRequestState("Nada para ler em voz alta.", true);
    return;
  }
  const turn = getTurn(turnId);
  if (!turn) return;
  const normalizedMode = normalizeAudioMode(mode);

  const replayed = await replayCachedTurnAudio(turnId, normalizedMode, { announce: true });
  if (replayed) return;

  const timeoutMs = estimateTtsTimeoutMs(text);
  const streamController = typeof AbortController === "function" ? new AbortController() : null;

  try {
    abortSpeechStream("replace_request");
    audioPlayer.pause();
    audioPlayer.currentTime = 0;
    resetAudioState(false);
    replaceTurnAudioSession(turn, normalizedMode);
    state.speech.activeTurnId = turnId;
    state.speech.mode = normalizedMode;
    state.speech.isLoading = true;
    state.speech.isBuffering = false;
    state.speech.isPaused = false;
    state.speech.isStreaming = true;
    state.speech.queue = [];
    state.speech.traceId = "";
    state.speech.abortReason = "";
    state.speech.streamController = streamController;
    state.speech.totalChunks = 0;
    state.speech.bufferedChunks = 0;
    state.speech.playedChunks = 0;
    state.speech.currentChunkIndex = 0;
    updateAudioProgress(0);
    renderThread({ autoscroll: false });

    await postNdjsonStream("/api/tts/stream", { text }, {
      timeoutMs,
      timeoutLabel: "A geracao do audio",
      controller: streamController,
      onEvent: async (packet) => {
        const event = String(packet?.event || "").trim();
        if (!event || event === "heartbeat") return;
        if (event === "started") {
          const traceId = String(packet?.trace_id || "").trim();
          state.speech.traceId = traceId;
          const session = getTurnAudioSession(turn, normalizedMode);
          if (session) {
            session.traceId = traceId;
            session.updatedAt = Date.now();
          }
          return;
        }
        if (event === "chunk") {
          const chunkBase64 = String(packet?.audio_base64 || "");
          if (!chunkBase64) return;
          const mime = String(packet?.mime_type || "audio/wav");
          const chunkUrl = base64ToBlobUrl(chunkBase64, mime);
          const chunkIndex = Math.max(1, Number(packet?.index || (state.speech.bufferedChunks + 1)));
          const totalChunks = Math.max(chunkIndex, Number(packet?.total || state.speech.totalChunks || chunkIndex));
          const chunkEntry = { url: chunkUrl, index: chunkIndex, total: totalChunks };
          queueAudioChunkAndMaybePlay(turnId, chunkEntry);
          const voice = String(packet?.voice || "charon");
          rememberStreamChunkForTurn(turn, normalizedMode, chunkEntry, {
            voice,
            mimeType: mime,
            traceId: state.speech.traceId,
            complete: false
          });
          turn.lastAudioMode = normalizedMode;
          setRequestState(`Audio em stream com voz: ${voice}.`);
          return;
        }
        if (event === "done") {
          state.speech.isStreaming = false;
          state.speech.isBuffering = false;
          const session = getTurnAudioSession(turn, normalizedMode);
          if (session) {
            session.complete = true;
            session.updatedAt = Date.now();
          }
          if (!state.speech.queue.length && audioPlayer.paused) {
            resetAudioState();
            renderThread({ autoscroll: false });
          }
        }
      }
    });
  } catch (err) {
    const aborted = err?.name === "AbortError" || streamController?.signal?.aborted;
    const userStopped = aborted && state.speech.abortReason === "user_stop";
    if (userStopped) {
      return;
    }
    state.speech.isStreaming = false;
    state.speech.isBuffering = false;
    state.speech.streamController = null;
    const isTimeout = String(err?.code || "").trim() === "request_timeout";
    const traceId = String(err?.traceId || state.speech.traceId || "").trim();
    let detail = isTimeout
      ? `${err.message} Tente novamente ou use um texto menor.`
      : String(err?.message || "Falha desconhecida.");
    if (traceId && !detail.includes("trace_id")) {
      detail = `${detail} [trace_id=${traceId}]`;
    }
    setRequestState(`Falha no TTS: ${detail}`, true);
    if (!state.speech.queue.length && audioPlayer.paused) {
      resetAudioState();
      renderThread({ autoscroll: false });
    } else {
      renderThread({ autoscroll: false });
    }
  } finally {
    if (state.speech.streamController === streamController) {
      state.speech.streamController = null;
    }
  }
}

async function ensureExplanation(turn) {
  if (turn.explanation) return turn.explanation;
  const result = await postJson("/api/explain", {
    query: turn.query,
    answer: turn.answer,
    docs: docsForExplain(turn)
  });
  turn.explanation = String(result?.explanation || "").trim();
  persistSession();
  return turn.explanation;
}

async function handleTurnAction(action, turnId, audioMode = "") {
  const turn = getTurn(turnId);
  if (!turn || turn.status !== "done") return;

  if (action === "focus-docs") {
    setActiveTurn(turn.id, { scroll: true });
    setEvidenceOpen(true);
    renderEvidence();
    return;
  }
  if (action === "save-turn") {
    turn.saved = !turn.saved;
    persistSession();
    renderThread({ autoscroll: false });
    setRequestState(turn.saved ? "Resposta salva." : "Resposta removida dos salvos.");
    return;
  }
  if (action === "stop") {
    stopSpeaking();
    return;
  }
  if (action === "toggle-playback") {
    await togglePlayback(turn.id);
    return;
  }
  if (action === "replay-audio") {
    const replayMode = normalizeAudioMode(audioMode || state.speech.mode || turn.lastAudioMode || "resposta");
    const replayed = await replayCachedTurnAudio(turn.id, replayMode, { announce: true });
    if (!replayed) {
      setRequestState("Ainda nao ha audio salvo para reiniciar.", true);
    }
    return;
  }
  if (action === "listen") {
    await startSpeaking(turn.id, "resposta", turn.answer || "");
    return;
  }
  if (action === "font-down") {
    adjustAnswerFontScale(-1);
    return;
  }
  if (action === "font-up") {
    adjustAnswerFontScale(1);
    return;
  }
  if (action === "explain") {
    try {
      setRequestState("Gerando explicacao...");
      const explanation = await ensureExplanation(turn);
      setRequestState("Explicacao pronta.");
      await startSpeaking(turn.id, "explicacao", explanation || "Nao foi possivel gerar explicacao.");
    } catch (err) {
      setRequestState(`Erro ao explicar: ${err.message}`, true);
    }
  }
}

function handleLibraryAction(action, turnId) {
  const turn = getTurn(turnId);
  if (!turn) return;

  if (action === "open-turn") {
    setActiveTurn(turn.id, { scroll: true });
    if (window.innerWidth <= 1160) {
      setLibraryOpen(false);
    }
    return;
  }
  if (action === "toggle-save") {
    turn.saved = !turn.saved;
    persistSession();
    renderThread({ autoscroll: false });
    setRequestState(turn.saved ? "Resposta salva." : "Resposta removida dos salvos.");
  }
}

function makePendingTurn(query) {
  return {
    id: nowId(),
    query,
    status: "pending",
    answer: "",
    docs: [],
    meta: {},
    explanation: "",
    error: "",
    startedAt: Date.now(),
    saved: false,
    lastAudioMode: "resposta",
    pipeline: makePipelineRuntime("real")
  };
}

function startPendingTicker() {
  if (state.pendingTickerId !== null) return;
  state.pendingTickerId = window.setInterval(() => {
    const pending = getLatestPendingTurn();
    if (!pending) {
      stopPendingTicker();
      return;
    }
    const snap = pipelineSnapshot(pending);
    setRequestState(`Processando consulta (${snap.currentStepName})... ${snap.elapsedSec.toFixed(1)}s.`);
    if (!updatePendingPipelineUI(pending)) {
      renderThread({ autoscroll: false });
    }
  }, PENDING_REFRESH_MS);
}

function stopPendingTicker() {
  if (state.pendingTickerId === null) return;
  clearInterval(state.pendingTickerId);
  state.pendingTickerId = null;
}

async function runQueryWithRealtimeProgress(turn, payload) {
  try {
    return await postQueryStream("/api/query/stream", payload, (packet) => {
      const stage = String(packet?.stage || "").trim();
      if (!stage) return;
      applyPipelineStageEvent(turn, stage, packet?.payload || {});
      persistSession();
      const snap = pipelineSnapshot(turn);
      setRequestState(`Processando consulta (${snap.currentStepName})... ${snap.elapsedSec.toFixed(1)}s.`);
      if (!updatePendingPipelineUI(turn)) {
        renderThread({ autoscroll: false });
      }
    }, {
      timeoutMs: QUERY_STREAM_TIMEOUT_MS,
      timeoutLabel: QUERY_STREAM_TIMEOUT_LABEL
    });
  } catch (err) {
    if (err?.streamUnavailable) {
      turn.pipeline = makePipelineRuntime("real");
      return await postJson("/api/query", payload, {
        timeoutMs: QUERY_STREAM_TIMEOUT_MS,
        timeoutLabel: QUERY_STREAM_TIMEOUT_LABEL
      });
    }
    throw err;
  }
}

function clearChatHistory() {
  if (!state.turns.length) {
    setRequestState("Chat ja esta limpo.");
    return;
  }
  const confirmClear = window.confirm("Limpar todo o historico de conversa e resultados?");
  if (!confirmClear) return;

  stopPendingTicker();
  audioPlayer.pause();
  audioPlayer.currentTime = 0;
  resetAudioState(true);
  state.turns.forEach((turn) => releaseTurnAudioCaches(turn));

  state.turns = [];
  state.activeTurnId = null;
  if (queryInput) queryInput.value = "";

  persistSession();
  renderThread({ autoscroll: false });
  renderEvidence();
  refreshHeaderBadges();
  setRequestState("Chat limpo.");
  queryInput?.focus();
}

async function submitQuery() {
  const query = queryInput.value.trim();
  if (!query) {
    setRequestState("Digite uma pergunta antes de enviar.", true);
    return;
  }

  const turn = makePendingTurn(query);
  const payload = apiPayload(query);
  state.turns.push(turn);
  state.activeTurnId = turn.id;
  queryInput.value = "";
  persistSession();
  setSettingsOpen(false);
  setAcervoOpen(false);
  renderThread();
  renderEvidence();
  startPendingTicker();

  askBtn.disabled = true;
  setRequestState("Processando consulta...");

  try {
    const data = await runQueryWithRealtimeProgress(turn, payload);
    turn.status = "done";
    turn.answer = String(data?.answer || "");
    turn.docs = Array.isArray(data?.docs) ? data.docs : [];
    turn.meta = data?.meta || {};
    persistSession();
    renderThread();
    microTypeAnswer(turn.id);
    renderEvidence();
    const total = typeof turn.meta?.total_seconds === "number" ? `${turn.meta.total_seconds.toFixed(2)}s` : "ok";
    const generationWarning = String(turn.meta?.generation_warning?.message || "").trim();
    if (generationWarning) {
      setRequestState(`Consulta concluida (${total}). AVISO DE CONFIGURACAO: ${generationWarning}`);
    } else {
      setRequestState(`Consulta concluida (${total}).`);
    }
    ensureExplanation(turn).catch(() => {});
  } catch (err) {
    turn.status = "error";
    turn.error = err.message || "Falha ao consultar API.";
    persistSession();
    renderThread();
    renderEvidence();
    setRequestState(`Erro: ${turn.error}`, true);
  } finally {
    askBtn.disabled = false;
    if (!hasPendingTurn()) {
      stopPendingTicker();
    }
  }
}

async function checkHealth() {
  const base = state.apiBase.replace(/\/$/, "");
  const fallbackBase = "http://127.0.0.1:8000";
  try {
    const response = await fetch(`${base}/health`);
    if (!response.ok) throw new Error(`${response.status}`);
    const data = await response.json();
    const model = safeText(data?.defaults?.reranker_model, "-");
    const tts = safeText(data?.defaults?.tts_voice, "charon");
    const ttsRate = safeText(String(data?.defaults?.tts_rate ?? "1.2"), "1.2");
    const ttsPitch = safeText(String(data?.defaults?.tts_pitch_semitones ?? "-4.5"), "-4.5");
    const breakAlt = safeText(String(data?.defaults?.tts_break_alt_ms ?? "450"), "450");
    const breakArt = safeText(String(data?.defaults?.tts_break_art_ms ?? "900"), "900");
    const maxSsml = safeText(String(data?.defaults?.tts_max_ssml_chars ?? "5000"), "5000");
    setRequestState(
      `API online. Reranker local: ${model}. TTS: ${tts} | rate=${ttsRate}, pitch=${ttsPitch}, breakAltMs=${breakAlt}, breakArtMs=${breakArt}, maxSsmlChars=${maxSsml}.`
    );
  } catch (_) {
    if (base !== fallbackBase) {
      try {
        const fallbackResponse = await fetch(`${fallbackBase}/health`);
        if (fallbackResponse.ok) {
          const data = await fallbackResponse.json();
          state.apiBase = fallbackBase;
          localStorage.setItem("jurisai_api_base", state.apiBase);
          if (apiBaseInput) apiBaseInput.value = state.apiBase;
          loadRagConfigMetadata();

          const model = safeText(data?.defaults?.reranker_model, "-");
          const tts = safeText(data?.defaults?.tts_voice, "charon");
          setRequestState(`API online em ${fallbackBase}. URL ajustada automaticamente. Reranker local: ${model}. TTS: ${tts}.`);
          return;
        }
      } catch (_) {
        // fallback failed; show generic unavailable status below
      }
    }
    setRequestState("API indisponivel. Confirme backend em /health.", true);
  }
}

function bindEvents() {
  toggleSettingsBtn?.addEventListener("click", () => setSettingsOpen(true));
  closeSettingsBtn?.addEventListener("click", () => setSettingsOpen(false));
  closeAcervoBtn?.addEventListener("click", () => setAcervoOpen(false));
  clearChatBtn?.addEventListener("click", clearChatHistory);
  closeLibraryBtn?.addEventListener("click", () => setLibraryOpen(false));

  railModeButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const mode = normalizeLibraryMode(button.dataset.libraryMode);
      if (state.library.open && state.library.mode === mode) {
        setLibraryOpen(false);
      } else {
        setLibraryMode(mode, { open: true });
      }
    });
  });

  document.querySelectorAll("[data-open-settings]").forEach((el) => {
    el.addEventListener("click", () => setSettingsOpen(true));
  });
  for (const button of openAcervoBtns) {
    button.addEventListener("click", () => setAcervoOpen(true));
  }

  closeOnboardingBtn?.addEventListener("click", () => setOnboardingOpen(false, { markSeen: true }));
  onboardingPrimaryBtn?.addEventListener("click", () => setOnboardingOpen(false, { markSeen: true }));
  openOnboardingGuideBtn?.addEventListener("click", () => setOnboardingOpen(true));
  closeAboutBtn?.addEventListener("click", () => setAboutOpen(false));
  for (const button of openAboutBtns) {
    button.addEventListener("click", () => setAboutOpen(true));
  }

  aboutTabs?.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("[data-about-tab-target]") : null;
    if (!target) return;
    const tab = target.getAttribute("data-about-tab-target") || "acervo";
    setAboutActiveTab(tab);
  });

  copyPixKeyBtn?.addEventListener("click", async () => {
    const key = String(pixKeyText?.textContent || "").trim();
    if (!key) {
      setRequestState("Chave PIX indisponivel no momento.", true);
      return;
    }
    try {
      await navigator.clipboard.writeText(key);
      setRequestState("Chave PIX copiada.");
    } catch (_) {
      setRequestState("Nao foi possivel copiar automaticamente. Copie manualmente o texto.", true);
    }
  });

  overlay?.addEventListener("click", () => {
    if (document.body.dataset.onboardingOpen === "true") {
      setOnboardingOpen(false, { markSeen: true });
      return;
    }
    if (document.body.dataset.aboutOpen === "true") {
      setAboutOpen(false);
      return;
    }
    if (document.body.dataset.acervoOpen === "true") {
      setAcervoOpen(false);
      return;
    }
    setSettingsOpen(false);
    setLibraryOpen(false);
    if (window.innerWidth <= 1160) {
      setEvidenceOpen(false);
    }
  });

  toggleEvidenceBtn?.addEventListener("click", () => {
    const open = document.body.dataset.evidenceOpen !== "true";
    setEvidenceOpen(open);
  });

  apiBaseInput?.addEventListener("change", () => {
    state.apiBase = apiBaseInput.value.trim() || "http://127.0.0.1:8000";
    localStorage.setItem("jurisai_api_base", state.apiBase);
    checkHealth();
    loadRagConfigMetadata();
    loadUserCorpusSources();
  });

  rerankerBackend?.addEventListener("change", () => {
    refreshHeaderBadges();
    persistSession();
  });

  geminiRerankModelInput?.addEventListener("change", () => {
    syncGeminiRerankModelStateFromInput();
    setRagConfigStatus("Modelo do reranker Gemini atualizado. Clique em Salvar ajustes para feedback.");
    persistSession();
  });

  preferRecent?.addEventListener("change", () => {
    persistSession();
  });
  userSourcePriorityToggle?.addEventListener("change", () => {
    persistSession();
  });
  indexUserCorpusBtn?.addEventListener("click", indexUserCorpusNow);
  sourceFiltersList?.addEventListener("change", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target || !target.matches(".source-checkbox")) return;
    state.acervo.selectedSources = selectedSourceValues();
    persistSession();
  });
  userCorpusSources?.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("[data-action][data-source-id]") : null;
    if (!target) return;
    const action = String(target.getAttribute("data-action") || "");
    const sourceId = String(target.getAttribute("data-source-id") || "").trim();
    if (!sourceId) return;
    if (action === "delete-source") {
      setUserSourceDeletedState(sourceId, true);
      return;
    }
    if (action === "restore-source") {
      setUserSourceDeletedState(sourceId, false);
    }
  });

  resetRagConfigBtn?.addEventListener("click", resetRagConfigToDefaults);
  saveRagConfigBtn?.addEventListener("click", saveRagConfigNow);

  generationModelInput?.addEventListener("change", () => {
    syncGenerationModelStateFromInputs();
    setRagConfigStatus("Modelo principal atualizado. Clique em Salvar ajustes para feedback.");
    persistSession();
  });

  generationFallbackModelInput?.addEventListener("change", () => {
    syncGenerationModelStateFromInputs();
    setRagConfigStatus("Modelo fallback atualizado. Clique em Salvar ajustes para feedback.");
    persistSession();
  });

  onboardingSaveKeyBtn?.addEventListener("click", saveGeminiKeyFromOnboarding);

  ragAdvancedGroups?.addEventListener("input", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const control = target.closest(".rag-control");
    if (!control) return;
    const key = control.getAttribute("data-rag-key") || "";
    const type = (control.getAttribute("data-rag-type") || "").toLowerCase();
    if (!key || !type) return;

    const item = schemaItemByKey(key);
    if (!item) return;

    if (target.matches("[data-role='range']")) {
      const num = control.querySelector("[data-role='number']");
      if (num) num.value = target.value;
      updateRagConfigValue(key, target.value);
    } else if (target.matches("[data-role='number']")) {
      const range = control.querySelector("[data-role='range']");
      if (range) range.value = target.value;
      updateRagConfigValue(key, target.value);
    } else if (target.matches("[data-role='text']")) {
      updateRagConfigValue(key, target.value);
    } else if (target.matches("[data-role='bool']")) {
      updateRagConfigValue(key, target.checked);
    } else {
      return;
    }

    if (ragValueChanged(key)) {
      control.classList.add("changed");
    } else {
      control.classList.remove("changed");
    }
    setRagConfigStatus("Parametros atualizados. Serao aplicados na proxima consulta.");
  });

  askBtn?.addEventListener("click", submitQuery);
  queryInput?.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      submitQuery();
    }
  });

  thread?.addEventListener("click", async (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;

    const docRef = target.closest(".doc-ref-link");
    if (docRef) {
      event.preventDefault();
      focusDocReference(docRef.dataset.turn, docRef.dataset.docIndex);
      return;
    }

    const button = target.closest("[data-action]");
    if (!button) return;
    const action = button.dataset.action;
    const turnId = button.dataset.turn;
    const audioMode = button.dataset.mode || "";
    await handleTurnAction(action, turnId, audioMode);
  });

  libraryList?.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;

    const item = target.closest(".library-item");
    if (item && !target.closest("[data-library-action]")) {
      const turnId = item.getAttribute("data-turn-id") || "";
      if (turnId) {
        handleLibraryAction("open-turn", turnId);
      }
      return;
    }

    const button = target.closest("[data-library-action]");
    if (!button) return;
    const action = button.dataset.libraryAction;
    const turnId = button.dataset.turn;
    handleLibraryAction(action, turnId);
  });

  window.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (document.body.dataset.onboardingOpen === "true") {
      setOnboardingOpen(false, { markSeen: true });
      return;
    }
    if (document.body.dataset.aboutOpen === "true") {
      setAboutOpen(false);
      return;
    }
    if (document.body.dataset.settingsOpen === "true") {
      setSettingsOpen(false);
      return;
    }
    if (document.body.dataset.acervoOpen === "true") {
      setAcervoOpen(false);
      return;
    }
    if (state.library.open) {
      setLibraryOpen(false);
    }
  });
}

function init() {
  const stored = loadStoredSession();
  state.turns = stored.turns;
  state.activeTurnId = stored.activeTurnId;
  state.answerFontScale = stored.answerFontScale;
  state.library.mode = normalizeLibraryMode(stored.libraryMode);
  state.ragConfigVersion = stored.ragConfigVersion || "";
  state.ragConfigValues = stored.ragConfigValues || {};
  state.acervo.selectedSources = Array.isArray(stored.sourceSelection) && stored.sourceSelection.length
    ? stored.sourceSelection
    : ["ratio"];
  applyAnswerFontScale();

  apiBaseInput.value = state.apiBase;
  rerankerBackend.value = stored.rerankerBackend || "local";
  preferRecent.checked = stored.preferRecent !== false;
  if (userSourcePriorityToggle) {
    userSourcePriorityToggle.checked = stored.preferUserSources !== false;
  }
  resetUserCorpusStages();
  refreshHeaderBadges();

  if (window.innerWidth <= 1160) {
    setEvidenceOpen(false);
  } else if (typeof stored.evidenceOpen === "boolean") {
    setEvidenceOpen(stored.evidenceOpen);
  } else {
    setEvidenceOpen(true);
  }

  bindEvents();
  setLibraryOpen(false);
  renderThread();
  renderEvidence();
  renderLibraryPanel();
  refreshRailButtons();
  refreshIcons();
  setAboutActiveTab(state.about.activeTab || "acervo");
  setAboutOpen(false);
  persistSession();
  syncGenerationModelInputsFromState();
  syncGeminiRerankModelInputFromState();
  if (!state.onboardingSeen) {
    setOnboardingOpen(true);
    setRequestState("Guia inicial aberto. Configure GEMINI_API_KEY para comecar.");
  } else {
    setOnboardingOpen(false);
  }
  checkHealth();
  loadRagConfigMetadata();
  loadUserCorpusSources();
  fetchGeminiStatus().then((hasKey) => {
    if (!hasKey) {
      setOnboardingOpen(true);
      setRequestState("GEMINI_API_KEY obrigatoria para consultar. Configure no guia inicial.", true);
    }
  }).catch(() => {});

  audioPlayer.ontimeupdate = () => {
    if (!state.speech.activeTurnId) return;
    const totalChunks = Math.max(1, Number(state.speech.totalChunks || 1));
    const chunkIndex = Math.max(1, Number(state.speech.currentChunkIndex || 1));
    if (!Number.isFinite(audioPlayer.duration) || audioPlayer.duration <= 0) return;
    const localPct = Math.max(0, Math.min(1, (audioPlayer.currentTime / audioPlayer.duration)));
    const pct = Math.max(0, Math.min(100, ((chunkIndex - 1 + localPct) / totalChunks) * 100));
    updateAudioProgress(pct);
  };

  audioPlayer.onended = () => {
    if (state.speech.currentChunkIndex > 0) {
      state.speech.playedChunks = Math.max(state.speech.playedChunks, state.speech.currentChunkIndex);
      state.speech.currentChunkIndex = 0;
      if (state.speech.totalChunks > 0) {
        updateAudioProgress((state.speech.playedChunks / state.speech.totalChunks) * 100);
      } else {
        updateAudioProgress(100);
      }
    } else {
      updateAudioProgress(100);
    }
    const turnId = state.speech.activeTurnId;
    if (turnId) {
      playNextQueuedChunk(turnId).then((startedNext) => {
        if (startedNext) return;
        if (state.speech.isStreaming) {
          state.speech.isLoading = true;
          state.speech.isBuffering = true;
          state.speech.isPaused = false;
          renderThread({ autoscroll: false });
          refreshAudioProgressUI(turnId);
          return;
        }
        setTimeout(() => {
          resetAudioState();
          renderThread({ autoscroll: false });
        }, 200);
      }).catch((err) => {
        resetAudioState();
        renderThread({ autoscroll: false });
        setRequestState(`Falha ao tocar proximo bloco de audio: ${String(err?.message || err)}`, true);
      });
      return;
    }
    setTimeout(() => {
      resetAudioState();
      renderThread({ autoscroll: false });
    }, 200);
  };

  audioPlayer.onerror = () => {
    abortSpeechStream("player_error");
    resetAudioState();
    renderThread({ autoscroll: false });
    setRequestState("Falha ao reproduzir audio.", true);
  };

  window.addEventListener("resize", () => {
    if (window.innerWidth > 1160) {
      setSettingsOpen(false);
      setEvidenceOpen(true);
    } else if (state.library.open) {
      setEvidenceOpen(false);
    }
  });
}

init();

