/* NVColor — Fluent settings frontend */

const $ = (id) => document.getElementById(id);

const I18N = {
  en: {
    subtitle: "Color presets for desktop & games",
    presetsNav: "Presets",
    new: "New",
    delete: "Delete",
    apply: "Apply",
    preset: "Preset",
    name: "Name",
    hotkey: "Hotkey",
    hotkeyPlaceholder: "ctrl+alt+1",
    capture: "Capture",
    capturing: "Press keys…",
    color: "Color",
    brightness: "Brightness",
    contrast: "Contrast",
    gamma: "Gamma",
    vibrance: "Digital Vibrance",
    hue: "Hue",
    savePreset: "Save preset",
    hardReset: "Hard reset",
    automation: "Automation",
    watchProcess: "Watch game process",
    allDisplays: "Apply to all displays",
    processes: "Processes",
    processesPlaceholder: "game.exe, other.exe",
    onStart: "On start",
    onExit: "On exit",
    processesHint: "Comma-separated process names, e.g. process.exe",
    config: "Config",
    configHint: 'Import / export full <span class="mono">config.json</span> (presets, hotkeys, automation).',
    import: "Import…",
    export: "Export…",
    captureHint: "Alt / Ctrl / Shift + key",
    applied: "Applied · {name}",
    saved: "Saved · {name}",
    created: "Created · {name}",
    deleted: "Deleted",
    automationSaved: "Automation saved",
    hardResetDone: "Hard reset",
    exported: "Exported · {path}",
    imported: "Imported · {path}",
    hotkeySet: "Hotkey · {spec}",
    livePreview: "Live preview",
    loadError: "Error loading presets",
    noPresets: "No presets in config",
    errorPrefix: "Error: ",
  },
  ru: {
    subtitle: "Цветовые пресеты для рабочего стола и игр",
    presetsNav: "Пресеты",
    new: "Новый",
    delete: "Удалить",
    apply: "Применить",
    preset: "Пресет",
    name: "Имя",
    hotkey: "Хоткей",
    hotkeyPlaceholder: "ctrl+alt+1",
    capture: "Захват",
    capturing: "Нажмите клавиши…",
    color: "Цвет",
    brightness: "Яркость",
    contrast: "Контраст",
    gamma: "Гамма",
    vibrance: "Цифровая интенсивность",
    hue: "Оттенок",
    savePreset: "Сохранить",
    hardReset: "Сброс",
    automation: "Автоматизация",
    watchProcess: "Следить за процессом",
    allDisplays: "На все мониторы",
    processes: "Процессы",
    processesPlaceholder: "game.exe, other.exe",
    onStart: "При запуске",
    onExit: "При выходе",
    processesHint: "Имена процессов через запятую, напр. process.exe",
    config: "Конфиг",
    configHint: 'Импорт / экспорт полного <span class="mono">config.json</span> (пресеты, хоткеи, автоматизация).',
    import: "Импорт…",
    export: "Экспорт…",
    captureHint: "Alt / Ctrl / Shift + клавиша",
    applied: "Применён · {name}",
    saved: "Сохранено · {name}",
    created: "Создан · {name}",
    deleted: "Удалено",
    automationSaved: "Автоматизация сохранена",
    hardResetDone: "Сброс выполнен",
    exported: "Экспортировано · {path}",
    imported: "Импортировано · {path}",
    hotkeySet: "Хоткей · {spec}",
    livePreview: "Живой предпросмотр",
    loadError: "Ошибка загрузки пресетов",
    noPresets: "В конфиге нет пресетов",
    errorPrefix: "Ошибка: ",
  },
};

const state = {
  selected: null,
  current: null,
  presets: {},
  hotkeys: {},
  capturing: false,
  liveTimer: null,
  ready: false,
  lang: "en",
};

function t(key, vars) {
  const table = I18N[state.lang] || I18N.en;
  let text = table[key] ?? I18N.en[key] ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      text = text.replaceAll(`{${k}}`, String(v));
    }
  }
  return text;
}

function syncNavLayout() {
  const nav = document.querySelector(".nav");
  const actions = document.querySelector(".nav-actions");
  if (!nav || !actions) return;

  // Let buttons dictate natural width, then lock column to that size.
  nav.style.width = "max-content";
  const need = Math.ceil(actions.getBoundingClientRect().width) + 24; // padding
  const width = Math.max(252, Math.min(360, need));
  nav.style.width = `${width}px`;
}

/** min-width per button = longest label across all locales (+ padding/border). */
function syncI18nButtonMinWidths() {
  const buttons = document.querySelectorAll("button[data-i18n]");
  if (!buttons.length) return;

  const measure = document.createElement("span");
  measure.setAttribute("aria-hidden", "true");
  measure.style.cssText =
    "position:absolute;left:-9999px;top:0;visibility:hidden;white-space:nowrap;pointer-events:none;";
  document.body.appendChild(measure);

  const langs = Object.keys(I18N);
  for (const btn of buttons) {
    const key = btn.getAttribute("data-i18n");
    if (!key) continue;

    const keys = [key];
    // Capture toggles between two labels
    if (btn.id === "btn-capture") keys.push("capturing");

    const cs = getComputedStyle(btn);
    measure.style.font = cs.font;
    measure.style.letterSpacing = cs.letterSpacing;
    measure.style.fontWeight = cs.fontWeight;
    measure.style.fontSize = cs.fontSize;
    measure.style.fontFamily = cs.fontFamily;

    let maxText = 0;
    for (const lang of langs) {
      const table = I18N[lang] || {};
      for (const k of keys) {
        const label = table[k] ?? I18N.en[k] ?? k;
        measure.textContent = label;
        maxText = Math.max(maxText, measure.getBoundingClientRect().width);
      }
    }

    const pad =
      (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
    const border =
      (parseFloat(cs.borderLeftWidth) || 0) + (parseFloat(cs.borderRightWidth) || 0);
    btn.style.minWidth = `${Math.ceil(maxText + pad + border)}px`;
  }

  measure.remove();
}

/** Shared label column width = longest .row/.slider-row label across locales. */
function syncLabelColumnWidth() {
  const labels = document.querySelectorAll(".row label[data-i18n], .slider-row label[data-i18n]");
  if (!labels.length) return;

  const sample = labels[0];
  const cs = getComputedStyle(sample);
  const measure = document.createElement("span");
  measure.setAttribute("aria-hidden", "true");
  measure.style.cssText =
    "position:absolute;left:-9999px;top:0;visibility:hidden;white-space:nowrap;pointer-events:none;";
  measure.style.font = cs.font;
  measure.style.letterSpacing = cs.letterSpacing;
  measure.style.fontWeight = cs.fontWeight;
  measure.style.fontSize = cs.fontSize;
  measure.style.fontFamily = cs.fontFamily;
  document.body.appendChild(measure);

  let maxText = 0;
  const langs = Object.keys(I18N);
  for (const el of labels) {
    const key = el.getAttribute("data-i18n");
    if (!key) continue;
    for (const lang of langs) {
      const label = (I18N[lang] || {})[key] ?? I18N.en[key] ?? key;
      measure.textContent = label;
      maxText = Math.max(maxText, measure.getBoundingClientRect().width);
    }
  }
  measure.remove();

  const width = Math.ceil(maxText);
  document.documentElement.style.setProperty("--label-col", `${width}px`);
}

function applyLocale() {
  document.documentElement.lang = state.lang === "ru" ? "ru" : "en";

  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.getAttribute("data-i18n"));
  });
  document.querySelectorAll("[data-i18n-html]").forEach((el) => {
    el.innerHTML = t(el.getAttribute("data-i18n-html"));
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.setAttribute("placeholder", t(el.getAttribute("data-i18n-placeholder")));
  });

  const btn = $("btn-capture");
  if (btn) {
    btn.textContent = state.capturing ? t("capturing") : t("capture");
  }

  $("lang-en").classList.toggle("active", state.lang === "en");
  $("lang-ru").classList.toggle("active", state.lang === "ru");

  requestAnimationFrame(() => {
    syncI18nButtonMinWidths();
    syncLabelColumnWidth();
    syncNavLayout();
  });
}

async function setLanguage(lang) {
  const next = lang === "ru" ? "ru" : "en";
  if (next === state.lang) return;
  state.lang = next;
  applyLocale();
  try {
    await apiCall("set_language", next);
  } catch (_) {
    /* local UI still updates */
  }
}

function setStatus(_text) {
  /* Status strip removed from UI */
}

function fmt(n) {
  return Number(n).toFixed(2);
}

function waitApi() {
  return new Promise((resolve) => {
    const tick = () => {
      if (window.pywebview && window.pywebview.api) {
        resolve(window.pywebview.api);
        return;
      }
      setTimeout(tick, 40);
    };
    tick();
  });
}

async function apiCall(name, ...args) {
  const api = await waitApi();
  return api[name](...args);
}

function comboValue(el) {
  return el?.dataset?.value || "";
}

function getComboMenu(el) {
  if (!el) return null;
  if (el._comboMenu) return el._comboMenu;
  const menu = el.querySelector(".combo-menu");
  if (menu) {
    el._comboMenu = menu;
    menu.dataset.owner = el.id || "";
  }
  return menu || null;
}

function setComboValue(el, value, silent) {
  if (!el) return;
  const next = value || "";
  el.dataset.value = next;
  const label = el.querySelector(".combo-value");
  if (label) label.textContent = next;
  const menu = getComboMenu(el);
  menu?.querySelectorAll(".combo-option").forEach((opt) => {
    opt.classList.toggle("active", opt.dataset.value === next);
  });
  if (!silent) {
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
}

function closeCombo(el) {
  if (!el) return;
  el.classList.remove("open");
  el.setAttribute("aria-expanded", "false");
  const menu = getComboMenu(el);
  if (menu) {
    menu.hidden = true;
    menu.style.top = "";
    menu.style.left = "";
    menu.style.width = "";
    menu.style.maxHeight = "";
    // Keep menu on body so it stays above backdrop-filter cards
    if (menu.parentElement !== document.body) {
      document.body.appendChild(menu);
    }
  }
}

function closeAllCombos(except) {
  document.querySelectorAll(".combo.open").forEach((node) => {
    if (node !== except) closeCombo(node);
  });
}

function placeComboMenu(el) {
  const trigger = el.querySelector(".combo-trigger");
  const menu = getComboMenu(el);
  if (!trigger || !menu) return;
  const rect = trigger.getBoundingClientRect();
  const gap = 4;
  const maxH = 220;
  const spaceBelow = window.innerHeight - rect.bottom - gap - 8;
  const spaceAbove = rect.top - gap - 8;
  const openUp = spaceBelow < 140 && spaceAbove > spaceBelow;
  const avail = Math.max(80, openUp ? spaceAbove : spaceBelow);
  const height = Math.min(maxH, avail);

  menu.style.position = "fixed";
  menu.style.zIndex = "9999";
  menu.style.width = `${Math.round(rect.width)}px`;
  menu.style.left = `${Math.round(rect.left)}px`;
  menu.style.maxHeight = `${Math.round(height)}px`;

  if (openUp) {
    const h = Math.min(menu.scrollHeight || height, height);
    menu.style.top = `${Math.round(rect.top - gap - h)}px`;
  } else {
    menu.style.top = `${Math.round(rect.bottom + gap)}px`;
  }
}

function openCombo(el) {
  if (!el) return;
  closeAllCombos(el);
  el.classList.add("open");
  el.setAttribute("aria-expanded", "true");
  const menu = getComboMenu(el);
  if (!menu) return;
  if (menu.parentElement !== document.body) {
    document.body.appendChild(menu);
  }
  menu.hidden = false;
  placeComboMenu(el);
  requestAnimationFrame(() => placeComboMenu(el));
}

function fillSelect(el, names, value) {
  if (!el) return;
  const prev = value || comboValue(el);
  const menu = getComboMenu(el);
  if (!menu) return;
  menu.innerHTML = "";
  for (const name of names) {
    const opt = document.createElement("button");
    opt.type = "button";
    opt.className = "combo-option";
    opt.setAttribute("role", "option");
    opt.dataset.value = name;
    opt.textContent = name;
    opt.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      setComboValue(el, name);
      closeCombo(el);
    });
    menu.appendChild(opt);
  }
  const next = names.includes(prev) ? prev : names[0] || "";
  setComboValue(el, next, true);
}

function bindCombo(el) {
  if (!el || el.dataset.bound === "1") return;
  el.dataset.bound = "1";
  const menu = getComboMenu(el);
  if (menu && menu.parentElement !== document.body) {
    document.body.appendChild(menu);
  }
  const trigger = el.querySelector(".combo-trigger");
  const toggle = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (el.classList.contains("open")) closeCombo(el);
    else openCombo(el);
  };
  trigger?.addEventListener("click", toggle);
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggle(e);
    } else if (e.key === "Escape") {
      closeCombo(el);
    }
  });
}

function renderPresets() {
  const list = $("preset-list");
  list.innerHTML = "";
  const names = Object.keys(state.presets);
  for (const name of names) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "preset-item" + (name === state.selected ? " active" : "");
    btn.setAttribute("role", "option");
    btn.dataset.name = name;

    const title = document.createElement("div");
    title.className = "name";
    if (name === state.current) {
      const dot = document.createElement("span");
      dot.className = "dot";
      title.appendChild(dot);
    }
    title.appendChild(document.createTextNode(name));

    const hk = document.createElement("div");
    hk.className = "hk";
    hk.textContent = formatHotkey(state.hotkeys[name] || "");

    btn.appendChild(title);
    btn.appendChild(hk);
    btn.addEventListener("click", () => selectPreset(name));
    btn.addEventListener("dblclick", () => applySelected(name));
    list.appendChild(btn);
  }
}

function loadPresetFields(name) {
  const raw = state.presets[name] || {
    brightness: 0.5,
    contrast: 0.5,
    gamma: 1.0,
    vibrance: 50,
    hue: 0,
  };
  $("name").value = name;
  $("hotkey").value = formatHotkey(state.hotkeys[name] || "");
  $("brightness").value = raw.brightness ?? 0.5;
  $("contrast").value = raw.contrast ?? 0.5;
  $("gamma").value = raw.gamma ?? 1.0;
  $("vibrance").value = raw.vibrance ?? 50;
  $("hue").value = raw.hue ?? 0;
  updateSliderLabels();
}

function updateSliderLabels() {
  $("brightness-val").textContent = fmt($("brightness").value);
  $("contrast-val").textContent = fmt($("contrast").value);
  $("gamma-val").textContent = fmt($("gamma").value);
  $("vibrance-val").textContent = String(Math.round(Number($("vibrance").value)));
  $("hue-val").textContent = String(Math.round(Number($("hue").value)));
}

async function selectPreset(name) {
  state.selected = name;
  loadPresetFields(name);
  renderPresets();
  setStatus(name);
  try {
    await apiCall("select_preset", name);
  } catch (_) {
    /* local-only ok */
  }
}

async function applySelected(name) {
  const target = name || state.selected || $("name").value.trim();
  if (!target) return;
  const res = await apiCall("apply", target);
  if (res && res.error) setStatus(t("errorPrefix") + res.error);
  else setStatus(t("applied", { name: target }));
}

function scheduleLive() {
  updateSliderLabels();
  if (state.liveTimer) clearTimeout(state.liveTimer);
  state.liveTimer = setTimeout(async () => {
    state.liveTimer = null;
    await apiCall(
      "live",
      Number($("brightness").value),
      Number($("contrast").value),
      Number($("gamma").value),
      Math.round(Number($("vibrance").value)),
      Math.round(Number($("hue").value))
    );
    setStatus(t("livePreview"));
  }, 40);
}

async function savePreset() {
  const res = await apiCall(
    "save",
    $("name").value.trim(),
    Number($("brightness").value),
    Number($("contrast").value),
    Number($("gamma").value),
    $("hotkey").value.trim(),
    state.selected,
    Math.round(Number($("vibrance").value)),
    Math.round(Number($("hue").value))
  );
  if (res && res.error) {
    setStatus(t("errorPrefix") + res.error);
    return;
  }
  state.selected = res.name;
  setStatus(t("saved", { name: res.name }));
  await refresh();
}

async function newPreset() {
  const res = await apiCall(
    "new_preset",
    Number($("brightness").value),
    Number($("contrast").value),
    Number($("gamma").value),
    Math.round(Number($("vibrance").value)),
    Math.round(Number($("hue").value))
  );
  if (res && res.error) {
    setStatus(t("errorPrefix") + res.error);
    return;
  }
  state.selected = res.name;
  await refresh();
  setStatus(t("created", { name: res.name }));
}

async function deletePreset() {
  if (!state.selected) return;
  const res = await apiCall("delete_preset", state.selected);
  if (res && res.error) {
    setStatus(t("errorPrefix") + res.error);
    return;
  }
  state.selected = "Default";
  await refresh();
  setStatus(t("deleted"));
}

async function saveOptions() {
  const res = await apiCall("save_options", {
    watch_enabled: $("watch-enabled").checked,
    all_displays: $("all-displays").checked,
    processes: $("processes").value,
    on_start: comboValue($("on-start")),
    on_exit: comboValue($("on-exit")),
  });
  if (res && res.error) setStatus(t("errorPrefix") + res.error);
  else setStatus(t("automationSaved"));
}

async function hardReset() {
  await apiCall("hard_reset");
  setStatus(t("hardResetDone"));
  await refresh();
}

async function exportConfig() {
  const res = await apiCall("export_config");
  if (res && res.cancelled) {
    setStatus("");
    return;
  }
  if (res && res.error) {
    setStatus(t("errorPrefix") + res.error);
    return;
  }
  setStatus(t("exported", { path: res.path || "config.json" }));
}

async function importConfig() {
  const res = await apiCall("import_config");
  if (res && res.cancelled) {
    setStatus("");
    return;
  }
  if (res && res.error) {
    setStatus(t("errorPrefix") + res.error);
    return;
  }
  state.selected = "Default";
  if (res.presets) applyState(res);
  else await refresh();
  setStatus(t("imported", { path: res.path || "config.json" }));
}

function toggleCapture() {
  state.capturing = !state.capturing;
  const btn = $("btn-capture");
  if (state.capturing) {
    btn.textContent = t("capturing");
    btn.classList.add("capturing");
    setStatus(t("captureHint"));
  } else {
    btn.textContent = t("capture");
    btn.classList.remove("capturing");
  }
}

const SHIFT_SYMBOL_TO_KEY = {
  "!": "1",
  "@": "2",
  "#": "3",
  "$": "4",
  "%": "5",
  "^": "6",
  "&": "7",
  "*": "8",
  "(": "9",
  ")": "0",
  _: "-",
  "+": "=",
};

function physicalKeyFromEvent(e) {
  const code = e.code || "";
  if (/^Digit[0-9]$/.test(code)) return code.slice(5);
  if (/^Numpad[0-9]$/.test(code)) return code.slice(6);
  if (/^Key[A-Z]$/.test(code)) return code.slice(3).toLowerCase();
  if (/^F([1-9]|1[0-2])$/.test(code)) return code.toLowerCase();

  let k = (e.key || "").toLowerCase();
  if (k.startsWith("arrow")) k = k.slice(5);
  if (SHIFT_SYMBOL_TO_KEY[k]) return SHIFT_SYMBOL_TO_KEY[k];
  if (k.length === 1) return k;
  return k;
}

function formatHotkeyParts(ctrl, alt, shift, win, keyToken) {
  const parts = [];
  if (alt) parts.push("Alt");
  if (ctrl) parts.push("Ctrl");
  if (shift) parts.push("Shift");
  if (win) parts.push("Win");
  let keyLabel = keyToken;
  if (/^f([1-9]|1[0-2])$/i.test(keyToken)) keyLabel = keyToken.toUpperCase();
  else if (/^[a-z]$/i.test(keyToken)) keyLabel = keyToken.toUpperCase();
  parts.push(keyLabel);
  return parts.join("+");
}

function formatHotkey(spec) {
  if (!spec) return "";
  const raw = String(spec)
    .replace(/-/g, "+")
    .split("+")
    .map((p) => p.trim())
    .filter(Boolean);
  let ctrl = false,
    alt = false,
    shift = false,
    win = false;
  let key = null;
  for (const part of raw) {
    const p = part.toLowerCase();
    if (p === "alt" || p === "menu") alt = true;
    else if (p === "ctrl" || p === "control") ctrl = true;
    else if (p === "shift") shift = true;
    else if (p === "win" || p === "windows" || p === "super" || p === "meta") win = true;
    else key = SHIFT_SYMBOL_TO_KEY[p] || p;
  }
  if (!key) return "";
  return formatHotkeyParts(ctrl, alt, shift, win, key);
}

function onKeyDown(e) {
  if (!state.capturing) return;
  const keyName = (e.key || "").toLowerCase();
  if (["shift", "control", "alt", "meta"].includes(keyName)) return;
  if (["enter", "escape", "tab"].includes(keyName)) return;

  if (!e.ctrlKey && !e.altKey && !e.shiftKey && !e.metaKey) return;

  const keyToken = physicalKeyFromEvent(e);
  if (!keyToken) return;

  const spec = formatHotkeyParts(e.ctrlKey, e.altKey, e.shiftKey, e.metaKey, keyToken);
  $("hotkey").value = spec;
  state.capturing = false;
  $("btn-capture").textContent = t("capture");
  $("btn-capture").classList.remove("capturing");
  setStatus(t("hotkeySet", { spec }));
  e.preventDefault();
}

function applyState(payload) {
  if (!payload) return;
  state.presets = payload.presets || {};
  state.hotkeys = payload.hotkeys || {};
  state.current = payload.current || "Default";
  if (!state.selected || !(state.selected in state.presets)) {
    state.selected = payload.selected || state.current || "Default";
  }

  if (payload.ui_language) {
    const next = payload.ui_language === "ru" ? "ru" : "en";
    if (next !== state.lang) {
      state.lang = next;
      applyLocale();
    } else {
      $("lang-en").classList.toggle("active", state.lang === "en");
      $("lang-ru").classList.toggle("active", state.lang === "ru");
    }
  }

  const names = Object.keys(state.presets);
  fillSelect($("on-start"), names, payload.watch?.preset || "Default");
  fillSelect($("on-exit"), names, payload.watch?.on_exit_preset || "Default");

  $("watch-enabled").checked = !!payload.watch?.enabled;
  $("all-displays").checked = !!payload.apply_all_displays;
  $("processes").value = (payload.watch?.process_names || []).join(", ");

  renderPresets();
  if (state.selected in state.presets) loadPresetFields(state.selected);
  if (payload.status) setStatus(payload.status);
}

async function refresh() {
  try {
    const payload = await apiCall("get_state", state.selected);
    if (!payload || payload.error) {
      setStatus(t("loadError"));
      console.error("get_state failed", payload);
      return;
    }
    applyState(payload);
    if (!Object.keys(state.presets).length) {
      setStatus(t("noPresets"));
    }
  } catch (err) {
    console.error(err);
    setStatus(t("errorPrefix") + err);
  }
}

// Called from Python via evaluate_js
window.refreshFromPython = function (payload) {
  try {
    const data = typeof payload === "string" ? JSON.parse(payload) : payload;
    applyState(data);
  } catch (err) {
    console.error(err);
  }
};

function bind() {
  $("btn-new").addEventListener("click", newPreset);
  $("btn-delete").addEventListener("click", deletePreset);
  $("btn-apply").addEventListener("click", () => applySelected());
  $("btn-save").addEventListener("click", savePreset);
  $("btn-reset").addEventListener("click", hardReset);
  $("btn-capture").addEventListener("click", toggleCapture);
  $("btn-import").addEventListener("click", importConfig);
  $("btn-export").addEventListener("click", exportConfig);
  $("lang-en").addEventListener("click", () => setLanguage("en"));
  $("lang-ru").addEventListener("click", () => setLanguage("ru"));

  bindCombo($("on-start"));
  bindCombo($("on-exit"));

  for (const id of ["brightness", "contrast", "gamma", "vibrance", "hue"]) {
    $(id).addEventListener("input", scheduleLive);
  }

  for (const id of ["watch-enabled", "all-displays", "on-start", "on-exit"]) {
    $(id).addEventListener("change", saveOptions);
  }
  $("processes").addEventListener("change", saveOptions);
  $("processes").addEventListener("blur", saveOptions);

  document.addEventListener("click", (e) => {
    if (e.target.closest(".combo") || e.target.closest(".combo-menu")) return;
    closeAllCombos();
  });
  document.querySelector(".content")?.addEventListener(
    "scroll",
    () => closeAllCombos(),
    { passive: true }
  );

  window.addEventListener("keydown", onKeyDown);
}

async function boot() {
  if (state.ready) return;
  bind();
  applyLocale();
  state.ready = true;
  await refresh();
}

window.addEventListener("pywebviewready", () => {
  boot();
});

document.addEventListener("DOMContentLoaded", async () => {
  await waitApi();
  await boot();
});
