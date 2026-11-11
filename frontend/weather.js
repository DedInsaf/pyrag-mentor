const weatherView = document.querySelector("#weather-view");
const weatherForm = document.querySelector("#forecast-form");
const placeChoice = document.querySelector("#place-choice");
const photoFields = document.querySelector("#photo-fields");
const weatherMessage = document.querySelector("#weather-message");
const weatherPhotos = document.querySelector("#weather-photos");
let forecastRequest;

document.addEventListener("weather:login", async () => {
  weatherView.classList.remove("hidden");
  try {
    const response = await fetch("/weather/places");
    if (!response.ok) return;
    const places = await response.json();
    placeChoice.replaceChildren(new Option("Своё фото", ""));
    for (const place of places) {
      placeChoice.add(new Option(place.title, place.id));
    }
  } catch {
    weatherMessage.textContent = "Каталог временно недоступен.";
  }
});

placeChoice.addEventListener("change", () => {
  photoFields.disabled = Boolean(placeChoice.value);
  photoFields.classList.toggle("hidden", Boolean(placeChoice.value));
});

document.querySelector("#locate").addEventListener("click", () => {
  if (!navigator.geolocation) {
    weatherMessage.textContent = "Геолокация недоступна. Введите координаты вручную.";
    return;
  }
  navigator.geolocation.getCurrentPosition(({ coords }) => {
    weatherForm.elements.latitude.value = coords.latitude.toFixed(5);
    weatherForm.elements.longitude.value = coords.longitude.toFixed(5);
    weatherMessage.textContent = "Координаты подставлены.";
  }, () => {
    weatherMessage.textContent = "Не удалось получить геолокацию. Введите координаты вручную.";
  }, { timeout: 10000 });
});

weatherForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(weatherForm);
  if (data.get("place_id")) {
    data.delete("file");
  } else if (!data.get("file")?.size) {
    weatherMessage.textContent = "Загрузите фото или выберите место.";
    return;
  } else {
    data.delete("place_id");
    const title = data.get("title").trim();
    if (title) data.set("title", title);
    else data.delete("title");
  }
  data.set("image_engine", document.querySelector("#weather-ai").checked ? "ai" : "preview");
  const submit = weatherForm.querySelector('[type="submit"]');
  submit.disabled = true;
  weatherPhotos.classList.add("hidden");
  weatherMessage.textContent = "Получаем прогноз и обрабатываем фото…";
  forecastRequest = new AbortController();
  try {
    const response = await fetch("/weather/forecast", {
      method: "POST",
      body: data,
      signal: forecastRequest.signal,
      headers: { Authorization: "Bearer " + sessionStorage.getItem(tokenKey) },
    });
    const result = await response.json();
    if (!response.ok) {
      weatherMessage.textContent = typeof result.detail === "string" ? result.detail : "Проверьте параметры прогноза.";
      return;
    }
    const time = new Date(result.forecast.time).toLocaleString("ru-RU");
    weatherMessage.textContent = time + " · " + result.description;
    document.querySelector("#weather-original").src = "data:image/jpeg;base64," + result.original;
    document.querySelector("#weather-result").src = "data:image/jpeg;base64," + result.image;
    weatherPhotos.classList.remove("hidden");
  } catch (error) {
    if (error.name !== "AbortError") weatherMessage.textContent = "Не удалось получить прогноз.";
  } finally {
    submit.disabled = false;
  }
});

document.addEventListener("weather:logout", () => {
  forecastRequest?.abort();
  weatherForm.reset();
  photoFields.disabled = false;
  photoFields.classList.remove("hidden");
  weatherView.classList.add("hidden");
  weatherPhotos.classList.add("hidden");
  weatherMessage.textContent = "";
  document.querySelector("#weather-original").removeAttribute("src");
  document.querySelector("#weather-result").removeAttribute("src");
});
