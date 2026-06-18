import pypdf


def get_text(file):
    try:
        if file.filename.lower().endswith('.pdf'):
            return process_pdf(file)
        if file.filename.lower().endswith('.txt'):
            return process_txt(file)
    except Exception as e:
        return f"Не удалось прочитать файл: {e}"


def process_txt(file):
    try:
        return file.read().decode('utf-8', errors='ignore')
    except Exception as e:
        return f"Ошибка обработки TXT: {str(e)}"


def process_pdf(file):
    try:
        pdf_reader = pypdf.PdfReader(file)  # Просто передаем объект file вместо пути!
        return "".join([page.extract_text() for page in pdf_reader.pages])
    except Exception as e:
        return f"Ошибка обработки PDF: {str(e)}"
