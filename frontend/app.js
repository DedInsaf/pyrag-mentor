const tokenKey = "pyrag_access_token";
const authView = document.querySelector("#auth-view");
const profileView = document.querySelector("#profile-view");
const message = document.querySelector("#form-message");
const registerForm = document.querySelector("#register-form");
const loginForm = document.querySelector("#login-form");

const errorTranslations = {
  "Email already registered": "Этот email уже зарегистрирован.",
  "Username already taken": "Такое имя пользователя уже занято.",
  "User already exists": "Пользователь с такими данными уже существует.",
  "Invalid credentials": "Неверная почта или пароль.",
  "Account is disabled": "Этот аккаунт отключён.",
  "Invalid or expired token": "Сессия закончилась. Войдите снова."
};

function showMessage(text, type = "error") {
  message.textContent = text;
  message.className = `message ${type}`;
}

function clearMessage() {
  message.textContent = "";
  message.className = "message hidden";
}

function apiError(payload) {
  if (typeof payload?.detail === "string") {
    return errorTranslations[payload.detail] || payload.detail;
  }
  if (Array.isArray(payload?.detail)) {
    return payload.detail.map((item) => item.msg.replace(/^Value error, /, "")).join(" ");
  }
  return "Не удалось выполнить запрос. Попробуйте ещё раз.";
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) }
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(apiError(payload));
  return payload;
}

function setLoading(form, loading) {
  const button = form.querySelector("button[type='submit']");
  button.disabled = loading;
  button.querySelector("span").textContent = loading ? "Подождите…" : button.dataset.label;
}

function showProfile(user) {
  authView.classList.add("hidden");
  profileView.classList.remove("hidden");
  document.querySelector("#profile-name").textContent = user.full_name || user.username;
  document.querySelector("#profile-email").textContent = user.email;
  document.querySelector("#profile-username").textContent = user.username;
  document.querySelector("#profile-role").textContent = user.role === "user" ? "Пользователь" : user.role;
}

async function loadProfile(token) {
  try {
    const user = await request("/auth/me", { headers: { Authorization: `Bearer ${token}` } });
    showProfile(user);
  } catch (error) {
    sessionStorage.removeItem(tokenKey);
    authView.classList.remove("hidden");
    profileView.classList.add("hidden");
    if (error.message) showMessage(error.message);
  }
}

async function submitAuth(form, path) {
  clearMessage();
  if (!form.reportValidity()) return;
  setLoading(form, true);
  const values = Object.fromEntries(new FormData(form));
  if (!values.full_name) delete values.full_name;
  try {
    const result = await request(path, { method: "POST", body: JSON.stringify(values) });
    sessionStorage.setItem(tokenKey, result.access_token);
    await loadProfile(result.access_token);
    form.reset();
  } catch (error) {
    showMessage(error.message);
  } finally {
    setLoading(form, false);
  }
}

document.querySelectorAll(".primary-button").forEach((button) => {
  button.dataset.label = button.querySelector("span").textContent;
});

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    const isRegister = tab.dataset.tab === "register";
    document.querySelectorAll(".tab").forEach((item) => {
      item.classList.toggle("active", item === tab);
      item.setAttribute("aria-selected", String(item === tab));
    });
    registerForm.classList.toggle("hidden", !isRegister);
    loginForm.classList.toggle("hidden", isRegister);
    document.querySelector("#card-title").textContent = isRegister ? "Создать аккаунт" : "С возвращением";
    document.querySelector("#card-subtitle").textContent = isRegister
      ? "Заполните данные — это займёт меньше минуты."
      : "Введите данные своего аккаунта.";
    clearMessage();
  });
});

document.querySelectorAll(".password-toggle").forEach((button) => {
  button.addEventListener("click", () => {
    const input = button.previousElementSibling;
    const shouldShow = input.type === "password";
    input.type = shouldShow ? "text" : "password";
    button.textContent = shouldShow ? "Скрыть" : "Показать";
    button.setAttribute("aria-label", shouldShow ? "Скрыть пароль" : "Показать пароль");
  });
});

registerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  submitAuth(registerForm, "/auth/register");
});

loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  submitAuth(loginForm, "/auth/login");
});

document.querySelector("#logout-button").addEventListener("click", () => {
  sessionStorage.removeItem(tokenKey);
  profileView.classList.add("hidden");
  authView.classList.remove("hidden");
  clearMessage();
});

async function checkHealth() {
  const status = document.querySelector("#server-status");
  try {
    const result = await request("/health");
    const online = result.status === "healthy";
    status.className = `server-status ${online ? "online" : "offline"}`;
    status.lastElementChild.textContent = online ? "Система работает" : "База данных недоступна";
  } catch {
    status.className = "server-status offline";
    status.lastElementChild.textContent = "Сервер недоступен";
  }
}

checkHealth();
const existingToken = sessionStorage.getItem(tokenKey);
if (existingToken) loadProfile(existingToken);
