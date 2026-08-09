const $ = (id) => document.getElementById(id);

const I18N = {
  en: {
    settings: "Settings",
    hardReset: "Hard reset",
    configFolder: "Config folder",
    quit: "Quit",
  },
  ru: {
    settings: "Настройки",
    hardReset: "Сброс",
    configFolder: "Папка конфига",
    quit: "Выход",
  },
};

let lang = "en";

function t(key) {
  return (I18N[lang] || I18N.en)[key] || I18N.en[key] || key;
}

function applyLocale() {
  document.documentElement.lang = lang === "ru" ? "ru" : "en";
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.getAttribute("data-i18n"));
  });
}

function waitApi() {
  return new Promise((resolve) => {
    const tick = () => {
      if (window.pywebview && window.pywebview.api) {
        resolve(window.pywebview.api);
        return;
      }
      setTimeout(tick, 30);
    };
    tick();
  });
}

async function apiCall(name, ...args) {
  const api = await waitApi();
  return api[name](...args);
}

function render(state) {
  if (!state) return;

  const next = state.ui_language === "ru" ? "ru" : "en";
  if (next !== lang) {
    lang = next;
    applyLocale();
  }

  const box = $("presets");
  box.innerHTML = "";
  for (const name of state.presets || []) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "item";
    btn.setAttribute("role", "menuitemradio");
    btn.dataset.preset = name;

    const check = document.createElement("span");
    check.className = "check";
    check.textContent = name === state.current ? "●" : "";

    const label = document.createElement("span");
    label.className = "label";
    label.textContent = name;

    btn.appendChild(check);
    btn.appendChild(label);
    btn.addEventListener("click", async () => {
      await apiCall("apply_preset", name);
      await apiCall("hide");
    });
    box.appendChild(btn);
  }

  requestAnimationFrame(async () => {
    const h = Math.ceil($("menu").getBoundingClientRect().height);
    try {
      await apiCall("report_height", h);
    } catch (_) {
      /* ignore */
    }
  });
}

async function refresh() {
  const state = await apiCall("get_menu_state");
  render(state);
}

document.getElementById("menu").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  const action = btn.dataset.action;
  await apiCall("action", action);
});

window.refreshTrayMenu = function (payload) {
  try {
    const data = typeof payload === "string" ? JSON.parse(payload) : payload;
    render(data);
  } catch (err) {
    console.error(err);
  }
};

window.addEventListener("pywebviewready", refresh);
document.addEventListener("DOMContentLoaded", async () => {
  await waitApi();
  await refresh();
});

window.addEventListener("keydown", async (e) => {
  if (e.key === "Escape") {
    await apiCall("hide");
  }
});
