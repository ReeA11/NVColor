<p align="center">
  <img src="assets/nvcolor.png" alt="NVColor" width="128" height="128">
</p>

<h1 align="center">NVColor</h1>

<p align="center">
  Цветовые пресеты для Windows: яркость, контраст, гамма, Digital Vibrance и Hue.
</p>

## Скачать

Готовый **`NVColor.exe`** — в [Releases](../../releases) (вкладка справа на странице репозитория).

1. Скачай последний релиз  
2. Положи `NVColor.exe` в любую папку  
3. Запусти  

Рядом с exe при первом запуске появится `config.json` с твоими пресетами.

Нужен [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) (обычно уже есть вместе с Edge).

## Возможности

- Тёмный Fluent UI настроек
- Пресеты + хоткеи
- Живой предпросмотр слайдеров
- Автопереключение по процессу игры
- Импорт / экспорт конфига
- Интерфейс EN / RU
- Hard reset при выходе

## Что в репозитории

Исходный код приложения. Сборка для пользователей не нужна — бери готовый exe из Releases.

Пример схемы конфига: [`config.example.json`](config.example.json).

## Требования

- Windows 10 / 11  
- WebView2  
- Для Digital Vibrance / Hue — NVIDIA GPU и драйвер (гамма работает и без NVIDIA)

## Лицензия

MIT

---

<details>
<summary>English</summary>

**NVColor** — Windows tray app for display color presets (brightness / contrast / gamma via Win32, Digital Vibrance & Hue via NVAPI).

Download the portable **`NVColor.exe`** from [Releases](../../releases). Source code is in this repository; end users do not need to build from scripts.

MIT License.
</details>
