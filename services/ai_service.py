import json
from google import genai
from google.genai import types


def get_available_models(api_key):
    """Динамически запрашивает список моделей и помечает Free Tier"""
    try:
        print(api_key)
        client = genai.Client(api_key=api_key)
        models = client.models.list()

        filtered_models = []
        free_models_keywords = ["flash", "pro"]

        for m in models:
            model_id = m.name.replace("models/", "")
            if "tuning" not in model_id and "experimental" not in model_id:
                is_free = any(kw in model_id.lower() for kw in free_models_keywords)
                tier_suffix = " (Доступна бесплатно)" if is_free else " (Платный тариф)"
                is_default = (model_id == "gemini-2.5-flash" or model_id == "gemini-1.5-flash")

                filtered_models.append({
                    "id": model_id,
                    "name": f"{model_id.upper()}{tier_suffix}",
                    "default": is_default
                })

        filtered_models.sort(key=lambda x: x["id"], reverse=True)
        return filtered_models if filtered_models else [
            {"id": "gemini-2.5-flash", "name": "GEMINI-2.5-FLASH (Доступна бесплатно)", "default": True}
        ]
    except Exception:
        return [{"id": "gemini-2.5-flash", "name": "GEMINI-2.5-FLASH (Локальный дефолт)", "default": True}]


def get_gemini_evaluation_single_shot(api_key, model_id, student_name, student_answers, headers, user_prompt,
                                      book_text):
    """
    Делает СТРОГО один одиночный запрос к Gemini API без внутренних циклов и скрытых пауз.
    """
    client = genai.Client(api_key=api_key)

    system_instruction = f"""Ты — опытный школьный учитель-проверяющий.
Дети отвечали на тест, имеющий следующую структуру вопросов (шапка таблицы):
{json.dumps(headers, ensure_ascii=False)}

При проверке строго руководствуйся следующими пожеланиями преподавателя:
{user_prompt}

Ты обязан вернуть ответ СТРОГО в формате JSON, без разметки типа ```json. Структура ответа:
{{
  "results": [
    {{
      "question": "Точный текст вопроса из шапки",
      "score": "Оценка по критериям преподавателя - только число",
      "comment": "Ответь на то, о чем в промте просил преподователь указать в комментарии"
    }}
  ]
}}"""

    user_content = f"""Вот текст книги, на основе которой необходимо провести строгую проверку ответов:

--- НАЧАЛО ТЕКСТА КНИГИ ---
{book_text}
--- КОНЕЦ ТЕКСТА КНИГИ ---

Ученик: {student_name}. 
Вот ответы этого ученика, которые тебе нужно оценить: {json.dumps(student_answers, ensure_ascii=False)}"""

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        temperature=0.3
    )
    print(api_key)
    # 🎯 Чистый одиночный запрос. Ошибки 429 или 503 сразу летят на уровень выше в app.py
    response = client.models.generate_content(
        model=model_id,
        contents=user_content,
        config=config
    )
    return json.loads(response.text)
