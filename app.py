import os
import time
import threading
import io
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file
from openpyxl import Workbook

from services.sheets_service import fetch_public_sheet_data
from services.file_parser import get_text
from services.ai_service import get_available_models, get_gemini_evaluation_single_shot

app = Flask(__name__)
app.secret_key = os.urandom(24)

progress_status = {"status": "idle", "current": 0, "total": 0, "logs": []}
final_results = []
original_headers = []

# Глобальный массив ключей в оперативной памяти
active_api_keys = []


def grader_worker(sheet_url, user_prompt, book_text, model_id):
    global progress_status, final_results, original_headers, active_api_keys

    progress_status = {
        "status": "processing",
        "current": 0,
        "total": 0,
        "logs": ["🚀 Инициализация подсистем ИИ-агента...", "⏳ Анализ структуры загруженного текста..."]
    }
    final_results = []
    original_headers = []

    try:
        if not active_api_keys:
            raise Exception("В оперативной памяти нет доступных API-ключей! Перезапустите приложение.")

        progress_status["logs"].append(f"Загружено ключей в память для ротации: {len(active_api_keys)}")

        book_length = len(book_text)

        # 1. Находим вес одного ученика в токенах (коэффициент 0.47 + 5000 на промпт)
        tokens_per_student = (book_length * 0.47) + 5000

        # 2. Находим, сколько человек МАКСИМУМ влезает в минуту по токенам (в 250 000)
        # Используем целочисленное деление (int), так как человек не может быть дробным
        max_students_by_tokens = int(250000 / tokens_per_student)

        # Защита: если книга настолько огромная, что даже один человек не влезает (0),
        # принудительно ставим 1, иначе будет ошибка деления на ноль.
        if max_students_by_tokens < 1:
            max_students_by_tokens = 1

        # 3. Отсекаем, если получилось больше 5 человек в минуту (жесткий лимит RPM)
        final_students_per_minute = min(max_students_by_tokens, 5)

        # 4. Делим 60 секунд на это количество и добавляем 5 доп. секунд запаса
        calculated_interval = (60.0 / final_students_per_minute) + 5.0

        # Финальный лог для вывода в интерфейс, чтобы вы видели всю математику
        progress_status["logs"].append(
            f"📊 Расчет лимитов: 1 ученик = {tokens_per_student:.0f} токенов. "
            f"В минуту влезает: {max_students_by_tokens} чел. (с ограничением частоты: {final_students_per_minute} чел.)."
        )

        progress_status["logs"].append(f"Размер книги: {book_length} символов.")
        progress_status["logs"].append(
            f"🎯 Итоговый интервал безопасности между стартами: {calculated_interval:.2f} сек.")

        progress_status["logs"].append("Подключение к Google Таблице...")
        all_rows = fetch_public_sheet_data(sheet_url)

        original_headers = all_rows[0]
        data_rows = all_rows[1:]

        valid_rows = [r for r in data_rows if r and len(r) > 0 and "".join(r).strip()]
        total_students = len(valid_rows)
        progress_status["total"] = total_students

        real_student_num = 1
        current_key_index = 0  # Активный ключ в памяти

        for idx, row in enumerate(data_rows):
            if not row or len(row) == 0 or not "".join(row).strip():
                continue

            student_name = f"Ученик №{real_student_num}"

            student_answers = []
            for col_idx in range(2, len(row)):
                if col_idx < len(row) and col_idx < len(original_headers):
                    student_answers.append({
                        "question": original_headers[col_idx],
                        "answer": row[col_idx]
                    })

            evaluation = None
            elapsed_time = 0.0

            # 🎯 СТРОГИЙ ДВУХЭТАПНЫЙ ЦИКЛ ПРОВЕРКИ КЛЮЧА (С ЗАЩИТОЙ ОТ ЦЕПОЧКИ 503 -> 429)
            while current_key_index < len(active_api_keys):
                active_key = active_api_keys[current_key_index]

                progress_status["logs"].append(
                    f"Процесс: Анализ ответов {student_name} через Ключ №{current_key_index + 1}... (Строка {idx + 2})"
                )

                start_time = time.perf_counter()
                try:
                    # Попытка №1
                    evaluation = get_gemini_evaluation_single_shot(
                        api_key=active_key, model_id=model_id, student_name=student_name,
                        student_answers=student_answers, headers=original_headers,
                        user_prompt=user_prompt, book_text=book_text
                    )
                    elapsed_time = time.perf_counter() - start_time
                    break  # Успешно! Выходим из while

                except Exception as api_error:
                    error_msg = str(api_error)
                    elapsed_time = time.perf_counter() - start_time

                    # 🛠️ СЦЕНАРИЙ 1: Сервер перегружен (Ошибка 503)
                    if "503" in error_msg:
                        progress_status["logs"].append(
                            f"⚠️ Сервер Gemini перегружен (ошибка 503). Начинаем штурм с паузой 30 сек...")

                        server_saved = False
                        while not server_saved:
                            time.sleep(30.0)  # Пауза СТРОГО 30 секунд по вашему требованию
                            try:
                                progress_status["logs"].append(
                                    f"🔄 Повторный штурм сервера через Ключ №{current_key_index + 1}...")
                                start_time = time.perf_counter()
                                evaluation = get_gemini_evaluation_single_shot(
                                    api_key=active_key, model_id=model_id, student_name=student_name,
                                    student_answers=student_answers, headers=original_headers,
                                    user_prompt=user_prompt, book_text=book_text
                                )
                                elapsed_time = time.perf_counter() - start_time
                                server_saved = True  # Сервер пробит, всё ок!
                            except Exception as retry_server_error:
                                retry_server_msg = str(retry_server_error)

                                if "503" in retry_server_msg:
                                    # Сервер всё еще лежит, продолжаем штурм дальше
                                    continue

                                elif "429" in retry_server_msg or "ResourceExhausted" in retry_server_msg:
                                    # 💥 Учтено: после 503 вывалилась 429!
                                    # Подменяем текущую ошибку и выходим из штурма сервера напрямую в блок обработки 429
                                    progress_status["logs"].append(
                                        f"⚠️ После перегрузки 503 ключ поймал лимит 429. Перенаправляем в блок ротации...")
                                    api_error = retry_server_error
                                    error_msg = retry_server_msg
                                    break
                                else:
                                    # Любая другая непредвиденная ошибка — завершаем штурм и пробрасываем наверх
                                    api_error = retry_server_error
                                    error_msg = retry_server_msg
                                    break

                        if server_saved:
                            break  # Если успешно пробили сервер, выходим из основного while к сохранению данных

                    # 🛠️ СЦЕНАРИЙ 2: Исчерпан лимит запросов ключа (Ошибка 429 / ResourceExhausted)
                    # Сюда код попадет либо сразу, либо если 429 выскочила после 503 внутри штурма
                    if "429" in error_msg or "ResourceExhausted" in error_msg:
                        progress_status["logs"].append(
                            f"⚠️ Ключ №{current_key_index + 1} находится в таймауте 429. Ожидаем 30 сек...")
                        time.sleep(30.0)

                        try:
                            # Одиночный повторный запрос после ожидания окна
                            progress_status["logs"].append(
                                f"🔄 Одиночный запрос после паузы 429 через Ключ №{current_key_index + 1}...")
                            start_time = time.perf_counter()
                            evaluation = get_gemini_evaluation_single_shot(
                                api_key=active_key, model_id=model_id, student_name=student_name,
                                student_answers=student_answers, headers=original_headers,
                                user_prompt=user_prompt, book_text=book_text
                            )
                            elapsed_time = time.perf_counter() - start_time
                            break  # Ключ восстановился, выходим из while
                        except Exception as retry_error:
                            retry_msg = str(retry_error)

                            # Если и после этого опять 429 или вернулась 503 — ключ считается выжженным
                            if "429" in retry_msg or "ResourceExhausted" in retry_msg or "503" in retry_msg:
                                progress_status["logs"].append(
                                    f"🛑 Ключ №{current_key_index + 1} окончательно исчерпан или нестабилен. Ротация...")

                                current_key_index += 1  # Смещаем указатель на следующий ключ
                                if current_key_index >= len(active_api_keys):
                                    raise Exception(
                                        "❌ Все загруженные в память API-ключи полностью исчерпали свои лимиты!")
                                continue  # Уходим на новый круг while с новым ключом
                            else:
                                raise retry_error
                    else:
                        # Ошибки авторизации (401), плохой запрос (400) и т.д. прерывают выполнение
                        raise api_error

            real_student_num += 1

            # Сохранение результатов в структуру
            student_row = {
                "Порядковый номер": student_name,
                "Номер в рейтинге из формы": row[1] if len(row) > 1 else ""
            }

            for res_idx, res in enumerate(evaluation.get("results", [])):
                col_target_idx = 2 + res_idx
                student_row[f"col_{col_target_idx}_score"] = res.get("score", "")
                student_row[f"col_{col_target_idx}_comment"] = res.get("comment", "")

            print(student_row)
            final_results.append(student_row)
            progress_status["current"] += 1
            progress_status["logs"].append(f"Успешно checked: Проверка работы {student_name} завершена")

            # ⏱️ ИДЕАЛЬНЫЙ РАСЧЕТ ОСТАТКА ПАУЗЫ ДЛЯ СКОЛЬЗЯЩЕГО ОКНАТЕКУЩЕГО КЛЮЧА
            if progress_status["current"] < total_students:
                remaining_sleep = calculated_interval - elapsed_time
                if remaining_sleep > 0:
                    progress_status["logs"].append(f"⏱️ До выравнивания окна осталось {remaining_sleep:.1f} с. Спим...")
                    time.sleep(remaining_sleep)

        progress_status["status"] = "completed"
        progress_status["logs"].append("🎉 Проверка всех работ успешно завершена!")

    except Exception as e:
        import traceback
        print("\n❌ СИСТЕМНЫЙ СБОЙ ВОРКЕРА:")
        traceback.print_exc()
        progress_status["status"] = "error"
        progress_status["logs"].append(f"❌ Критическая ошибка: {str(e)}")


@app.route('/', methods=['GET', 'POST'])
def index():
    global active_api_keys
    if request.method == 'POST':
        file = request.files.get('keys_file')
        if not file or not file.filename:
            return "Файл ключей не загружен", 400

        try:
            raw_content = file.read().decode('utf-8', errors='ignore')
            active_api_keys = [line.strip() for line in raw_content.splitlines() if line.strip()]
        except Exception as e:
            return f"Ошибка обработки файла ключей: {e}", 400

        if not active_api_keys:
            return "Файл не содержит ни одного валидного API-ключа!", 400

        return redirect(url_for('config'))

    return render_template('index.html')


@app.route('/config', methods=['GET', 'POST'])
def config():
    global active_api_keys
    if not active_api_keys:
        return redirect(url_for('index'))

    try:
        models = get_available_models(active_api_keys)
    except Exception:
        models = [{"id": "gemini-2.5-flash", "name": "GEMINI-2.5-FLASH (Дефолт)", "default": True}]

    if request.method == 'POST':
        sheet_url = request.form.get('sheet_url')
        user_prompt = request.form.get('user_prompt')
        model_id = request.form.get('model_id')
        file = request.files.get('book_file')

        if not file:
            return render_template('config.html', models=models, error="Загрузите файл книги")

        book_text = get_text(file)

        thread = threading.Thread(target=grader_worker, args=(
            sheet_url, user_prompt, book_text, model_id
        ))
        thread.start()
        return redirect(url_for('progress'))

    return render_template('config.html', models=models)


@app.route('/progress')
def progress(): return render_template('progress.html')


@app.route('/get_progress')
def get_progress(): return jsonify(progress_status)


@app.route('/download')
def download_excel():
    global final_results, original_headers
    if not final_results or not original_headers:
        return "Нет данных", 400

    wb = Workbook()
    ws = wb.active
    ws.title = "Результаты проверки"

    excel_headers = ["Порядковый номер", "Номер в рейтинге из формы"]

    for col_idx in range(2, len(original_headers)):
        question_text = original_headers[col_idx]
        excel_headers.append(f"{question_text} (Оценка)")
        excel_headers.append(f"{question_text} (Комментарий)")

    ws.append(excel_headers)

    for student_data in final_results:
        row_to_write = [
            student_data.get("Порядковый номер", ""),
            student_data.get("Номер в рейтинге из формы", "")
        ]

        for col_idx in range(2, len(original_headers)):
            row_to_write.append(student_data.get(f"col_{col_idx}_score", ""))
            row_to_write.append(student_data.get(f"col_{col_idx}_comment", ""))

        ws.append(row_to_write)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name="rezultaty_gemini.xlsx")
