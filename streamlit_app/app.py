"""Weather workspace backed by the FastAPI application."""

import base64
import os
from datetime import datetime

import httpx
import streamlit as st

API = os.getenv("WEATHER_API_URL", "http://127.0.0.1:8000")
st.set_page_config(page_title="Погода в кадре", page_icon="🌦", layout="wide")


def call(method, path, **kwargs):
    headers = (
        {"Authorization": f"Bearer {st.session_state.token}"}
        if st.session_state.get("token")
        else {}
    )
    try:
        response = httpx.request(
            method, API + path, headers=headers, timeout=180, **kwargs
        )
        if not response.is_success:
            detail = response.json().get("detail", f"Ошибка {response.status_code}")
            st.error(detail if isinstance(detail, str) else "Проверьте значения полей.")
            return None
        if response.headers.get("content-type", "").startswith("image/"):
            return response.content
        return response.json()
    except (httpx.HTTPError, ValueError):
        st.error("Сервер временно недоступен.")
        return None


def coordinates():
    left, right = st.columns(2)
    return (
        left.number_input("Широта", -90.0, 90.0, 55.7900, format="%.5f"),
        right.number_input("Долгота", -180.0, 180.0, 49.1200, format="%.5f"),
    )


def file_part(photo):
    return (photo.name, photo.getvalue(), photo.type)


st.title("Погода в кадре")
if not st.session_state.get("token"):
    tab = st.radio("Аккаунт", ["Вход", "Регистрация"], horizontal=True)
    with st.form("account"):
        email = st.text_input("Почта")
        username = st.text_input("Имя пользователя") if tab == "Регистрация" else ""
        password = st.text_input("Пароль", type="password")
        if tab == "Регистрация":
            st.caption("Минимум 8 символов, заглавная буква и цифра.")
        if st.form_submit_button(tab):
            body = {"email": email, "password": password}
            if username:
                body["username"] = username
            result = call(
                "POST",
                "/auth/register" if tab == "Регистрация" else "/auth/login",
                json=body,
            )
            if result:
                st.session_state.token = result["access_token"]
                st.session_state.role = result["role"]
                st.rerun()
    st.stop()

if st.sidebar.button("Выйти"):
    st.session_state.clear()
    st.rerun()

page = st.sidebar.radio(
    "Раздел",
    [
        "Прогноз по фото",
        "Каталог мест",
        "Добавить фото",
        "Мои вклады",
        "Прогнозы списком",
        "Сравнение режимов",
        "Модерация",
        "Состояние системы",
    ],
)

if page in ("Прогноз по фото", "Сравнение режимов"):
    st.header(page)
    places = call("GET", "/weather/places") or []
    by_id = {row["id"]: row["title"] for row in places}
    place = st.selectbox(
        "Место из каталога",
        [None, *by_id],
        format_func=lambda key: by_id.get(key, "Загрузить своё фото"),
    )
    photo = (
        st.file_uploader("Фото места", type=["jpeg", "jpg", "png", "webp"])
        if place is None
        else None
    )
    latitude, longitude = coordinates() if place is None else (0, 0)
    if place is None:
        st.caption(
            "Укажите координаты места съёмки. "
            "На главной странице можно подставить геолокацию."
        )
    hours = st.slider("Через сколько часов", 1, 48, 3)
    ai = st.checkbox("AI-редактирование (фото отправится в Hugging Face / fal.ai)")
    engine = st.selectbox(
        "Текстовое описание", ["rules", "auto", "yandexgpt", "huggingface"]
    )
    mode = st.selectbox(
        "Режим",
        [
            "full",
            "baseline",
            "glossary",
            "tm",
            "tm_hybrid",
            "agents_only",
            "tm_hybrid_critic",
            "tm_hybrid_editor",
        ],
    )
    if st.button("Показать прогноз", type="primary"):
        if not place and not photo:
            st.warning("Выберите место или загрузите фото.")
        else:
            data = {
                "latitude": latitude,
                "longitude": longitude,
                "hours": hours,
                "image_engine": "ai" if ai else "preview",
                "engine": engine,
                "mode": mode,
            }
            if place:
                data["place_id"] = place
            with st.spinner("Получаем прогноз и обрабатываем фото…"):
                result = call(
                    "POST",
                    "/weather/forecast",
                    data=data,
                    files={"file": file_part(photo)} if photo else None,
                )
            if result:
                left, right = st.columns(2)
                left.image(
                    base64.b64decode(result["original"]), caption="Исходное фото"
                )
                right.image(
                    base64.b64decode(result["image"]), caption="Визуализация прогноза"
                )
                data = result["forecast"]
                st.caption(
                    datetime.fromisoformat(data["time"])
                    .astimezone()
                    .strftime("%d.%m.%Y %H:%M %Z")
                )
                cols = st.columns(3)
                cols[0].metric("Температура", f'{data["temperature_2m"]} °C')
                cols[1].metric(
                    "Вероятность осадков", f'{data["precipitation_probability"]}%'
                )
                cols[2].metric("Облачность", f'{data["cloud_cover"]}%')
                st.write(result["description"])
                with st.expander("Как получен результат"):
                    st.json(
                        {
                            key: result[key]
                            for key in (
                                "engine_used",
                                "mode",
                                "cached",
                                "reasoning_log",
                                "critic_score",
                                "context",
                            )
                        }
                    )
    if page == "Сравнение режимов":
        st.subheader("Сравнить движки на одном прогнозе")
        engines = st.multiselect(
            "Движки",
            ["rules", "yandexgpt", "huggingface"],
            default=["rules", "yandexgpt"],
        )
        if st.button("Сравнить движки", disabled=len(engines) < 2):
            chosen = next((row for row in places if row["id"] == place), None)
            payload = {
                "latitude": chosen["latitude"] if chosen else latitude,
                "longitude": chosen["longitude"] if chosen else longitude,
                "title": chosen["title"] if chosen else "Локация",
                "hours": hours,
                "engines": engines,
            }
            compared = call("POST", "/weather/ensemble", json=payload)
            if compared:
                st.json(compared)
elif page == "Каталог мест":
    q = st.text_input("Название места")
    places = call("GET", "/weather/places", params={"q": q}) or []
    if not places:
        st.info("Здесь появятся фотографии после модерации.")
    for place in places:
        st.subheader(place["title"])
        image = call("GET", f'/weather/places/{place["id"]}/image')
        if image:
            st.image(image, width=340)
elif page == "Добавить фото":
    title = st.text_input("Название популярного места")
    lat, lon = coordinates()
    photo = st.file_uploader(
        "Фото, которое вы можете опубликовать", type=["jpg", "jpeg", "png", "webp"]
    )
    publish = st.checkbox("Разрешаю показывать это фото и координаты в общем каталоге")
    if st.button("Отправить на проверку", disabled=not (title and photo and publish)):
        if call(
            "POST",
            "/weather/places",
            data={"title": title, "latitude": lat, "longitude": lon, "publish": "true"},
            files={"file": file_part(photo)},
        ):
            st.success("Фото отправлено. После одобрения вы получите 10 баллов.")
elif page == "Мои вклады":
    data = call("GET", "/weather/contributions/me")
    if data:
        st.metric("Баллы", data["points"])
        labels = {
            "approved": "Опубликовано",
            "pending": "На проверке",
            "rejected": "Отклонено",
        }
        for photo in data["photos"]:
            st.write(f'{photo["title"]} · {labels[photo["status"]]}')
elif page == "Прогнозы списком":
    values = st.text_area(
        "По одной локации на строку: широта, долгота, часы",
        "55.79, 49.12, 3\n55.75, 37.62, 6",
    )
    if st.button("Получить прогнозы"):
        try:
            rows = []
            for line in values.splitlines():
                if line.strip():
                    latitude, longitude, hours = line.split(",")
                    rows.append(
                        {
                            "latitude": float(latitude),
                            "longitude": float(longitude),
                            "hours": int(hours),
                        }
                    )
        except ValueError:
            st.error("Проверьте формат строк.")
        else:
            result = call("POST", "/weather/batch", json=rows)
            if result:
                st.json(result)
elif page == "Модерация":
    if st.session_state.role not in ("editor", "admin"):
        st.info("Раздел доступен модераторам.")
        st.stop()
    with st.expander("Глоссарий и архив прогноза"):
        library = st.radio("Набор", ["glossary", "memory"], horizontal=True)
        query = st.text_input("Поиск по набору")
        records = call("GET", f"/weather-admin/{library}", params={"q": query})
        if records:
            st.dataframe(records)
        csv_file = st.file_uploader("CSV UTF-8: title,text,source", type=["csv"])
        if st.button("Импортировать CSV", disabled=csv_file is None) and csv_file:
            imported = call(
                "POST",
                f"/weather-admin/{library}/import-csv",
                files={"file": file_part(csv_file)},
            )
            if imported:
                st.success(f'Добавлено записей: {imported["added"]}')
    queue = call("GET", "/hitl/uncertain")
    if queue:
        for photo in queue["photos"]:
            key = photo["id"]
            st.subheader(photo["title"])
            image = call("GET", f"/hitl/photos/{key}/image")
            if image:
                st.image(image, width=360)
            for column, label, decision in zip(
                st.columns(2),
                ("Одобрить", "Отклонить"),
                ("approved", "rejected"),
                strict=True,
            ):
                if column.button(label, key=f"{key}-{decision}") and call(
                    "POST", f"/hitl/photos/{key}/{decision}"
                ):
                    st.rerun()
        for row in queue["forecasts"]:
            key = row["id"]
            text = st.text_area(row["question"], row["draft"], key=key)
            if st.button("Сохранить исправление", key=f"{key}-confirm"):
                if call("POST", f"/hitl/uncertain/{key}/confirm", json={"text": text}):
                    st.rerun()
            if st.button("Отклонить", key=f"{key}-reject") and call(
                "POST", f"/hitl/uncertain/{key}/reject"
            ):
                st.rerun()
        if not queue["photos"] and not queue["forecasts"]:
            st.info("Очередь пуста.")
else:
    result = call("GET", "/health")
    if result:
        st.json(result)
    if st.session_state.role in ("editor", "admin"):
        cache = call("GET", "/weather-admin/cache/stats")
        if cache:
            st.metric("Записей в кэше", cache["entries"])
            st.metric("Обращений к кэшу", cache["hits"])
        if st.button("Очистить кэш") and call("DELETE", "/weather-admin/cache"):
            st.rerun()
