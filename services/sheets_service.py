import requests
import csv
import re
from io import StringIO


def parse_sheet_id(url):
    """Строго извлекает 44-значный ID Google Таблицы из любой ссылки"""
    if not url:
        return ""
    url_str = str(url).strip()
    match = re.search(r'/d/([a-zA-Z0-9-_]{44})', url_str)
    if match:
        return match.group(1)
    backup_match = re.search(r'([a-zA-Z0-9-_]{44})', url_str)
    if backup_match:
        return backup_match.group(1)
    return ""


def fetch_public_sheet_data(sheet_url):
    """Скачивает данные таблицы через CSV-экспорт Google Docs с жестким контролем UTF-8"""
    sheet_id = parse_sheet_id(sheet_url)

    if not sheet_id or len(sheet_id) != 44:
        raise Exception("Не удалось распознать ID Google Таблицы. Проверьте правильность ссылки.")

    # Формируем точный адрес экспорта
    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    print(f" Лог: Отправка запроса по адресу: {csv_url}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    response = requests.get(csv_url, headers=headers, timeout=10)

    if response.status_code != 200:
        raise Exception(f"Google Sheets вернул статус {response.status_code}. Проверьте права доступа ссылки.")

    # Декодируем сырые байты в UTF-8 (защита от кракозябр и зависаний на Windows)
    raw_text = response.content.decode('utf-8', errors='ignore')

    f = StringIO(raw_text)
    reader = csv.reader(f)
    all_rows = list(reader)

    if not all_rows:
        raise Exception("Google Таблица прочитана, но она пустая.")

    print(f" Лог: Таблица успешно скачана и декодирована! Найдено строк: {len(all_rows)}")
    return all_rows
